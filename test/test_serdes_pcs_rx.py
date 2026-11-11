#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

import unittest

from migen import *

from litex.gen import *
from litex.gen.sim import *

from liteiclink.serdes.pcs.gearbox import BitstreamGearbox
from liteiclink.serdes.pcs.rx import BlockSynchronizer, BlockRX
from liteiclink.serdes.pcs.tx import BlockTX


# DUT ------------------------------------------------------------------------------------------------

class DUT(LiteXModule):
    def __init__(self):
        self.cd_sys = ClockDomain()
        self.syncer = BlockSynchronizer()


class BitstreamDUT(LiteXModule):
    def __init__(self):
        self.cd_sys = ClockDomain()
        self.gearbox = BitstreamGearbox(in_width=1, out_width=66)
        self.syncer = BlockSynchronizer()
        self.comb += [
            self.gearbox.source.connect(self.syncer.sink),
            self.gearbox.slip.eq(self.syncer.slip),
            self.syncer.source.ready.eq(1),
        ]


class BlockLinkDUT(LiteXModule):
    """BlockTX -> BlockRX (66-bit words), corrupting the sync header of block ``corrupt_index``."""
    def __init__(self, corrupt_index):
        self.cd_sys  = ClockDomain()
        self.tx      = BlockTX()
        self.rx      = BlockRX(input_width=66)
        self.corrupt = Signal()
        count = Signal(16)
        self.sync += If(self.rx.sink.valid & self.rx.sink.ready, count.eq(count + 1))
        self.comb += [
            self.corrupt.eq(count == corrupt_index),
            self.tx.source.ready.eq(self.rx.sink.ready),
            self.rx.sink.valid.eq(self.tx.source.valid),
            self.rx.sink.data.eq(Mux(self.corrupt,
                Cat(Constant(0b00, 2), self.tx.source.data[2:]),
                self.tx.source.data)),
        ]


# Test 64b/66b Block Synchronizer ---------------------------------------------------------------------

class TestBlockSynchronizer(unittest.TestCase):
    def test_acquire_from_misaligned_serial_bitstream(self):
        payloads = [((i * 0x1f123bb5a5a5a5a5) ^ (i << 23) ^ 0xdeadbeef01234567) & ((1 << 64) - 1)
                    for i in range(160)]
        blocks = [(payload << 2) | 0b10 for payload in payloads]
        bits = [1]
        for block in blocks:
            bits.extend((block >> i) & 1 for i in range(66))

        dut = BitstreamDUT()
        slip_count = 0
        locked = False

        def generator():
            nonlocal slip_count, locked
            bit_index = 0
            for _ in range(20000):
                valid = bit_index < len(bits)
                yield dut.gearbox.sink.valid.eq(valid)
                if valid:
                    yield dut.gearbox.sink.data.eq(bits[bit_index])

                sink_ready = (yield dut.gearbox.sink.ready)
                if valid and sink_ready:
                    bit_index += 1
                yield
                if (yield dut.syncer.slip):
                    slip_count += 1
                if (yield dut.syncer.block_lock):
                    locked = True
                    break

        run_simulation(dut, generators={"sys": generator()}, clocks={"sys": 10})
        self.assertGreater(slip_count, 0)
        self.assertTrue(locked)

    def test_acquire_lose_and_reacquire_lock(self):
        good_block = (0x0123456789abcdef << 2) | 0b10
        bad_block  = (0x0123456789abcdef << 2) | 0b00
        dut = DUT()
        locks = []
        slips = []

        def generator():
            blocks = [good_block] * 64 + [bad_block] * 16 + [good_block] * 65
            index = 0
            for _ in range(512):
                valid = index < len(blocks)
                yield dut.syncer.sink.valid.eq(valid)
                if valid:
                    yield dut.syncer.sink.data.eq(blocks[index])
                yield dut.syncer.source.ready.eq(1)

                sink_ready = (yield dut.syncer.sink.ready)
                if valid and sink_ready:
                    index += 1
                yield
                locks.append((yield dut.syncer.block_lock))
                slips.append((yield dut.syncer.slip))
                if index == len(blocks):
                    break

        run_simulation(dut, generators={"sys": generator()}, clocks={"sys": 10})

        self.assertTrue(any(locks))
        self.assertTrue(any(slips))
        first_lock = locks.index(1)
        self.assertIn(0, locks[first_lock + 1:])
        self.assertTrue(locks[-1])


    def test_lock_and_candidate_are_held_during_downstream_stall(self):
        good_block = (0x0123456789abcdef << 2) | 0b10
        dut = DUT()
        stalled_candidates = []
        locks_during_stall = []

        def producer():
            for _ in range(80):
                yield dut.syncer.sink.valid.eq(1)
                yield dut.syncer.sink.data.eq(good_block)
                while True:
                    yield
                    if (yield dut.syncer.sink.ready):
                        break
            yield dut.syncer.sink.valid.eq(0)

        def consumer():
            hold = False
            hold_cycles = 0
            for cycle in range(256):
                yield dut.syncer.source.ready.eq(not hold)
                yield
                if (yield dut.syncer.block_lock) and not hold:
                    hold = True
                elif hold and hold_cycles < 6:
                    self.assertEqual((yield dut.syncer.sink.ready), 0)
                    self.assertEqual((yield dut.syncer.source.valid), 1)
                    stalled_candidates.append((yield dut.syncer.source.data))
                    locks_during_stall.append((yield dut.syncer.block_lock))
                    hold_cycles += 1
                elif hold:
                    hold = False
                if hold_cycles == 6 and (yield dut.syncer.source.ready) and not (yield dut.syncer.block_lock):
                    break

        run_simulation(dut, [producer(), consumer()], clocks={"sys": 10})
        self.assertEqual(len(stalled_candidates), 6)
        self.assertEqual(len(set(stalled_candidates)), 1)
        self.assertTrue(all(locks_during_stall))

    def test_invalid_headers_request_slip_before_lock(self):
        bad_block = (0x0123456789abcdef << 2) | 0b11
        dut = DUT()
        slips = []
        locks = []

        def generator():
            for _ in range(20):
                yield dut.syncer.sink.valid.eq(1)
                yield dut.syncer.sink.data.eq(bad_block)
                yield dut.syncer.source.ready.eq(1)
                yield
                slips.append((yield dut.syncer.slip))
                locks.append((yield dut.syncer.block_lock))

        run_simulation(dut, generators={"sys": generator()}, clocks={"sys": 10})
        # Clause 49 Figure 49-14: while unlocked, each invalid header requests a slip. The first
        # header is presented one cycle after being written: 19 are transferred in the 20 samples.
        self.assertEqual(sum(slips), 19)
        self.assertFalse(locks[-1])

    def test_locked_keeps_lock_below_16_invalid_headers(self):
        good_block = (0x0123456789abcdef << 2) | 0b10
        bad_block  = (0x0123456789abcdef << 2) | 0b11
        dut = DUT()
        locks = []
        slips = []

        def generator():
            # Lock, then 15 invalid headers in a 64-header window: lock is kept, no slip.
            blocks = [good_block] * 64 + [bad_block] * 15 + [good_block] * 49
            for block in blocks:
                yield dut.syncer.sink.valid.eq(1)
                yield dut.syncer.sink.data.eq(block)
                yield dut.syncer.source.ready.eq(1)
                yield
                locks.append((yield dut.syncer.block_lock))
                slips.append((yield dut.syncer.slip))

        run_simulation(dut, generators={"sys": generator()}, clocks={"sys": 10})
        first_lock = locks.index(1)
        self.assertNotIn(0, locks[first_lock:])
        self.assertEqual(sum(slips), 0)



# Test 64b/66b Block Receiver -------------------------------------------------------------------------

class TestBlockRX(unittest.TestCase):
    def test_invalid_header_only_drops_its_block(self):
        # One invalid sync header after lock: only that block is lost. The descrambler must still
        # process it, otherwise the following valid blocks are corrupted. Downstream stalls check
        # that the control flags stay aligned with the payloads.
        import random
        rng      = random.Random(62)
        n        = 200
        corrupt  = 120
        blocks   = [(rng.getrandbits(64), rng.getrandbits(1)) for _ in range(n)]
        dut      = BlockLinkDUT(corrupt_index=corrupt)
        received = []

        def send():
            for payload, control in blocks:
                yield dut.tx.sink.valid.eq(1)
                yield dut.tx.sink.data.eq(payload)
                yield dut.tx.sink.control.eq(control)
                yield
                while not (yield dut.tx.sink.ready):
                    yield
            yield dut.tx.sink.valid.eq(0)

        def receive():
            for cycle in range(4*n):
                # Periodic downstream stalls (ready applies from the next cycle).
                yield dut.rx.source.ready.eq((cycle % 7) != 3)
                if (yield dut.rx.source.valid) and (yield dut.rx.source.ready):
                    received.append(((yield dut.rx.source.data), (yield dut.rx.source.control)))
                yield

        run_simulation(dut, [send(), receive()], clocks={"sys": 10})

        # The first block after lock is descrambled with a stale history: compare from the second
        # received block, located in the sent sequence.
        start    = blocks.index(received[1])
        expected = [b for i, b in enumerate(blocks) if (i >= start) and (i != corrupt)]
        self.assertLess(start, corrupt)
        self.assertEqual(received[1:], expected[:len(received) - 1])
        self.assertGreater(len(received), n - start - 5)


if __name__ == "__main__":
    unittest.main()

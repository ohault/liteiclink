#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

import unittest

from migen import *
from litex.gen import *
from litex.gen.sim import *
from liteiclink.serdes.pcs import PCS64b66b


class GenericLoopback(LiteXModule):
    def __init__(self, raw_width):
        self.cd_sys = ClockDomain()
        self.pcs = PCS64b66b(raw_width=raw_width, reset_value=(1 << 58) - 1)
        self.comb += self.pcs.tx.connect(self.pcs.rx)


class TestGenericPCSBlocks(unittest.TestCase):
    def test_generic_tx_to_rx_preserves_payload_and_header_type(self):
        blocks = [
            (((i * 0x1f123bb5a5a5a5a5) ^ (i << 21) ^ 0xdeadbeef01234567)
             & ((1 << 64) - 1), i & 1)
            for i in range(256)
        ]
        for raw_width in (20, 40, 80):
            with self.subTest(raw_width=raw_width):
                self.run_loopback(raw_width, blocks)

    def run_loopback(self, raw_width, blocks):
        dut = GenericLoopback(raw_width)
        received = []
        accepted = [0]
        lock_history = []

        def producer():
            for payload, control in blocks:
                yield dut.pcs.sink.valid.eq(1)
                yield dut.pcs.sink.data.eq(payload)
                yield dut.pcs.sink.control.eq(control)
                for _ in range(1000):
                    yield
                    if (yield dut.pcs.sink.ready):
                        accepted[0] += 1
                        break
                else:
                    self.fail("Generic TX input stalled")
            yield dut.pcs.sink.valid.eq(0)

        def consumer():
            for cycle in range(30000):
                yield dut.pcs.source.ready.eq(cycle % 11 < 6)
                yield
                if (yield dut.pcs.source.valid) and (yield dut.pcs.source.ready):
                    received.append(((yield dut.pcs.source.data), (yield dut.pcs.source.control)))
                lock_history.append((yield dut.pcs.block_lock))
                if (accepted[0] == len(blocks) and len(received) >= len(blocks) - 80 and
                        (yield dut.pcs.block_lock)):
                    break

        run_simulation(dut, [producer(), consumer()], clocks={"sys": 10})
        self.assertEqual(accepted[0], len(blocks))
        self.assertTrue(any(lock_history))
        self.assertTrue(lock_history[-1])
        # Initial headers are discarded while block lock is acquired, and the
        # self-synchronous descrambler needs 58 payload bits to settle.
        expected = blocks[64:]
        matched = 0
        matched_start = None
        for i in range(len(received)):
            for j in range(len(expected)):
                run = 0
                while (i + run < len(received) and j + run < len(expected) and
                       received[i + run] == expected[j + run]):
                    run += 1
                if run > matched:
                    matched = run
                    matched_start = j
        self.assertGreaterEqual(matched, 32)
        recovered_types = {control for _, control in expected[matched_start:matched_start + matched]}
        self.assertEqual(recovered_types, {0, 1})


if __name__ == "__main__":
    unittest.main()

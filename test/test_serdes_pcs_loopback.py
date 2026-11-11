#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

import unittest

from migen import *

from litex.gen import *
from litex.gen.sim import *
from litex.soc.interconnect import stream

from liteiclink.serdes.pcs.gearbox import BitstreamGearbox
from liteiclink.serdes.pcs.rx import DataBlockRX
from liteiclink.serdes.pcs.tx import DataBlockTX


class BitSlipChannel(LiteXModule):
    def __init__(self, insert_after):
        self.sink = sink = stream.Endpoint([("data", 1)])
        self.source = source = stream.Endpoint([("data", 1)])
        count = Signal(max=insert_after + 2)
        repeat_pending = Signal()
        repeated_bit = Signal()
        insert_now = count == insert_after
        self.comb += [
            sink.ready.eq(~repeat_pending & source.ready),
            source.valid.eq(repeat_pending | sink.valid),
            source.data.eq(Mux(repeat_pending, repeated_bit, sink.data)),
        ]
        self.sync += If(repeat_pending,
            If(source.ready, repeat_pending.eq(0))
        ).Elif(sink.valid & sink.ready,
            count.eq(count + 1),
            If(insert_now,
                repeated_bit.eq(sink.data),
                repeat_pending.eq(1)
            )
        )


class DUT(LiteXModule):
    def __init__(self):
        self.cd_sys = ClockDomain()
        self.encoder = DataBlockTX(reset_value=(1 << 58) - 1)
        self.serializer = BitstreamGearbox(in_width=66, out_width=1)
        self.channel = BitSlipChannel(insert_after=90*66 + 10)
        self.receiver = DataBlockRX(reset_value=(1 << 58) - 1)
        self.comb += [
            self.encoder.source.connect(self.serializer.sink),
            self.serializer.source.connect(self.channel.sink),
            self.channel.source.connect(self.receiver.sink),
        ]


class TestPCSLoopback(unittest.TestCase):
    def test_tx_to_serial_rx_recovers_after_acquisition_and_bit_slip(self):
        payloads = [((i * 0x1f123bb5a5a5a5a5) ^ (i << 23) ^ 0xdeadbeef01234567) & ((1 << 64) - 1)
                    for i in range(320)]
        dut = DUT()
        received = []
        accepted = 0
        locked = False
        lock_history = []

        def generator():
            nonlocal accepted, locked
            for _ in range(40000):
                valid = accepted < len(payloads)
                yield dut.encoder.sink.valid.eq(valid)
                if valid:
                    yield dut.encoder.sink.data.eq(payloads[accepted])
                yield dut.receiver.source.ready.eq(1)

                if valid and (yield dut.encoder.sink.ready):
                    accepted += 1
                if (yield dut.receiver.source.valid):
                    received.append((yield dut.receiver.source.data))
                locked = (yield dut.receiver.block_lock)
                lock_history.append(locked)
                yield
                if accepted == len(payloads) and len(received) >= len(payloads) - 64:
                    break

        run_simulation(dut, generators={"sys": generator()}, clocks={"sys": 10})

        self.assertTrue(received)
        self.assertEqual(accepted, len(payloads))
        self.assertTrue(locked)
        self.assertIn(False, lock_history)
        first_lock = lock_history.index(True)
        self.assertIn(False, lock_history[first_lock + 1:])
        self.assertTrue(locked)
        # Once reacquired, the descrambler catches up within one payload word.
        # Check that at least eight consecutive payloads are recovered exactly.
        recovered_run = 0
        for rx_index in range(len(received)):
            for tx_index in range(len(payloads)):
                length = 0
                while (rx_index + length < len(received) and
                       tx_index + length < len(payloads) and
                       received[rx_index + length] == payloads[tx_index + length]):
                    length += 1
                recovered_run = max(recovered_run, length)
        self.assertGreaterEqual(recovered_run, 8)


class ControlDUT(LiteXModule):
    def __init__(self):
        self.cd_sys = ClockDomain()
        self.encoder = DataBlockTX(reset_value=(1 << 58) - 1)
        self.serializer = BitstreamGearbox(in_width=66, out_width=1)
        self.receiver = DataBlockRX(reset_value=(1 << 58) - 1)
        self.comb += [
            self.encoder.source.connect(self.serializer.sink),
            self.serializer.source.connect(self.receiver.sink),
        ]


class TestPCSControlLoopback(unittest.TestCase):
    def test_xgmii_control_block_formats_round_trip(self):
        filler = (0x0123456789abcdef, 0)
        items = [filler] * 66
        items += [
            (sum(byte << (8*lane) for lane, byte in enumerate([0x07, 0x06, 0xfe, 0x1c, 0x3c, 0x7c, 0xbc, 0xf7])), 0xff),
            (0xfb | (0x11223344556677 << 8), 0x01),
        ]
        for lane in range(8):
            data = sum((0xfd if i == lane else (0x07 if i > lane else (0x20 + i))) << (8*i)
                       for i in range(8))
            items.append((data, (0xff << lane) & 0xff))
        ordered_set = 0x9c | (0x00332211 << 8) | (0x07070707 << 32)
        items.append((ordered_set, 0xf1))
        control_bytes = [0x07, 0x06, 0xfe, 0x1c]
        lane4_q = sum(byte << (8*i) for i, byte in enumerate(control_bytes)) | (0x9c << 32) | (0x332211 << 40)
        lane4_s = (lane4_q & ~(0xff << 32)) | (0xfb << 32)
        items.append((lane4_q, 0x1f))
        items.append((lane4_s, 0x1f))
        q0_s4 = 0x9c | (0x00332211 << 8) | (0xfb << 32) | (0x665544 << 40)
        q0_q4 = (q0_s4 & ~(0xff << 32)) | (0x9c << 32)
        items.append((q0_s4, 0x11))
        items.append((q0_q4, 0x11))
        items += [filler] * 12

        dut = ControlDUT()
        accepted = 0
        received = []
        locked = False

        def generator():
            nonlocal accepted, locked
            for _ in range(24000):
                valid = accepted < len(items)
                yield dut.encoder.sink.valid.eq(valid)
                if valid:
                    data, ctrl = items[accepted]
                    yield dut.encoder.sink.data.eq(data)
                    yield dut.encoder.sink.ctrl.eq(ctrl)
                yield dut.receiver.source.ready.eq(1)
                if valid and (yield dut.encoder.sink.ready):
                    accepted += 1
                if (yield dut.receiver.source.valid):
                    received.append(((yield dut.receiver.source.data), (yield dut.receiver.source.ctrl)))
                locked = (yield dut.receiver.block_lock)
                yield
                if accepted == len(items) and len(received) >= len(items) - 64:
                    break

        run_simulation(dut, generators={"sys": generator()}, clocks={"sys": 10})
        self.assertEqual(accepted, len(items))
        self.assertTrue(locked)
        # Acquisition discards the first 64 blocks, and the first output word
        # gives the self-synchronizing descrambler its prior-bit history.
        self.assertEqual(received[1:], items[66:])


if __name__ == "__main__":
    unittest.main()

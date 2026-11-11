#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

import unittest

from migen import *
from litex.gen import *
from litex.gen.sim import *

from liteiclink.serdes.pcs.gtp import GTPRawAdapter
from liteiclink.serdes.pcs.phy import PCS64b66bPHY


class FakeRawGTP(LiteXModule):
    def __init__(self, width=20):
        self.cd_tx = ClockDomain()
        self.cd_rx = ClockDomain()
        self.raw_datapath = True
        self.raw_rx_bitslip_supported = True
        self.raw_tx_data = Signal(width)
        self.raw_rx_data = Signal(width)
        self.raw_rx_bitslip = Signal()
        self.tx_ready = Signal(reset=1)
        self.rx_ready = Signal(reset=1)


class DUT(LiteXModule):
    def __init__(self):
        self.cd_sys = ClockDomain()
        self.phy = FakeRawGTP()
        self.adapter = GTPRawAdapter(self.phy, rx_fifo_depth=8)




class LoopbackDUT(LiteXModule):
    def __init__(self, width=20):
        self.cd_sys = ClockDomain()
        self.phy = FakeRawGTP(width)
        self.link = PCS64b66bPHY(GTPRawAdapter(self.phy, rx_fifo_depth=16))
        self.comb += self.phy.raw_rx_data.eq(self.phy.raw_tx_data)

class TestGTPRawAdapter(unittest.TestCase):
    def test_continuous_tx_rx_words_and_bitslip_passthrough(self):
        dut = DUT()
        tx_seen = []
        rx_seen = []
        bitslip_seen = []
        underflow_seen = []

        def tx_process():
            for word in range(1, 20):
                yield dut.adapter.tx.valid.eq(1)
                yield dut.adapter.tx.data.eq(word)
                yield
                if (yield dut.adapter.tx.ready):
                    tx_seen.append((yield dut.phy.raw_tx_data))
            yield dut.adapter.tx.valid.eq(0)
            yield dut.adapter.rx_bitslip.eq(1)
            yield
            bitslip_seen.append((yield dut.phy.raw_rx_bitslip))
            yield dut.adapter.rx_bitslip.eq(0)
            for _ in range(4):
                yield
            underflow_seen.append((yield dut.adapter.tx_underflow))

        def rx_process():
            yield dut.adapter.rx.ready.eq(1)
            for word in range(1, 80):
                yield dut.phy.raw_rx_data.eq(word)
                yield
                if (yield dut.adapter.rx.valid) and (yield dut.adapter.rx.ready):
                    rx_seen.append((yield dut.adapter.rx.data))

        run_simulation(dut, generators={"tx": tx_process(), "rx": rx_process()},
                       clocks={"sys": 10, "tx": 10, "rx": 10})
        self.assertEqual(tx_seen[:10], list(range(2, 12)))
        self.assertGreaterEqual(len(rx_seen), 60)
        self.assertEqual(rx_seen[:10], list(range(2, 12)))
        self.assertEqual(bitslip_seen, [1])
        self.assertEqual(underflow_seen, [1])
        self.assertEqual(dut.adapter.bitslip_supported, True)

    def test_full_pcs_link_with_independent_tx_rx_clocks(self):
        blocks = [
            (((i * 0x1f123bb5a5a5a5a5) ^ (i << 17) ^ 0xdeadbeef01234567)
             & ((1 << 64) - 1), i & 1)
            for i in range(1600)
        ]
        dut = LoopbackDUT()
        accepted = [0]
        received = []
        lock_history = []
        slip_count = [0]

        def producer():
            for payload, control in blocks:
                yield dut.link.sink.valid.eq(1)
                yield dut.link.sink.data.eq(payload)
                yield dut.link.sink.control.eq(control)
                for _ in range(2000):
                    yield
                    if (yield dut.link.sink.ready):
                        accepted[0] += 1
                        break
                else:
                    self.fail("TX block stream stalled")
            yield dut.link.sink.valid.eq(0)

        def consumer():
            for cycle in range(20000):
                yield dut.link.source.ready.eq(cycle % 7 != 0)
                yield
                if (yield dut.link.source.valid) and (yield dut.link.source.ready):
                    received.append(((yield dut.link.source.data), (yield dut.link.source.control)))
                lock_history.append((yield dut.link.block_lock))
                if (yield dut.link.pcs.rx_block.synchronizer.slip):
                    slip_count[0] += 1
                if (accepted[0] == len(blocks) and len(received) >= 100 and
                        (yield dut.link.block_lock)):
                    break

        run_simulation(dut, generators={"tx": producer(), "rx": consumer()},
                       clocks={"sys": 10, "tx": 10, "rx": (10, 2)})
        self.assertEqual(accepted[0], len(blocks))
        self.assertGreater(slip_count[0], 0)
        self.assertTrue(lock_history[-1])
        expected = blocks[64:]
        longest = 0
        for i in range(len(received)):
            for j in range(len(expected)):
                run = 0
                while (i + run < len(received) and j + run < len(expected) and
                       received[i + run] == expected[j + run]):
                    run += 1
                longest = max(longest, run)
        self.assertGreaterEqual(longest, 32)

    def test_sustained_rx_stall_sets_overflow(self):
        dut = DUT()
        overflow = []

        def rx_process():
            yield dut.adapter.rx.ready.eq(0)
            for word in range(32):
                yield dut.phy.raw_rx_data.eq(word)
                yield
            for _ in range(2):
                yield
            overflow.append((yield dut.adapter.rx_overflow))

        run_simulation(dut, generators={"rx": rx_process()},
                       clocks={"sys": 10, "tx": 10, "rx": 10})
        self.assertEqual(overflow, [1])

    def test_reports_raw_adapter_elaboration(self):
        dut = DUT()
        dut.get_fragment()
        self.assertEqual(dut.adapter.data_width, 20)
        self.assertEqual(len(dut.adapter.rx_fifo.sink.data), 20)


if __name__ == "__main__":
    unittest.main()

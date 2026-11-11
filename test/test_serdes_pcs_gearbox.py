#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

import unittest
from math import gcd

from migen import *

from litex.gen import *
from litex.gen.sim import *

from liteiclink.serdes.pcs.gearbox import BitstreamGearbox


class DUT(LiteXModule):
    def __init__(self, in_width, out_width):
        self.cd_sys = ClockDomain()
        self.gearbox = BitstreamGearbox(in_width, out_width)


class TestBitstreamGearbox(unittest.TestCase):
    def run_gearbox(self, in_width, out_width, stall=False):
        nwords = out_width // gcd(in_width, out_width)
        mask = (1 << in_width) - 1
        words = [((i * 0x1f123bb5) ^ (i << 19) ^ mask) & mask for i in range(nwords)]

        bitstream = sum(word << (i * in_width) for i, word in enumerate(words))
        noutputs = (nwords * in_width) // out_width
        out_mask = (1 << out_width) - 1
        expected = [(bitstream >> (i * out_width)) & out_mask for i in range(noutputs)]

        dut = DUT(in_width, out_width)
        outputs = []
        accepted = []

        def producer():
            for word in words:
                yield dut.gearbox.sink.valid.eq(1)
                yield dut.gearbox.sink.data.eq(word)
                for _ in range(4096):
                    yield
                    if (yield dut.gearbox.sink.ready):
                        accepted.append(word)
                        break
                else:
                    self.fail("Input stalled")
            yield dut.gearbox.sink.valid.eq(0)

        def consumer():
            for cycle in range(4096):
                ready = not stall or (cycle % 5 != 0)
                yield dut.gearbox.source.ready.eq(ready)
                yield
                if (yield dut.gearbox.source.valid) and (yield dut.gearbox.source.ready):
                    outputs.append((yield dut.gearbox.source.data))
                if len(outputs) == noutputs:
                    break

        run_simulation(dut, [producer(), consumer()], clocks={"sys": 10})
        self.assertEqual(accepted, words)
        self.assertEqual(outputs, expected)

    def test_66_to_20(self): self.run_gearbox(66, 20)
    def test_66_to_40(self): self.run_gearbox(66, 40)
    def test_66_to_80(self): self.run_gearbox(66, 80)
    def test_20_to_66(self): self.run_gearbox(20, 66)
    def test_40_to_66(self): self.run_gearbox(40, 66)
    def test_80_to_66(self): self.run_gearbox(80, 66)
    def test_66_to_20_with_backpressure(self): self.run_gearbox(66, 20, stall=True)


if __name__ == "__main__":
    unittest.main()

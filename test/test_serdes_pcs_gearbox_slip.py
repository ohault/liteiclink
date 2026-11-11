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


class DUT(LiteXModule):
    def __init__(self):
        self.cd_sys = ClockDomain()
        self.gearbox = BitstreamGearbox(in_width=8, out_width=4)


class TestBitstreamGearboxSlip(unittest.TestCase):
    def test_slip_discards_one_earliest_bit(self):
        words = [0b11010011, 0b00101101, 0b10100110, 0b01111000]
        bitstream = sum(word << (8*i) for i, word in enumerate(words))
        expected = [(bitstream >> (4*i)) & 0xf for i in range(2)]
        expected += [(bitstream >> (9 + 4*i)) & 0xf for i in range(3)]
        dut = DUT()
        outputs = []

        def generator():
            input_index = 0
            for _ in range(64):
                valid = input_index < len(words)
                slip = len(outputs) == 1
                yield dut.gearbox.sink.valid.eq(valid)
                if valid:
                    yield dut.gearbox.sink.data.eq(words[input_index])
                yield dut.gearbox.source.ready.eq(1)
                yield dut.gearbox.slip.eq(slip)

                sink_ready = (yield dut.gearbox.sink.ready)
                source_valid = (yield dut.gearbox.source.valid)
                source_data = (yield dut.gearbox.source.data)
                if valid and sink_ready:
                    input_index += 1
                if source_valid:
                    outputs.append(source_data)
                yield
                if len(outputs) == len(expected):
                    break

        run_simulation(dut, generators={"sys": generator()}, clocks={"sys": 10})
        self.assertEqual(outputs, expected)


if __name__ == "__main__":
    unittest.main()

#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

import unittest

from migen import *

from litex.gen import *
from litex.gen.sim import *

from liteiclink.serdes.pcs.scrambler import Descrambler, Scrambler


# DUT ------------------------------------------------------------------------------------------------

class DUT(LiteXModule):
    def __init__(self, width=64, reset_value=(1 << 58) - 1, roundtrip=True):
        self.cd_sys = ClockDomain()
        self.scrambler   = Scrambler(width=width, reset_value=reset_value)
        if roundtrip:
            self.descrambler = Descrambler(width=width, reset_value=reset_value)
            self.comb += self.scrambler.source.connect(self.descrambler.sink)


# Test 64b/66b Scrambler -----------------------------------------------------------------------------

class TestScrambler(unittest.TestCase):
    def test_clause_49_serial_reference_vector(self):
        # Clause 49 permits any initial state. This vector uses all ones as
        # a fixed test seed and serializes each 64-bit word least-significant
        # bit first, as specified by Figure 49-8's register convention.
        words = [
            0x0123456789abcdef,
            0xfedcba9876543210,
            0x0000000000000000,
            0xffffffffffffffff,
        ]
        expected = [
            0x6b3a4d6789abcdef,
            0xd967221875542ee3,
            0x254bdc64d2445c81,
            0xc304a29cc958dce4,
        ]
        dut = DUT(roundtrip=False)
        outputs = []

        def generator():
            input_index = 0
            for _ in range(32):
                valid = input_index < len(words)
                yield dut.scrambler.sink.valid.eq(valid)
                if valid:
                    yield dut.scrambler.sink.data.eq(words[input_index])
                yield dut.scrambler.source.ready.eq(1)

                sink_ready = (yield dut.scrambler.sink.ready)
                source_valid = (yield dut.scrambler.source.valid)
                source_data = (yield dut.scrambler.source.data)
                if valid and sink_ready:
                    input_index += 1
                if source_valid:
                    outputs.append(source_data)
                yield
                if input_index == len(words) and len(outputs) == len(words):
                    break

        run_simulation(dut, generators={"sys": generator()}, clocks={"sys": 10})
        self.assertEqual([f"{word:016x}" for word in outputs],
                         [f"{word:016x}" for word in expected])

    def test_roundtrip_across_words(self):
        words = [((i * 0x1f123bb5a5a5a5a5) ^ (i << 37) ^ 0xdeadbeef01234567) & ((1 << 64) - 1)
                 for i in range(24)]
        dut = DUT()
        outputs = []

        def generator():
            input_index = 0
            for cycle in range(512):
                valid = input_index < len(words)
                ready = True
                yield dut.scrambler.sink.valid.eq(valid)
                if valid:
                    yield dut.scrambler.sink.data.eq(words[input_index])
                yield dut.descrambler.source.ready.eq(ready)

                sink_ready = (yield dut.scrambler.sink.ready)
                source_valid = (yield dut.descrambler.source.valid)
                source_ready = (yield dut.descrambler.source.ready)
                source_data = (yield dut.descrambler.source.data)
                if valid and sink_ready:
                    input_index += 1
                if source_valid and source_ready:
                    outputs.append(source_data)
                yield
                if input_index == len(words) and len(outputs) == len(words):
                    break

        run_simulation(dut, generators={"sys": generator()}, clocks={"sys": 10})
        self.assertEqual(outputs, words)


if __name__ == "__main__":
    unittest.main()

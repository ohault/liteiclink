#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

import unittest

from migen import *

from litex.gen import *
from litex.gen.sim import *

from liteiclink.serdes.pcs.tx import BlockTX, DataBlockTX


# DUT ------------------------------------------------------------------------------------------------

class DUT(LiteXModule):
    def __init__(self):
        self.cd_sys = ClockDomain()
        self.encoder = DataBlockTX(reset_value=(1 << 58) - 1)


class GenericDUT(LiteXModule):
    def __init__(self):
        self.cd_sys = ClockDomain()
        self.encoder = BlockTX(reset_value=(1 << 58) - 1)


# Test 64b/66b Data-Block Transmitter ----------------------------------------------------------------

class TestDataBlockTX(unittest.TestCase):
    def test_header_and_scrambled_payload(self):
        payloads = [
            0x0123456789abcdef,
            0xfedcba9876543210,
            0x0000000000000000,
            0xffffffffffffffff,
        ]
        scrambled = [
            0x6b3a4d6789abcdef,
            0xd967221875542ee3,
            0x254bdc64d2445c81,
            0xc304a29cc958dce4,
        ]
        expected = [(word << 2) | 0b10 for word in scrambled]
        dut = DUT()
        outputs = []

        def generator():
            input_index = 0
            for _ in range(32):
                valid = input_index < len(payloads)
                yield dut.encoder.sink.valid.eq(valid)
                if valid:
                    yield dut.encoder.sink.data.eq(payloads[input_index])
                yield dut.encoder.source.ready.eq(1)

                sink_ready = (yield dut.encoder.sink.ready)
                source_valid = (yield dut.encoder.source.valid)
                source_data = (yield dut.encoder.source.data)
                if valid and sink_ready:
                    input_index += 1
                if source_valid:
                    outputs.append(source_data)
                yield
                if input_index == len(payloads) and len(outputs) == len(payloads):
                    break

        run_simulation(dut, generators={"sys": generator()}, clocks={"sys": 10})
        self.assertEqual(outputs, expected)
        self.assertTrue(all((block & 0b11) == 0b10 for block in outputs))


class TestGenericBlockTX(unittest.TestCase):
    def test_data_and_control_headers_with_stalls(self):
        payloads = [
            (0x0123456789abcdef, 0),
            (0xfedcba9876543210, 1),
            (0x0000000000000000, 0),
            (0xffffffffffffffff, 1),
        ]
        scrambled = [
            0x6b3a4d6789abcdef,
            0xd967221875542ee3,
            0x254bdc64d2445c81,
            0xc304a29cc958dce4,
        ]
        expected = [(word << 2) | (0b01 if control else 0b10)
                    for (payload, control), word in zip(payloads, scrambled)]
        dut = GenericDUT()
        outputs = []

        def producer():
            for payload, control in payloads:
                yield dut.encoder.sink.valid.eq(1)
                yield dut.encoder.sink.data.eq(payload)
                yield dut.encoder.sink.control.eq(control)
                while True:
                    yield
                    if (yield dut.encoder.sink.ready):
                        break
            yield dut.encoder.sink.valid.eq(0)

        def consumer():
            for cycle in range(128):
                yield dut.encoder.source.ready.eq(cycle % 4 != 0)
                yield
                if (yield dut.encoder.source.valid) and (yield dut.encoder.source.ready):
                    outputs.append((yield dut.encoder.source.data))
                if len(outputs) == len(expected):
                    break

        run_simulation(dut, [producer(), consumer()], clocks={"sys": 10})
        self.assertEqual(outputs, expected)


if __name__ == "__main__":
    unittest.main()

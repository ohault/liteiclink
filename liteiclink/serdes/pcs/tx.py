#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream

from liteiclink.serdes.pcs.scrambler import Scrambler


def _control_code(byte):
    """Map an XGMII control character to its Clause 49 seven-bit code."""
    codes = {
        0x07: 0x00, # /I/
        0x06: 0x06, # /LI/
        0xfe: 0x1e, # /E/
        0x1c: 0x2d, # /R/
        0x3c: 0x33,
        0x7c: 0x4b,
        0xbc: 0x55,
        0xdc: 0x66,
        0xf7: 0x78,
    }
    expression = Constant(0x1e, 7) # Invalid control character -> /E/.
    for xgmii_code, pcs_code in reversed(list(codes.items())):
        expression = Mux(byte == xgmii_code, Constant(pcs_code, 7), expression)
    return expression


# Generic 64b/66b Block Transmitter ---------------------------------------------------------------

class BlockTX(LiteXModule):
    """Add 64b/66b sync headers and scramble generic 64-bit block payloads.

    ``sink.control`` selects the sync header: 0 produces ``10`` (data),
    and 1 produces ``01`` (control). Payload bit 0 is transmitted first.
    The header bypasses the payload scrambler and remains aligned under stalls.
    """
    def __init__(self, reset_value=0):
        self.sink   = sink   = stream.Endpoint([("data", 64), ("control", 1)])
        self.source = source = stream.Endpoint([("data", 66)])

        self.scrambler = scrambler = Scrambler(width=64, reset_value=reset_value)
        header = Signal(2, reset=0b10)

        self.comb += [
            scrambler.sink.data.eq(sink.data),
            scrambler.sink.valid.eq(sink.valid),
            sink.ready.eq(scrambler.sink.ready),
            scrambler.source.ready.eq(source.ready),
            source.valid.eq(scrambler.source.valid),
            source.data.eq(Cat(header, scrambler.source.data)),
        ]
        self.sync += If(sink.valid & sink.ready,
            header.eq(Mux(sink.control, 0b01, 0b10))
        )


# 64b/66b Data and Control-Block Transmitter ----------------------------------------------------------

class DataBlockTX(LiteXModule):
    """Encode XGMII transfers as scrambled 64b/66b data or control blocks.

    ``sink.data`` contains eight XGMII octets, lane 0 in the least-significant
    byte. ``sink.ctrl`` marks control lanes. Data blocks, full control blocks,
    start/terminate blocks, and the Clause 49 ordered-set formats are supported.
    """
    def __init__(self, reset_value=0):
        self.sink   = sink   = stream.Endpoint([("data", 64), ("ctrl", 8)])
        self.source = source = stream.Endpoint([("data", 66)])

        self.block_tx = block_tx = BlockTX(reset_value=reset_value)
        raw_payload = Signal(64)
        control_block = Signal()

        self.comb += [raw_payload.eq(sink.data), control_block.eq(0)]

        # Build the encoded payload for the supported XGMII control formats.
        encoding = If((sink.ctrl == 0xff) & (sink.data[:8] != 0xfd),
            control_block.eq(1),
            raw_payload.eq(Cat(Constant(0x1e, 8), *[_control_code(sink.data[8*i:8*(i+1)]) for i in range(8)]))
        ).Elif((sink.ctrl == 0x01) & (sink.data[:8] == 0xfb),
            control_block.eq(1),
            raw_payload.eq(Cat(Constant(0x78, 8), sink.data[8:64]))
        )

        # Terminate delimiter in lane k, then control characters in higher lanes.
        term_types = [0x87, 0x99, 0xaa, 0xb4, 0xcc, 0xd2, 0xe1, 0xff]
        for lane, block_type in enumerate(term_types):
            term_mask = (0xff << lane) & 0xff
            condition = (sink.ctrl == term_mask) & (sink.data[8*lane:8*(lane+1)] == 0xfd)
            parts = [Constant(block_type, 8)]
            parts += [sink.data[8*i:8*(i+1)] for i in range(lane)]
            parts += [_control_code(sink.data[8*i:8*(i+1)]) for i in range(lane + 1, 8)]
            if lane < 7:
                parts += [Constant(0, 7 - lane)]
            encoding = encoding.Elif(condition,
                control_block.eq(1),
                raw_payload.eq(Cat(*parts))
            )

        # Sequence/signal ordered-set at lane 0, with an O code for /Q/ or /Fsig/.
        encoding = encoding.Elif((sink.ctrl == 0xf1) & ((sink.data[:8] == 0x9c) | (sink.data[:8] == 0x5c)),
            control_block.eq(1),
            raw_payload.eq(Cat(Constant(0x4b, 8), sink.data[8:32], Mux(sink.data[:8] == 0x5c, Constant(0xf, 4), Constant(0, 4)),
                              *[_control_code(sink.data[8*i:8*(i+1)]) for i in range(4, 8)]))
        )
        # Ordered set at lane 4 after four control characters.
        encoding = encoding.Elif((sink.ctrl == 0x1f) & ((sink.data[32:40] == 0x9c) | (sink.data[32:40] == 0x5c)),
            control_block.eq(1),
            raw_payload.eq(Cat(Constant(0x2d, 8), *[_control_code(sink.data[8*i:8*(i+1)]) for i in range(4)],
                              Mux(sink.data[32:40] == 0x5c, Constant(0xf, 4), Constant(0, 4)), sink.data[40:64]))
        ).Elif((sink.ctrl == 0x1f) & (sink.data[32:40] == 0xfb),
            control_block.eq(1),
            raw_payload.eq(Cat(Constant(0x33, 8), *[_control_code(sink.data[8*i:8*(i+1)]) for i in range(4)],
                              Constant(0, 4), sink.data[40:64]))
        )
        # Ordered-set or start delimiter in lane 4, preceded by /Q/ in lane 0.
        encoding = encoding.Elif((sink.ctrl == 0x11) & ((sink.data[:8] == 0x9c) | (sink.data[:8] == 0x5c)) & (sink.data[32:40] == 0xfb),
            control_block.eq(1),
            raw_payload.eq(Cat(Constant(0x66, 8), sink.data[8:32], Mux(sink.data[:8] == 0x5c, Constant(0xf, 4), Constant(0, 4)), Constant(0, 4), sink.data[40:64]))
        ).Elif((sink.ctrl == 0x11) & ((sink.data[:8] == 0x9c) | (sink.data[:8] == 0x5c)) & ((sink.data[32:40] == 0x9c) | (sink.data[32:40] == 0x5c)),
            control_block.eq(1),
            raw_payload.eq(Cat(Constant(0x55, 8), sink.data[8:32], Mux(sink.data[:8] == 0x5c, Constant(0xf, 4), Constant(0, 4)), Mux(sink.data[32:40] == 0x5c, Constant(0xf, 4), Constant(0, 4)), sink.data[40:64]))
        )
        self.comb += encoding

        self.comb += [
            block_tx.sink.data.eq(raw_payload),
            block_tx.sink.control.eq(control_block),
            block_tx.sink.valid.eq(sink.valid),
            sink.ready.eq(block_tx.sink.ready),
            block_tx.source.connect(source),
        ]

#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

from functools import reduce
from operator import or_

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream

from liteiclink.serdes.pcs.gearbox import BitstreamGearbox
from liteiclink.serdes.pcs.scrambler import Descrambler


# 64b/66b Block Synchronizer -------------------------------------------------------------------------

class BlockSynchronizer(LiteXModule):
    """Check 66-bit block headers and request one-bit slips when needed.

    The input is a stream of 66-bit candidate blocks from a bitstream
    converter. ``slip`` requests that converter to advance its candidate
    boundary by one bit. The converter must honor each pulse before
    presenting the next candidate block. This module acquires lock after a
    clean 64-header window and loses lock after the standard invalid-header
    threshold. While unlocked, input candidates are consumed and discarded.
    """
    def __init__(self):
        self.sink   = sink   = stream.Endpoint([("data", 66)])
        self.source = source = stream.Endpoint([("data", 66)])

        self.block_lock = Signal()
        self.slip       = Signal()

        sh_count         = Signal(7)
        sh_invalid_count = Signal(5)

        sh_valid = sink.data[0] ^ sink.data[1]
        input_transfer = sink.valid & sink.ready

        next_sh_count         = Signal(7)
        next_sh_invalid_count = Signal(5)
        self.comb += [
            next_sh_count.eq(sh_count + 1),
            next_sh_invalid_count.eq(sh_invalid_count + ~sh_valid),

            sink.ready.eq(~self.block_lock | source.ready),
            source.valid.eq(self.block_lock & sink.valid),
            source.data.eq(sink.data),
        ]

        # IEEE 802.3 Clause 49 Figure 49-14: 64 valid headers in a window
        # acquire lock. An invalid header requests a one-bit slip while
        # unlocked (sh_invalid_cnt = 16 + !block_lock); while locked, 16
        # invalid headers in a window clear lock and request a slip. A locked
        # window with fewer than 16 invalid headers retains lock and starts
        # another 64-header window.
        slip_request = ~sh_valid & (~self.block_lock | (next_sh_invalid_count >= 16))
        self.sync += [
            self.slip.eq(0),
            If(input_transfer,
                If(slip_request,
                    self.block_lock.eq(0),
                    self.slip.eq(1),
                    sh_count.eq(0),
                    sh_invalid_count.eq(0),
                ).Elif(next_sh_count == 64,
                    If(next_sh_invalid_count == 0,
                        self.block_lock.eq(1)
                    ),
                    sh_count.eq(0),
                    sh_invalid_count.eq(0),
                ).Else(
                    sh_count.eq(next_sh_count),
                    sh_invalid_count.eq(next_sh_invalid_count),
                )
            )
        ]


def _control_character(code):
    """Map a Clause 49 seven-bit control code back to its XGMII character."""
    codes = {
        0x00: 0x07, # /I/
        0x06: 0x06, # /LI/
        0x1e: 0xfe, # /E/
        0x2d: 0x1c, # /R/
        0x33: 0x3c,
        0x4b: 0x7c,
        0x55: 0xbc,
        0x66: 0xdc,
        0x78: 0xf7,
    }
    expression = Constant(0xfe, 8)
    for pcs_code, xgmii_code in reversed(list(codes.items())):
        expression = Mux(code == pcs_code, Constant(xgmii_code, 8), expression)
    return expression


# Generic 64b/66b Block Receiver -------------------------------------------------------------------

class BlockRX(LiteXModule):
    """Find 64b/66b block boundaries and descramble their 64-bit payloads.

    The serial input is bit 0 first. Valid blocks are emitted with their
    payload and a ``control`` flag (1 for sync header ``01``, 0 for ``10``).
    Block lock and the upstream one-bit slip request are exposed for status
    and integration with PMA-specific alignment logic.
    """
    def __init__(self, reset_value=0, input_width=1):
        assert input_width > 0
        self.sink   = sink   = stream.Endpoint([("data", input_width)])
        self.source = source = stream.Endpoint([("data", 64), ("control", 1)])

        self.block_lock = Signal()
        self.gearbox = gearbox = BitstreamGearbox(in_width=input_width, out_width=66)
        self.synchronizer = synchronizer = BlockSynchronizer()
        self.descrambler = descrambler = Descrambler(width=64, reset_value=reset_value)

        header = synchronizer.source.data[:2]
        header_valid = (header == 0b01) | (header == 0b10)
        output_control      = Signal()
        output_header_valid = Signal()

        # Every locked block goes through the self-synchronizing descrambler, including blocks with
        # an invalid sync header: skipping their payload would break the descrambler history and
        # corrupt the following valid block. Invalid blocks are dropped at the descrambler output.
        # The header flags are registered on the same transfer as the descrambler stage, so they
        # stay aligned with its output under backpressure.
        self.comb += [
            sink.connect(gearbox.sink),
            gearbox.source.connect(synchronizer.sink),
            gearbox.slip.eq(synchronizer.slip),
            self.block_lock.eq(synchronizer.block_lock),

            descrambler.sink.data.eq(synchronizer.source.data[2:]),
            descrambler.sink.valid.eq(synchronizer.source.valid),
            synchronizer.source.ready.eq(descrambler.sink.ready),

            source.valid.eq(descrambler.source.valid & output_header_valid),
            source.data.eq(descrambler.source.data),
            source.control.eq(output_control),
            descrambler.source.ready.eq(source.ready | ~output_header_valid),
        ]
        self.sync += If(synchronizer.source.valid & synchronizer.source.ready,
            output_control.eq(header == 0b01),
            output_header_valid.eq(header_valid),
        )


# 64b/66b Data and Control-Block Receiver --------------------------------------------------------------

class DataBlockRX(LiteXModule):
    """Recover eight XGMII lanes from a serial 64b/66b stream.

    The one-bit sink uses bit 0 first. The output carries eight XGMII bytes
    in ``data`` and their control mask in ``ctrl``. Data, full-control,
    start, terminate, and lane-0 sequence ordered-set blocks are decoded.
    """
    def __init__(self, reset_value=0):
        self.sink   = sink   = stream.Endpoint([("data", 1)])
        self.source = source = stream.Endpoint([("data", 64), ("ctrl", 8)])

        self.block_rx = block_rx = BlockRX(reset_value=reset_value)
        # Keep access to the framing primitives for status and debug users.
        self.block_lock = block_rx.block_lock
        self.gearbox = block_rx.gearbox
        self.synchronizer = block_rx.synchronizer
        self.descrambler = block_rx.descrambler

        is_control_block = block_rx.source.control
        is_data_block = ~is_control_block
        payload = block_rx.source.data
        block_type = payload[:8]

        terminate_types = [0x87, 0x99, 0xaa, 0xb4, 0xcc, 0xd2, 0xe1, 0xff]
        supported_types = [0x1e, 0x2d, 0x33, 0x4b, 0x55, 0x66, 0x78] + terminate_types
        known_control_type = reduce(or_, [block_type == t for t in supported_types])
        decoded_valid = is_data_block | (is_control_block & known_control_type)

        lane_bytes = []
        lane_controls = []
        for lane in range(8):
            byte = Signal(8)
            control = Signal()
            decode = If(is_data_block,
                byte.eq(payload[8*lane:8*(lane+1)]), control.eq(0)
            ).Elif(is_control_block & (block_type == 0x1e),
                byte.eq(_control_character(payload[8 + 7*lane:8 + 7*(lane+1)])), control.eq(1)
            ).Elif(is_control_block & (block_type == 0x78),
                If(lane == 0,
                    byte.eq(0xfb), control.eq(1)
                ).Else(
                    byte.eq(payload[8 + 8*(lane-1):8 + 8*lane]), control.eq(0)
                )
            ).Elif(is_control_block & (block_type == 0x4b),
                If(lane == 0,
                    byte.eq(Mux(payload[32:36] == 0xf, 0x5c, 0x9c)), control.eq(1)
                ).Elif(lane < 4,
                    byte.eq(payload[8*lane:8*(lane+1)]), control.eq(0)
                ).Else(
                    byte.eq(_control_character(payload[36 + 7*(lane-4):36 + 7*(lane-3)])), control.eq(1)
                )
            ).Elif(is_control_block & (block_type == 0x2d),
                If(lane < 4,
                    byte.eq(_control_character(payload[8 + 7*lane:8 + 7*(lane+1)])), control.eq(1)
                ).Elif(lane == 4,
                    byte.eq(Mux(payload[36:40] == 0xf, 0x5c, 0x9c)), control.eq(1)
                ).Else(
                    byte.eq(payload[40 + 8*(lane-5):48 + 8*(lane-5)]), control.eq(0)
                )
            ).Elif(is_control_block & (block_type == 0x33),
                If(lane < 4,
                    byte.eq(_control_character(payload[8 + 7*lane:8 + 7*(lane+1)])), control.eq(1)
                ).Elif(lane == 4,
                    byte.eq(0xfb), control.eq(1)
                ).Else(
                    byte.eq(payload[40 + 8*(lane-5):48 + 8*(lane-5)]), control.eq(0)
                )
            ).Elif(is_control_block & ((block_type == 0x66) | (block_type == 0x55)),
                If(lane == 0,
                    byte.eq(Mux(payload[32:36] == 0xf, 0x5c, 0x9c)), control.eq(1)
                ).Elif(lane == 4,
                    If(block_type == 0x55,
                        byte.eq(Mux(payload[36:40] == 0xf, 0x5c, 0x9c)), control.eq(1)
                    ).Else(
                        byte.eq(0xfb), control.eq(1)
                    )
                ).Elif(lane < 4,
                    byte.eq(payload[8*lane:8*(lane+1)]), control.eq(0)
                ).Else(
                    byte.eq(payload[40 + 8*(lane-5):48 + 8*(lane-5)]), control.eq(0)
                )
            )
            for terminate_lane, terminate_type in enumerate(terminate_types):
                if lane < terminate_lane:
                    byte_value = payload[8 + 8*lane:16 + 8*lane]
                    ctrl_value = 0
                elif lane == terminate_lane:
                    byte_value = Constant(0xfd, 8)
                    ctrl_value = 1
                else:
                    code_start = 8 + 8*terminate_lane + 7*(lane-terminate_lane-1)
                    byte_value = _control_character(payload[code_start:code_start+7])
                    ctrl_value = 1
                decode = decode.Elif(is_control_block & (block_type == terminate_type),
                    byte.eq(byte_value), control.eq(ctrl_value)
                )
            self.comb += decode
            lane_bytes.append(byte)
            lane_controls.append(control)

        self.comb += [
            sink.connect(block_rx.sink),
            block_rx.source.ready.eq(source.ready | ~decoded_valid),
            source.valid.eq(block_rx.source.valid & decoded_valid),
            source.data.eq(Cat(*lane_bytes)),
            source.ctrl.eq(Cat(*lane_controls)),
        ]

#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream


# Bitstream Gearbox ---------------------------------------------------------------------------------

class BitstreamGearbox(LiteXModule):
    """Convert a continuous bitstream between parallel word widths.

    The least-significant bit of each input word is the earliest bit in time.
    Output words use the same convention: bit 0 is the earliest bit in the
    output word.

    The gearbox does not know about PCS blocks, headers, symbols, or line
    codes. It only preserves the order of bits. Input and output widths are
    independent positive integers.

    The ready/valid interface supports backpressure. Bits already accepted
    from the input remain buffered until transferred to the output. A reset
    discards any partially accumulated word. An optional one-cycle ``slip``
    request discards one earliest buffered bit without emitting an output
    word, allowing a block synchronizer to scan the full input bit alignment.
    """
    def __init__(self, in_width, out_width):
        assert in_width  > 0
        assert out_width > 0

        self.sink   = sink   = stream.Endpoint([("data", in_width)])
        self.source = source = stream.Endpoint([("data", out_width)])
        self.slip   = Signal()

        # # #

        # Keep enough space for the largest occupancy reached by accepting
        # one input word when no output word is consumed.
        buffer_width = 2*in_width + out_width - 1
        count_width  = bits_for(buffer_width)

        buffer = Signal(buffer_width)
        count  = Signal(count_width)
        slip_pending = Signal()

        slip_request = self.slip | slip_pending
        slip_pop     = slip_request & (count != 0)

        self.comb += [
            source.data.eq(buffer[:out_width]),
            source.valid.eq((count >= out_width) & ~slip_request),
        ]

        # A normal output transfer or a one-bit slip may make room for an
        # input word in the same cycle.
        pop = (source.valid & source.ready) | slip_pop
        pop_width = Mux(slip_pop, 1, out_width)
        self.comb += sink.ready.eq(
            Mux(pop,
                count <= (buffer_width - in_width + pop_width),
                count <= (buffer_width - in_width)
            )
        )

        push = sink.valid & sink.ready

        count_after_pop = Signal(count_width)
        self.comb += If(pop,
            count_after_pop.eq(count - pop_width)
        ).Else(
            count_after_pop.eq(count)
        )

        shifted_buffer = Mux(slip_pop, buffer >> 1, buffer >> out_width)

        self.sync += [
            If(slip_request,
                If(slip_pop,
                    slip_pending.eq(0)
                ).Else(
                    slip_pending.eq(1)
                )
            ).Else(
                slip_pending.eq(0)
            ),
            If(push | pop,
                count.eq(count_after_pop + Mux(push, in_width, 0)),
                If(pop,
                    If(push,
                        buffer.eq(shifted_buffer | (Cat(sink.data, Constant(0, buffer_width - in_width)) << count_after_pop))
                    ).Else(
                        buffer.eq(shifted_buffer)
                    )
                ).Elif(push,
                    buffer.eq(buffer | (Cat(sink.data, Constant(0, buffer_width - in_width)) << count))
                )
            )
        ]

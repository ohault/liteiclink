#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream


# 64b/66b Self-Synchronizing Scrambler --------------------------------------------------------------

class Scrambler(LiteXModule):
    """Scramble or descramble a continuous bitstream with the Clause 49 polynomial.

    Input and output bit 0 are the earliest bit in time. The 64b/66b sync
    header is not part of this interface: connect only the 64-bit payload.

    For the scrambler, each output bit is ``input[n] ^ output[n-39] ^
    output[n-58]``. For the descrambler, the same recurrence uses received
    scrambled bits at both delay taps. The 58-bit delay state advances only
    when a ready/valid transfer occurs, so stalls do not change the stream.

    Clause 49 does not require a particular initial state. ``reset_value``
    selects a deterministic implementation reset value; both link ends need
    at least 58 payload bits to self-synchronize after a state mismatch.
    """
    def __init__(self, width=64, descramble=False, reset_value=0):
        assert width > 0
        assert 0 <= reset_value < (1 << 58)

        self.sink   = sink   = stream.Endpoint([("data", width)])
        self.source = source = stream.Endpoint([("data", width)])

        # State bit 0 holds the most recently processed payload bit. Thus
        # taps 38 and 57 correspond to delays of 39 and 58 bits.
        state = Signal(58, reset=reset_value)

        output_bits = []
        for i in range(width):
            # Expand the parallel recurrence directly. Bits at least 39/58
            # positions behind this bit are in the current word; earlier
            # taps come from the registered history. This avoids a long
            # chain of 58-bit shift expressions in the combinational logic.
            delay_line = [sink.data[j] for j in range(i)] if descramble else output_bits
            tap_39 = delay_line[i - 39] if i >= 39 else state[38 - i]
            tap_58 = delay_line[i - 58] if i >= 58 else state[57 - i]
            output_bit = sink.data[i] ^ tap_39 ^ tap_58
            output_bits.append(output_bit)

        # State bit 0 is the most recent bit. Keep the last 58 transmitted
        # scrambled bits for the scrambler and received scrambled bits for
        # the descrambler, retaining older state when width is below 58.
        state_bits = [sink.data[i] if descramble else output_bits[i]
                      for i in range(width)]
        next_state = Cat(*list(reversed(state_bits[-58:])))
        if width < 58:
            next_state = Cat(next_state, state[:58-width])

        self.comb += [
            sink.ready.eq(~source.valid | source.ready),
        ]
        self.sync += If(sink.ready,
            source.valid.eq(sink.valid),
            If(sink.valid,
                source.data.eq(Cat(*output_bits)),
                state.eq(next_state)
            )
        )


class Descrambler(Scrambler):
    """Clause 49 self-synchronizing descrambler."""
    def __init__(self, width=64, reset_value=0):
        super().__init__(width=width, descramble=True, reset_value=reset_value)

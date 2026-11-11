# Physical Coding Sublayer (PCS)

## Scope

The PCS package contains vendor-independent line-coding and block-processing
logic. It is deliberately separate from the transceiver-specific PMA wrappers
in `liteiclink/serdes/`.

The first implementation target is a full-duplex FPGA-to-FPGA link between
two LiteX Acorn Baseboard Mini boards over SFP0. The initial physical backend
is Xilinx 7-series GTP. The PCS itself must not depend on a GTP class or on
the Acorn board.

The PCS does not implement an Ethernet MAC, Ethernet framing, packet routing,
or an application protocol. Those functions belong above the PCS.

## Layer boundaries

The intended transmit path is:

```
upper-layer block stream
        |
        v
      PCS TX
  - block formation
  - optional scrambling
  - line coding / sync header
  - continuous bitstream gearbox
        |
        v
      PMA TX
  - vendor-specific parallel interface
  - serializer and electrical interface
```

The receive path is the reverse:

```
      PMA RX
  - vendor-specific parallel interface
  - deserializer
        |
        v
      PCS RX
  - continuous bitstream gearbox
  - block synchronization
  - descrambling
  - block interpretation
        |
        v
upper-layer block stream
```

The PMA boundary is a parallel bitstream interface. Its word width is a
property of the selected transceiver configuration, not of the PCS. The PCS
must therefore not assume that its logical block width is an integer multiple
of the PMA word width.

## Alignment is layered

Three different mechanisms must remain distinct:

1. **PMA word alignment** establishes the parallel word boundaries emitted by
   the transceiver. It is a transceiver/backend concern.
2. **PCS block synchronization** finds the 66-bit block boundaries from the
   64b/66b synchronization headers. It is a PCS receive function and must be
   able to acquire, lose, and reacquire block lock.
3. **Protocol framing** identifies packets or messages above the PCS. It is
   not provided by 64b/66b block synchronization.

In particular, the existing comma-based `BruteforceClockAligner` is not a
64b/66b block synchronizer and must not be reused for that purpose.

## Initial coding convention

The initial coding target is the IEEE 802.3 64b/66b convention:

- 64-bit block payload preceded by a 2-bit synchronization header;
- `01` denotes a data block and `10` denotes a control block;
- the synchronization header is not scrambled;
- the 64-bit block payload is scrambled according to the selected standard
  convention.

The implementation must explicitly document bit order at every boundary.
The scrambler polynomial, state initialization, shift direction, and bit
ordering must be verified against independent reference vectors before
hardware integration. A generic LFSR that merely uses a familiar polynomial
is not sufficient evidence of interoperability.

The first milestone may constrain which control-block formats are supported,
but that restriction must be explicit and tested. No Ethernet MAC or Ethernet
frame format is implied by using the IEEE 802.3 64b/66b coding convention.

## Gearbox requirements

A 66-bit logical block stream does not align naturally with common transceiver
parallel widths such as 20, 40, or 80 bits. The gearbox must operate as a
continuous bitstream converter, retaining bit position across parallel words
and across block boundaries.

It must not wait for a complete least-common-multiple-sized batch before
producing output. For example, the 66-to-20 conversion has a 660-bit common
period, but the datapath must stream continuously.

The gearbox contract and tests will define:

- least-significant-bit-first temporal ordering (bit 0 is transmitted first);
- continuous operation across consecutive input words;
- valid/ready backpressure behavior;
- reset behavior, including reset with a partially accumulated word;
- supported input/output widths and behavior for unequal TX/RX widths.

## PMA capabilities

A backend must report actual capabilities rather than capabilities inferred
from a transceiver family name. Relevant properties include:

- TX and RX parallel datapath widths;
- TX and RX clock domains;
- availability of raw TX and RX datapaths;
- TX and RX readiness;
- availability and semantics of physical RX word alignment;
- availability of native encoding or gearbox functions, if used.

Native transceiver functions are optional optimizations. A backend without a
native gearbox or encoder must remain usable when the function can be
implemented in fabric. The PCS must not silently assume that a raw datapath
exists: this must be verified for each wrapper and primitive configuration.

## Compatibility constraints

- Existing LiteICLink transceiver wrappers and their public interfaces remain
  unchanged during the initial PCS work.
- Existing 8b/10b behavior remains the default and is not refactored as part
  of the initial PCS work.
- PCS simulation must be possible without instantiating a vendor transceiver.
- The first implementation is added incrementally, with independent tests
  before GTP integration.

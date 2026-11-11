# Initial 64b/66b transmitter block format

`DataBlockTX` accepts a continuous stream of 64-bit payload words and emits
one packed 66-bit 64b/66b data block for each accepted input word. The first
implementation supports data blocks only; control blocks and their block-type
formats remain deferred. The payload is opaque to this layer, so using this
module does not add an Ethernet MAC, packet framing, or an application
protocol.

The block layout in the output vector is:

| Bits | Meaning |
| --- | --- |
| 1:0 | Sync header, data value `01` |
| 65:2 | Scrambled 64-bit payload |

Bit 0 is earliest in time. Therefore the packed value in bits 1:0 is `0b10`,
which transmits as `0` followed by `1`, the data sync header `01`.
Payload bit 0 is the earliest payload bit. The sync header bypasses the
scrambler, which advances continuously across accepted payload words.

IEEE 802.3 Clause 49.2.4.1 states that the leftmost bit in binary values is
transmitted first and that TxB<0> is the first transmitted bit. Clause
49.2.4.3 assigns `01` to data blocks and `10` to control blocks; Clause
49.2.6 specifies that the header bypasses payload scrambling. See
[IEEE 802.3 Clause 49](https://www.my-wire.de/schnittstellenbeschreibung/ethernet.pdf).

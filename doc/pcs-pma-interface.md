# PCS/PMA boundary audit and interface proposal

**Status:** M1 raw PMA mode and the initial M2 generic 64b/66b substrate are
implemented on this branch. The generic PCS-to-PHY link and GTP adapter are
covered by simulation/elaboration tests. The Acorn CLE-215+ hardware example
is prepared, but no physical-board validation has been run.

## Purpose and ownership

The goal in issue [#62](https://github.com/enjoy-digital/liteiclink/issues/62)
is to make coding selectable independently of the FPGA transceiver and to
support non-Ethernet FPGA links. It does not require LiteICLink to reimplement
Ethernet's MAC or its BASE-R PCS.

LiteEth already owns the Ethernet-specific path: MAC-facing stream, XGMII
adapter, IEEE 802.3 Clause 49 64b/66b encoder/decoder, scrambler, block lock,
and Ethernet link diagnostics. Its BASE-R PHY composes that PCS with a
transceiver-specific PMA. The PMA uses LiteICLink's PLL and transceiver
initialization support. Keep this division intact: Ethernet/XGMII semantics
belong in LiteEth.

LiteICLink owns the FPGA/transceiver-specific resources: PLLs, DRP, primitive
configuration, reset and initialization, physical datapath clocks, and
transceiver data paths. A generic coding experiment in LiteICLink must not
require XGMII, MAC framing, Ethernet control characters, or BASE-R link
semantics.

## Existing interfaces found in source

### LiteICLink GTP

`GTP` currently offers 20- or 40-bit transceiver datapaths. Its public stream
endpoint presents `data` bytes plus a `ctrl` bit per byte; the wrapper runs a
fabric 8b/10b encoder/decoder around the raw 10-bit symbol lanes. The default
RX comma aligner searches for K28.5 and restarts RX to obtain word alignment.
These are useful existing 8b/10b services, but they are not a generic raw PCS
interface. See [GTP implementation](../liteiclink/serdes/gtp_7series.py)
and [SerDes interface documentation](serdes.md).

### LiteEth BASE-R

LiteEth's `PCS` converts XGMII transfers to 64-bit payload plus 2-bit header,
then scrambles and connects to a PMA. On RX it consumes the corresponding
PMA data/header, performs block synchronization, descrambling, block
classification, error handling, and returns XGMII. The PMA wrapper exposes
its data/header lanes and an RX bitslip request to the PCS. The LiteEth BASE-R
wrapper composes PCS and PMA, while importing LiteICLink's PLL and transceiver
helpers. See the [BASE-R design note](https://github.com/enjoy-digital/liteeth/blob/master/doc/baser.md),
[PCS wrapper](https://github.com/enjoy-digital/liteeth/blob/master/liteeth/phy/serial/baser/pcs/__init__.py),
[PCS transmit path](https://github.com/enjoy-digital/liteeth/blob/master/liteeth/phy/serial/baser/pcs/tx.py),
and [UltraScale+ PMA](https://github.com/enjoy-digital/liteeth/blob/master/liteeth/phy/serial/baser/pma/gty_usp.py).

## Proposed first boundary

Add an **opt-in raw PMA interface** to one LiteICLink backend first, while
preserving its current stream API and default behavior. Start with the GTP
backend because it is the Acorn Baseboard Mini target identified in issue #62.

The raw interface should make these facts explicit:

| Item | Proposed contract |
| --- | --- |
| TX data | `data_width` raw bits, driven every `tx` clock |
| RX data | `data_width` raw bits, sampled every `rx` clock |
| Width | A backend-reported/configured physical word width; no fixed 66-bit PMA assumption |
| Clocks | Separate TX and RX clock domains, with frequencies and reset behavior documented |
| Readiness | Existing TX/RX initialization status remains visible |
| Alignment controls | Backend capability for word alignment and/or RX bitslip is exposed explicitly; it is not represented as PCS block lock |
| Coding | No 8b/10b or other line coding in raw mode; the PCS owns coding and block synchronization |
| Default API | Current 8b/10b stream endpoints remain compatible and unchanged unless raw mode is selected |

The PMA should not interpret symbols, block headers, packets, or XGMII control
characters. It delivers raw parallel words and reports transceiver status.
A PCS connects to these words using a width adapter that preserves the
continuous bit order across physical-word boundaries. Coding logic should not
need to know whether the backend width is 20, 40, or another supported value.

A common PCS shell should not pretend every coding scheme has the same payload
format. 8b/10b symbols have data/control characters; a block code has its own
payload and synchronization rules; raw NRZ has no symbol framing. The common
contract can cover PMA attachment, clocks, readiness, synchronization/status
signals, and error reporting, while each coding profile defines its own
payload-side interface.

## Implemented generic boundary and remaining profile work

`BlockTX` and `BlockRX` provide a generic 64b/66b coding substrate. They
apply the 64b/66b sync headers and Clause 49 self-synchronous scrambler
convention; RX also finds block alignment and descrambles the payload. Their
payload interface is a 64-bit block plus a data/control header flag. They do
not encode XGMII control characters, Ethernet frames, MAC traffic, or a custom
non-Ethernet framing format.

`DataBlockTX` and `DataBlockRX` remain a separate XGMII/Clause 49 reference
profile. They are not used as the generic payload interface and are not
connected to LiteEth's BASE-R PCS.

`PCS64b66b` joins the generic block stages to configurable raw PMA word
widths. `RawPHYInterface` defines the continuous-word adapter contract;
`PCS64b66bPHY` places TX and RX logic in their separate clock domains, and
`GTPRawAdapter` maps it to the GTP raw datapath. Payload clock-domain
crossing remains outside this wrapper. The GTP adapter reports TX underflow
and RX overflow because continuous PMA traffic cannot be backpressured.

The exact non-Ethernet block types, framing, link startup, and interoperable
payload protocol are still open design work. The generic 64b/66b substrate
does not define those semantics. The bitstream gearbox remains coding-agnostic
and preserves continuous bit order across width conversions.

## Milestones

1. **M0 — Boundary agreed:** complete. The raw PMA boundary is continuous,
   width-configurable words with separate TX/RX clocks and explicit readiness
   and alignment capability.
2. **M1 — GTP raw mode:** complete. The optional GTP raw mode preserves the
   existing default 8b/10b interface and exposes 20/40-bit raw words.
3. **M2 — Generic 64b/66b substrate:** initial TX/RX block stages, scrambler,
   block lock, width conversion, raw-PHY contract, and GTP adapter are
   implemented and tested. A defined non-Ethernet payload/framing profile is
   still needed before this can be called a complete link protocol.
4. **M3 — Acorn validation:** the GTP PCS loopback bench and host block-lock
   check are prepared for the SQRL Acorn CLE-215+. Physical validation remains
   pending. Check reset, block-lock acquisition/recovery, payload integrity,
   and adapter error status on hardware.
5. **Later:** add other PMA backends or coding modes when their precise wire
   formats and interoperability expectations are specified.

LiteEth's Ethernet BASE-R PCS and the existing default GTP 8b/10b interface
remain outside this generic non-Ethernet PCS path.

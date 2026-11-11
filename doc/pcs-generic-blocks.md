# Generic 64b/66b PCS block path

`BlockTX` and `BlockRX` form a vendor-independent 64b/66b block layer.
They do not implement Ethernet frames or XGMII control encoding.

## Transmit

`BlockTX.sink` accepts a 64-bit payload and a `control` bit. `control=0`
selects data sync header `10`; `control=1` selects control sync header `01`.
Payload bit 0 is transmitted first. The two-bit header bypasses the
self-synchronous payload scrambler. Header and payload remain paired through
ready/valid stalls.

The XGMII-specific `DataBlockTX` remains responsible for mapping XGMII lanes
and control characters into the 64-bit payload and control flag. It delegates
header generation and scrambling to `BlockTX`.

## Receive

`BlockRX.sink` accepts serial bits, least-significant bit first, by default.
Its `input_width` parameter can match wider raw PMA words. It performs 66-bit
candidate assembly, header lock and one-bit slip requests, then descrambles
valid block payloads. `BlockRX.source` emits the 64-bit payload
and the decoded `control` flag. `block_lock` is exposed for status. The RX
stage does not interpret control block types or Ethernet/XGMII semantics.

`DataBlockRX` consumes this generic interface and handles the existing Clause
49 control-block and XGMII decoding.

## Raw PMA word integration

`PCS64b66b` in `liteiclink/serdes/pcs/core.py` connects generic block streams
to raw PMA word streams. Its `raw_width` parameter controls both TX and RX
word widths; 20, 40, and 80-bit configurations are covered by loopback tests.
The `tx` endpoint emits PMA words, while `rx` accepts them. `block_lock`
exposes RX synchronization status. The wrapper contains no device-specific
PMA controls; clocking, reset sequencing, and any transceiver-level bitslip
signals remain the responsibility of the PMA integration.

## PHY adapter contract

`RawPHYInterface` defines the raw word boundary used by a PHY adapter:
`tx` accepts words from the PCS, `rx` delivers words to the PCS, and status
reports TX/RX readiness, bit-slip support, TX underflow, and RX overflow.
`PCS64b66bPHY` joins that interface to `PCS64b66b` and places TX and RX logic
in their respective clock domains. It does not add a clock-domain crossing
for the payload side; the system must provide one if its producer or consumer
uses another clock.

`GTPRawAdapter` in `liteiclink/serdes/pcs/gtp.py` implements this contract for
an already-instantiated GTP configured with `raw_datapath=True`. It uses a
small RX FIFO to absorb short stalls. The GTP cannot pause incoming PMA words,
so a sustained RX stall sets sticky `rx_overflow`; a TX gap while the GTP is
ready emits zero words and sets sticky `tx_underflow`. Both flags clear on
reset. The adapter's explicit RX bitslip input is passed to GTP hardware only
when the selected GTP configuration supports it. The PCS block synchronizer's
soft gearbox slip remains separate and is not automatically sent to RXSLIDE.

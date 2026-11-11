# GTP raw datapath

`GTP(..., raw_datapath=True, clock_aligner=False)` exposes the transceiver's
already serialized-width PMA words directly to the fabric. `raw_tx_data` and
`raw_rx_data` are 20 or 40 bits wide, as selected by `data_width`. The TX word
is sampled in the TX clock domain; the RX word is registered in the recovered
RX clock domain. Their bit numbering follows the GTPE2 `TXDATA` and `RXDATA`
ports. The existing TX/RX clocks, initialization readiness, polarity, loopback,
and line PRBS controls remain available.

Raw mode bypasses the fabric 8b/10b encoder and decoder. `add_stream_endpoints()`
therefore raises `RuntimeError` in this mode. The default remains the existing
8b/10b stream interface. Raw mode requires explicitly setting
`clock_aligner=False`; it does not perform K28.5-based alignment. When the RX
buffer is bypassed, `raw_rx_bitslip` controls the GTPE2 `RXSLIDE` input and
`raw_rx_bitslip_supported` is `True`. With the RX buffer enabled, RXSLIDE is
disabled by the primitive configuration and the support flag is `False`.
Call `add_raw_control()` to add raw-mode CSR status for TX/RX readiness and bit
slip capability. When RX bit slip is supported, writing `1` to the
`raw_rx_bitslip_request` CSR sends a one-cycle request into the RX clock domain;
writing `0` does nothing. The capability remains visible in status when RX
buffering makes bit slip unavailable.

This is a raw PMA interface, not an Ethernet PCS or XGMII interface. A protocol
layer must provide its own encoding, framing, and alignment. LiteEth's 1000BASE-X
and 10GBASE-R PCS implementations remain the appropriate place for Ethernet
PCS functions.

The SQRL Acorn CLE-215+ integration example is documented separately in
[`gtp-raw-datapath-acorn.md`](gtp-raw-datapath-acorn.md). The example's board
constraints and host workflow are specific to that platform; the GTP raw
datapath API described above is independent of it.

# SQRL Acorn CLE-215+ raw GTP and 64b/66b PCS example

This is an integration example for one board. LiteICLink's raw GTP API is
board-independent; the PCIe transceiver lane, clock source, LEDs, UARTBone, and
constraints in this example are specific to the SQRL Acorn CLE-215+.

The SoC sends a changing generic 64-bit payload with alternating data/control
sync headers through `PCS64b66bPHY` and `GTPRawAdapter`. The RX path exposes
block lock and adapter underflow/overflow through the `pcs_status` CSR; LED 3
also indicates block lock. The board pins, clocks, LEDs, UARTBone, and GTP
instance are Acorn-specific. The PCS and raw adapter interfaces are reusable.

Build and load the example with the Xilinx tools installed:

```sh
python3 bench/serdes/sqrl_acorn_gtp_raw.py --build --load
```

With the Acorn on a LiteX Acorn Baseboard Mini, add `--baseboard-mini`: UARTBone
then uses the baseboard USB-UART instead of the Acorn P2 header. The GTP lane is
unchanged (PCIe lane 0, the SATA connector on the baseboard); the PCS check runs
in near-end PMA loopback and needs no cable.

The GTP TX buffer is kept (`tx_buffer_enable=True`) and the RX buffer is bypassed
(for the RX bit slip). With the TX buffer bypassed and the fabric reference clock,
TX initialization does not complete on this board. Validated on hardware with this
configuration (CLE-215+, 2.5 Gbps, near-end PMA loopback): block lock in 10/10 runs
(about 48 ms each), no adapter underflow/overflow, and 0 PRBS7/PRBS31 errors on all
RX bit-slip phases.

Connect to the board's UARTBone serial port with LiteX Server (replace the port
with the device name on your host):

```sh
litex_server --uart --uart-port /dev/ttyUSB0 --uart-baudrate 115200
```

In another terminal, check PCS block lock in near-end PMA loopback:

```sh
python3 bench/serdes/test_sqrl_acorn_gtp_pcs.py --csr-csv sqrl_acorn_pcs.csv
```

The utility waits for GTP readiness, enables near-end PMA loopback, waits for
64b/66b block lock, reports adapter errors, then disables loopback. The PCS
transmits continuously during the check.

The separate raw-link PRBS utility remains available for physical-lane
commissioning and bit-slip diagnostics:

```sh
python3 bench/serdes/test_sqrl_acorn_gtp_raw.py --csr-csv sqrl_acorn_pcs.csv
```

It enables PRBS and measures errored PRBS words over successive hardware RX
bit-slip phases. PRBS mode bypasses PCS framing at the transceiver, so it is a
raw link diagnostic rather than a PCS block-lock test.

For an external raw link, connect the Acorn PCIe GTP lane to a far-end device
configured to transmit the selected PRBS polynomial. Use `--external` to leave
internal loopback disabled:

```sh
python3 bench/serdes/test_sqrl_acorn_gtp_raw.py --csr-csv sqrl_acorn_pcs.csv --external
```

The utility still enables local TX PRBS and checks incoming RX PRBS. PRBS errors
are counted per errored word interval, not per erroneous bit, and PRBS checking
does not identify a protocol word boundary. This is a raw link diagnostic, not
Ethernet alignment.

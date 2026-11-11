#!/usr/bin/env python3

#
# This file is part of LiteICLink.
#
# SPDX-License-Identifier: BSD-2-Clause

# TEST ONLY: GTP TX initialization debug on the SQRL Acorn CLE-215+ (on a LiteX Acorn Baseboard Mini),
# PCIe lane 0, reference clock from the fabric. Exposes add_init_status() CSRs; --tx-buffer selects
# the TX buffer mode and --param overrides GTPE2_CHANNEL parameters/ports for experiments.

import argparse

from migen import *

from litex.gen import *

from litex_boards.platforms import sqrl_acorn

from litex.build.generic_platform import *
from litex.build.io import DifferentialInput

from litex.soc.cores.clock import S7PLL
from litex.soc.cores.code_8b10b import K
from litex.soc.integration.soc_core import SoCMini
from litex.soc.integration.builder import Builder

from liteiclink.serdes.gtp_7series import GTPQuadPLL, GTP

_transceiver_io = [
    ("pcie_tx", 0, Subsignal("p", Pins("B6")),  Subsignal("n", Pins("A6"))),
    ("pcie_rx", 0, Subsignal("p", Pins("B10")), Subsignal("n", Pins("A10"))),
]

class CRG(LiteXModule):
    def __init__(self, platform, sys_clk_freq, refclk_freq):
        self.cd_sys    = ClockDomain()
        self.cd_refclk = ClockDomain()
        clk200    = platform.request("clk200")
        clk200_se = Signal()
        self.specials += DifferentialInput(clk200.p, clk200.n, clk200_se)
        self.pll = pll = S7PLL()
        pll.register_clkin(clk200_se, 200e6)
        pll.create_clkout(self.cd_sys,    sys_clk_freq)
        pll.create_clkout(self.cd_refclk, refclk_freq, margin=0)

class TXInitSoC(SoCMini):
    def __init__(self, platform, tx_buffer_enable, params, linerate=2.5e9):
        sys_clk_freq = int(100e6)
        SoCMini.__init__(self, platform, sys_clk_freq,
            ident=f"GTP TX init debug: tx_buffer_enable={int(tx_buffer_enable)} " +
                " ".join(f"{k}={v}" for k, v in params.items()))
        self.add_uartbone()
        self.crg = CRG(platform, sys_clk_freq, 125e6)

        platform.add_platform_command("set_property SEVERITY {{Warning}} [get_drc_checks REQP-49]")
        self.pll = pll = GTPQuadPLL(self.crg.cd_refclk.clk, 125e6, linerate, refclk_from_fabric=True)
        self.serdes0 = serdes0 = GTP(pll, platform.request("pcie_tx"), platform.request("pcie_rx"), sys_clk_freq,
            data_width       = 20,
            tx_buffer_enable = tx_buffer_enable,
            rx_buffer_enable = True,
            clock_aligner    = False,
        )
        serdes0.add_stream_endpoints()
        serdes0.add_controls()
        serdes0.add_init_status()
        for k, v in params.items():
            serdes0.gtp_params[k] = v
        self.comb += [
            serdes0.sink.valid.eq(1),
            serdes0.sink.ctrl.eq(0b01),
            serdes0.sink.data.eq(Cat(Constant(K(28, 5), 8), Constant(0, 8))),
        ]
        platform.add_period_constraint(serdes0.cd_tx.clk, 1e9/serdes0.tx_clk_freq)
        platform.add_period_constraint(serdes0.cd_rx.clk, 1e9/serdes0.rx_clk_freq)
        platform.add_false_path_constraints(self.crg.cd_sys.clk, serdes0.cd_tx.clk, serdes0.cd_rx.clk)

        # Leds: TX ready, RX ready, QPLL lock.
        self.comb += [
            platform.request("user_led", 0).eq(serdes0.tx_ready),
            platform.request("user_led", 1).eq(serdes0.rx_ready),
            platform.request("user_led", 2).eq(pll.lock),
        ]

def main():
    parser = argparse.ArgumentParser(description="TEST ONLY: GTP TX init debug on SQRL Acorn (Baseboard Mini).")
    parser.add_argument("--build",      action="store_true", help="Build bitstream.")
    parser.add_argument("--tx-buffer",  default=0, type=int, choices=[0, 1], help="GTP TX buffer enable.")
    parser.add_argument("--param",      action="append", default=[], help="GTPE2_CHANNEL override, e.g. p_TXSYNC_OVRD=1 or i_TXOUTCLKSEL=2 (repeatable).")
    parser.add_argument("--output-dir", default="build/gtp_txinit", help="Build directory.")
    args = parser.parse_args()

    params = {}
    for p in args.param:
        k, v = p.split("=", 1)
        params[k] = int(v, 0)

    platform = sqrl_acorn.Platform()
    platform.add_extension(sqrl_acorn.litex_acorn_baseboard_mini, prepend=True) # UART on the baseboard.
    platform.add_extension(_transceiver_io)
    soc = TXInitSoC(platform, tx_buffer_enable=bool(args.tx_buffer), params=params)
    builder = Builder(soc, output_dir=args.output_dir, csr_csv=f"{args.output_dir}/csr.csv")
    builder.build(run=args.build)

if __name__ == "__main__":
    main()

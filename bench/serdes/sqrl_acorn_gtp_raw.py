#!/usr/bin/env python3

#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

import argparse
import os

from migen import *
from migen.genlib.cdc import MultiReg
from litex.gen import *
from litex_boards.platforms import sqrl_acorn
from litex.build.generic_platform import *
from litex.soc.cores.clock import *
from litex.soc.integration.soc import *
from litex.soc.integration.builder import *
from litex.soc.interconnect.csr import CSRField, CSRStatus

from liteiclink.serdes.gtp_7series import GTPQuadPLL, GTP
from liteiclink.serdes.pcs.gtp import GTPRawAdapter
from liteiclink.serdes.pcs.phy import PCS64b66bPHY


_transceiver_io = [
    ("pcie_tx", 0,
        Subsignal("p", Pins("B6")),
        Subsignal("n", Pins("A6")),
    ),
    ("pcie_rx", 0,
        Subsignal("p", Pins("B10")),
        Subsignal("n", Pins("A10")),
    ),
]


class CRG(LiteXModule):
    def __init__(self, platform, sys_clk_freq):
        self.rst = Signal()
        self.cd_sys = ClockDomain()
        clk200 = platform.request("clk200")
        self.pll = pll = S7PLL()
        self.comb += pll.reset.eq(self.rst)
        pll.register_clkin(clk200, 200e6)
        pll.create_clkout(self.cd_sys, sys_clk_freq)


class GTPRawTestSoC(SoCMini):
    def __init__(self, platform, linerate=2.5e9):
        sys_clk_freq = int(100e6)
        SoCMini.__init__(self, platform, sys_clk_freq, ident="LiteICLink 64b/66b PCS over raw GTP on Acorn CLE-215+")
        self.add_uartbone()
        self.crg = CRG(platform, sys_clk_freq)

        # Generate the 125 MHz GTP reference clock from the fabric PLL.
        self.cd_refclk = ClockDomain()
        self.crg.pll.create_clkout(self.cd_refclk, 125e6)
        platform.add_platform_command("set_property SEVERITY {{Warning}} [get_drc_checks REQP-49]")
        self.pll = pll = GTPQuadPLL(self.cd_refclk.clk, 125e6, linerate, refclk_from_fabric=True)

        self.serdes0 = serdes0 = GTP(
            pll, platform.request("pcie_tx"), platform.request("pcie_rx"), sys_clk_freq,
            data_width=20,
            # TX buffer kept: TX buffer bypass with the fabric reference clock does not finish TX
            # initialization on the Acorn. RX buffer bypassed: required for the RX bit slip.
            tx_buffer_enable=True,
            rx_buffer_enable=False,
            clock_aligner=False,
        )
        serdes0.add_controls()
        serdes0.add_clock_cycles()
        # Readiness status for the host utility (raw path: no transceiver RX bit slip).
        serdes0._raw_status = CSRStatus(fields=[
            CSRField("tx_ready", size=1), CSRField("rx_ready", size=1),
            CSRField("rx_bitslip_supported", size=1),
        ])
        self.comb += [
            serdes0._raw_status.fields.tx_ready.eq(serdes0.tx_ready),
            serdes0._raw_status.fields.rx_ready.eq(serdes0.rx_ready),
        ]

        # Reusable PCS/PHY adapter stays independent of this Acorn-specific SoC.
        self.pcs_link = pcs_link = PCS64b66bPHY(GTPRawAdapter(serdes0))
        tx_payload = Signal(64)
        self.comb += [
            pcs_link.sink.valid.eq(pcs_link.tx_ready),
            pcs_link.sink.data.eq(tx_payload),
            pcs_link.sink.control.eq(tx_payload[0]),
            pcs_link.source.ready.eq(1),
        ]
        self.sync.tx += If(pcs_link.sink.valid & pcs_link.sink.ready,
            tx_payload.eq(tx_payload + 1)
        )

        # Expose synchronized PCS/adapter status for bench observation.
        block_lock_sys = Signal()
        tx_underflow_sys = Signal()
        rx_overflow_sys = Signal()
        self.specials += [
            MultiReg(pcs_link.block_lock, block_lock_sys, "sys"),
            MultiReg(pcs_link.raw_phy.tx_underflow, tx_underflow_sys, "sys"),
            MultiReg(pcs_link.raw_phy.rx_overflow, rx_overflow_sys, "sys"),
        ]
        self.pcs_status = CSRStatus(fields=[
            CSRField("block_lock", size=1, description="RX 64b/66b block lock."),
            CSRField("tx_underflow", size=1, description="Sticky TX raw-word underflow."),
            CSRField("rx_overflow", size=1, description="Sticky RX raw-word overflow."),
        ])
        self.comb += [
            self.pcs_status.fields.block_lock.eq(block_lock_sys),
            self.pcs_status.fields.tx_underflow.eq(tx_underflow_sys),
            self.pcs_status.fields.rx_overflow.eq(rx_overflow_sys),
        ]

        platform.add_period_constraint(serdes0.cd_tx.clk, 1e9/serdes0.tx_clk_freq)
        platform.add_period_constraint(serdes0.cd_rx.clk, 1e9/serdes0.rx_clk_freq)
        platform.add_false_path_constraints(self.crg.cd_sys.clk, serdes0.cd_tx.clk, serdes0.cd_rx.clk)

        # LEDs show activity in the recovered receive word and clock domains.
        for i, domain in enumerate(("sys", "tx", "rx")):
            counter = Signal(32)
            if domain == "sys":
                self.sync += counter.eq(counter + 1)
            elif domain == "tx":
                self.sync.tx += counter.eq(counter + 1)
            else:
                self.sync.rx += counter.eq(counter + 1)
            self.comb += platform.request("user_led", i).eq(counter[26])
        self.comb += platform.request("user_led", 3).eq(block_lock_sys)


def main():
    parser = argparse.ArgumentParser(description="64b/66b PCS over raw GTP example on Acorn CLE-215+")
    parser.add_argument("--build", action="store_true", help="Build bitstream")
    parser.add_argument("--load", action="store_true", help="Load bitstream to SRAM")
    parser.add_argument("--linerate", default="2.5e9", help="Line rate (default: 2.5e9)")
    parser.add_argument("--baseboard-mini", action="store_true", help="Acorn on a LiteX Acorn Baseboard Mini (UARTBone on the baseboard USB-UART)")
    args = parser.parse_args()

    platform = sqrl_acorn.Platform()
    if args.baseboard_mini:
        # Baseboard IOs first: "serial" is then the baseboard USB-UART instead of the Acorn P2 header.
        platform.add_extension(sqrl_acorn.litex_acorn_baseboard_mini, prepend=True)
    platform.add_extension(_transceiver_io)
    soc = GTPRawTestSoC(platform, linerate=float(args.linerate))
    builder = Builder(soc, csr_csv="sqrl_acorn_pcs.csv")
    builder.build(run=args.build)

    if args.load:
        programmer = soc.platform.create_programmer()
        programmer.load_bitstream(os.path.join(builder.gateware_dir, soc.build_name + ".bit"))


if __name__ == "__main__":
    main()

#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace


BENCH_PATH = Path(__file__).resolve().parents[1] / "bench/serdes/sqrl_acorn_gtp_raw.py"
HOST_PATH  = Path(__file__).resolve().parents[1] / "bench/serdes/test_sqrl_acorn_gtp_raw.py"
PCS_HOST_PATH = Path(__file__).resolve().parents[1] / "bench/serdes/test_sqrl_acorn_gtp_pcs.py"


class FakeCSR:
    def __init__(self, value=0):
        self.writes = []
        self.value = value

    def write(self, value):
        self.writes.append(value)

    def read(self):
        return self.value


class TestGTPRawBench(unittest.TestCase):
    def test_acorn_soc_elaborates_without_vendor_tools(self):
        bench = runpy.run_path(str(BENCH_PATH))
        platform = bench["sqrl_acorn"].Platform()
        platform.add_extension(bench["_transceiver_io"])
        soc = bench["GTPRawTestSoC"](platform)
        soc.get_fragment()
        self.assertTrue(hasattr(soc, "pcs_link"))
        self.assertIn("main_pcs_status", [csr.name for csr in soc.get_csrs()])

    def test_acorn_baseboard_mini_uartbone_on_baseboard_uart(self):
        # --baseboard-mini: UARTBone on the baseboard USB-UART (G1/Y13), not the Acorn P2 header.
        bench = runpy.run_path(str(BENCH_PATH))
        sqrl_acorn = bench["sqrl_acorn"]
        platform = sqrl_acorn.Platform()
        platform.add_extension(sqrl_acorn.litex_acorn_baseboard_mini, prepend=True)
        platform.add_extension(bench["_transceiver_io"])
        soc = bench["GTPRawTestSoC"](platform)
        soc.get_fragment()
        serial = [res for res, _ in platform.constraint_manager.matched if res[0] == "serial"]
        self.assertEqual(len(serial), 1)
        pins = [c.identifiers for s in serial[0][2:] for c in s.constraints if hasattr(c, "identifiers")]
        self.assertEqual(pins, [["G1"], ["Y13"]])

    def test_pcs_host_utility_imports(self):
        host = runpy.run_path(str(PCS_HOST_PATH))
        self.assertIn("PCSLink", host)

    def test_pcs_host_utility_waits_for_readiness_and_lock(self):
        host = runpy.run_path(str(PCS_HOST_PATH))
        csrs = {
            "serdes0_raw_status": FakeCSR(value=0b11),
            "serdes0_loopback": FakeCSR(),
            "main_pcs_status": FakeCSR(value=0b001),
        }
        link = host["PCSLink"](SimpleNamespace(d=csrs), 0)
        link.wait_ready(timeout=0.1)
        status = link.wait_block_lock(timeout=0.1)
        self.assertEqual(status, 0b001)
        link.loopback.write(0b010)
        self.assertEqual(csrs["serdes0_loopback"].writes, [0b010])

    def test_host_utility_external_mode_disables_internal_loopback(self):
        host = runpy.run_path(str(HOST_PATH))
        names = ("raw_status", "raw_rx_bitslip_request", "tx_prbs_config",
                 "rx_prbs_config", "rx_prbs_errors", "loopback")
        csrs = {f"serdes0_{name}": FakeCSR() for name in names}
        serdes = host["SerDes"](SimpleNamespace(d=csrs), 0)

        serdes.configure("prbs7", external=True)
        self.assertEqual(csrs["serdes0_loopback"].writes[-1], 0)
        self.assertEqual(csrs["serdes0_tx_prbs_config"].writes[-1], 0b01)
        self.assertEqual(csrs["serdes0_rx_prbs_config"].writes[-1], 0b01)

        serdes.configure("prbs15", external=False)
        self.assertEqual(csrs["serdes0_loopback"].writes[-1], 0b010)


if __name__ == "__main__":
    unittest.main()

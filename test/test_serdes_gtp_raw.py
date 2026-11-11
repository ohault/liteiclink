#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

import unittest

from migen import ClockDomain, Instance, Signal
from litex.gen import LiteXModule
from liteiclink.serdes.gtp_7series import GTP
from liteiclink.serdes.pcs.gtp import GTPRawAdapter
from liteiclink.serdes.pcs.phy import PCS64b66bPHY


class DummyQPLL:
    config = {"linerate": 2.5e9, "d": 1, "clkin": 125e6}
    channel = 0
    clk = Signal()
    refclk = Signal()
    lock = Signal()
    reset = Signal()


class Pads:
    p = Signal()
    n = Signal()




class RawPCSModule(LiteXModule):
    def __init__(self, width=20, rx_buffer_enable=False):
        self.cd_sys = ClockDomain()
        self.gtp = GTP(
            DummyQPLL(), Pads(), Pads(), 125e6,
            data_width=width,
            raw_datapath=True,
            clock_aligner=False,
            rx_buffer_enable=rx_buffer_enable,
        )
        self.link = PCS64b66bPHY(GTPRawAdapter(self.gtp))

class TestGTPRawDatapath(unittest.TestCase):
    def make_gtp(self, **kwargs):
        return GTP(DummyQPLL(), Pads(), Pads(), 125e6, **kwargs)

    def assert_has_gtp_channel(self, gtp):
        fragment = gtp.get_fragment()
        channels = [s for s in fragment.specials
            if isinstance(s, Instance) and s.of == "GTPE2_CHANNEL"]
        self.assertEqual(len(channels), 1)

    def test_gtp_channel_is_instantiated(self):
        for width in (20, 40):
            self.assert_has_gtp_channel(self.make_gtp(data_width=width))
            self.assert_has_gtp_channel(self.make_gtp(data_width=width, raw_datapath=True,
                clock_aligner=False))

    def test_default_controls_and_clock_cycles_elaborate(self):
        gtp = self.make_gtp()
        gtp.add_controls()
        gtp.add_clock_cycles()
        self.assert_has_gtp_channel(gtp)

    def test_raw_words_and_elaboration(self):
        for width in (20, 40):
            gtp = self.make_gtp(data_width=width, raw_datapath=True, clock_aligner=False)
            self.assertEqual(len(gtp.raw_tx_data), width)
            self.assertEqual(len(gtp.raw_rx_data), width)
            self.assertEqual(gtp.raw_rx_bitslip_supported, True)
            self.assertFalse(hasattr(gtp, "encoder"))
            gtp.get_fragment()
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                gtp.add_stream_endpoints()

    def test_generic_pcs_and_gtp_raw_adapter_elaborate(self):
        for width in (20, 40):
            top = RawPCSModule(width=width)
            self.assertEqual(len(top.link.pcs.tx.data), width)
            self.assertEqual(top.link.raw_phy.data_width, width)
            self.assertTrue(top.link.rx_bitslip_supported)
            top.get_fragment()

    def test_generic_adapter_reports_missing_hardware_bitslip(self):
        top = RawPCSModule(width=20, rx_buffer_enable=True)
        self.assertFalse(top.link.rx_bitslip_supported)
        top.get_fragment()

    def test_raw_mode_requires_explicit_alignment_choice(self):
        with self.assertRaisesRegex(ValueError, "clock_aligner=False"):
            self.make_gtp(raw_datapath=True)

    def test_raw_mode_with_rx_buffer_reports_no_bitslip(self):
        gtp = self.make_gtp(raw_datapath=True, clock_aligner=False, rx_buffer_enable=True)
        self.assertFalse(gtp.raw_rx_bitslip_supported)
        gtp.get_fragment()

    def test_raw_controls_elaborate_and_default_mode_rejects_them(self):
        gtp = self.make_gtp(raw_datapath=True, clock_aligner=False)
        gtp.add_raw_control()
        gtp.get_fragment()
        gtp = self.make_gtp()
        with self.assertRaisesRegex(RuntimeError, "raw_datapath=True"):
            gtp.add_raw_control()

    def test_default_keeps_8b10b_endpoints(self):
        gtp = self.make_gtp()
        self.assertTrue(hasattr(gtp, "encoder"))
        gtp.add_stream_endpoints()
        gtp.get_fragment()


if __name__ == "__main__":
    unittest.main()

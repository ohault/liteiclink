#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

from migen import *
from migen.genlib.cdc import MultiReg

from litex.gen import *
from litex.soc.interconnect import stream

from liteiclink.serdes.pcs.core import PCS64b66b


class RawPHYInterface(LiteXModule):
    """Contract for a continuous, parallel-word raw PMA interface.

    ``tx`` is a ready/valid sink for words sent toward the PMA. ``rx`` is a
    ready/valid source of words received from the PMA. A PHY adapter must
    accept that PMA RX cannot be paused: it should provide enough elasticity
    for ordinary PCS flow control and report any overflow. Long RX consumer
    stalls still require a system-level recovery policy.
    """
    def __init__(self, data_width):
        assert data_width > 0
        self.data_width = data_width
        self.tx = stream.Endpoint([("data", data_width)])
        self.rx = stream.Endpoint([("data", data_width)])
        self.tx_ready = Signal()
        self.rx_ready = Signal()
        self.rx_bitslip = Signal()
        self.rx_bitslip_supported = False
        self.tx_underflow = Signal()
        self.rx_overflow = Signal()


class PCS64b66bPHY(LiteXModule):
    """Connect ``PCS64b66b`` to an implementation of ``RawPHYInterface``.

    Payload input and TX PCS logic run in ``tx_domain``. RX PCS logic and
    payload output run in ``rx_domain``. Clock-domain crossing for payloads
    belongs outside this link wrapper.
    """
    def __init__(self, raw_phy, reset_value=0, tx_domain="tx", rx_domain="rx"):
        self.pcs = pcs = PCS64b66b(
            raw_width=raw_phy.data_width,
            reset_value=reset_value,
            tx_domain=tx_domain,
            rx_domain=rx_domain,
        )
        self.submodules.raw_phy = raw_phy
        self.sink = pcs.sink
        self.source = pcs.source
        self.block_lock = pcs.block_lock
        self.rx_bitslip = Signal()
        self.tx_ready = raw_phy.tx_ready
        self.rx_ready = raw_phy.rx_ready
        self.rx_bitslip_supported = raw_phy.rx_bitslip_supported

        self.comb += [
            pcs.tx.connect(raw_phy.tx),
            raw_phy.rx.connect(pcs.rx),
            raw_phy.rx_bitslip.eq(self.rx_bitslip),
        ]

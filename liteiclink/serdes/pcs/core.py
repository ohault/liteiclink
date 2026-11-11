#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *
from litex.soc.interconnect import stream

from liteiclink.serdes.pcs.gearbox import BitstreamGearbox
from liteiclink.serdes.pcs.rx import BlockRX
from liteiclink.serdes.pcs.tx import BlockTX


class PCS64b66b(LiteXModule):
    """Generic 64b/66b PCS between block streams and raw PMA words.

    ``sink``/``source`` carry generic 64-bit payloads and a control-block
    flag. ``tx``/``rx`` carry raw PMA words of ``raw_width`` bits. The wrapper
    has no board, transceiver, Ethernet MAC, or XGMII dependencies.
    """
    def __init__(self, raw_width=20, reset_value=0, tx_domain="sys", rx_domain="sys"):
        assert raw_width > 0
        self.sink   = sink   = stream.Endpoint([("data", 64), ("control", 1)])
        self.source = source = stream.Endpoint([("data", 64), ("control", 1)])
        self.tx     = tx     = stream.Endpoint([("data", raw_width)])
        self.rx     = rx     = stream.Endpoint([("data", raw_width)])

        self.tx_block = tx_block = ClockDomainsRenamer(tx_domain)(BlockTX(reset_value=reset_value))
        self.tx_gearbox = tx_gearbox = ClockDomainsRenamer(tx_domain)(
            BitstreamGearbox(in_width=66, out_width=raw_width))
        self.rx_block = rx_block = ClockDomainsRenamer(rx_domain)(
            BlockRX(reset_value=reset_value, input_width=raw_width))

        self.block_lock = rx_block.block_lock

        self.comb += [
            sink.connect(tx_block.sink),
            tx_block.source.connect(tx_gearbox.sink),
            tx_gearbox.source.connect(tx),

            rx.connect(rx_block.sink),
            rx_block.source.connect(source),
        ]

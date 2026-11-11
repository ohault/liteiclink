#
# This file is part of LiteICLink.
#
# Copyright (c) 2026 Olivier Hault
# SPDX-License-Identifier: BSD-2-Clause

from migen import *
from migen.genlib.cdc import MultiReg

from litex.gen import *
from litex.soc.interconnect import stream

from liteiclink.serdes.pcs.phy import RawPHYInterface


class GTPRawAdapter(RawPHYInterface):
    """Adapt the GTP raw symbols path (tx_raw_enable/tx_raw/rx_raw) to ``RawPHYInterface``.

    TX words are consumed in the GTP ``tx`` domain. RX words are captured in
    the GTP ``rx`` domain into a small synchronous FIFO, which absorbs brief
    downstream stalls. A sustained RX stall cannot be backpressured into the
    PMA and sets ``rx_overflow``. TX gaps emit zero words and set
    ``tx_underflow`` once the GTP is ready.
    """
    def __init__(self, gtp, rx_fifo_depth=4):
        if not hasattr(gtp, "tx_raw"):
            raise ValueError("GTPRawAdapter requires a transceiver with a raw path (tx_raw/rx_raw)")
        if rx_fifo_depth < 2:
            raise ValueError("rx_fifo_depth must be at least 2")

        data_width = len(gtp.tx_raw)
        super().__init__(data_width)

        # No transceiver RX bit slip: block alignment is done by the PCS gearbox slip.
        self.bitslip_supported = False
        self.rx_bitslip_supported = False

        tx_ready_tx = Signal()
        rx_ready_rx = Signal()
        self.specials += [
            MultiReg(gtp.tx_ready, tx_ready_tx, "tx"),
            MultiReg(gtp.rx_ready, rx_ready_rx, "rx"),
        ]

        self.rx_fifo = rx_fifo = ClockDomainsRenamer("rx")(
            stream.SyncFIFO([("data", data_width)], rx_fifo_depth, buffered=True)
        )

        self.comb += [
            self.tx.ready.eq(tx_ready_tx),
            gtp.tx_raw_enable.eq(1),
            gtp.tx_raw.eq(Mux(self.tx.valid, self.tx.data, 0)),

            rx_fifo.sink.valid.eq(rx_ready_rx),
            rx_fifo.sink.data.eq(gtp.rx_raw),
            rx_fifo.source.connect(self.rx),

            self.tx_ready.eq(tx_ready_tx),
            self.rx_ready.eq(rx_ready_rx),
        ]

        tx_started = Signal()
        self.sync.tx += [
            If(tx_ready_tx & self.tx.valid,
                tx_started.eq(1)
            ),
            If(tx_ready_tx & tx_started & ~self.tx.valid,
                self.tx_underflow.eq(1)
            ),
        ]
        self.sync.rx += If(rx_ready_rx & ~rx_fifo.sink.ready,
            self.rx_overflow.eq(1)
        )

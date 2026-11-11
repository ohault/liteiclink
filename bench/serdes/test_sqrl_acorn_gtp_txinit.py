#!/usr/bin/env python3

#
# This file is part of LiteICLink.
#
# SPDX-License-Identifier: BSD-2-Clause

# TEST ONLY: read the GTP TX init debug status of sqrl_acorn_gtp_txinit.py (through litex_server).

import time
import argparse

from litex import RemoteClient

TX_STATES = ["POWER-DOWN", "DRP", "WAIT-PLL-RESET", "WAIT-INIT-DELAY", "WAIT-GTP-RESET",
    "ALIGN", "WAIT-ALIGN", "WAIT-FIRST-ALIGN-DONE", "WAIT-SECOND-ALIGN-DONE", "READY"]
GT_STATUS = ["plllock", "txresetdone", "txdlysresetdone", "txphinitdone", "txphaligndone"]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csr-csv", default="build/gtp_txinit/csr.csv")
    parser.add_argument("--port",    default=1234, type=int)
    parser.add_argument("--samples", default=20, type=int, help="Status samples (100 ms apart).")
    args = parser.parse_args()

    bus = RemoteClient(csr_csv=args.csr_csv, port=args.port)
    bus.open()
    r = lambda name: getattr(bus.regs, f"serdes0_{name}").read()
    ident = "".join(chr(bus.read(bus.bases.identifier_mem + 4*i) & 0xff) for i in range(128)).split("\0")[0]
    print(ident)

    bus.regs.serdes0_tx_init_clear.write(1)
    tx0, rx0, t0 = r("tx_clk_ticks"), r("rx_clk_ticks"), time.time()
    states = {}
    gt_seen = {n: set() for n in GT_STATUS}
    for _ in range(args.samples):
        time.sleep(0.1)
        st = r("tx_init_status")
        state = st & 0xf
        states[TX_STATES[state] if state < len(TX_STATES) else state] = states.get(state, 0) + 1
        gt = r("tx_gt_status")
        for i, n in enumerate(GT_STATUS):
            gt_seen[n].add((gt >> i) & 1)
    st = r("tx_init_status")
    tx1, rx1, t1 = r("tx_clk_ticks"), r("rx_clk_ticks"), time.time()
    visited = [s for i, s in enumerate(TX_STATES) if (st >> (8 + i)) & 1]
    dt = t1 - t0
    print(f"tx_ready={r('tx_ready')} rx_ready={r('rx_ready')}")
    print(f"current state samples: {states}")
    print(f"visited since clear: {visited}")
    print(f"restarts: {r('tx_init_restarts')} in {dt:.1f}s")
    print("gt status seen: " + ", ".join(f"{n}={sorted(v)}" for n, v in gt_seen.items()))
    print(f"tx clock: {(tx1 - tx0)*2**16/dt/1e6:.2f} MHz, rx clock: {(rx1 - rx0)*2**16/dt/1e6:.2f} MHz")
    bus.close()

if __name__ == "__main__":
    main()

"""BookSim day 2 (C52, worklist step 4): the two-component gap
decomposition at the T1 seatings, governed by the step-4 pre-registration
(FIXLIST) and the reviewer-signed frame:

    [bound -> BookSim]   = NETWORK-INTERNAL share (queueing / flow
                           control / flit competition; free pipelining)
    [BookSim -> silicon] = PROTOCOL share (consumer buffering and
                           per-block handshakes; above the network)

All quantities in the BRIDGE CALIBER (unicast decomposition; 17-flit
wire; max(channel, injection) reference on both rails):
    T_opt  = max(channel bound, injection bound)          [gate-A rail]
    T_pess = sum over packets of (17 + 14 h + 7)          [gate-B rail]
    T_book = measured batch completion.
Per point: the guard-gated lambda AND the absolute deviation are both
reported with the guard's verdict; across points the BookSim ratio
bar5/bar1 isolates the network-internal distance sensitivity, and
silicon's measured 2.53x divided by it QUANTIFIES the protocol share.

    python3 scripts/analyze_booksim_slack.py -> analysis/booksim_slack.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import booksim_bridge as bb

WS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

# T1 frozen {K:2, P:2}, unicast decomposition (A1/A3 records); 392
# packets per slice-destination. Nodes are row-major (y*6+x).
POINTS = {
    "bar1_adjacent": {"flows": [(0, 1, 392), (0, 6, 392), (0, 7, 392)],
                      "hops": (1, 1, 2), "measured_norm": 1.000},
    "bar5_corners": {"flows": [(0, 5, 392), (0, 30, 392), (0, 35, 392)],
                     "hops": (5, 5, 10), "measured_norm": 2.530},
}
SILICON_RATIO = 2.530


def rails(flows, hops):
    b = bb.flit_bounds(flows)
    t_opt = max(b.values())
    t_pess = sum(n * (17 + 14 * h + 7) for (_, _, n), h in zip(flows, hops))
    return t_opt, t_pess, b


def main():
    out = {"points": {}, "caliber": "unicast-decomposition (pre-reg label)"}
    for name, p in POINTS.items():
        t_opt, t_pess, bounds = rails(p["flows"], p["hops"])
        r = bb.run_batch(p["flows"])
        g = bb.lam(r["cycles"] * bb.CHANNEL_CYCLE_S,
                   t_opt * bb.CHANNEL_CYCLE_S,
                   t_pess * bb.CHANNEL_CYCLE_S)
        out["points"][name] = {
            "flows": p["flows"], "measured_norm": p["measured_norm"],
            "bounds": bounds,
            "t_opt_cycles": t_opt, "t_pess_cycles": t_pess,
            "t_book_cycles": r["cycles"],
            "net_internal_cycles": r["cycles"] - t_opt,
            "net_internal_frac_of_opt": (r["cycles"] - t_opt) / t_opt,
            "guard": g,
        }
    b1 = out["points"]["bar1_adjacent"]["t_book_cycles"]
    b5 = out["points"]["bar5_corners"]["t_book_cycles"]
    out["booksim_ratio_bar5_over_bar1"] = b5 / b1
    out["protocol_share_ratio"] = SILICON_RATIO / (b5 / b1)
    with open(os.path.join(WS, "analysis", "booksim_slack.json"), "w") as f:
        json.dump(out, f, indent=1)
    for name, d in out["points"].items():
        print(f"{name}: opt {d['t_opt_cycles']}  book {d['t_book_cycles']}  "
              f"pess {d['t_pess_cycles']}  net-internal +{d['net_internal_frac_of_opt']:.2%}  "
              f"guard={d['guard']['reported']}"
              + (f" lambda={d['guard'].get('lambda'):.4f}"
                 if d['guard']['reported'] == 'lambda' else ""))
    print(f"booksim ratio bar5/bar1 = {out['booksim_ratio_bar5_over_bar1']:.4f}")
    print(f"protocol share = 2.530 / ratio = {out['protocol_share_ratio']:.3f}x "
          f"(the bulk, expected)")


if __name__ == "__main__":
    main()

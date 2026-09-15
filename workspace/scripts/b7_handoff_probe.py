"""B7: the corrected hand-off term's EXTERNAL adjudication, and the
ranking it induces, on a small package instance.

The S6 cross-traffic instance is not BookSim-tractable (1e7 packets),
so this runs on the bridge's own 6x6 = 36-die mesh -- same grid,
routing and hop caliber the step-4 pre-registration fixed. The
readings are about the TERM and its RANKING, not about the 576-die
numbers.

HALF A -- the term vs a packet-level router network. A 2.7B-style
hand-off: a producer set of P dies R-splits V words to a consumer set
of C dies (every producer to every consumer, the frozen convention).
Three scorings per geometry: our busiest-link term, the bridge's own
flit-caliber bound (gate: identical after conversion), and BookSim's
measured batch completion. Our term is an OCCUPANCY BOUND, so BookSim
must land at or above it.

HALF B -- the ranking. Several seatings of a scaled-down cross-traffic
load, ranked by our term and by BookSim; Spearman correlation, top-k
overlap, selected-solution regret.

    python3 scripts/b7_handoff_probe.py -> analysis/b7_handoff_probe.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import booksim_bridge as bb
from scripts import search_eval as se

K = 6                                  # the small package: 6x6 = 36 dies
WORD_B = 1.0                           # 8-bit activations, the standing unit
OUT = os.path.join(se.A, "b7_handoff_probe.json")


def node(x, y):
    return y * K + x


def handoff_flows(prod, cons, v_words):
    """The frozen R-split convention: each producer ships v/P words to
    EVERY consumer. Returns [(src, dst, words)]."""
    piece = v_words / len(prod)
    return [(p, c, piece) for p in prod for c in cons if p != c]


def our_busiest_words(flows):
    """Our hand-off term's numerator: words on the busiest (link,
    direction) under XY routing -- the same accumulation
    search_eval.busiest_link_words does, on this grid."""
    load = {}
    for s, d, w in flows:
        sx, sy, dx, dy = s % K, s // K, d % K, d // K
        x, y = sx, sy
        while x != dx:                                   # X first
            step = 1 if dx > x else -1
            load[("h", min(x, x + step), y, step)] = \
                load.get(("h", min(x, x + step), y, step), 0.0) + w
            x += step
        while y != dy:
            step = 1 if dy > y else -1
            load[("v", x, min(y, y + step), step)] = \
                load.get(("v", x, min(y, y + step), step), 0.0) + w
            y += step
    return max(load.values(), default=0.0)


def our_busiest_words_ports(flows):
    """The post-F-B7 term: busiest over links AND node ports (one
    injection + one ejection port per die at the link rate)."""
    load = {}
    for s, d, w in flows:
        for e in _path_edges(s, d):
            load[e] = load.get(e, 0.0) + w
        load[("inj", s)] = load.get(("inj", s), 0.0) + w
        load[("ej", d)] = load.get(("ej", d), 0.0) + w
    return max(load.values(), default=0.0)


def to_packets(flows):
    return [(s, d, bb.packets_for(w * WORD_B)) for s, d, w in flows
            if w > 0]


GEOMETRIES = {
    # compact: producers and consumers in adjacent 2x2 blocks
    "compact": ([node(0, 0), node(1, 0), node(0, 1), node(1, 1)],
                [node(2, 0), node(3, 0), node(2, 1), node(3, 1)]),
    # dispersed: producers and consumers spread over the whole grid
    "dispersed": ([node(0, 0), node(5, 1), node(1, 4), node(4, 5)],
                  [node(5, 0), node(0, 2), node(3, 3), node(2, 5)]),
    # stacked: consumers behind one another on a single row -- every
    # flow funnels through the same eastward links
    "stacked": ([node(0, 2), node(0, 3), node(1, 2), node(1, 3)],
                [node(4, 2), node(5, 2), node(4, 3), node(5, 3)]),
}


def half_a(v_words):
    rows = {}
    for name, (prod, cons) in GEOMETRIES.items():
        fl = handoff_flows(prod, cons, v_words)
        pk = to_packets(fl)
        ours_words = our_busiest_words(fl)
        # our term in bridge units: words -> flits on the busiest link
        ours_flits = ours_words * WORD_B / bb.FLIT_PAYLOAD_B
        fb = bb.flit_bounds(pk, k=K)
        book = bb.run_batch(pk, k=K)
        # the bridge's channel bound counts whole packets (padding); our
        # term counts words -- compare on the PACKET-quantised volume
        ours_packet_flits = max(
            sum(n * bb.PACKET_FLITS for (s, d, n) in pk
                if _crosses(s, d, e)) for e in _edges(pk)) if pk else 0
        ours_ports = our_busiest_words_ports(fl)
        ref = max(fb["channel_bound_cycles"], fb["injection_bound_cycles"])
        rows[name] = {
            "n_flows": len(fl), "packets": sum(n for _, _, n in pk),
            "ours_busiest_words": ours_words,
            "ours_busiest_words_ports": ours_ports,
            "ours_ports_over_wireonly": ours_ports / ours_words,
            "booksim_over_ours_ports": book["cycles"] / ref,
            "ours_busiest_flits_wordexact": ours_flits,
            "ours_busiest_flits_packetised": ours_packet_flits,
            "bridge_channel_bound_cycles": fb["channel_bound_cycles"],
            "bridge_injection_bound_cycles": fb["injection_bound_cycles"],
            "booksim_cycles": book["cycles"],
            "booksim_over_ours": (book["cycles"] / ours_packet_flits
                                  if ours_packet_flits else float("nan")),
            "booksim_over_bridge_ref": (
                book["cycles"] / max(fb["channel_bound_cycles"],
                                     fb["injection_bound_cycles"]))}
        r = rows[name]
        print(f"  {name:10} flows {r['n_flows']:3d} packets "
              f"{r['packets']:5d} | ours(busiest, packetised flits) "
              f"{r['ours_busiest_flits_packetised']:7d} == bridge channel "
              f"bound {r['bridge_channel_bound_cycles']:7d} ? "
              f"{r['ours_busiest_flits_packetised'] == r['bridge_channel_bound_cycles']}"
              f" | injection bound {r['bridge_injection_bound_cycles']:7d}"
              f" | BookSim {r['booksim_cycles']:7d} = "
              f"{r['booksim_over_ours']:.3f}x ours, "
              f"{r['booksim_over_bridge_ref']:.3f}x the bridge reference")
    return rows


def _edges(pk):
    es = set()
    for s, d, n in pk:
        for e in _path_edges(s, d):
            es.add(e)
    return es


def _path_edges(s, d):
    sx, sy, dx, dy = s % K, s // K, d % K, d // K
    x, y, out = sx, sy, []
    while x != dx:
        step = 1 if dx > x else -1
        out.append(("h", min(x, x + step), y, step))
        x += step
    while y != dy:
        step = 1 if dy > y else -1
        out.append(("v", x, min(y, y + step), step))
        y += step
    return out


def _crosses(s, d, e):
    return e in _path_edges(s, d)


# ------------------------------------------------------------- half B
def seatings():
    """Six seatings of a 4-stage chain on the 36-die package: each stage
    holds 4 dies. The families mirror the named baselines' geometries."""
    out = {}
    out["sequential"] = [[node(i % K, i // K) for i in range(4 * s, 4 * s + 4)]
                         for s in range(4)]
    out["clustered"] = [[node(2 * (s % 2) + dx, 2 * (s // 2) + dy)
                         for dy in range(2) for dx in range(2)]
                        for s in range(4)]
    out["snake"] = [[node(x, s) for x in ([0, 1, 2, 3] if s % 2 == 0
                                          else [5, 4, 3, 2])]
                    for s in range(4)]
    out["dispersed"] = [[node((s + 3 * i) % K, (2 * i + s) % K)
                         for i in range(4)] for s in range(4)]
    out["corners"] = [[node(0, 0), node(5, 0), node(0, 5), node(5, 5)],
                      [node(1, 1), node(4, 1), node(1, 4), node(4, 4)],
                      [node(2, 2), node(3, 2), node(2, 3), node(3, 3)],
                      [node(0, 2), node(5, 2), node(0, 3), node(5, 3)]]
    out["striped"] = [[node(x, s) for x in range(4)] for s in range(4)]
    return out


def half_b(v_words):
    """A small cross-traffic load: stage s feeds s+1 and s+2 (the
    fan-out structure, scaled to 4 stages)."""
    pairs = [(0, 1), (1, 2), (2, 3), (0, 2), (1, 3)]
    rows = {}
    for name, stages in seatings().items():
        flows = []
        for a, b in pairs:
            flows += handoff_flows(stages[a], stages[b], v_words)
        # our term: the mix's busiest link over all hand-offs at once
        ours = our_busiest_words(flows)
        pk = to_packets(flows)
        book = bb.run_batch(pk, k=K)
        rows[name] = {"ours_busiest_words": ours,
                      "booksim_cycles": book["cycles"],
                      "packets": sum(n for _, _, n in pk)}
        print(f"  {name:11} ours {ours:9.0f} words | BookSim "
              f"{book['cycles']:7d} cycles ({rows[name]['packets']} packets)")
    return rows


def spearman(a, b):
    n = len(a)
    ra = {k: i for i, k in enumerate(sorted(a, key=a.get))}
    rb = {k: i for i, k in enumerate(sorted(b, key=b.get))}
    d2 = sum((ra[k] - rb[k]) ** 2 for k in a)
    return 1 - 6 * d2 / (n * (n * n - 1))


def main():
    if not bb.available():
        raise SystemExit("booksim binary missing -- see BUILD_NOTES.md")
    out = {"grid": f"{K}x{K}", "quantifier": "observed",
           "evaluation_set": "3 declared hand-off geometries; 6 declared "
                             "seatings of a 4-stage cross-traffic load",
           "note": "small-package instance; the term and its ranking, not "
                   "the 576-die numbers"}
    v_a = 8192.0
    print(f"HALF A -- the hand-off term vs BookSim (V = {v_a:.0f} words):")
    out["half_a"] = {"v_words": v_a, "rows": half_a(v_a)}
    v_b = 2048.0
    print(f"\nHALF B -- the ranking (V = {v_b:.0f} words per hand-off):")
    rows = half_b(v_b)
    out["half_b"] = {"v_words": v_b, "rows": rows}
    ours = {k: v["ours_busiest_words"] for k, v in rows.items()}
    book = {k: v["booksim_cycles"] for k, v in rows.items()}
    rho = spearman(ours, book)
    order_o = sorted(ours, key=ours.get)
    order_b = sorted(book, key=book.get)
    top1 = order_o[0] == order_b[0]
    top3 = len(set(order_o[:3]) & set(order_b[:3]))
    sel_regret = book[order_o[0]] / book[order_b[0]]
    out["half_b"].update({
        "spearman_rho": rho, "our_order": order_o, "booksim_order": order_b,
        "top1_agree": top1, "top3_overlap": top3,
        "selected_regret_under_booksim": sel_regret,
        "no_full_inversion": book[order_o[0]] < book[order_o[-1]]})
    print(f"\n  Spearman rho {rho:.3f} | our order {order_o}")
    print(f"  BookSim order {order_b}")
    print(f"  top-1 agree {top1}, top-3 overlap {top3}/3, selected-solution "
          f"regret under BookSim {sel_regret:.4f}, no full inversion "
          f"{out['half_b']['no_full_inversion']}")
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()

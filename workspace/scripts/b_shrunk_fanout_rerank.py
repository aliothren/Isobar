"""S7 / instance B on a SHRUNK COMPLETE instance under two judges.

Same logical shape as the full instance B: stages i -> i+2, i+4, i+8,
R-split (each producer die ships V/|P| to every consumer die), ONE
merged batch, XY routing, ports at the link rate. 9 stages x 4 dies =
36 dies fill the 6x6 mesh (13 pairs). V is scaled to a tractable packet
count and recorded. Candidates: named rules on this grid, random draws
(5 seeds), SA endpoints (3 seeds from random + 1 from clustered; the
objective is our merged busiest-resource load). Judges on the same
batch: ours = max over links AND ports of the merged load; BookSim =
batch duration (all packets ready at t = 0), with its packet/network
latency and hop averages.

    python3 scripts/b_shrunk_fanout_rerank.py -> analysis/b_shrunk_fanout_rerank.json
"""
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import b7_handoff_probe as pr
from scripts import booksim_bridge as bb
from scripts import search_eval as se

OUT = os.path.join(se.A, "b_shrunk_fanout_rerank.json")
K, N_STAGES, PER = 6, 9, 4
FANOUT = (2, 4, 8)
V = 65536.0                        # words per pair (scaled; recorded)
STEPS, ALPHA, SEEDS = 1200, 0.996, (0, 1, 2)
PAIRS = [(s, s + k) for s in range(N_STAGES) for k in FANOUT if s + k < N_STAGES]


def node(x, y):
    return y * K + x


def flows_of(stages):
    fl = []
    for a, b in PAIRS:
        fl += pr.handoff_flows(stages[a], stages[b], V)
    return fl


def ours(stages):
    return pr.our_busiest_words_ports(flows_of(stages))


def link_only(stages):
    return pr.our_busiest_words(flows_of(stages))


def port_max(stages):
    inj, ej = {}, {}
    for s, d, w in flows_of(stages):
        inj[s] = inj.get(s, 0.0) + w
        ej[d] = ej.get(d, 0.0) + w
    return max(max(inj.values()), max(ej.values()))


def booksim(stages):
    pk = [(s, d, bb.packets_for(w)) for s, d, w in flows_of(stages) if w > 0]
    r = bb.run_batch(pk, k=K)
    r["packets"] = sum(p for _, _, p in pk)
    return r


# ------------------------------------------------------------ candidates
def gen_named():
    out = {}
    out["sequential"] = [[node(i % K, i // K) for i in range(4 * s, 4 * s + 4)]
                         for s in range(N_STAGES)]
    order = []
    for y in range(K):
        xs = list(range(K)) if y % 2 == 0 else list(range(K - 1, -1, -1))
        order += [node(x, y) for x in xs]
    out["snake"] = [order[4 * s:4 * s + 4] for s in range(N_STAGES)]
    blocks = [[node(2 * bx + dx, 2 * by + dy) for dy in range(2) for dx in range(2)]
              for by in range(3) for bx in range(3)]
    out["clustered"] = blocks
    out["dispersed"] = [[s + 9 * j for j in range(4)] for s in range(N_STAGES)]
    out["striped"] = [[node(s % K, r) for r in range(4)] if s < 6
                      else [node(s % K, 4 + (r // 3)) for r in range(4)]
                      for s in range(N_STAGES)]
    # striped falls back: last three stages take the two bottom rows
    bottom = [node(x, y) for y in (4, 5) for x in range(K)]
    out["striped"] = [[node(s, r) for r in range(4)] for s in range(6)] + \
                     [bottom[4 * j:4 * j + 4] for j in range(3)]
    return out


def gen_random(seed):
    rng = random.Random(seed)
    ids = list(range(K * K))
    rng.shuffle(ids)
    return [ids[4 * s:4 * s + 4] for s in range(N_STAGES)]


def anneal(start, seed, t0):
    rng = random.Random(seed)
    cur = [list(s) for s in start]
    j = ours(cur)
    best, best_st = j, [list(s) for s in cur]
    curve = []
    for k in range(STEPS):
        t = t0 * (ALPHA ** k)
        a, b = rng.sample(range(N_STAGES), 2)
        i, m = rng.randrange(PER), rng.randrange(PER)
        cand = [list(s) for s in cur]
        cand[a][i], cand[b][m] = cand[b][m], cand[a][i]
        v = ours(cand)
        if v < j - 1e-9 or (t > 0 and rng.random() < math.exp(-(v - j) / t)):
            cur, j = cand, v
            if v < best:
                best, best_st = v, [list(s) for s in cand]
        if (k + 1) % 100 == 0:
            curve.append((k + 1, best))
    return best_st, best, curve


def spearman(a, b):
    def rk(x):
        o = sorted(range(len(x)), key=lambda i: x[i])
        r = [0] * len(x)
        for k, i in enumerate(o):
            r[i] = k
        return r
    ra, rb = rk(a), rk(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    return (sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
            / ((sum((x - ma) ** 2 for x in ra) ** 0.5)
               * (sum((y - mb) ** 2 for y in rb) ** 0.5)))


def main():
    cands = gen_named()
    for s in range(5):
        cands[f"random_s{s}"] = gen_random(s)
    rungs = {n: ours(st) for n, st in cands.items() if not n.startswith("random_s")}
    rungs["random_s0"] = ours(cands["random_s0"])
    t0 = (max(rungs.values()) - min(rungs.values())) / 20.0
    runs = {}
    for start, seeds in (("random_s0", SEEDS), ("clustered", (0,))):
        for s in seeds:
            t = time.perf_counter()
            st, v, curve = anneal(cands[start], 7919 * s + 3, t0)
            key = f"sa_from_{start}_s{s}"
            cands[key] = st
            runs[key] = {"start": start, "sa_seed": s, "t0_words": t0,
                         "best_words": v, "curve": curve,
                         "wall_s": time.perf_counter() - t}
    rows = {}
    for n, st in cands.items():
        t = time.perf_counter()
        bk = booksim(st)
        rows[n] = {"stages": st, "ours_words": ours(st),
                   "link_only_words": link_only(st), "port_max_words": port_max(st),
                   "busiest_is": "port" if port_max(st) >= link_only(st) else "link",
                   "booksim_cycles": bk["cycles"], "packets": bk["packets"],
                   "packet_latency_avg": bk.get("packet_latency_avg"),
                   "network_latency_avg": bk.get("network_latency_avg"),
                   "hops_avg": bk.get("hops_avg"),
                   "booksim_wall_s": time.perf_counter() - t}
        # our term in BookSim's units for the ratio: words/8 B flits... use packets*17 on the busiest resource? report the plain ratio of normalised values
    # normalise: ours in flit-cycles = words / 8 (8 B flits) -- ratio to BookSim cycles
    for n, r in rows.items():
        r["ours_flit_cycles"] = r["ours_words"] / bb.FLIT_PAYLOAD_B
        r["booksim_over_ours"] = r["booksim_cycles"] / r["ours_flit_cycles"]
    names = list(rows)
    o = [rows[n]["ours_words"] for n in names]
    b = [rows[n]["booksim_cycles"] for n in names]
    rnd = [n for n in names if n.startswith("random_s")]
    base_ours = min(rnd, key=lambda n: rows[n]["ours_words"])
    base_book = min(rnd, key=lambda n: rows[n]["booksim_cycles"])
    ends = [n for n in names if n.startswith("sa_")]
    summary = {
        "spearman": spearman(o, b),
        "top1_ours": names[o.index(min(o))], "top1_booksim": names[b.index(min(b))],
        "ratio_min": min(rows[n]["booksim_over_ours"] for n in names),
        "ratio_max": max(rows[n]["booksim_over_ours"] for n in names),
        "strongest_random_under_ours": base_ours,
        "strongest_random_under_booksim": base_book,
        "endpoints": {e: {
            "gain_ours_vs_ours_best_random_pct": (1 - rows[e]["ours_words"] / rows[base_ours]["ours_words"]) * 100,
            "gain_booksim_vs_ours_best_random_pct": (1 - rows[e]["booksim_cycles"] / rows[base_ours]["booksim_cycles"]) * 100,
            "gain_booksim_vs_booksim_best_random_pct": (1 - rows[e]["booksim_cycles"] / rows[base_book]["booksim_cycles"]) * 100,
            "A_over_floor": rows[e]["ours_words"] / rows[e]["port_max_words"],
            "busiest_is": rows[e]["busiest_is"]} for e in ends}}
    out = {"note": __doc__.strip(), "grid": f"{K}x{K}", "stages": N_STAGES,
           "per_stage": PER, "fanout": FANOUT, "n_pairs": len(PAIRS), "V_words": V,
           "schedule": {"t0_words": t0, "alpha": ALPHA, "steps": STEPS},
           "runs": runs, "rows": rows, "summary": summary}
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"{'candidate':24} {'ours(M)':>8} {'link':>7} {'port':>6} {'busiest':>7} "
          f"{'BookSim cyc':>11} {'ratio':>6} {'pkt lat':>8} {'net lat':>8} {'hops':>5}")
    for n in names:
        r = rows[n]
        print(f"{n:24} {r['ours_words']/1e6:8.3f} {r['link_only_words']/1e6:7.3f} "
              f"{r['port_max_words']/1e6:6.3f} {r['busiest_is']:>7} {r['booksim_cycles']:11d} "
              f"{r['booksim_over_ours']:6.3f} {r['packet_latency_avg'] or 0:8.0f} "
              f"{r['network_latency_avg'] or 0:8.0f} {r['hops_avg'] or 0:5.2f}")
    s = summary
    print(f"Spearman {s['spearman']:.3f}; top-1 ours {s['top1_ours']} / BookSim "
          f"{s['top1_booksim']}; ratio {s['ratio_min']:.3f}..{s['ratio_max']:.3f}; "
          f"strongest random: ours {s['strongest_random_under_ours']}, BookSim "
          f"{s['strongest_random_under_booksim']}")
    for e, v in s["endpoints"].items():
        print(f"  {e:24} gain ours {v['gain_ours_vs_ours_best_random_pct']:+6.2f}% | BookSim vs "
              f"ours-best random {v['gain_booksim_vs_ours_best_random_pct']:+6.2f}% | BookSim vs "
              f"BookSim-best random {v['gain_booksim_vs_booksim_best_random_pct']:+6.2f}% | "
              f"A/floor {v['A_over_floor']:.2f} ({v['busiest_is']})")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()

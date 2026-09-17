"""S8-C: the fan-out task on a 24x24 mesh KEEPING 17 DIES PER STAGE, under
two judges. 9 stages x 17 dies = 153 of 576 dies, pairs +2/+4/+8 (13),
R-split (each producer die ships V/17 to every consumer die), ONE
merged batch, XY, ports at the link rate (kappa 1). V scaled for a
tractable packet count (recorded). Candidates: named rules on this
grid, random draws (5 seeds), SA endpoints (3 seeds from random + 1
from clustered; objective = our merged busiest resource over links AND
ports; moves = swap two dies between stages, or move one die to a free
slot). Judges on the same batch: ours; BookSim batch duration with its
packet / network latency and hop averages. The bottleneck type of every
candidate is READ, not imposed.

    python3 scripts/b_fanout_24x24_rerank.py -> analysis/b_fanout_24x24_rerank.json
"""
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import booksim_bridge as bb
from scripts import search_eval as se

OUT = os.path.join(se.A, "b_fanout_24x24_rerank.json")
K, N_STAGES, PER = 24, 9, 17
FANOUT = (2, 4, 8)
V = 350000.0 / 4          # 87,500 words per pair: 40 packets per flow, ~154k packets
                          # per candidate (the batch accounting fails at ~605k)
STEPS, ALPHA, SEEDS = 1200, 0.996, (0, 1, 2)
PAIRS = [(s, s + k) for s in range(N_STAGES) for k in FANOUT if s + k < N_STAGES]


def node(x, y):
    return y * K + x


def path_edges(s, d):
    sx, sy, dx, dy = s % K, s // K, d % K, d // K
    x, y, out = sx, sy, []
    while x != dx:
        st = 1 if dx > x else -1
        out.append(("h", min(x, x + st), y, st))
        x += st
    while y != dy:
        st = 1 if dy > y else -1
        out.append(("v", x, min(y, y + st), st))
        y += st
    return out


_PATH = {}


def edges(s, d):
    key = (s, d)
    if key not in _PATH:
        _PATH[key] = path_edges(s, d)
    return _PATH[key]


def flows_of(stages):
    fl = []
    for a, b in PAIRS:
        piece = V / len(stages[a])
        fl += [(p, c, piece) for p in stages[a] for c in stages[b] if p != c]
    return fl


def loads(stages, ports=True):
    load = {}
    for s, d, w in flows_of(stages):
        for e in edges(s, d):
            load[e] = load.get(e, 0.0) + w
        if ports:
            load[("inj", s)] = load.get(("inj", s), 0.0) + w
            load[("ej", d)] = load.get(("ej", d), 0.0) + w
    return load


def ours(stages):
    return max(loads(stages).values())


def link_only(stages):
    return max(loads(stages, ports=False).values())


def port_max(stages):
    return max(v for k, v in loads(stages).items() if k[0] in ("inj", "ej"))


def booksim(stages):
    pk = [(s, d, bb.packets_for(w)) for s, d, w in flows_of(stages) if w > 0]
    r = bb.run_batch(pk, k=K)
    r["packets"] = sum(p for _, _, p in pk)
    return r


def gen_named():
    out = {}
    seq = [node(i % K, i // K) for i in range(N_STAGES * PER)]
    out["sequential"] = [seq[PER * s:PER * (s + 1)] for s in range(N_STAGES)]
    order = []
    for y in range(K):
        xs = list(range(K)) if y % 2 == 0 else list(range(K - 1, -1, -1))
        order += [node(x, y) for x in xs]
    out["snake"] = [order[PER * s:PER * (s + 1)] for s in range(N_STAGES)]
    # clustered: 3x6 rectangles (18 slots, 17 used) tiled 8 across x 4 down, taken in snake order
    rects = []
    for ry in range(4):
        cols = range(8) if ry % 2 == 0 else range(7, -1, -1)
        for rx in cols:
            rects.append([node(3 * rx + dx, 6 * ry + dy) for dy in range(6) for dx in range(3)])
    out["clustered"] = [r[:PER] for r in rects[:N_STAGES]]
    out["dispersed"] = [[s + N_STAGES * j for j in range(PER)] for s in range(N_STAGES)]
    return out


def gen_random(seed):
    rng = random.Random(seed)
    ids = list(range(K * K))
    rng.shuffle(ids)
    return [ids[PER * s:PER * (s + 1)] for s in range(N_STAGES)]


def anneal(start, seed, t0):
    rng = random.Random(seed)
    cur = [list(s) for s in start]
    used = set(d for s in cur for d in s)
    free = [i for i in range(K * K) if i not in used]
    j = ours(cur)
    best, best_st, curve = j, [list(s) for s in cur], []
    for k in range(STEPS):
        t = t0 * (ALPHA ** k)
        cand = [list(s) for s in cur]
        if rng.random() < 0.4:
            a = rng.randrange(N_STAGES)
            i = rng.randrange(PER)
            fi = rng.randrange(len(free))
            cand[a][i], free_new = free[fi], cand[a][i]
        else:
            a, b = rng.sample(range(N_STAGES), 2)
            i, m = rng.randrange(PER), rng.randrange(PER)
            cand[a][i], cand[b][m] = cand[b][m], cand[a][i]
            free_new = None
        v = ours(cand)
        if v < j - 1e-9 or (t > 0 and rng.random() < math.exp(-(v - j) / t)):
            if free_new is not None:
                free[fi] = free_new
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
        for kk, i in enumerate(o):
            r[i] = kk
        return r
    ra, rb = rk(a), rk(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    return (sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
            / ((sum((x - ma) ** 2 for x in ra) ** 0.5) * (sum((y - mb) ** 2 for y in rb) ** 0.5)))


def main():
    cands = gen_named()
    for s in range(5):
        cands[f"random_s{s}"] = gen_random(s)
    rungs = {n: ours(st) for n, st in cands.items()}
    t0 = (max(rungs.values()) - min(rungs.values())) / 20.0
    runs = {}
    for start, seeds in (("random_s0", SEEDS), ("clustered", (0,))):
        for s in seeds:
            t = time.perf_counter()
            st, v, curve = anneal(cands[start], 7919 * s + 3, t0)
            key = f"sa_from_{start}_s{s}"
            cands[key] = st
            runs[key] = {"start": start, "sa_seed": s, "t0_words": t0, "best_words": v,
                         "curve": curve, "wall_s": time.perf_counter() - t}
            print(f"  {key:24} -> {v/1e6:.3f}M words ({runs[key]['wall_s']:.0f} s)", flush=True)
    rows = {}
    for n, st in cands.items():
        t = time.perf_counter()
        bk = booksim(st)
        lo, po = link_only(st), port_max(st)
        rows[n] = {"stages": st, "ours_words": ours(st), "link_only_words": lo,
                   "port_max_words": po, "A_over_floor": ours(st) / po,
                   "busiest_is": "port" if po >= lo else "link",
                   "booksim_cycles": bk["cycles"], "packets": bk["packets"],
                   "packet_latency_avg": bk.get("packet_latency_avg"),
                   "network_latency_avg": bk.get("network_latency_avg"),
                   "hops_avg": bk.get("hops_avg"), "booksim_wall_s": time.perf_counter() - t,
                   "booksim_over_ours": bk["cycles"] / (ours(st) / bb.FLIT_PAYLOAD_B)}
        r = rows[n]
        print(f"  {n:24} ours {r['ours_words']/1e6:7.3f}M ({r['busiest_is']}, A/floor "
              f"{r['A_over_floor']:.2f}) | BookSim {r['booksim_cycles']:8d} cyc ratio "
              f"{r['booksim_over_ours']:.3f} | pkt {r['packet_latency_avg'] or 0:.0f} net "
              f"{r['network_latency_avg'] or 0:.0f} hops {r['hops_avg'] or 0:.2f} | "
              f"{r['booksim_wall_s']:.0f} s", flush=True)
    names = list(rows)
    o = [rows[n]["ours_words"] for n in names]
    b = [rows[n]["booksim_cycles"] for n in names]
    rnd = [n for n in names if n.startswith("random_s")]
    base_ours = min(rnd, key=lambda n: rows[n]["ours_words"])
    base_book = min(rnd, key=lambda n: rows[n]["booksim_cycles"])
    ends = [n for n in names if n.startswith("sa_")]
    summary = {"spearman": spearman(o, b),
               "top1_ours": names[o.index(min(o))], "top1_booksim": names[b.index(min(b))],
               "ratio_min": min(rows[n]["booksim_over_ours"] for n in names),
               "ratio_max": max(rows[n]["booksim_over_ours"] for n in names),
               "strongest_random_under_ours": base_ours,
               "strongest_random_under_booksim": base_book,
               "endpoints": {e: {
                   "gain_ours_vs_ours_best_random_pct": (1 - rows[e]["ours_words"] / rows[base_ours]["ours_words"]) * 100,
                   "gain_booksim_vs_ours_best_random_pct": (1 - rows[e]["booksim_cycles"] / rows[base_ours]["booksim_cycles"]) * 100,
                   "gain_booksim_vs_booksim_best_random_pct": (1 - rows[e]["booksim_cycles"] / rows[base_book]["booksim_cycles"]) * 100,
                   "A_over_floor": rows[e]["A_over_floor"], "busiest_is": rows[e]["busiest_is"]}
                   for e in ends}}
    out = {"note": __doc__.strip(), "grid": f"{K}x{K}", "stages": N_STAGES, "per_stage": PER,
           "fanout": FANOUT, "n_pairs": len(PAIRS), "V_words": V,
           "schedule": {"t0_words": t0, "alpha": ALPHA, "steps": STEPS},
           "runs": runs, "rows": rows, "summary": summary}
    json.dump(out, open(OUT, "w"), indent=1)
    s = summary
    print(f"Spearman {s['spearman']:.3f}; top-1 ours {s['top1_ours']} / BookSim {s['top1_booksim']}; "
          f"ratio {s['ratio_min']:.3f}..{s['ratio_max']:.3f}; strongest random: ours "
          f"{s['strongest_random_under_ours']}, BookSim {s['strongest_random_under_booksim']}")
    for e, v in s["endpoints"].items():
        print(f"  {e:24} gain ours {v['gain_ours_vs_ours_best_random_pct']:+6.2f}% | BookSim vs "
              f"ours-best random {v['gain_booksim_vs_ours_best_random_pct']:+6.2f}% | BookSim vs "
              f"BookSim-best random {v['gain_booksim_vs_booksim_best_random_pct']:+6.2f}% | "
              f"A/floor {v['A_over_floor']:.2f} ({v['busiest_is']})")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()

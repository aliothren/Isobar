"""V3 E3: discriminability, ranking and decision quality (2026-10-08).

Candidate libraries with fixed workload, tiling, logical traffic, routing
and execution; only the seating changes. For every candidate the record
keeps the proxies (total words, integer word-hops, max-hops sum, mean
hops, links-only bottleneck sum, the full bottleneck sum over links and
ports at kappa) and the full-model latency; for the BookSim scenarios
also the packet-level completion time (kappa = 1, serial hand-offs: the
batch times of the hand-offs are summed).

Scenarios (all on square meshes so the bridge's node index equals the
slot index):
  mech4x4     the ffn1 -> ffn2 hand-off (25 flows) on a 4x4 mesh
  layer6x6    one 2.7B layer (17 dies, 4 hand-offs) on a 6x6 mesh
  layers2_8x8 two 2.7B layers (34 dies, 9 hand-offs) on an 8x8 mesh
  layer12x12  one 2.7B layer on a 12x12 mesh (sparse)
  decode6x6   one 2.7B decode layer on a 6x6 mesh (short flows)
  ref544      the reference configuration, proxies only (no BookSim)
  fanout24    the recorded 13-candidate fan-out batch (b_fanout_24x24_rerank.json), re-used

    python3 scripts/v3_discrim.py libraries [--scenarios a,b] [--n-random 50] [--no-booksim]
    python3 scripts/v3_discrim.py ablation  [--configs ref_k2,ref_k1,ref_k4,layer6x6_k1]
Outputs under analysis/v3/e3/.
"""
import argparse
import csv
import json
import math
import os
import random
import statistics
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import cimsim_cli as cli            # noqa: E402
from scripts import llm_workload as lw           # noqa: E402
from scripts import search_baselines as sb       # noqa: E402
from scripts import search_eval as se            # noqa: E402
from scripts import search_sa as sa              # noqa: E402
from scripts import search_space as ss           # noqa: E402
from scripts import v3_sweep as v3               # noqa: E402

A = os.path.join(WS, "analysis")
OUT = os.path.join(A, "v3", os.environ.get("E3_DIR", "e3_k2"))
REF = json.load(open(os.path.join(A, "scale_2p7b_per_op.json")))
BW = 0.4
# V3 (2026-10-09): comparisons are made at the main configuration's port ratio.
# The analytic side uses kappa 2; BookSim needs a perfect-square concentration,
# so it runs at c = 4 terminals per die, which is the same regime (ports never
# bind beyond kappa 2). kappa = 1 is the port-bound corner and is not a
# comparison setting (its earlier runs are kept under analysis/v3/e3/).
KAPPA_AN = float(os.environ.get("E3_KAPPA_AN", "2"))
KAPPA_BS = int(os.environ.get("E3_KAPPA_BS", "4"))
TOLS = (0.001, 0.005, 0.01)


# ------------------------------------------------------------------ helpers
def spearman(a, b):
    def ranks(x):
        order = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else None


def inversions(a, b):
    """Fraction of candidate pairs ordered differently by a and b (ties ignored)."""
    n, inv, tot = len(a), 0, 0
    for i in range(n):
        for j in range(i + 1, n):
            da, db = a[i] - a[j], b[i] - b[j]
            if da == 0 or db == 0:
                continue
            tot += 1
            if (da > 0) != (db > 0):
                inv += 1
    return inv / tot if tot else None


def tie_groups(vals, tol):
    """Groups of candidate indices whose proxy values agree within tol
    (relative, 0 = exact). Greedy on the sorted values."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    groups, cur = [], [order[0]]
    for i in order[1:]:
        base = vals[cur[0]]
        if (vals[i] == base) if tol == 0 else (abs(vals[i] - base) <= tol * max(abs(base), 1e-30)):
            cur.append(i)
        else:
            groups.append(cur); cur = [i]
    groups.append(cur)
    return [g for g in groups if len(g) > 1]


def proxies_of(handoffs, icl, kappa):
    """handoffs: list of flow lists. Returns the proxy dict."""
    out = {"words": 0.0, "word_hops": 0, "max_hops": 0, "A_full": 0.0, "A_links": 0.0, "A_full_k1": 0.0,
           "n_flows": 0, "hop_sum": 0, "port_floor": 0.0}
    for fl in handoffs:
        loads = se.resource_loads(fl, icl, ports=True, kappa=kappa)
        out["A_full"] += max(loads.values())
        out["A_links"] += max(v for k, v in loads.items() if k[0] != "port")
        loads1 = se.resource_loads(fl, icl, ports=True, kappa=1.0)
        out["A_full_k1"] += max(loads1.values())
        out["port_floor"] += max(v for k, v in loads1.items() if k[0] == "port")
        hops = [int(round(icl.hops(*f["nodes"]))) for f in fl]
        out["word_hops"] += int(sum(round(f["volume"] * f["width"]) * h for f, h in zip(fl, hops)))
        out["max_hops"] += max(hops) if hops else 0
        out["hop_sum"] += sum(hops)
        out["words"] += sum(f["volume"] * f["width"] for f in fl)
        out["n_flows"] += len(fl)
    out["mean_hops"] = out["hop_sum"] / out["n_flows"] if out["n_flows"] else 0.0
    return out


# ------------------------------------------------------------------ instances
def make_W(grid, L, S=512, kappa=1.0, phase="prefill"):
    fab = v3.make_fabric(grid, "mesh", "xy")
    acc = dict(REF); acc = json.loads(json.dumps(REF)); acc["config"]["n_layers"] = L
    W = v3.V3Workload(fab, acc, ("M", "C"))
    W.port_ratio = kappa
    return W


def handoffs_of(W, pi, phase):
    return [fl for _, fl in cli.handoff_flows(W, pi, phase)]


def booksim_time(handoffs, k, scale, bb, kappa=None):
    kappa = KAPPA_BS if kappa is None else kappa
    """Serial semantics: sum over hand-offs of the batch completion cycles at
    the volume scale; returns (cycles, packets, bound cycles)."""
    tot, n_pk, bound = 0, 0, 0
    for fl in handoffs:
        agg = {}
        for f in fl:
            a, b = f["nodes"]
            agg[(a, b)] = agg.get((a, b), 0.0) + f["volume"] * f["width"]
        flows = [(a, b, bb.packets_for(w * scale)) for (a, b), w in agg.items()]
        n_pk += sum(n for _, _, n in flows)
        bound += max(bb.flit_bounds(flows, k=k, kappa=kappa).values())
        tot += bb.run_batch(flows, k=k, kappa=kappa)["cycles"]
    return tot, n_pk, bound


def trajectory_sampler(J, every=100):
    seen = []

    def wrapped(pi):
        wrapped.calls += 1
        if wrapped.calls % every == 0:
            seen.append(pi)
        return J(pi)
    wrapped.calls = 0
    wrapped.seen = seen
    return wrapped


class ProxyObjective:
    """Full-recompute proxy objectives on a V3Workload (small instances only)."""

    def __init__(self, W, kind, phase, kappa):
        self.W, self.kind, self.phase, self.kappa = W, kind, phase, kappa

    def __call__(self, pi):
        hs = handoffs_of(self.W, pi, self.phase)
        p = proxies_of(hs, self.W.die_ic, self.kappa)
        return {"links_only": p["A_links"], "word_hops": float(p["word_hops"]), "max_hops": float(p["max_hops"])}[self.kind]


def build_mech4x4(n_random, with_booksim, log=print):
    """The ffn1 -> ffn2 hand-off (5 producers, 5 consumers, 25 flows) on a
    4x4 mesh: candidates are (producer slots, consumer slots) pairs; the
    latency object is the hand-off service time A / B + propagation."""
    bb = None
    if with_booksim:
        from scripts import booksim_bridge as bb
    W = make_W((4, 4), 1, kappa=KAPPA_AN)  # fabric and chain only (the layer itself does not fit 16 slots)
    base = lw.block_chain(W.cfg, W.S, "prefill", on_chip=True, max_dies=10 ** 6)
    names = [e["name"] for e in base]
    prev_e, e = base[names.index("ffn1")], base[names.index("ffn2")]
    icl, fab = W.die_ic, W.fab
    n = 16

    def flows(pc):
        return [se._one_boundary_flows(prev_e, e, list(pc[0]), list(pc[1]), fab)]

    def cost(pc, kind="full"):
        p = proxies_of(flows(pc), icl, KAPPA_AN)
        return {"full": p["A_full"], "links_only": p["A_links"], "word_hops": float(p["word_hops"]), "max_hops": float(p["max_hops"])}[kind]

    def anneal(start, kind, seed, steps=1200, every=None):
        rng = random.Random(seed)
        prod, cons = list(start[0]), list(start[1])
        jb = cost((prod, cons), kind); cur = 1.0
        best, best_pc, seen = cur, (list(prod), list(cons)), []
        t0 = v3.T0_NORM
        for k in range(steps):
            t = t0 * 0.996 ** k
            p2, c2 = list(prod), list(cons)
            used = set(p2) | set(c2)
            if rng.random() < 0.5:        # swap an endpoint between the two sets
                i, j = rng.randrange(5), rng.randrange(5); p2[i], c2[j] = c2[j], p2[i]
            else:                          # move one endpoint to an empty slot
                free = [s for s in range(n) if s not in used]
                tgt = rng.choice(free)
                if rng.random() < 0.5:
                    p2[rng.randrange(5)] = tgt
                else:
                    c2[rng.randrange(5)] = tgt
            j2 = cost((p2, c2), kind) / jb
            if j2 < cur - 1e-15 or (t > 0 and rng.random() < math.exp(-(j2 - cur) / t)):
                prod, cons, cur = p2, c2, j2
                if cur < best - 1e-15:
                    best, best_pc = cur, (list(prod), list(cons))
            if every and (k + 1) % every == 0:
                seen.append((list(prod), list(cons)))
        return best_pc, seen
    cands = {"compact_fill": (list(range(0, 5)), list(range(5, 10)))}
    for s in range(n_random):
        rng = random.Random(s); slots = rng.sample(range(n), 10); cands[f"random_s{s}"] = (slots[:5], slots[5:])
    start = min(cands, key=lambda c: cost(cands[c]))
    for kind in ("full", "links_only", "word_hops", "max_hops"):
        for s in range(3):
            pc, seen = anneal(cands[start], kind, 1000003 * s + 1, every=(200 if kind == "full" and s == 0 else None))
            cands[f"sa_{kind}_s{s}"] = pc
            for i, pcs in enumerate(seen):
                cands[f"traj_{(i + 1) * 200}"] = pcs
    rows = {}
    for cname, pc in cands.items():
        hs = flows(pc)
        p = proxies_of(hs, icl, KAPPA_AN)
        hops = max(icl.hops(*f["nodes"]) for f in hs[0])
        p["T_s"] = p["A_full"] / (BW * 1e9) + hops * 20e-9
        p["H_s"] = p["A_full"] / (BW * 1e9); p["handoff_T_s"] = p["H_s"]
        if with_booksim:
            cyc, npk, bound = booksim_time(hs, 4, 0.01, bb)
            p.update({"booksim_cycles": cyc, "booksim_packets": npk, "bound_cycles": bound, "booksim_over_bound": cyc / bound})
        rows[cname] = {**p, "pi": json.dumps(pc)}
    log(f"[mech4x4] {len(cands)} candidates")
    return {"scenario": "mech4x4", "grid": (4, 4), "L": None, "phase": "prefill", "only_handoff": "ffn2", "scale": 0.01,
            "kappa": KAPPA_AN, "kappa_booksim": KAPPA_BS, "n_candidates": len(cands), "start": start, "candidates": rows}


def build_library(name, n_random, with_booksim, log=print):
    if name == "mech4x4":
        return build_mech4x4(n_random, with_booksim, log)
    bb = None
    if with_booksim:
        from scripts import booksim_bridge as bb
    scen = {"layer6x6": dict(grid=(6, 6), L=1, phase="prefill", scale=0.01),
            "layers2_8x8": dict(grid=(8, 8), L=2, phase="prefill", scale=0.01),
            "layer12x12": dict(grid=(12, 12), L=1, phase="prefill", scale=0.01),
            "decode6x6": dict(grid=(6, 6), L=1, phase="decode", scale=1.0),
            "ref544": dict(grid=(24, 24), L=32, phase="prefill", scale=None)}[name]
    phase, k = scen["phase"], scen["grid"][0]
    W = make_W(scen["grid"], scen["L"], kappa=KAPPA_AN, phase=phase)
    mu = {phase: 1.0}
    only = scen.get("only_handoff")

    def hand(pi):
        hs = cli.handoff_flows(W, pi, phase)
        return [fl for n, fl in hs if (only is None or n.split("@")[0] == only)]
    cands = {}
    for r in sb.NAMES:
        if r != "random":
            try:
                cands[r] = sb.generate(r, W, seed=0)
            except Exception:
                pass
    for s in range(n_random):
        cands[f"random_s{s}"] = sb.generate("random", W, seed=s)
    # searches under four objectives from the best random, 3 seeds each, trajectory samples from the full one
    T0 = v3.T0_NORM
    n_slots = W.fab.level("die").per_parent
    steps = 1200 if name != "ref544" else 1200
    t_eval = {n: se.score(p, W, mu=mu, d2d_gbps=BW).t_opt_s for n, p in cands.items()}
    start = min(cands, key=t_eval.get)
    t_base = t_eval[start]
    for kind in ("full", "links_only", "word_hops", "max_hops"):
        for s in range(3):
            if kind == "full":
                J0 = cli.Objective(W, cands[start], mu, "single", BW, 1.0, "t")
                Jn = lambda pi, J0=J0: J0(pi) / t_base
            else:
                P = ProxyObjective(W, kind, phase, KAPPA_AN)
                jb = P(cands[start])
                Jn = lambda pi, P=P, jb=jb: P(pi) / jb
            Js = trajectory_sampler(Jn, every=200) if (kind == "full" and s == 0) else Jn
            r = sa.anneal(Js, cands[start], n_slots, sa.Schedule(t0=T0, alpha=0.996, steps=steps), seed=1000003 * s + 1)
            cands[f"sa_{kind}_s{s}"] = r.best_pi
            if kind == "full" and s == 0:
                for i, pi in enumerate(Js.seen):
                    cands[f"traj_{(i + 1) * 200}"] = pi
    # proxies and the full model for every candidate
    rows = {}
    t0 = time.perf_counter()
    for n, pi in cands.items():
        hs = hand(pi)
        p = proxies_of(hs, W.die_ic, KAPPA_AN)
        sc = se.score(pi, W, mu=mu, d2d_gbps=BW)
        p["T_s"] = sc.t_opt_s
        p["H_s"] = sc.per_phase[phase]["decomp"]["d2d_serial_s"]
        p["handoff_T_s"] = p["A_full"] / (BW * 1e9)
        rows[n] = p
    log(f"[{name}] {len(cands)} candidates scored in {time.perf_counter() - t0:.0f} s")
    if with_booksim and scen["scale"] is not None:
        t0 = time.perf_counter()
        for n, pi in cands.items():
            cyc, npk, bound = booksim_time(hand(pi), k, scen["scale"], bb)
            rows[n]["booksim_cycles"] = cyc; rows[n]["booksim_packets"] = npk; rows[n]["bound_cycles"] = bound
            rows[n]["booksim_over_bound"] = cyc / bound if bound else None
        log(f"[{name}] BookSim on {len(cands)} candidates in {time.perf_counter() - t0:.0f} s")
    return {"scenario": name, "grid": scen["grid"], "L": scen["L"], "phase": phase, "only_handoff": only,
            "scale": scen["scale"], "kappa": KAPPA_AN, "kappa_booksim": KAPPA_BS, "n_candidates": len(cands), "start": start,
            "candidates": {n: {**rows[n], "pi": pi.to_json() if name != "ref544" else None} for n, pi in cands.items()}}


def analyse_library(lib):
    names = list(lib["candidates"])
    c = lib["candidates"]
    ref_key = "booksim_cycles" if "booksim_cycles" in c[names[0]] else "T_s"
    ref = [c[n][ref_key] for n in names]
    out = {"scenario": lib["scenario"], "reference": ref_key, "n": len(names), "correlations": {}, "inversions": {},
           "tie_groups": {}, "selection_regret": {}}
    for prox in ("A_full", "A_links", "word_hops", "max_hops", "mean_hops", "T_s"):
        vals = [c[n][prox] for n in names]
        if len(set(vals)) == 1:
            out["correlations"][prox] = "n/a (constant)"
            out["inversions"][prox] = "n/a (constant)"
        else:
            out["correlations"][prox] = spearman(vals, ref)
            out["inversions"][prox] = inversions(vals, ref)
        # selection regret: the candidate the proxy would pick (min; ties -> first in name order) vs the reference optimum
        best_ref = min(ref)
        pick = min(names, key=lambda n: (c[n][prox], n))
        picks = [n for n in names if c[n][prox] == c[pick][prox]]
        regrets = [c[n][ref_key] / best_ref - 1 for n in picks]
        out["selection_regret"][prox] = {"selected": pick, "tie_set_size": len(picks),
                                         "regret_min": min(regrets), "regret_max": max(regrets)}
        out["tie_groups"][prox] = {}
        for tol in (0.0,) + TOLS:
            gs = tie_groups(vals, tol)
            spans = [(max(c[n][ref_key] for n in [names[i] for i in g]) / min(c[n][ref_key] for n in [names[i] for i in g]) - 1) for g in gs]
            out["tie_groups"][prox][f"tol{tol:g}"] = {"n_groups": len(gs), "largest": max((len(g) for g in gs), default=0),
                                                      "members_in_groups": sum(len(g) for g in gs),
                                                      "ref_span_max": max(spans) if spans else 0.0,
                                                      "ref_span_median": statistics.median(spans) if spans else 0.0}
    if ref_key == "booksim_cycles":
        ratios = [c[n]["booksim_over_bound"] for n in names]
        out["booksim_over_bound"] = {"min": min(ratios), "median": statistics.median(ratios), "max": max(ratios)}
    return out


def cmd_libraries(args):
    os.makedirs(OUT, exist_ok=True)
    scens = args.scenarios.split(",") if args.scenarios else ["mech4x4", "layer6x6", "layers2_8x8", "layer12x12", "decode6x6", "ref544"]
    libs, analyses = {}, {}
    for s in scens:
        path = os.path.join(OUT, f"library_{s}.json")
        if os.path.exists(path) and not args.redo:
            lib = json.load(open(path))
        else:
            lib = build_library(s, args.n_random if s != "ref544" else 100, not args.no_booksim)
            json.dump(lib, open(path, "w"))
        libs[s] = lib
        analyses[s] = analyse_library(lib)
        print(json.dumps(analyses[s]["correlations"]), analyses[s].get("booksim_over_bound"))
    # the recorded fan-out batch, re-used
    fan = os.path.join(A, "b_fanout_24x24_rerank.json")
    if os.path.exists(fan):
        d = json.load(open(fan))
        analyses["fanout24_recorded"] = {"note": "recorded 13-candidate batch, kappa 1, reused as is", "summary": d.get("summary")}
    json.dump(analyses, open(os.path.join(OUT, "discriminability.json"), "w"), indent=1)
    with open(os.path.join(OUT, "candidates.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "candidate", "T_ms", "H_ms", "A_full", "A_links", "A_full_k1", "port_floor", "word_hops", "max_hops",
                    "mean_hops", "words", "booksim_cycles", "bound_cycles", "booksim_over_bound", "packets"])
        for s, lib in libs.items():
            for n, c in lib["candidates"].items():
                w.writerow([s, n, f"{c['T_s']*1e3:.4f}", f"{c['H_s']*1e3:.4f}", f"{c['A_full']:.0f}", f"{c['A_links']:.0f}",
                            f"{c['A_full_k1']:.0f}", f"{c['port_floor']:.0f}", c["word_hops"], c["max_hops"], f"{c['mean_hops']:.4f}",
                            f"{c['words']:.0f}", c.get("booksim_cycles", ""), c.get("bound_cycles", ""),
                            f"{c['booksim_over_bound']:.4f}" if c.get("booksim_over_bound") else "", c.get("booksim_packets", "")])
    print("->", OUT)


# ------------------------------------------------------------------ ablation
def ablation_mech4x4(n_random):
    """The four objectives on the link-bound 4x4 hand-off (kappa 1), judged by
    the hand-off service time and by BookSim; starts = compact, best random,
    random seed 0; 5 seeds; 1200 steps; normalized temperature."""
    from scripts import booksim_bridge as bb
    lib = build_mech4x4(0, False, log=lambda *a: None)      # just the instance pieces via a rebuild below
    W = make_W((4, 4), 1, kappa=KAPPA_AN)
    base = lw.block_chain(W.cfg, W.S, "prefill", on_chip=True, max_dies=10 ** 6)
    names = [e["name"] for e in base]
    prev_e, e = base[names.index("ffn1")], base[names.index("ffn2")]
    icl, fab = W.die_ic, W.fab

    def flows(pc):
        return [se._one_boundary_flows(prev_e, e, list(pc[0]), list(pc[1]), fab)]

    def cost(pc, kind):
        p = proxies_of(flows(pc), icl, KAPPA_AN)
        return {"full": p["A_full"], "links_only": p["A_links"], "word_hops": float(p["word_hops"]), "max_hops": float(p["max_hops"])}[kind]

    def anneal(start, kind, seed, steps=1200):
        rng = random.Random(seed)
        prod, cons = list(start[0]), list(start[1])
        jb = cost((prod, cons), kind) or 1.0; cur = 1.0
        best, best_pc = cur, (list(prod), list(cons))
        for k in range(steps):
            t = v3.T0_NORM * 0.996 ** k
            p2, c2 = list(prod), list(cons)
            used = set(p2) | set(c2)
            if rng.random() < 0.5:
                i, j = rng.randrange(5), rng.randrange(5); p2[i], c2[j] = c2[j], p2[i]
            else:
                tgt = rng.choice([s for s in range(16) if s not in used])
                if rng.random() < 0.5:
                    p2[rng.randrange(5)] = tgt
                else:
                    c2[rng.randrange(5)] = tgt
            j2 = cost((p2, c2), kind) / jb
            if j2 < cur - 1e-15 or (t > 0 and rng.random() < math.exp(-(j2 - cur) / t)):
                prod, cons, cur = p2, c2, j2
                if cur < best - 1e-15:
                    best, best_pc = cur, (list(prod), list(cons))
        return best_pc
    cands = {"compact_fill": (list(range(0, 5)), list(range(5, 10)))}
    for s in range(n_random):
        rng = random.Random(s); sl = rng.sample(range(16), 10); cands[f"random_s{s}"] = (sl[:5], sl[5:])
    Tc = {n: cost(pc, "full") for n, pc in cands.items()}
    strongest = min(cands, key=Tc.get)
    starts = {"compact": "compact_fill", "random_best": strongest, "random_s0": "random_s0"}
    runs = {}
    for kind in ("full", "links_only", "word_hops", "max_hops"):
        for i, (sn, cn) in enumerate(sorted(starts.items())):
            for s in range(5):
                pc = anneal(cands[cn], kind, 1000003 * s + i)
                A = cost(pc, "full")
                cyc, npk, bound = booksim_time(flows(pc), 4, 0.01, bb)
                runs[f"{kind}_{sn}_s{s}"] = {"objective": kind, "start": sn, "seed": s, "A_full": A,
                                              "gain_vs_strongest_pct": (1 - A / Tc[strongest]) * 100,
                                              "booksim_cycles": cyc, "bound_cycles": bound, "pi": json.dumps(pc)}
    cyc0, _, _ = booksim_time(flows(cands[strongest]), 4, 0.01, bb)
    summary = {}
    for kind in ("full", "links_only", "word_hops", "max_hops"):
        per_seed = [min(runs[f"{kind}_{sn}_s{s}"]["A_full"] for sn in starts) for s in range(5)]
        bs = [min(runs[f"{kind}_{sn}_s{s}"]["booksim_cycles"] for sn in starts) for s in range(5)]
        summary[kind] = {"A_median": statistics.median(per_seed), "A_min": min(per_seed), "A_max": max(per_seed),
                         "gain_median_pct": (1 - statistics.median(per_seed) / Tc[strongest]) * 100,
                         "booksim_median_cycles": statistics.median(bs),
                         "booksim_gain_vs_strongest_pct": (1 - statistics.median(bs) / cyc0) * 100}
    for kind in summary:
        summary[kind]["overhead_vs_full_median_pct"] = (summary[kind]["A_median"] / summary["full"]["A_median"] - 1) * 100
        summary[kind]["booksim_overhead_vs_full_pct"] = (summary[kind]["booksim_median_cycles"] / summary["full"]["booksim_median_cycles"] - 1) * 100
    return {"config": f"mech4x4_k{KAPPA_AN:g}", "grid": (4, 4), "kappa": KAPPA_AN, "kappa_booksim": KAPPA_BS, "n_random": n_random, "strongest": strongest,
            "A_base": Tc[strongest], "strongest_booksim_cycles": cyc0, "starts": starts, "runs": runs, "summary": summary}


def cmd_ablation(args):
    os.makedirs(OUT, exist_ok=True)
    if args.configs.startswith("mech4x4"):
        rec = ablation_mech4x4(args.n_random)
        json.dump({rec["config"]: rec}, open(os.path.join(OUT, f"ablation_{rec['config']}.json"), "w"), indent=1)
        print(json.dumps(rec["summary"], indent=1)); return
    cfgs = {"ref_k2": dict(grid=(24, 24), L=32, kappa=2.0), "ref_k1": dict(grid=(24, 24), L=32, kappa=1.0),
            "ref_k4": dict(grid=(24, 24), L=32, kappa=4.0), "layer6x6_k1": dict(grid=(6, 6), L=1, kappa=1.0),
            "layer6x6_k2": dict(grid=(6, 6), L=1, kappa=2.0), "layers2_8x8_k2": dict(grid=(8, 8), L=2, kappa=2.0)}
    which = args.configs.split(",") if args.configs else list(cfgs)
    res = {}
    for name in which:
        c = cfgs[name]
        W = make_W(c["grid"], c["L"], kappa=c["kappa"])
        mu = {"prefill": 1.0}
        cands = {r: sb.generate(r, W, seed=0) for r in sb.NAMES if r != "random"}
        for s in range(args.n_random):
            cands[f"random_s{s}"] = sb.generate("random", W, seed=s)
        T = {n: se.score(p, W, mu=mu, d2d_gbps=BW).t_opt_s for n, p in cands.items()}
        rules = [n for n in cands if not n.startswith("random_s")]
        starts = {"rule": min(rules, key=T.get), "random_best": min([n for n in cands if n.startswith("random_s")], key=T.get),
                  "random_s0": "random_s0"}
        strongest = min(cands, key=T.get); t_base = T[strongest]
        n_dies = sum(W.inventory().values())
        steps = v3.budget(n_dies)
        n_slots = W.fab.level("die").per_parent
        runs = {}
        for kind in ("full", "links_only", "word_hops", "max_hops"):
            for i, (sn, cn) in enumerate(sorted(starts.items())):
                for s in range(5):
                    if kind == "full":
                        J0 = cli.Objective(W, cands[cn], mu, "single", BW, 1.0, "t"); jb = t_base
                        Jn = lambda pi, J0=J0, jb=jb: J0(pi) / jb
                    else:
                        if c["L"] > 2:
                            # the proxies on the full model: rebuild flows per call (cimsim_cli.handoff_flows), ~37 ms each
                            P = ProxyObjective(W, kind, "prefill", c["kappa"])
                        else:
                            P = ProxyObjective(W, kind, "prefill", c["kappa"])
                        jb = P(cands[strongest])
                        Jn = lambda pi, P=P, jb=jb: P(pi) / jb
                    t = time.perf_counter()
                    r = sa.anneal(Jn, cands[cn], n_slots, sa.Schedule(t0=v3.T0_NORM, alpha=0.996, steps=steps), seed=1000003 * s + i)
                    Tend = se.score(r.best_pi, W, mu=mu, d2d_gbps=BW).t_opt_s
                    runs[f"{kind}_{sn}_s{s}"] = {"objective": kind, "start": sn, "seed": s, "T_s": Tend,
                                                  "gain_vs_strongest_pct": (1 - Tend / t_base) * 100, "wall_s": time.perf_counter() - t,
                                                  "pi": r.best_pi.to_json() if c["L"] <= 2 else None}
                print(f"[{name}] {kind} {sn}: " + ", ".join(f"{runs[f'{kind}_{sn}_s{s}']['gain_vs_strongest_pct']:.2f}%" for s in range(5)), flush=True)
        summary = {}
        for kind in ("full", "links_only", "word_hops", "max_hops"):
            per_seed = [min(runs[f"{kind}_{sn}_s{s}"]["T_s"] for sn in starts) for s in range(5)]
            summary[kind] = {"T_median_s": statistics.median(per_seed), "T_min_s": min(per_seed), "T_max_s": max(per_seed),
                             "gain_median_pct": (1 - statistics.median(per_seed) / t_base) * 100}
        for kind in summary:
            summary[kind]["overhead_vs_full_median_pct"] = (summary[kind]["T_median_s"] / summary["full"]["T_median_s"] - 1) * 100
            summary[kind]["overhead_vs_full_best_pct"] = (summary[kind]["T_min_s"] / summary["full"]["T_min_s"] - 1) * 100
        rec = {"config": name, **c, "n_dies": n_dies, "steps": steps, "strongest": strongest, "T_base_s": t_base,
               "starts": starts, "t0_norm": v3.T0_NORM, "runs": runs, "summary": summary}
        if name in ("layer6x6_k1", "layer6x6_k2", "layers2_8x8_k2"):
            from scripts import booksim_bridge as bb
            kk = int(c["grid"][0]); kb = 1 if c["kappa"] == 1 else KAPPA_BS
            for n, r_ in runs.items():
                pi = ss.Pi.from_json(r_["pi"])
                cyc, npk, bound = booksim_time(handoffs_of(W, pi, "prefill"), kk, 0.01, bb, kappa=kb)
                r_["booksim_cycles"] = cyc; r_["bound_cycles"] = bound
            cyc, _, _ = booksim_time(handoffs_of(W, cands[strongest], "prefill"), kk, 0.01, bb, kappa=kb)
            rec["strongest_booksim_cycles"] = cyc
            for kind in summary:
                bs = [min(runs[f"{kind}_{sn}_s{s}"]["booksim_cycles"] for sn in starts) for s in range(5)]
                summary[kind]["booksim_median_cycles"] = statistics.median(bs)
                summary[kind]["booksim_gain_vs_strongest_pct"] = (1 - statistics.median(bs) / cyc) * 100
        res[name] = rec
        json.dump(res, open(os.path.join(OUT, f"ablation_{name}.json"), "w"), indent=1)
        print(f"[{name}] " + " | ".join(f"{k}: {v['gain_median_pct']:.2f}% (+{v['overhead_vs_full_median_pct']:.2f}% vs full)" for k, v in summary.items()), flush=True)
    print("->", os.path.join(OUT, "ablation.json"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("libraries", "ablation"))
    ap.add_argument("--scenarios", default="")
    ap.add_argument("--configs", default="")
    ap.add_argument("--n-random", type=int, default=50)
    ap.add_argument("--no-booksim", action="store_true")
    ap.add_argument("--redo", action="store_true")
    args = ap.parse_args()
    {"libraries": cmd_libraries, "ablation": cmd_ablation}[args.cmd](args)


if __name__ == "__main__":
    main()

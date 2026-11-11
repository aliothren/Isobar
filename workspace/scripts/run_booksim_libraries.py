"""The BookSim candidate libraries of Figs. 3(b) and 4: small instances of
the 2.7B-class reference (account results/reference/reference_2p7b_S512.json)
on which every candidate seating is scored by the analytic model and by
the packet-level BookSim simulator, with the workload, tiling, logical
traffic, routing and execution fixed and only the seating varied.

Sets and scenarios (square meshes, so the bridge's node index equals the
slot index):
  offload   attention on the central digital unit; analytic die ports and
            unit interface at kappa = 4 (BookSim's c = 4 terminals per node)
              offload6x6         one layer, prefill (volumes x 0.01), 6x6
              offload_decode6x6  one layer, decode, 6x6
              offload2_8x8       two layers, prefill (volumes x 0.01), 8x8
  onchip    attention on a CIM die, kappa = 2 (the equal-word-hops example)
              layer6x6           one layer, prefill (volumes x 0.01), 6x6

Candidates per scenario: the named rules, 50 random fills, the endpoints of
annealer runs under four objectives and samples along one run. BookSim
completion time = the sum of the batch completion cycles of the hand-offs
(serial execution); the BookSim binary is built from tools/booksim2.

    python3 scripts/run_booksim_libraries.py [--set offload|onchip|all] [--n-random 50] [--redo] [--no-booksim]
      -> results/booksim/offload/library_<scenario>.json, results/booksim/onchip/library_layer6x6.json
"""
import argparse
import json
import math
import os
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import experiment as v3             # noqa: E402
from scripts import objective as ob              # noqa: E402
from scripts import paths                        # noqa: E402
from scripts import search_baselines as sb       # noqa: E402
from scripts import search_eval as se            # noqa: E402
from scripts import search_sa as sa              # noqa: E402

BW = 0.4                       # mesh link rate (GB/s per direction) of the analytic side
KAPPA_BS = 4                   # BookSim terminals per node (c of the concentrated mesh)
SCENARIOS = {"offload6x6": dict(grid=(6, 6), L=1, phase="prefill", scale=0.01, offload=True),
             "offload_decode6x6": dict(grid=(6, 6), L=1, phase="decode", scale=1.0, offload=True),
             "offload2_8x8": dict(grid=(8, 8), L=2, phase="prefill", scale=0.01, offload=True),
             "layer6x6": dict(grid=(6, 6), L=1, phase="prefill", scale=0.01)}
SETS = {"offload": (4.0, ("offload6x6", "offload_decode6x6", "offload2_8x8")), "onchip": (2.0, ("layer6x6",))}


# ------------------------------------------------------------------ rank helpers
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
def make_W(grid, L, S=512, kappa=1.0, phase="prefill", offload=False):
    fab = v3.make_fabric(grid, "mesh", "xy")
    acc = json.load(open(paths.REFERENCE_ACCOUNT)); acc["config"]["n_layers"] = L
    W = v3.AccountWorkload(fab, acc, ("M", "C"))
    W.port_ratio = kappa
    if offload:        # the central unit; its interface equals the die ports (kappa links) so that BookSim's c terminals per node express it
        from scripts import offload as offload_mod, placement as pm
        W.offload = offload_mod.build(pm.sequential_fill(fab).slots["die"], L, position="center", K=1, overrides={"link_bandwidth_gbps": BW * kappa})
    return W


def handoffs_of(W, pi, phase):
    return [fl for _, fl in ob.handoff_flows(W, pi, phase)]


def booksim_time(handoffs, k, scale, bb, kappa=None):
    """Serial semantics: sum over hand-offs of the batch completion cycles at
    the volume scale; returns (cycles, packets, bound cycles)."""
    kappa = KAPPA_BS if kappa is None else kappa
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
    """Full-recompute proxy objectives on an AccountWorkload (small instances only)."""

    def __init__(self, W, kind, phase, kappa):
        self.W, self.kind, self.phase, self.kappa = W, kind, phase, kappa

    def __call__(self, pi):
        hs = handoffs_of(self.W, pi, self.phase)
        p = proxies_of(hs, self.W.die_ic, self.kappa)
        return {"links_only": p["A_links"], "word_hops": float(p["word_hops"]), "max_hops": float(p["max_hops"])}[self.kind]


def build_library(name, n_random, with_booksim, kappa, log=print):
    """Score every candidate of one scenario: the named rules, n_random random
    fills, the endpoints of three annealer runs under each of four objectives
    (the full objective, links only, word-hops, max-hops; all started from
    the best candidate of the rules and fills) and samples along the first
    full-objective run; with BookSim, the packet-level completion time."""
    bb = None
    if with_booksim:
        from scripts import booksim_bridge as bb
    scen = SCENARIOS[name]
    phase, k = scen["phase"], scen["grid"][0]
    W = make_W(scen["grid"], scen["L"], kappa=kappa, phase=phase, offload=scen.get("offload", False))
    mu = {phase: 1.0}
    only = scen.get("only_handoff")

    def hand(pi):
        hs = ob.handoff_flows(W, pi, phase)
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
    n_slots = W.usable_slots() if getattr(W, "offload", None) is not None else W.fab.level("die").per_parent
    steps = 1200
    t_eval = {n: se.score(p, W, mu=mu, d2d_gbps=BW).t_opt_s for n, p in cands.items()}
    start = min(cands, key=t_eval.get)
    t_base = t_eval[start]
    for kind in ("full", "links_only", "word_hops", "max_hops"):
        for s in range(3):
            if kind == "full":
                J0 = ob.Objective(W, cands[start], mu, "single", BW, 1.0, "t")
                Jn = lambda pi, J0=J0: J0(pi) / t_base
            else:
                P = ProxyObjective(W, kind, phase, kappa)
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
        p = proxies_of(hs, W.die_ic, kappa)
        sc = se.score(pi, W, mu=mu, d2d_gbps=BW)
        p["T_s"] = sc.t_opt_s
        p["H_s"] = sc.per_phase[phase]["decomp"]["d2d_serial_s"]
        p["handoff_T_s"] = p["A_full"] / (BW * 1e9)
        rows[n] = p
    log(f"[{name}] {len(cands)} candidates scored in {time.perf_counter() - t0:.0f} s")
    if with_booksim:
        t0 = time.perf_counter()
        for n, pi in cands.items():
            cyc, npk, bound = booksim_time(hand(pi), k, scen["scale"], bb)
            rows[n]["booksim_cycles"] = cyc; rows[n]["booksim_packets"] = npk; rows[n]["bound_cycles"] = bound
            rows[n]["booksim_over_bound"] = cyc / bound if bound else None
        log(f"[{name}] BookSim on {len(cands)} candidates in {time.perf_counter() - t0:.0f} s")
    return {"scenario": name, "grid": scen["grid"], "L": scen["L"], "phase": phase, "only_handoff": only,
            "scale": scen["scale"], "kappa": kappa, "kappa_booksim": KAPPA_BS, "n_candidates": len(cands), "start": start,
            "candidates": {n: {**rows[n], "pi": pi.to_json()} for n, pi in cands.items()}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=("offload", "onchip", "all"), default="all")
    ap.add_argument("--n-random", type=int, default=50)
    ap.add_argument("--no-booksim", action="store_true", help="analytic scores only")
    ap.add_argument("--redo", action="store_true", help="rebuild libraries that already exist")
    args = ap.parse_args()
    for name in (("offload", "onchip") if args.set == "all" else (args.set,)):
        kappa, scens = SETS[name]
        out = paths.ensure(os.path.join(paths.BOOKSIM, name))
        for s in scens:
            path = os.path.join(out, f"library_{s}.json")
            if os.path.exists(path) and not args.redo:
                print(f"[{s}] exists: {path}")
                continue
            lib = build_library(s, args.n_random, not args.no_booksim, kappa)
            json.dump(lib, open(path, "w"))
            c = lib["candidates"]
            names = [n for n in c if "booksim_cycles" in c[n]]
            if names:
                rho = spearman([c[n]["A_full"] for n in names], [c[n]["booksim_cycles"] for n in names])
                print(f"[{s}] Spearman(analytic, BookSim) = {rho:.3f} over {len(names)} candidates -> {path}")


if __name__ == "__main__":
    main()

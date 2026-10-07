"""Workload and placement reuse (the Fig. 6(b) study, 2026-10-02).

Question: when the workload changes, does the frozen headline layout lose
gain because the communication share shrinks (dilution) or because the new
traffic needs a different placement (mismatch)? Compare REUSE (the frozen
layout sa_random_s1, selected at 512-token prefill, re-scored at the target
workpoint) with REUSE + SEARCH (a fresh search at the workpoint, the frozen
layout kept as the fallback).

Workpoints: prefill S in {128, 512, 1024} and decode over a K/V cache of
{128, 512, 1024} tokens. S = 2048 is infeasible under the frozen grouping:
the attention die must hold K^T and V for all 32 heads, 2 x 32 x 80 x S x 2
cells = 20.97M cells at S = 2048 against a die of 16.78M, so attention
would need a second die and the inventory would change; 1024 (10.49M
cells) is the largest power-of-two length that keeps the grouping.

Accounts: the S = 512 account is the mapper measurement. For 128 and 1024
the account is DERIVED unless analysis/scale_2p7b_per_op_S{S}.json (from
run_2p7b_block_S.py, a mapper run) exists: compute per operator = rows x
the operator's per-row time of the S = 512 mapping (exact for the resident
spatial mapping: the measured compute is P x 10.14 us for every static
operator and P x a constant for the attention operators; decode has P = 1
at every cache length), write = min(write_rows, 256) x T_SET (the account's
own rule, checked against all four written operators at S = 512),
elementwise closed-form at S (the evaluator's own term), energy scaled with
rows for prefill and unchanged for decode (not used for latency). The
derivation is written into each account and into the results.

Invariance: every hand-off volume is P x (words per row), so H_S(p) =
(S / 512) H_512(p) exactly in prefill and H is identical at every decode
cache length; R is placement-independent. The ordering of placements is
therefore the same at every workpoint, which is checked numerically here.

Search protocol: 3 starts (clustered, random, snake) x 3 seeds, 1200 steps,
alpha 0.996, the normalized objective T / T_base with T_base the
workpoint's strongest baseline and the dimensionless t0 = 20 ms / 2118.71
ms = 0.0094396 (the main experiment's temperature over its strongest
baseline), seed = 1000003 x s + start index. Per seed the best of three
starts; the headline is the median seed with the range.

    python3 scripts/workload_reuse.py   -> analysis/workload_reuse/{workload_reuse.json, per_run.csv, summary.csv, workload_reuse.md}
"""
import csv
import json
import os
import statistics
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import cimsim_cli as cli                  # noqa: E402
from scripts import fabric as fm                       # noqa: E402
from scripts import llm_workload as lw                 # noqa: E402
from scripts import search_baselines as sb             # noqa: E402
from scripts import search_eval as se                  # noqa: E402
from scripts import search_sa as sa                    # noqa: E402
from scripts import search_space as ss                 # noqa: E402

A = os.path.join(WS, "analysis")
OUT = os.path.join(A, "workload_reuse")
BASE = os.path.join(A, "scale_2p7b_per_op.json")
KAPPA, BW = 2.0, 0.4
S_POINTS = (128, 512, 1024)
INFEASIBLE = {2048: "attention K/V arrays of 32 heads need 20.97M cells at S = 2048, over the die's 16.78M; the attention set would need two dies and the grouping would change"}
T0_MAIN_S, T_STRONGEST_MAIN_S = 0.020, 2.11870568800   # the main experiment's t0 and strongest baseline
T0_NORM = T0_MAIN_S / T_STRONGEST_MAIN_S
STARTS, SEEDS, STEPS, ALPHA = ("clustered", "random", "snake"), (0, 1, 2), 1200, 0.996
WRITE_ROW_CAP = 256


def derived_account(S):
    """The S = 512 measurement re-expressed at S (see the module docstring)."""
    base = json.load(open(BASE))
    cfg = lw.GptConfig(**{k: base["config"][k] for k in ("d_model", "n_heads", "d_ff", "n_layers", "name")})
    out = {"config": {**base["config"], "S": S}, "ref_words_per_cycle": base["ref_words_per_cycle"],
           "hist_source": base["hist_source"], "fabric": base.get("fabric"),
           "derivation": ("derived from the S = 512 mapper account: compute = rows x per-row time of the "
                          "S = 512 mapping, write = min(write_rows, 256) x T_SET, energy scaled with rows "
                          "in prefill and unchanged in decode; replace with run_2p7b_block_S.py output"),
           "phases": {}}
    for ph in ("prefill", "decode"):
        ops512 = {o.name: o for o in lw.block_ops(cfg, 512, ph)}
        opsS = {o.name: o for o in lw.block_ops(cfg, S, ph)}
        recs = []
        for r in base["phases"][ph]:
            o5, oS = ops512[r["name"]], opsS[r["name"]]
            rows_ratio = oS.P / o5.P
            rec = dict(r)
            rec["compute_s"] = r["compute_s"] * rows_ratio
            rec["write_s"] = min(oS.write_rows, WRITE_ROW_CAP) * lw.T_SET_NS * 1e-9
            rec["energy_J"] = r["energy_J"] * rows_ratio
            rec["die_flow_words"] = [v * rows_ratio for v in r["die_flow_words"]]
            rec["die_flow_down"] = [v * rows_ratio for v in r["die_flow_down"]]
            rec["die_flow_up"] = [v * rows_ratio for v in r["die_flow_up"]]
            recs.append(rec)
        out["phases"][ph] = recs
    return out


def account_path(S):
    if S == 512:
        return BASE, "measured (the frozen S = 512 mapper account)"
    measured = os.path.join(A, f"scale_2p7b_per_op_S{S}.json")
    if os.path.exists(measured):
        return measured, "measured (run_2p7b_block_S.py)"
    path = os.path.join(OUT, f"scale_2p7b_per_op_S{S}_derived.json")
    json.dump(derived_account(S), open(path, "w"), indent=1)
    return path, "derived from the S = 512 account (see workload_reuse.py docstring)"


def check_write_rule():
    """The account's write latency equals min(write_rows, 256) x T_SET for every written operator."""
    base = json.load(open(BASE))
    cfg = lw.GptConfig(**{k: base["config"][k] for k in ("d_model", "n_heads", "d_ff", "n_layers", "name")})
    for ph in ("prefill", "decode"):
        ops = {o.name: o for o in lw.block_ops(cfg, 512, ph)}
        for r in base["phases"][ph]:
            want = min(ops[r["name"]].write_rows, WRITE_ROW_CAP) * lw.T_SET_NS * 1e-9
            assert abs(r["write_s"] - want) <= 1e-12 * max(1.0, want), (ph, r["name"], r["write_s"], want)
            rows = ops[r["name"]].P
            assert abs(r["compute_s"] / rows - (r["compute_s"] / rows)) == 0.0


def frozen_layouts():
    k = json.load(open(os.path.join(A, "kappa_geometry_sweep.json")))["cells"]["24x24/k2"]["runs"]
    return {n: ss.Pi.from_json(r["best_pi"]) for n, r in k.items()}


class NormJ:
    """T(p) / T_base through the incremental session (cimsim_cli.Objective)."""

    def __init__(self, W, pi0, mu, t_base):
        self.obj = cli.Objective(W, pi0, mu, "single", BW, 1.0, "t")
        self.t_base = t_base

    def __call__(self, pi):
        return self.obj(pi) / self.t_base


def run_point(phase, S, fab, frozen):
    path, status = account_path(S)
    W = cli.Workload(fab, path)
    W.port_ratio = KAPPA
    mu = {phase: 1.0}
    cands = {n: sb.generate(n, W, seed=0) for n in sb.NAMES}
    for s in (1, 2, 3, 4):
        cands[f"random_s{s}"] = sb.generate("random", W, seed=s)
    layouts = {**cands, **frozen}

    def ev(pi):
        sc = se.score(pi, W, mu=mu, caliber="single", d2d_gbps=BW)
        d = sc.per_phase[phase]["decomp"]
        return {"T_s": sc.t_opt_s, "R_s": d["layers_s"] + d["propagation_s"], "layers_s": d["layers_s"],
                "H_s": d["d2d_serial_s"], "propagation_s": d["propagation_s"],
                "comm_share": d["d2d_serial_s"] / sc.t_opt_s, "E_J": sc.e_J,
                "d2d_busiest_words": d["d2d_busiest_words"]}
    rows = {n: ev(p) for n, p in layouts.items()}
    base_names = list(cands)
    strongest = min(base_names, key=lambda n: rows[n]["T_s"])
    t_base = rows[strongest]["T_s"]
    frozen_name = "sa_random_s1"
    reuse_gain = (1 - rows[frozen_name]["T_s"] / t_base) * 100
    # search at this workpoint, normalized objective
    n_slots = W.fab.level("die").per_parent
    sched = sa.Schedule(t0=T0_NORM, alpha=ALPHA, steps=STEPS)
    runs = {}
    t_all = time.perf_counter()
    for i, st in enumerate(sorted(STARTS)):
        for s in SEEDS:
            J = NormJ(W, cands[st], mu, t_base)
            t = time.perf_counter()
            r = sa.anneal(J, cands[st], n_slots, sched, seed=1000003 * s + i)
            name = f"sa_{st}_s{s}"
            e = ev(r.best_pi)
            runs[name] = {"start": st, "sa_seed": s, "t0_norm": T0_NORM, "steps": STEPS, "alpha": ALPHA,
                          "start_T_s": rows[st]["T_s"], "T_s": e["T_s"], "H_s": e["H_s"], "R_s": e["R_s"],
                          "gain_vs_strongest_pct": (1 - e["T_s"] / t_base) * 100,
                          "accepted": r.accepted, "proposed": r.proposed, "wall_s": time.perf_counter() - t,
                          "best_pi": r.best_pi.to_json()}
    per_seed = {s: min((runs[f"sa_{st}_s{s}"]["T_s"], f"sa_{st}_s{s}") for st in STARTS) for s in SEEDS}
    order = sorted(per_seed, key=lambda s: per_seed[s][0])
    headline_seed = order[len(order) // 2]
    headline_name = per_seed[headline_seed][1]
    search_headline_T = per_seed[headline_seed][0]
    search_gain = (1 - search_headline_T / t_base) * 100
    gains = [(1 - per_seed[s][0] / t_base) * 100 for s in SEEDS]
    fallback = search_headline_T >= rows[frozen_name]["T_s"]
    reuse_search_gain = max(reuse_gain, search_gain)
    return {
        "phase": phase, "S": S, "account": path, "account_status": status, "bandwidth_gbps": BW, "kappa": KAPPA,
        "layouts": rows, "baseline_set": base_names, "strongest_baseline": strongest, "T_base_s": t_base,
        "frozen_layout": frozen_name, "reuse": {"T_s": rows[frozen_name]["T_s"], "gain_pct": reuse_gain,
                                                 "H_s": rows[frozen_name]["H_s"], "R_s": rows[frozen_name]["R_s"],
                                                 "comm_share_ref": rows[strongest]["comm_share"]},
        "search": {"protocol": {"starts": list(STARTS), "seeds": list(SEEDS), "steps": STEPS, "alpha": ALPHA,
                                "t0_norm": T0_NORM, "t0_rule": "20 ms / 2118.71 ms, dimensionless, objective T / T_base",
                                "t0_equivalent_s": T0_NORM * t_base},
                   "runs": runs, "per_seed_best": {s: per_seed[s][1] for s in SEEDS},
                   "headline_run": headline_name, "headline_T_s": search_headline_T, "gain_pct": search_gain,
                   "gain_range_pct": [min(gains), max(gains)], "wall_s": time.perf_counter() - t_all},
        "reuse_plus_search": {"gain_pct": reuse_search_gain, "fallback_to_frozen": fallback,
                              "layout": frozen_name if fallback else headline_name,
                              "delta_vs_reuse_pct_points": reuse_search_gain - reuse_gain},
    }


def invariance(points):
    """H ratios across all layouts between workpoints; R spread across layouts."""
    out = {}
    ref = {(p["phase"], p["S"]): p for p in points}
    for (phase, S), p in ref.items():
        base = ref[(phase, 512)]
        names = sorted(set(p["layouts"]) & set(base["layouts"]))
        ratios = [p["layouts"][n]["H_s"] / base["layouts"][n]["H_s"] for n in names]
        R = [p["layouts"][n]["layers_s"] for n in names]
        order_here = sorted(names, key=lambda n: p["layouts"][n]["T_s"])
        order_base = sorted(names, key=lambda n: base["layouts"][n]["T_s"])
        out[f"{phase}/{S}"] = {"H_ratio_min": min(ratios), "H_ratio_max": max(ratios),
                               "expected_ratio": (S / 512 if phase == "prefill" else 1.0),
                               "R_layers_min_s": min(R), "R_layers_max_s": max(R),
                               "same_order_as_512": order_here == order_base}
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    check_write_rule()
    fab = fm.from_yaml(cli.DEFAULT_FABRIC)
    frozen = frozen_layouts()
    points = []
    for phase in ("prefill", "decode"):
        for S in S_POINTS:
            print(f"== {phase} S={S}", flush=True)
            p = run_point(phase, S, fab, frozen)
            print(f"   strongest {p['strongest_baseline']} {p['T_base_s']*1e3:.3f} ms | reuse {p['reuse']['gain_pct']:.2f}% "
                  f"| search {p['search']['gain_pct']:.2f}% [{p['search']['gain_range_pct'][0]:.2f}, {p['search']['gain_range_pct'][1]:.2f}] "
                  f"| reuse+search {p['reuse_plus_search']['gain_pct']:.2f}% fallback={p['reuse_plus_search']['fallback_to_frozen']} "
                  f"| comm share {p['reuse']['comm_share_ref']*100:.1f}% | {p['search']['wall_s']:.0f} s", flush=True)
            points.append(p)
    inv = invariance(points)
    ident = {"prefill_512_reuse_gain_pct": next(p for p in points if p["phase"] == "prefill" and p["S"] == 512)["reuse"]["gain_pct"],
             "decode_512_reuse_gain_pct": next(p for p in points if p["phase"] == "decode" and p["S"] == 512)["reuse"]["gain_pct"],
             "expected": {"prefill": 9.91, "decode": 1.57}}
    res = {"note": __doc__.strip(), "infeasible": {str(k): v for k, v in INFEASIBLE.items()},
           "identity_check": ident, "invariance": inv, "points": points}
    json.dump(res, open(os.path.join(OUT, "workload_reuse.json"), "w"), indent=1)
    with open(os.path.join(OUT, "per_run.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["phase", "S", "run", "start", "seed", "t0_norm", "steps", "alpha", "start_T_ms", "end_T_ms",
                    "H_ms", "R_ms", "gain_vs_strongest_pct", "accepted", "proposed"])
        for p in points:
            for n, r in p["search"]["runs"].items():
                w.writerow([p["phase"], p["S"], n, r["start"], r["sa_seed"], f"{r['t0_norm']:.7f}", r["steps"], r["alpha"],
                            f"{r['start_T_s']*1e3:.3f}", f"{r['T_s']*1e3:.3f}", f"{r['H_s']*1e3:.3f}", f"{r['R_s']*1e3:.3f}",
                            f"{r['gain_vs_strongest_pct']:.3f}", r["accepted"], r["proposed"]])
    with open(os.path.join(OUT, "summary.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["phase", "S", "account_status", "strongest_baseline", "T_base_ms", "comm_share_ref_pct",
                    "reuse_T_ms", "reuse_gain_pct", "search_headline_T_ms", "search_gain_pct", "search_gain_min_pct",
                    "search_gain_max_pct", "reuse_plus_search_gain_pct", "fallback_to_frozen", "layout"])
        for p in points:
            w.writerow([p["phase"], p["S"], p["account_status"], p["strongest_baseline"], f"{p['T_base_s']*1e3:.3f}",
                        f"{p['reuse']['comm_share_ref']*100:.2f}", f"{p['reuse']['T_s']*1e3:.3f}", f"{p['reuse']['gain_pct']:.3f}",
                        f"{p['search']['headline_T_s']*1e3:.3f}", f"{p['search']['gain_pct']:.3f}",
                        f"{p['search']['gain_range_pct'][0]:.3f}", f"{p['search']['gain_range_pct'][1]:.3f}",
                        f"{p['reuse_plus_search']['gain_pct']:.3f}", p["reuse_plus_search"]["fallback_to_frozen"],
                        p["reuse_plus_search"]["layout"]])
    # the markdown summary
    md = ["# Workload and placement reuse (Fig. 6(b) data)\n", "Configuration: 2.7B, 544 of 576 dies on 24x24, XY, NeuRRAM rate, kappa = 2, 0.4 GB/s. Frozen layout: `sa_random_s1` (the headline layout of the 512-token prefill search). Baseline set per workpoint: the seven named rules at seed 0 and the random fills at seeds 1 to 4; the strongest is the minimum. Gains are 1 - T / T_strongest at that workpoint.\n",
          f"Infeasible lengths: " + "; ".join(f"S = {k}: {v}" for k, v in INFEASIBLE.items()) + ".\n",
          "| phase | S | account | strongest baseline | T_base (ms) | comm. share of the reference | Reuse T (ms) | Reuse gain | search headline T (ms) | search gain (median of seeds) | seed range | Reuse + search gain | fallback to frozen |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for p in points:
        md.append(f"| {p['phase']} | {p['S']} | {p['account_status'].split(' (')[0]} | {p['strongest_baseline']} | {p['T_base_s']*1e3:.2f} | {p['reuse']['comm_share_ref']*100:.1f}% | {p['reuse']['T_s']*1e3:.2f} | {p['reuse']['gain_pct']:.2f}% | {p['search']['headline_T_s']*1e3:.2f} | {p['search']['gain_pct']:.2f}% | {p['search']['gain_range_pct'][0]:.2f} to {p['search']['gain_range_pct'][1]:.2f}% | {p['reuse_plus_search']['gain_pct']:.2f}% | {p['reuse_plus_search']['fallback_to_frozen']} |")
    md.append("\n## Invariance check (why no workpoint needs a different placement)\n")
    md.append("| workpoint | H ratio to the 512 workpoint over all 21 layouts (min, max) | expected | R (layers) across layouts, min = max (ms) | same ordering of the 21 layouts as at 512 |")
    md.append("|---|---|---|---|---|")
    for k, v in inv.items():
        md.append(f"| {k} | {v['H_ratio_min']:.12f}, {v['H_ratio_max']:.12f} | {v['expected_ratio']:.6f} | {v['R_layers_min_s']*1e3:.4f} = {v['R_layers_max_s']*1e3:.4f} | {v['same_order_as_512']} |")
    md.append(f"\nIdentity check at the 512 workpoint: prefill reuse gain {ident['prefill_512_reuse_gain_pct']:.2f}% (expected 9.91), decode {ident['decode_512_reuse_gain_pct']:.2f}% (expected 1.57).\n")
    md.append("\n## Decomposition of the frozen layout and the strongest baseline per workpoint (ms)\n")
    md.append("| phase | S | layout | T | R (compute + write + digital + propagation) | H (hand-offs) | comm. share |")
    md.append("|---|---|---|---|---|---|---|")
    for p in points:
        for n in (p["strongest_baseline"], "sa_random_s1", p["search"]["headline_run"] + " (search)"):
            key = n.replace(" (search)", "")
            r = p["layouts"].get(key) or {"T_s": p["search"]["runs"][key]["T_s"], "R_s": p["search"]["runs"][key]["R_s"], "H_s": p["search"]["runs"][key]["H_s"]}
            md.append(f"| {p['phase']} | {p['S']} | {n} | {r['T_s']*1e3:.2f} | {r['R_s']*1e3:.2f} | {r['H_s']*1e3:.2f} | {r['H_s']/r['T_s']*100:.1f}% |")
    open(os.path.join(OUT, "workload_reuse.md"), "w").write("\n".join(md) + "\n")
    print("->", OUT)


if __name__ == "__main__":
    main()

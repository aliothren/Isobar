"""cimsim command line: the user entry to the deployment evaluator, the
named baselines, the placement search, the phase diagram and the BookSim
check, on any fabric file and any per-operator account.

    python3 scripts/cimsim_cli.py baseline --rule clustered --out pi.json
    python3 scripts/cimsim_cli.py evaluate --deployment pi.json --bandwidth 0.4
    python3 scripts/cimsim_cli.py search --bandwidth 0.4 --out-dir analysis/my_search
    python3 scripts/cimsim_cli.py phase --bandwidths 0.4,12.5 --out analysis/my_phase.json
    python3 scripts/cimsim_cli.py booksim --deployment pi.json --handoff ffn2@L3

Common options (every subcommand):
    --fabric F         fabric YAML (default models/fabric/mlx300_multidie576.yaml)
    --workload J       per-operator account JSON (default analysis/scale_2p7b_per_op.json)
    --kappa K          port ratio; default = the fabric's `ports: {ratio}` on the
                       die level, else 1.0
    --d2d-pj-per-word, --d2d-ns-per-hop
                       override the evaluator's package-link constants
                       (10 pJ per word, 20 ns per hop)

This module only wraps the platform's functions (search_eval, search_baselines,
search_sa, booksim_bridge); it adds no model. Every frozen result is produced
by the experiment scripts, not by this entry.
"""
import argparse
import json
import os
import statistics
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import fabric as fm                      # noqa: E402
from scripts import interconnect as ic                # noqa: E402
from scripts import llm_workload as lw                # noqa: E402
from scripts import placement as pm                   # noqa: E402
from scripts import search_baselines as sb            # noqa: E402
from scripts import search_eval as se                 # noqa: E402
from scripts import search_sa as sa                   # noqa: E402
from scripts import search_space as ss                # noqa: E402

DEFAULT_FABRIC = os.path.join(WS, "models", "fabric", "mlx300_multidie576.yaml")
DEFAULT_WORKLOAD = os.path.join(WS, "analysis", "scale_2p7b_per_op.json")
RULES = sb.NAMES
S_LO, S_HI, S_N = 0.02, 40.0, 256                     # device-rate axis, Mrows/s


# ------------------------------------------------------------- workload
class Workload(se.Workload2p7B):
    """Workload2p7B on an explicit fabric and an explicit account file."""

    def __init__(self, fabric, path):
        self.fab = fabric
        stored = json.load(open(path))
        c = stored["config"]
        self.cfg = lw.GptConfig(d_model=c["d_model"], n_heads=c["n_heads"],
                                d_ff=c["d_ff"], n_layers=c["n_layers"],
                                name=c["name"])
        self.S = c["S"]
        self.ops = {ph: {r["name"]: r for r in rows}
                    for ph, rows in stored["phases"].items()}
        self.pl = pm.sequential_fill(self.fab)
        self.die_ic = ic.build(self.fab, "die", self.pl)
        self.account_path = path


def load(args):
    """(W, kappa) from the common options; sets the evaluator's constants."""
    fab = fm.from_yaml(args.fabric)
    W = Workload(fab, args.workload)
    kappa = args.kappa
    if kappa is None:
        kappa = fab.level("die").port_ratio
        if kappa is None:
            print("note: no --kappa and the fabric declares no ports.ratio on "
                  "the die level; using kappa = 1.0 (ports at the link rate)")
            kappa = 1.0
    W.port_ratio = float(kappa)
    if args.d2d_pj_per_word is not None:
        se.PJ_D2D = float(args.d2d_pj_per_word)
    if args.d2d_ns_per_hop is not None:
        se.NS_PER_HOP_D2D = float(args.d2d_ns_per_hop)
    return W, float(kappa)


def phases_of(args):
    ph = [p.strip() for p in args.phases.split(",") if p.strip()]
    return {p: 1.0 for p in ph}


def setting(W, kappa, args):
    return {"fabric": W.fab.name, "fabric_file": os.path.abspath(args.fabric),
            "workload": W.cfg.name, "account_file": os.path.abspath(args.workload),
            "S": W.S, "n_layers": W.cfg.n_layers, "kappa": kappa,
            "bandwidth_gbps": getattr(args, "bandwidth", None),
            "phases": list(phases_of(args)) if hasattr(args, "phases") else None,
            "caliber": getattr(args, "caliber", None),
            "device_scale": getattr(args, "device_scale", None),
            "d2d_pj_per_word": se.PJ_D2D, "d2d_ns_per_hop": se.NS_PER_HOP_D2D}


# --------------------------------------------------------- hand-off flows
def handoff_flows(W, pi, phase):
    """[(into-set name, flows)] for every hand-off of the chain, in chain
    order, the wrap boundary excluded (the evaluator's convention)."""
    base = lw.block_chain(W.cfg, W.S, phase, on_chip=True,
                          max_dies=W.fab.level("die").per_parent)
    names = [f"{e['name']}@L{li}" for li in range(W.cfg.n_layers) for e in base]
    entries = {f"{e['name']}@L{li}": e for li in range(W.cfg.n_layers) for e in base}
    out = []
    for i in range(1, len(names)):
        prev, name = names[i - 1], names[i]
        out.append((name, se._one_boundary_flows(entries[prev], entries[name],
                                                 pi.seat[prev], pi.seat[name], W.fab)))
    return out


def handoff_row(name, flows, W, kappa):
    loads = se.resource_loads(flows, W.die_ic, ports=True, kappa=kappa)
    if not loads:
        return {"into": name, "words": 0.0, "busiest_words": 0.0, "binding": "none",
                "busiest_resource": None, "max_hops": 0, "n_flows": 0}
    key, a = max(loads.items(), key=lambda kv: kv[1])
    wire = max((v for k, v in loads.items() if k[0] != "port"), default=0.0)
    ports = max((v for k, v in loads.items() if k[0] == "port"), default=0.0)
    eps = 1e-9 * a
    if abs(a - ports) < eps and abs(a - wire) < eps:
        binding = "port=link"
    elif abs(a - ports) < eps:
        binding = "port"
    elif abs(a - wire) < eps:
        binding = "link"
    else:
        binding = "mixed"
    hops = max((W.die_ic.hops(*f["nodes"]) for f in flows), default=0)
    return {"into": name, "words": sum(f["volume"] * f["width"] for f in flows),
            "busiest_words": a, "binding": binding,
            "busiest_resource": [str(x) for x in key],
            "port_floor_words": ports, "wire_only_words": wire,
            "max_hops": hops, "n_flows": len(flows)}


# ----------------------------------------------------------------- evaluate
def cmd_evaluate(args):
    W, kappa = load(args)
    pi = ss.Pi.from_json(open(args.deployment).read())
    ok, why = ss.legal(pi, W.fab, W.inventory())
    if not ok:
        sys.exit(f"illegal deployment: {why}")
    mu = phases_of(args)
    t = time.perf_counter()
    sc = se.score(pi, W, mu=mu, caliber=args.caliber, d2d_gbps=args.bandwidth,
                  device_scale=args.device_scale)
    dt = time.perf_counter() - t
    out = {"setting": setting(W, kappa, args), "deployment": os.path.abspath(args.deployment),
           "t_opt_s": sc.t_opt_s, "t_pess_s": sc.t_pess_s, "e_J": sc.e_J,
           "delta": sc.delta, "per_phase": sc.per_phase, "score_wall_s": dt,
           "handoffs": {}}
    print(f"fabric {W.fab.name} | account {W.cfg.name} S={W.S} | kappa {kappa:g} | "
          f"B {args.bandwidth:g} GB/s | caliber {args.caliber} | device x{args.device_scale:g}")
    for ph, r in sc.per_phase.items():
        d = r["decomp"]
        print(f"[{ph}] latency {r['t_opt_s'] * 1e3:.3f} ms  energy {r['e_J']:.4f} J")
        print(f"    layers {d['layers_s'] * 1e3:.3f} ms | hand-offs {d['d2d_serial_s'] * 1e3:.3f} ms | "
              f"propagation {d['propagation_s'] * 1e3:.3f} ms | pipeline interval "
              f"{d['t_pipe_interval_s'] * 1e3:.3f} ms")
        print(f"    hand-off words {d['d2d_words']:.4g} total, {d['d2d_busiest_words']:.4g} on the "
              f"busiest resources | hand-off energy {d['d2d_flat_J'] + d['d2d_surplus_J']:.4f} J")
        rows = [handoff_row(n, fl, W, kappa) for n, fl in handoff_flows(W, pi, ph)]
        out["handoffs"][ph] = rows
        kinds = {}
        for r_ in rows:
            kinds[r_["binding"]] = kinds.get(r_["binding"], 0) + 1
        print(f"    {len(rows)} hand-offs; binding resource: " +
              ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
        if args.loads:
            top = sorted(rows, key=lambda r_: -r_["busiest_words"])[:args.loads]
            print(f"    busiest {len(top)} hand-offs (words on the busiest resource / link rate):")
            for r_ in top:
                print(f"      {r_['into']:<16} {r_['busiest_words']:12.0f} words  "
                      f"{r_['busiest_words'] / (args.bandwidth * 1e9) * 1e3:8.3f} ms  "
                      f"{r_['binding']:<9} {' '.join(r_['busiest_resource'])}  "
                      f"{r_['n_flows']} flows, {r_['max_hops']:.0f} hops max")
    if args.out:
        json.dump(out, open(args.out, "w"), indent=1)
        print(f"-> {args.out}")
    return out


# ----------------------------------------------------------------- baseline
def cmd_baseline(args):
    W, kappa = load(args)
    if args.rule not in RULES:
        sys.exit(f"unknown rule {args.rule}; choose from {', '.join(RULES)}")
    pi = sb.generate(args.rule, W, seed=args.seed)
    open(args.out, "w").write(pi.to_json())
    inv = W.inventory()
    print(f"{args.rule} (seed {args.seed}) on {W.fab.name}: {len(inv)} sets, "
          f"{sum(inv.values())} dies of {W.fab.level('die').per_parent} -> {args.out}")


# ------------------------------------------------------------------- search
class Objective:
    """Incremental objective on a ScoreSession: the requested Pi is diffed
    against the committed seats and only the touched hand-offs are
    re-priced (the search_linkage.SessionJ pattern, with every knob)."""

    def __init__(self, W, pi0, mu, caliber, bw, device_scale, column="t"):
        self.W, self.column = W, column
        self.sess = se.ScoreSession(pi0, W, mu=mu, caliber=caliber,
                                    d2d_gbps=bw, device_scale=device_scale)
        self.calls = 0

    def __call__(self, pi):
        self.calls += 1
        delta = {n: tuple(v) for n, v in pi.seat.items()
                 if tuple(v) != tuple(self.sess.pi.seat[n])}
        sc = (self.sess.update(delta) if delta else
              se._assemble(self.sess.pi, self.W, self.sess.bs, self.sess.mu,
                           self.sess.caliber, self.sess.d2d_gbps,
                           self.sess.device_scale))
        return sc.t_opt_s if self.column == "t" else sc.e_J


def default_t0(bw):
    """The frozen legs' temperatures: 20 ms at 0.4 GB/s, 2 ms at 12.5 GB/s;
    elsewhere 20 ms scaled by 0.4 / B (the objective's spread scales with
    1 / B), stated in the output."""
    if abs(bw - 0.4) < 1e-12:
        return 0.020
    if abs(bw - 12.5) < 1e-12:
        return 0.002
    return 0.020 * 0.4 / bw


def cmd_search(args):
    W, kappa = load(args)
    mu = phases_of(args)
    bw = args.bandwidth
    t0 = args.t0 if args.t0 is not None else default_t0(bw)
    sched = sa.Schedule(t0=t0, alpha=args.alpha, steps=args.steps)
    n_slots = W.fab.level("die").per_parent
    starts = [s.strip() for s in args.starts.split(",") if s.strip()]
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    os.makedirs(args.out_dir, exist_ok=True)
    for st in starts:
        if st not in RULES:
            sys.exit(f"unknown start rule {st}; choose from {', '.join(RULES)}")
    pi_start = {st: sb.generate(st, W, seed=0) for st in starts}
    print(f"fabric {W.fab.name} | account {W.cfg.name} | kappa {kappa:g} | B {bw:g} GB/s | "
          f"phases {','.join(mu)} | caliber {args.caliber} | {len(starts)} starts x "
          f"{len(seeds)} seeds | {args.steps} steps, alpha {args.alpha}, t0 {t0 * 1e3:g} ms")
    runs, T = {}, {}
    t_all = time.perf_counter()
    for i, st in enumerate(sorted(starts)):
        for s in seeds:
            J = Objective(W, pi_start[st], mu, args.caliber, bw, args.device_scale, args.objective)
            t = time.perf_counter()
            r = sa.anneal(J, pi_start[st], n_slots, sched, seed=1000003 * s + i)
            name = f"sa_{st}_s{s}"
            sc = se.score(r.best_pi, W, mu=mu, caliber=args.caliber, d2d_gbps=bw,
                          device_scale=args.device_scale)
            T[name] = sc.t_opt_s
            runs[name] = {"start": st, "sa_seed": s, "start_j": r.start_j, "best_j": r.best_j,
                          "t_opt_s": sc.t_opt_s, "e_J": sc.e_J, "accepted": r.accepted,
                          "proposed": r.proposed, "rejected_infeasible": r.rejected_infeasible,
                          "kind_counts": r.kind_counts, "wall_s": time.perf_counter() - t,
                          "best_pi": r.best_pi.to_json()}
            open(os.path.join(args.out_dir, f"{name}.json"), "w").write(r.best_pi.to_json())
            print(f"  {name:<20} {r.start_j * 1e3:9.2f} -> {r.best_j * 1e3:9.2f} ms  "
                  f"accepted {r.accepted}/{r.proposed}  {runs[name]['wall_s']:.1f} s")
    best = min(T, key=T.get)
    per_seed = {s: min(T[f"sa_{st}_s{s}"] for st in starts) for s in seeds}
    order = sorted(per_seed, key=per_seed.get)
    headline_seed = order[len(order) // 2]
    headline_name = min((f"sa_{st}_s{headline_seed}" for st in starts), key=T.get)
    summary = {"setting": setting(W, kappa, args), "schedule": {"t0_s": t0, "alpha": args.alpha,
               "steps": args.steps}, "starts": starts, "seeds": seeds,
               "best_of_all": {"run": best, "t_opt_s": T[best]},
               "headline": {"run": headline_name, "t_opt_s": T[headline_name],
                            "statistic": "median over seeds of the best endpoint over starts"},
               "endpoint_min_s": min(T.values()), "endpoint_median_s": statistics.median(T.values()),
               "endpoint_max_s": max(T.values()),
               "endpoint_spread_pct": (max(T.values()) / min(T.values()) - 1) * 100,
               "wall_s": time.perf_counter() - t_all}
    open(os.path.join(args.out_dir, "best_pi.json"), "w").write(runs[best]["best_pi"])
    open(os.path.join(args.out_dir, "headline_pi.json"), "w").write(runs[headline_name]["best_pi"])
    print(f"best endpoint {best}: {T[best] * 1e3:.2f} ms | headline {headline_name}: "
          f"{T[headline_name] * 1e3:.2f} ms | spread {summary['endpoint_spread_pct']:.2f}%")
    if not args.no_baselines:
        cands = {n: sb.generate(n, W, seed=0) for n in RULES}
        for s in (1, 2, 3, 4):
            cands[f"random_s{s}"] = sb.generate("random", W, seed=s)
        Tb = {n: se.score(p, W, mu=mu, caliber=args.caliber, d2d_gbps=bw,
                          device_scale=args.device_scale).t_opt_s for n, p in cands.items()}
        strongest = min(Tb, key=Tb.get)
        summary["baselines"] = {"t_opt_s": Tb, "strongest": strongest,
                                "gain_headline_pct": (1 - T[headline_name] / Tb[strongest]) * 100,
                                "gain_best_pct": (1 - T[best] / Tb[strongest]) * 100,
                                "gain_vs_sequential_pct": (1 - T[headline_name] / Tb["sequential"]) * 100}
        print(f"strongest baseline {strongest}: {Tb[strongest] * 1e3:.2f} ms | headline gain "
              f"{summary['baselines']['gain_headline_pct']:.2f}% | best-of-all "
              f"{summary['baselines']['gain_best_pct']:.2f}% | vs sequential fill "
              f"{summary['baselines']['gain_vs_sequential_pct']:.2f}%")
    json.dump({"summary": summary, "runs": runs}, open(os.path.join(args.out_dir, "search.json"), "w"),
              indent=1)
    print(f"-> {args.out_dir}/search.json, best_pi.json, headline_pi.json, sa_<start>_s<seed>.json")
    return summary


# -------------------------------------------------------------------- phase
def cmd_phase(args):
    import numpy as np
    W, kappa = load(args)
    mu = phases_of(args)
    phase = list(mu)[0]
    comp, wr, elw = W.layer_terms_s(phase)
    L = W.cfg.n_layers
    n_scaling, fixed = comp * L / args.device_scale, (wr + elw) * L
    rules = [r.strip() for r in args.rules.split(",") if r.strip()]
    A = {}
    for r in rules:
        sc = se.score(sb.generate(r, W, seed=0), W, mu={phase: 1.0}, caliber="single", d2d_gbps=1.0)
        A[r] = sc.per_phase[phase]["decomp"]["d2d_busiest_words"]
    a_min, a_max = min(A.values()), max(A.values())
    s_ref = 1.0 / W.fab.device.t_mvm_s / 1e6
    ss_ = np.geomspace(S_LO, S_HI, S_N)
    r_s = n_scaling * (s_ref / ss_) + fixed
    lo, hi = a_min / r_s / 1e9, a_max / r_s / 1e9
    bm, bp = float(np.interp(s_ref, ss_, lo)), float(np.interp(s_ref, ss_, hi))
    bws = [float(b) for b in args.bandwidths.split(",") if b.strip()]
    def region(b):
        return ("communication dominated for every placement" if b < bm else
                "communication masked for every placement" if b > bp else
                "placement decides")
    out = {"setting": setting(W, kappa, args), "phase": phase, "rules": rules,
           "A_words": A, "A_min_rule": min(A, key=A.get), "A_max_rule": max(A, key=A.get),
           "A_ratio": a_max / a_min, "n_scaling_s": n_scaling, "fixed_s": fixed,
           "device_rate_mrows_per_s": s_ref,
           "B_minus_gbps": bm, "B_plus_gbps": bp, "band_ratio": bp / bm,
           "bandwidths": {str(b): region(b) for b in bws},
           "curve": {"s_mrows_per_s": ss_.tolist(), "B_minus_gbps": lo.tolist(),
                     "B_plus_gbps": hi.tolist()}}
    print(f"fabric {W.fab.name} | account {W.cfg.name} | kappa {kappa:g} | phase {phase} | "
          f"{len(rules)} placements")
    print(f"busiest-resource words: min {a_min:.4g} ({out['A_min_rule']}), max {a_max:.4g} "
          f"({out['A_max_rule']}), ratio {a_max / a_min:.3f}")
    print(f"at the fabric's device rate {s_ref:.4f} Mrows/s: B- {bm:.3f} GB/s, B+ {bp:.3f} GB/s "
          f"(x{bp / bm:.2f})")
    for b in bws:
        print(f"  {b:g} GB/s: {region(b)}")
    if args.out:
        json.dump(out, open(args.out, "w"), indent=1)
        print(f"-> {args.out}")
    if args.png:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(5.2, 3.6))
        ax.fill_between(ss_, lo, hi, color="#f1e5bd", alpha=0.9, lw=0)
        ax.plot(ss_, lo, color="#6b7b8c", lw=1.0)
        ax.plot(ss_, hi, color="#6b7b8c", lw=1.0)
        ax.axvline(s_ref, color="#9a9a9a", lw=0.7, ls=":")
        for b in bws:
            ax.plot([s_ref], [b], "o", ms=4.5, color="#2b4a6f")
            ax.annotate(f"{b:g}", (s_ref, b), xytext=(4, 2), textcoords="offset points", fontsize=7)
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlabel("device rate (Mrows/s)"); ax.set_ylabel("link bandwidth per direction (GB/s)")
        ax.set_title(f"{W.fab.name}, kappa {kappa:g}: placement band", fontsize=9)
        ax.text(S_LO * 1.3, bp * 3, "communication masked", fontsize=7, color="#2b4a6f")
        ax.text(S_LO * 1.3, bm / 3, "communication exposed", fontsize=7, color="#1f2f3f")
        fig.tight_layout(); fig.savefig(args.png, dpi=200); plt.close(fig)
        print(f"-> {args.png}")
    return out


# ------------------------------------------------------------------ booksim
def cmd_booksim(args):
    from scripts import booksim_bridge as bb
    W, kappa = load(args)
    if not bb.available():
        sys.exit("BookSim binary missing: build per tools/booksim2/BUILD_NOTES.md")
    mx, my = W.fab.level("die").mesh
    k = args.k or mx
    if mx != my or k != mx:
        sys.exit(f"the bridge needs a square die mesh with k = X; fabric mesh is {mx}x{my}, k {k}")
    pi = ss.Pi.from_json(open(args.deployment).read())
    phase = list(phases_of(args))[0]
    pairs = dict(handoff_flows(W, pi, phase))
    if args.handoff not in pairs:
        sys.exit(f"unknown hand-off {args.handoff}; names look like ffn2@L3 (into-set)")
    flows = pairs[args.handoff]
    agg = {}
    for f in flows:
        a, b = f["nodes"]
        agg[(a, b)] = agg.get((a, b), 0.0) + f["volume"] * f["width"]
    book_flows = [(a, b, bb.packets_for(w * args.scale)) for (a, b), w in agg.items()]
    n_pk = sum(n for _, _, n in book_flows)
    if n_pk > 500_000:
        sys.exit(f"{n_pk} packets; lower --scale (the bridge's batch accounting fails near 600k)")
    row = handoff_row(args.handoff, flows, W, kappa)
    bounds = bb.flit_bounds(book_flows, k=k)
    ref = max(bounds.values())
    print(f"hand-off into {args.handoff}: {len(flows)} flows, {row['words']:.4g} words; the evaluator's "
          f"busiest resource {row['busiest_words']:.4g} words ({row['binding']}, "
          f"{' '.join(row['busiest_resource'])}) at kappa {kappa:g}")
    print(f"BookSim batch: {len(book_flows)} node pairs, {n_pk} packets at scale {args.scale:g} on a "
          f"{k}x{k} mesh, kappa 1 (one injection channel per node)")
    t = time.perf_counter()
    r = bb.run_batch(book_flows, k=k)
    print(f"  bound {ref} flit cycles (channel {bounds['channel_bound_cycles']}, injection "
          f"{bounds['injection_bound_cycles']}) | BookSim {r['cycles']} cycles | ratio "
          f"{r['cycles'] / ref:.4f} | {time.perf_counter() - t:.1f} s")
    for key in ("packet_latency_avg", "network_latency_avg", "hops_avg"):
        if key in r:
            print(f"  {key} {r[key]:.2f}")
    out = {"setting": setting(W, kappa, args), "handoff": row, "scale": args.scale, "k": k,
           "packets": n_pk, "bounds_cycles": bounds, "booksim": r, "ratio": r["cycles"] / ref}
    if args.out:
        json.dump(out, open(args.out, "w"), indent=1)
        print(f"-> {args.out}")
    return out


# ------------------------------------------------------------------- parser
def build_parser():
    ap = argparse.ArgumentParser(prog="cimsim_cli.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, bandwidth=True, phases="prefill"):
        p.add_argument("--fabric", default=DEFAULT_FABRIC, help="fabric YAML")
        p.add_argument("--workload", default=DEFAULT_WORKLOAD, help="per-operator account JSON")
        p.add_argument("--kappa", type=float, default=None,
                       help="port ratio; default = the fabric's ports.ratio on the die level, else 1")
        p.add_argument("--d2d-pj-per-word", type=float, default=None, help="package link energy per word")
        p.add_argument("--d2d-ns-per-hop", type=float, default=None, help="package link propagation per hop")
        p.add_argument("--phases", default=phases, help="comma-separated phases: prefill, decode")
        p.add_argument("--device-scale", type=float, default=1.0,
                       help="divides matrix compute time (2 = a device twice as fast)")
        if bandwidth:
            p.add_argument("--bandwidth", type=float, default=0.4, help="link bandwidth per direction, GB/s")
            p.add_argument("--caliber", default="single", choices=("single", "pipe"))

    p = sub.add_parser("evaluate", help="price one deployment")
    common(p, phases="prefill,decode")
    p.add_argument("--deployment", required=True, help="deployment JSON (Pi)")
    p.add_argument("--loads", type=int, default=8, help="print the N busiest hand-offs (0 = none)")
    p.add_argument("--out", default=None, help="write the full result JSON here")
    p.set_defaults(fn=cmd_evaluate)

    p = sub.add_parser("baseline", help="generate a named-rule deployment")
    common(p, bandwidth=False)
    p.add_argument("--rule", required=True, help=", ".join(RULES))
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", required=True, help="deployment JSON to write")
    p.set_defaults(fn=cmd_baseline)

    p = sub.add_parser("search", help="the placement search (simulated annealing over seats)")
    common(p)
    p.add_argument("--starts", default="clustered,random,snake", help="start rules, comma-separated")
    p.add_argument("--seeds", default="0,1,2", help="annealer seeds, comma-separated")
    p.add_argument("--steps", type=int, default=1200)
    p.add_argument("--alpha", type=float, default=0.996)
    p.add_argument("--t0", type=float, default=None, help="initial temperature in seconds (default per bandwidth)")
    p.add_argument("--objective", default="t", choices=("t", "e"), help="latency or energy")
    p.add_argument("--no-baselines", action="store_true", help="skip the strongest-baseline comparison")
    p.add_argument("--out-dir", required=True)
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("phase", help="placement band of the fabric at its device rate")
    common(p, bandwidth=False)
    p.add_argument("--bandwidths", default="0.4,12.5", help="bandwidths to classify, GB/s")
    p.add_argument("--rules", default=",".join(RULES), help="placement set: named rules")
    p.add_argument("--out", default=None, help="JSON with the boundary curves")
    p.add_argument("--png", default=None, help="draw a one-panel band figure here")
    p.set_defaults(fn=cmd_phase)

    p = sub.add_parser("booksim", help="one hand-off of a deployment through BookSim")
    common(p, bandwidth=False)
    p.add_argument("--deployment", required=True)
    p.add_argument("--handoff", required=True, help="the consuming set, e.g. ffn2@L3")
    p.add_argument("--scale", type=float, default=0.01, help="volume scale to keep the packet count tractable")
    p.add_argument("--k", type=int, default=None, help="mesh side (default: the fabric's die mesh)")
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_booksim)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.fn(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())

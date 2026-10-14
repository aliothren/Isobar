"""V3 supplementary sweeps (2026-10-08): the batch driver behind the
cross-configuration, scaling, tiling and protocol experiments. Host- or
container-runnable; closed-form on per-operator accounts (the frozen 2.7B
S = 512 mapper account, measured S-variants when present, otherwise
accounts DERIVED from the reference per-operator constants, declared per
config).

Protocol (V3): random pool of N independent fills (all saved); three
starts = the strongest named rule, the strongest random of the pool, and
random seed 0; SA seeds 0..4 (confirmation adds 5..14); budget
M(n) = max(1200, ceil(1200 n / 544)) with n the movable dies; objective
T / T_base with the dimensionless t0 = 20 ms / 2118.71 ms; alpha 0.996;
seed = 1000003 s + start index (starts sorted by name).

Per config the record carries every candidate's decomposition (N, F,
propagation, A, E), so any (device rate, bandwidth) point is arithmetic:
T = N / rate + F + prop + A / B; the ordering is invariant to rate and B,
which the record also checks numerically.

    python3 scripts/v3_sweep.py --unit e0              # the reference config under the new protocol
    python3 scripts/v3_sweep.py --unit e1a             # 2.7B: grid shape x routing x kappa
    python3 scripts/v3_sweep.py --list e1a             # print the planned config ids
Outputs under analysis/v3/<unit>/: configs.jsonl, summary.csv, runs.csv,
candidates.csv, manifest.json. Resumable: a config id already in
configs.jsonl is skipped.
"""
import argparse
import csv
import dataclasses as dc
import hashlib
import json
import math
import os
import statistics
import sys
import time

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import cimsim_cli as cli                  # noqa: E402
from scripts import fabric as fm                       # noqa: E402
from scripts import llm_workload as lw                 # noqa: E402
from scripts import interconnect as ic                 # noqa: E402
from scripts import placement as pm                    # noqa: E402
from scripts import search_baselines as sb             # noqa: E402
from scripts import search_eval as se                  # noqa: E402
from scripts import search_sa as sa                    # noqa: E402
from scripts import search_space as ss                 # noqa: E402
from scripts import offload as offload_mod           # noqa: E402

A = os.path.join(WS, "analysis")
V3 = os.path.join(A, "v3")
REF_ACCOUNT = os.path.join(A, "scale_2p7b_per_op.json")
CALIB = os.path.join(V3, "attention_calibration.json")
T0_NORM = 0.020 / 2.11870568800
ALPHA = 0.996
RATES = (1 / 16, 1 / 8, 1 / 4, 1 / 2, 1, 2, 4, 8, 16, 32)
BWS = (0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 4.0, 8.0, 12.5, 25.0, 50.0)
TILINGS = {"col": ("M",), "colrow": ("M", "C"), "row": ("C", "M"),
           "mixed": {"*": ("M", "C"), "ffn2": ("C", "M")},            # item 4.1: the wide-input operator row-split, the rest column-split
           "mixed2": {"*": ("M", "C"), "ffn2": ("C", "M"), "out_proj": ("C", "M")}}
REF_D, REF_DH = 2560, 80


# ------------------------------------------------------------------ accounts
def ref_constants():
    """Per-operator constants of the frozen S = 512 account: per-row compute
    time and energy per MAC (write energy removed), per op kind."""
    base = json.load(open(REF_ACCOUNT))
    cfg = lw.GptConfig(**{k: base["config"][k] for k in ("d_model", "n_heads", "d_ff", "n_layers", "name")})
    out = {}
    for ph in ("prefill", "decode"):
        ops = {o.name: o for o in lw.block_ops(cfg, 512, ph)}
        for r in base["phases"][ph]:
            o = ops[r["name"]]
            macs = o.P * o.C * o.M * o.N
            e_write = o.write_cells * lw.E_WRITE_PER_CELL_J
            out[(ph, r["name"])] = {"s_per_row": r["compute_s"] / o.P,
                                    "pj_per_mac": (r["energy_J"] - e_write) / macs * 1e12}
    return out, base


_REF = None


def derived_account(cfg, S, calib=None):
    """An account for (cfg, S) from the reference constants. Static operators:
    compute = P x t_row (exact under the resident mapping: every static
    operator of the reference measures P x 10.14 us). Attention: compute =
    P x the reference per-row constant of that operator and phase, replaced
    by the calibration table entry for (phase, op, S, dh) when present.
    Write = min(write_rows, 256) x T_SET (the account's rule). Energy =
    pJ per MAC of the reference operator kind x MACs + write cells x E_write."""
    global _REF
    if _REF is None:
        _REF = ref_constants()
    consts, base = _REF
    dh = cfg.d_model // cfg.n_heads
    out = {"config": {"d_model": cfg.d_model, "n_heads": cfg.n_heads, "d_ff": cfg.d_ff,
                      "n_layers": cfg.n_layers, "S": S, "name": cfg.name},
           "ref_words_per_cycle": base["ref_words_per_cycle"], "hist_source": base["hist_source"],
           "fabric": base.get("fabric"), "phases": {},
           "derivation": "derived from the frozen 2.7B S=512 account (static compute exact: P x t_row; "
                         "attention per-row constants from the reference or the calibration table; "
                         "write = min(rows,256) x T_SET; energy = ref pJ/MAC x MACs + write cells x E_write)",
           "attention_calibrated": {}}
    for ph in ("prefill", "decode"):
        recs = []
        for o in lw.block_ops(cfg, S, ph):
            c = consts[(ph, o.name)]
            s_row = c["s_per_row"]
            key = f"{ph}/{o.name}/S{S}/dh{dh}"
            if calib and key in calib:
                s_row = calib[key]["s_per_row"]
                out["attention_calibrated"][key] = True
            macs = o.P * o.C * o.M * o.N
            n_dies = 1 if o.kind == "dynamic" else None
            recs.append({"name": o.name, "kind": o.kind, "dies": n_dies,
                         "energy_J": c["pj_per_mac"] * 1e-12 * macs + o.write_cells * lw.E_WRITE_PER_CELL_J,
                         "compute_s": o.P * s_row,
                         "write_s": min(o.write_rows, 256) * lw.T_SET_NS * 1e-9,
                         "cycle_s": base["phases"][ph][0]["cycle_s"],
                         "ondie_serial_ref_s": None, "die_flow_words": [], "die_flow_down": [], "die_flow_up": []})
        out["phases"][ph] = recs
    return out


def load_calib():
    return json.load(open(CALIB)) if os.path.exists(CALIB) else None


class V3Workload(se.Workload2p7B):
    """Workload2p7B on an explicit fabric, an account DICT and a tiling preference."""

    def __init__(self, fabric, account, tiling_dims=("M", "C")):
        self.fab = fabric
        c = account["config"]
        self.cfg = lw.GptConfig(d_model=c["d_model"], n_heads=c["n_heads"], d_ff=c["d_ff"],
                                n_layers=c["n_layers"], name=c["name"],
                                **{k: c[k] for k in ("head_dim", "n_kv_heads", "ffn_gated", "activation") if k in c})
        self.S = c["S"]
        self.ops = {ph: {r["name"]: r for r in rows} for ph, rows in account["phases"].items()}
        self.pl = pm.sequential_fill(self.fab)
        self.die_ic = ic.build(self.fab, "die", self.pl)
        self.tiling_dims = dict(tiling_dims) if isinstance(tiling_dims, dict) else tuple(tiling_dims)
        self.account_status = account.get("derivation", "measured")


# ------------------------------------------------------------------ fabric
def make_fabric(grid, topology="mesh", routing="xy", per_parent=None):
    fab = fm.from_yaml(cli.DEFAULT_FABRIC)
    gx, gy = grid
    params = {"routing": routing, "hub": "center"} if topology in ("mesh", "torus") else {}
    levels = []
    for l in fab.levels:
        if l.name == "die":
            link = dc.replace(l.link, topology=topology, params=params)
            levels.append(dc.replace(l, mesh=(gx, gy), per_parent=per_parent or gx * gy, link=link))
        else:
            levels.append(l)
    return dc.replace(fab, name=f"{topology}{gx}x{gy}_{routing}", levels=levels).validate()


def grid_for(n_dies, aspect):
    """The smallest grid of the given aspect (X:Y = aspect) holding n_dies."""
    y = math.ceil(math.sqrt(n_dies / aspect))
    x = math.ceil(aspect * y)
    while x * y < n_dies:
        y += 1
        x = math.ceil(aspect * y)
    return (x, y)


# ------------------------------------------------------------------ one config
def budget(n_movable):
    return max(1200, math.ceil(1200 * n_movable / 544))


def unified_metrics(rec):
    """The communication columns on the paper's definition H = P + A/B, all
    from the SAME endpoint (the headline run): eta_P = 1 - (H1 + P1) /
    (H0 + P0), r0_P = (H0 + P0) / T_base, G_headline = 1 - T1 / T_base, so
    that G_headline = eta_P x r0_P holds exactly (R is common). The record's
    eta_comm / r0 are on H = A/B alone and G_e2e is the same headline gain;
    the summary's G median is the median over seeds and is a different
    statistic from the headline's own gain when the seed count is even."""
    c0 = rec["candidates"][rec["strongest"]]; h = rec["search"]["runs"][rec["search"]["headline"]]
    T0 = rec["T_base_s"]
    H0, H1 = c0["H_s"] + c0["prop_s"], h["H_s"] + h["prop_s"]
    eta = 1 - H1 / H0 if H0 else 0.0
    r0 = H0 / T0
    G = 1 - h["T_s"] / T0
    return {"eta_P": eta, "r0_P": r0, "G_headline": G, "eta_P_times_r0_P": eta * r0, "identity_abs_err": abs(G - eta * r0),
            "P_share_of_H0": c0["prop_s"] / H0 if H0 else 0.0, "headline_T_s": h["T_s"]}


def evaluate_config(spec, n_random, seeds, calib, log=print, objective="t_norm"):
    """spec: dict with model (d, dh, d_ff, L), S, phase, tiling, grid, topology,
    routing, kappa, bw; returns the full record."""
    t_cfg = time.perf_counter()
    cfg = lw.GptConfig(d_model=spec["d"], n_heads=spec["d"] // spec["dh"], d_ff=spec["d_ff"],
                       n_layers=spec["L"], name=spec.get("model_tag", f"d{spec['d']}"))
    S, phase = spec["S"], spec["phase"]
    # the account
    if spec.get("account_path"):          # a real model's measured account (next-round item 2): the configuration comes from the account
        if not os.path.exists(spec["account_path"]):
            return {"config_id": spec["config_id"], "spec": spec, "status": "no account", "reason": f"missing {spec['account_path']}"}
        account = json.load(open(spec["account_path"])); account_status = f"measured ({os.path.basename(spec['account_path'])})"
        if not account.get("phases", {}).get(phase):
            return {"config_id": spec["config_id"], "spec": spec, "status": "infeasible",
                    "reason": account.get("infeasible", {}).get(phase, f"no {phase} account")}
        c = account["config"]
        cfg = lw.GptConfig(d_model=c["d_model"], n_heads=c["n_heads"], d_ff=c["d_ff"], n_layers=spec["L"], name=c["name"],
                           **{k: c[k] for k in ("head_dim", "n_kv_heads", "ffn_gated", "activation") if k in c})
    elif spec["d"] == REF_D and spec["dh"] == REF_DH and spec["d_ff"] == 10240 and S == 512:   # block-level: any L
        account = json.load(open(REF_ACCOUNT)); account_status = "measured (frozen 2.7B S=512)"
    else:
        measured = os.path.join(V3, "accounts", f"d{spec['d']}_dh{spec['dh']}_ff{spec['d_ff']}_S{S}.json")
        if not os.path.exists(measured) and spec["d"] == REF_D and spec["dh"] == REF_DH and spec["d_ff"] == 10240:
            measured = os.path.join(A, f"scale_2p7b_per_op_S{S}.json")
        if os.path.exists(measured) and json.load(open(measured)).get("phases", {}).get(phase):
            account = json.load(open(measured)); account_status = f"measured ({os.path.basename(measured)})"
        else:
            account = derived_account(cfg, S, calib)
            account_status = "derived" + (" + attention calibration" if account["attention_calibrated"] else " (attention uncalibrated)")
    account = json.loads(json.dumps(account))
    account["config"]["n_layers"] = spec["L"]       # accounts are block-level; the depth is the spec's
    # capacity of the attention die: both attention operators co-resident
    att_cells = sum(lw.op_weight_cells(o) for o in lw.block_ops(cfg, S, phase) if o.kind == "dynamic")
    att_cap = account.get("attention_die_capacity", {}).get("cells", lw.DIE_WEIGHT_CELLS)     # an assumed larger attention die is declared in the account
    if att_cells > att_cap:
        return {"config_id": spec["config_id"], "spec": spec, "status": "infeasible",
                "reason": f"attention K/V arrays {att_cells} cells > die {att_cap}"}
    dims = TILINGS[spec["tiling"]]
    try:
        chain = lw.block_chain(cfg, S, phase, on_chip=not spec.get("offload"), max_dies=10 ** 6, dims=dims)
    except ValueError as e:
        return {"config_id": spec["config_id"], "spec": spec, "status": "infeasible", "reason": f"tiling: {e}"}
    dies_per_layer = sum(e["n_dies"] for e in chain)
    n_dies = dies_per_layer * spec["L"]
    grid = tuple(spec["grid"]) if spec.get("grid") else grid_for(n_dies, spec.get("aspect", 1.0))
    if grid[0] * grid[1] < n_dies:
        return {"config_id": spec["config_id"], "spec": spec, "status": "infeasible",
                "reason": f"{n_dies} dies do not fit the {grid[0]}x{grid[1]} grid"}
    fab = make_fabric(grid, spec["topology"], spec["routing"])
    W = V3Workload(fab, account, dims)
    W.port_ratio = float(spec["kappa"])
    bw = float(spec["bw"])
    mu = {phase: 1.0}
    off = None
    if spec.get("offload"):           # the agreed attention setting: a digital unit (hub) inside the package, K/V in its memory
        o = spec["offload"]
        slots_xy = pm.sequential_fill(fab).slots["die"]
        off = offload_mod.build(slots_xy, cfg.n_layers, position=o.get("position", "center"), K=int(o.get("K", 1)),
                                resource_mode=o.get("resource_mode", "per_unit"), overrides=o.get("unit"), co_located=bool(o.get("co_located", False)),
                                split=o.get("split", "layer"))
        W.offload = off
        kvc = offload_mod.kv_capacity(cfg, S, off, phase=phase)
        if not all(x["fits"] for x in kvc):
            return {"config_id": spec["config_id"], "spec": spec, "status": "infeasible",
                    "reason": "capacity (unit K/V memory): " + "; ".join(f"unit {x['unit']} needs {x['kv_bytes']} B of {x['capacity_bytes']:.0f}" for x in kvc if not x["fits"])}
        if n_dies + len(off.reserved_slots()) > grid[0] * grid[1]:
            return {"config_id": spec["config_id"], "spec": spec, "status": "infeasible",
                    "reason": f"{n_dies} dies + {len(off.reserved_slots())} unit nodes do not fit the {grid[0]}x{grid[1]} grid"}
    comp, wr, elw = W.layer_terms_s(phase)
    L = cfg.n_layers
    N_s, F_s = comp * L, (wr + elw) * L
    hub_wps = off.unit["link_bandwidth_gbps"] * 1e9 if off is not None else None

    def ev(pi):
        bs = W.boundaries(pi, phase)
        sc = se._assemble(pi, W, {phase: bs}, mu, "single", bw, 1.0)
        d = sc.per_phase[phase]["decomp"]
        row = {"T_s": sc.t_opt_s, "H_s": d["d2d_serial_s"], "prop_s": d["propagation_s"],
               "A_words": d["d2d_busiest_words"], "words": d["d2d_words"], "E_J": sc.e_J,
               "E_comm_J": d["d2d_flat_J"] + d["d2d_surplus_J"]}
        if off is not None:        # per-hand-off components so any (B_mesh, C_hub) point can be formed
            row["comp"] = [[round(b["link_words"]), round(b["dport_words"]), round(b["hub_words"])] for b in bs]
            row["hub_words_sum"] = d["hub_words_sum"]
        return row

    def H_of(row, B, C_hub=None):
        """The communication term at mesh bandwidth B (GB/s) for a candidate (offloaded: per-hand-off max over links, die ports, hub ports)."""
        if off is None:
            return row["A_words"] / (B * 1e9)
        C = (C_hub if C_hub is not None else off.unit["link_bandwidth_gbps"]) * 1e9
        return sum(max(max(l, dp) / (B * 1e9), h / C) for l, dp, h in row["comp"])
    # candidates
    t = time.perf_counter()
    cands, rule_failures = {}, {}
    for n in sb.NAMES:
        if n == "random":
            continue
        try:
            cands[n] = sb.generate(n, W, seed=0)
            if off is not None and any(s in off.reserved_slots() for v in cands[n].seat.values() for s in v):
                del cands[n]; rule_failures[n] = "seats a die on a unit node"
        except Exception as e:        # a rule that cannot handle this grid or chain (clustered on 9x9, least_manhattan on a 1-die chain)
            rule_failures[n] = str(e)[:160]
    for s in range(n_random):
        cands[f"random_s{s}"] = sb.generate("random", W, seed=s)
    rows = {n: ev(p) for n, p in cands.items()}
    t_cand = time.perf_counter() - t
    rules = [n for n in cands if not n.startswith("random_s")]
    randoms = [n for n in cands if n.startswith("random_s")]
    strongest_rule = min(rules, key=lambda n: rows[n]["T_s"])
    strongest_random = min(randoms, key=lambda n: rows[n]["T_s"])
    strongest = min(cands, key=lambda n: rows[n]["T_s"])
    t_base = rows[strongest]["T_s"]
    best_of = {k: min(rows[f"random_s{s}"]["T_s"] for s in range(min(k, n_random))) for k in (5, 20, 100, 500) if k <= n_random}
    # timing: full score
    tt = []
    for _ in range(12):
        t = time.perf_counter(); se.score(cands[strongest], W, mu=mu, d2d_gbps=bw); tt.append(time.perf_counter() - t)
    full_score_ms = statistics.median(tt) * 1e3
    # search
    R_s = N_s + F_s
    starts = {"rule": strongest_rule, "random_best": strongest_random, "random_s0": "random_s0"}
    n_slots = fab.level("die").per_parent if off is None else W.usable_slots()
    steps = budget(n_dies)
    sched = sa.Schedule(t0=T0_NORM, alpha=ALPHA, steps=steps)
    runs = {}
    t_search = time.perf_counter()
    for i, (sname, cname) in enumerate(sorted(starts.items())):
        for s in seeds:
            J = cli.Objective(W, cands[cname], mu, "single", bw, 1.0, "t")
            if objective == "t_norm":            # the V3 objective: T / T_base
                Jn = lambda pi, J=J: J(pi) / t_base
            elif objective == "h_norm":          # the communication term normalised by its own baseline value: (T - R) / (T_base - R), R = N + F
                Jn = lambda pi, J=J: (J(pi) - R_s) / (t_base - R_s)
            else:
                raise ValueError(objective)
            t = time.perf_counter()
            r = sa.anneal(Jn, cands[cname], n_slots, sched, seed=1000003 * s + i)
            wall = time.perf_counter() - t
            e = ev(r.best_pi)
            runs[f"sa_{sname}_s{s}"] = {"start": sname, "start_layout": cname, "sa_seed": s, "steps": steps,
                                        "t0_norm": T0_NORM, "alpha": ALPHA, "start_T_s": rows[cname]["T_s"],
                                        **e, "gain_pct": (1 - e["T_s"] / t_base) * 100, "accepted": r.accepted,
                                        "proposed": r.proposed, "wall_s": wall, "ms_per_step": wall / steps * 1e3,
                                        "best_pi": r.best_pi.to_json()}
    per_seed = {s: min((runs[f"sa_{sn}_s{s}"]["T_s"], f"sa_{sn}_s{s}") for sn in starts) for s in seeds}
    order = sorted(per_seed, key=lambda s: per_seed[s][0])
    headline_seed = order[len(order) // 2]
    headline = per_seed[headline_seed][1]
    gains = [(1 - per_seed[s][0] / t_base) * 100 for s in seeds]
    h = runs[headline]
    # metrics
    H0, H1 = rows[strongest]["H_s"], h["H_s"]
    A0, A1 = rows[strongest]["A_words"], h["A_words"]
    B_eq_off = None
    if off is not None:                # the mesh bandwidth at which the strongest baseline matches the selected layout's H (C_hub fixed)
        target = H1
        if H_of(rows[strongest], 1e9) < target:
            lo, hi = 1e-4, 1e6
            for _ in range(80):
                mid = math.sqrt(lo * hi)
                if H_of(rows[strongest], mid) > target:
                    lo = mid
                else:
                    hi = mid
            B_eq_off = math.sqrt(lo * hi)
    eta = 1 - H1 / H0 if H0 else 0.0
    r0 = H0 / t_base
    G = 1 - h["T_s"] / t_base
    # band over the 7 rules and over rules + pool (at rate 1): B_c solves H(B) = R, R = N + F (propagation excluded);
    # on chip H = A/B gives A/R in closed form; offloaded the hub plateau H(inf) = sum hub/C_hub may leave no finite boundary
    def B_c(row, R):
        if off is None:
            return row["A_words"] / R / 1e9
        if H_of(row, 1e9) >= R:            # the plateau alone exceeds R: no finite boundary
            return None
        lo, hi = 1e-4, 1e6
        for _ in range(80):
            mid = math.sqrt(lo * hi)
            if H_of(row, mid) > R:
                lo = mid
            else:
                hi = mid
        return math.sqrt(lo * hi)
    band = {}
    for key, names in (("rules", rules), ("rules_plus_pool", list(cands))):
        bcs = [B_c(rows[n], R_s) for n in names]
        fin = [b for b in bcs if b is not None]
        band[key] = {"B_minus": min(fin) if fin else None, "B_plus": max(fin) if fin else None,
                     "no_finite_boundary": sum(1 for b in bcs if b is None), "n": len(bcs)}
        band[key]["ratio"] = (band[key]["B_plus"] / band[key]["B_minus"]) if fin else None
    if band["rules"]["B_minus"] is None:
        band["rules"]["B_minus"] = band["rules"]["B_plus"] = float("nan")
    # cost grid: ordering invariance and G at every (rate, B) for the frozen pair (strongest, headline)
    grid_pts = []
    for rate in RATES:
        extra = ({band["rules"]["B_minus"] * rate, band["rules"]["B_plus"] * rate, math.sqrt(band["rules"]["B_minus"] * band["rules"]["B_plus"]) * rate}
                 if band["rules"]["B_minus"] == band["rules"]["B_minus"] else set())      # NaN-safe
        for B in sorted(set(BWS) | extra):
            def T(row):
                return N_s / rate + F_s + row["prop_s"] + H_of(row, B)
            Tb = {n: T(rows[n]) for n in cands}
            sb_pt = min(Tb, key=Tb.get)
            T0p, T1p = Tb[strongest], T(h)
            grid_pts.append({"rate": rate, "bw": B, "strongest": sb_pt, "same_strongest": sb_pt == strongest,
                             "T_base_s": T0p, "T_sel_s": T1p, "r": H_of(rows[strongest], B) / T0p,
                             "G_pct": (1 - T1p / T0p) * 100,
                             "region": ("no finite boundary" if band["rules"]["B_minus"] != band["rules"]["B_minus"] else
                                        "below" if B < band["rules"]["B_minus"] * rate else
                                        "above" if B > band["rules"]["B_plus"] * rate else "inside")})
    rec = {"config_id": spec["config_id"], "spec": spec, "status": "done",
           "account_status": account_status, "fabric": fab.name, "grid": grid, "n_dies": n_dies,
           "dies_per_layer": dies_per_layer, "chain": [(e["name"], e["n_dies"], e["split"]) for e in chain],
           "empty_slots": grid[0] * grid[1] - n_dies - (len(off.reserved_slots()) if off is not None else 0), "kappa": spec["kappa"], "bw_gbps": bw, "rule_failures": rule_failures,
           "N_s": N_s, "F_s": F_s, "write_s_per_layer": wr, "elementwise_s_per_layer": elw,
           "n_random": n_random, "candidates": rows,
           "strongest_rule": strongest_rule, "strongest_random": strongest_random, "strongest": strongest,
           "T_base_s": t_base, "random_best_of": best_of,
           "random_median_s": statistics.median(rows[n]["T_s"] for n in randoms),
           "random_spread_pct": (max(rows[n]["T_s"] for n in randoms) / min(rows[n]["T_s"] for n in randoms) - 1) * 100,
           "search": {"starts": starts, "seeds": list(seeds), "steps": steps, "t0_norm": T0_NORM, "alpha": ALPHA, "objective": objective,
                      "runs": runs, "per_seed_best": {s: per_seed[s][1] for s in seeds},
                      "headline": headline, "headline_T_s": h["T_s"], "gain_median_pct": statistics.median(gains),
                      "gain_min_pct": min(gains), "gain_max_pct": max(gains), "best_run": min(runs, key=lambda n: runs[n]["T_s"]),
                      "gain_best_pct": max(r_["gain_pct"] for r_ in runs.values()), "wall_s": time.perf_counter() - t_search},
           "metrics": {"eta_comm": eta, "r0": r0, "G_e2e": G, "eta_times_r": eta * r0,
                       "g_bw_eq": (A0 / A1 - 1 if A1 else None) if off is None else ((B_eq_off / bw - 1) if B_eq_off else None),
                       "B_eq_gbps": (bw * A0 / A1 if A1 else None) if off is None else B_eq_off,
                       "B_eq_note": None if off is None else ("mesh bandwidth alone cannot reach the selected layout's communication time (hub plateau)" if B_eq_off is None else "solved H_base(B_eq) = H_sel(B_ref) with C_hub fixed"),
                       "bw_reduction": 1 - A1 / A0 if A0 else None,
                       "gain_vs_default_pct": (1 - h["T_s"] / rows["sequential"]["T_s"]) * 100 if "sequential" in rows else None,
                       "gain_vs_strongest_rule_pct": (1 - h["T_s"] / rows[strongest_rule]["T_s"]) * 100,
                       "dE_pct": (h["E_J"] / rows[strongest]["E_J"] - 1) * 100,
                       "dE_comm_pct": (h["E_comm_J"] / rows[strongest]["E_comm_J"] - 1) * 100 if rows[strongest]["E_comm_J"] else None},
           "band": band, "cost_grid": grid_pts,
           "attention": ({"mode": "die", "note": "attention on one ReRAM die per layer, K/V programmed into the arrays"} if off is None else
                         {"mode": "unit", **off.to_json(), "kv_capacity": offload_mod.kv_capacity(cfg, S, off, phase=phase), "unit_layer_cost": W.unit_terms(phase),
                          "layer_breakdown_s": W.layer_breakdown_s(phase), "reserved_slots": sorted(off.reserved_slots())}),
           "unified": unified_metrics({"candidates": rows, "strongest": strongest, "T_base_s": t_base, "search": {"runs": runs, "headline": headline}}),
           "ordering_invariant_over_grid": all(p["same_strongest"] for p in grid_pts),
           "timing": {"candidates_s": t_cand, "full_score_ms": full_score_ms,
                      "ms_per_sa_step_median": statistics.median(r_["ms_per_step"] for r_ in runs.values()),
                      "config_wall_s": time.perf_counter() - t_cfg}}
    log(f"[{spec['config_id']}] {n_dies} dies on {grid[0]}x{grid[1]} | strongest {strongest} {t_base*1e3:.1f} ms "
        f"(rule {strongest_rule}, random best-of-{n_random}) | G median {rec['search']['gain_median_pct']:.2f}% "
        f"[{min(gains):.2f}, {max(gains):.2f}] | eta {eta*100:.1f}% r {r0*100:.1f}% | band {band['rules']['B_minus']:.3f}-{band['rules']['B_plus']:.3f} "
        f"| {rec['timing']['config_wall_s']:.0f} s")
    return rec


# ------------------------------------------------------------------ units
def base_spec(**kw):
    s = {"d": 2560, "dh": 80, "d_ff": 10240, "L": 32, "S": 512, "phase": "prefill", "tiling": "colrow",
         "grid": (24, 24), "topology": "mesh", "routing": "xy", "kappa": 2.0, "bw": 0.4, "model_tag": "2p7B"}
    s.update(kw)
    s["config_id"] = (f"{s['model_tag']}_dh{s['dh']}_ff{s['d_ff']}_L{s['L']}_{s['tiling']}_{s['phase']}{s['S']}_"
                      f"{'x'.join(map(str, s['grid'])) if s.get('grid') else 'auto%g' % s.get('aspect', 1.0)}_"
                      f"{s['topology']}_{s['routing']}_k{s['kappa']:g}_b{s['bw']:g}")
    return s


def unit_specs(unit):
    if unit == "e0":
        return [base_spec()]
    if unit == "e1a":
        shapes = [(24, 24), (18, 32), (32, 18), (16, 36), (36, 16), (12, 48), (48, 12), (9, 64), (64, 9),
                  (8, 72), (72, 8), (6, 96), (96, 6)]
        return [base_spec(grid=g, routing=r, kappa=k) for g in shapes for r in ("xy", "yx") for k in (1, 1.5, 2, 3, 4, 8)]
    if unit == "e1t":
        return [base_spec(topology=t, routing=r) for t in ("torus", "ring") for r in (("xy", "yx") if t == "torus" else ("xy",))]
    if unit == "e1s":      # workpoints on the reference model (lengths, phases)
        out = [base_spec(S=S, phase="prefill") for S in (128, 256, 512, 1024, 1536, 2048, 4096)]
        out += [base_spec(S=S, phase="decode") for S in (128, 256, 512, 1024, 1536, 2048, 4096)]
        return out
    if unit == "e2_depth":
        return [base_spec(L=L, grid=None, aspect=a, model_tag="2p7Bw") for L in (4, 8, 12, 16, 24, 32, 48, 64) for a in (1.0, 2.0)]
    if unit == "e2_width":
        fam = {64: (512, 768, 1024, 1536, 2048, 2560, 3072, 4096), 80: (640, 1280, 1920, 2560, 3200, 3840),
               128: (512, 1024, 1536, 2048, 2560, 3072, 4096)}
        return [base_spec(d=d, dh=dh, d_ff=4 * d, grid=None, aspect=a, model_tag=f"w{d}")
                for dh, ds in fam.items() for d in ds for a in (1.0, 2.0)]
    if unit == "e2_ffn":
        return [base_spec(d_ff=r * 2560, grid=None, aspect=a, model_tag="2p7Bf") for r in (2, 3, 4, 6, 8) for a in (1.0, 2.0)]
    if unit == "e1b":      # the dh = 64 model family: width x FFN ratio x depth, near-square grids
        return [base_spec(d=d, dh=64, d_ff=r * d, L=L, grid=None, aspect=1.0, model_tag=f"w{d}")
                for d in (512, 768, 1024, 1536, 2048, 2560, 3072, 4096) for r in (2, 4, 8) for L in (8, 32)]
    if unit == "e4":       # tiling variants on the reference model and two widths
        out = [base_spec(tiling=tl) for tl in ("col", "colrow", "row")]
        out += [base_spec(d=d, dh=64, d_ff=4 * d, grid=None, aspect=1.0, tiling=tl, model_tag=f"w{d}")
                for d in (1536, 4096) for tl in ("col", "colrow", "row")]
        return out
    if unit == "confirm":   # specs listed in analysis/v3/confirm_specs.json (written by v3_report.py)
        specs = json.load(open(os.path.join(V3, "confirm_specs.json")))
        return [base_spec(**{k: v for k, v in s.items() if k != "config_id"}) for s in specs]
    raise ValueError(unit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", required=True)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--n-random", type=int, default=100)
    ap.add_argument("--seeds", default="0,1,2,3,4")
    ap.add_argument("--only", default="", help="comma-separated config ids")
    args = ap.parse_args()
    specs = unit_specs(args.unit)
    if args.only:
        keep = set(args.only.split(","))
        specs = [s for s in specs if s["config_id"] in keep]
    if args.list:
        for s in specs:
            print(s["config_id"])
        print(len(specs), "configs")
        return
    out = os.path.join(V3, args.unit)
    os.makedirs(out, exist_ok=True)
    jl = os.path.join(out, "configs.jsonl")
    done = set()
    if os.path.exists(jl):
        for line in open(jl):
            done.add(json.loads(line)["config_id"])
    seeds = [int(x) for x in args.seeds.split(",")]
    calib = load_calib()
    manifest = {"unit": args.unit, "n_random": args.n_random, "seeds": seeds, "t0_norm": T0_NORM, "alpha": ALPHA,
                "budget_rule": "max(1200, ceil(1200 n/544))", "starts": "strongest rule, strongest random of the pool, random seed 0",
                "seed_formula": "1000003 s + start index (starts sorted by name)",
                "calibration_table": CALIB if calib else None, "planned": [s["config_id"] for s in specs]}
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=1)
    with open(jl, "a") as f:
        for spec in specs:
            if spec["config_id"] in done:
                continue
            rec = evaluate_config(spec, args.n_random, seeds, calib)
            f.write(json.dumps(rec) + "\n"); f.flush()
            if rec["status"] != "done":
                print(f"[{spec['config_id']}] {rec['status']}: {rec['reason']}")
    write_tables(out)


def write_tables(out):
    recs = [json.loads(l) for l in open(os.path.join(out, "configs.jsonl"))]
    with open(os.path.join(out, "summary.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["config_id", "status", "account_status", "d", "dh", "d_ff", "L", "S", "phase", "tiling", "grid", "topology",
                    "routing", "kappa", "bw_gbps", "n_dies", "empty_slots", "strongest", "strongest_rule", "strongest_random",
                    "T_base_ms", "random_best_of_5_ms", "random_best_of_20_ms", "random_best_of_100_ms", "random_spread_pct",
                    "steps", "headline_run", "headline_T_ms", "G_median_pct", "G_min_pct", "G_max_pct", "G_best_pct",
                    "eta_comm_pct", "r0_pct", "g_bw_eq_pct", "B_eq_gbps", "gain_vs_default_pct", "dE_pct",
                    "B_minus_rules", "B_plus_rules", "band_ratio_rules", "band_ratio_rules_plus_pool", "ordering_invariant",
                    "full_score_ms", "ms_per_sa_step", "search_wall_s", "config_wall_s", "reason"])
        for r in recs:
            s = r["spec"]
            if r["status"] != "done":
                w.writerow([r["config_id"], r["status"], "", s["d"], s["dh"], s["d_ff"], s["L"], s["S"], s["phase"], s["tiling"],
                            "x".join(map(str, s["grid"])) if s.get("grid") else "", s["topology"], s["routing"], s["kappa"], s["bw"]]
                           + [""] * 33 + [r.get("reason", "")])
                continue
            m, b, sr, t = r["metrics"], r["band"], r["search"], r["timing"]
            bo = r["random_best_of"]
            w.writerow([r["config_id"], r["status"], r["account_status"], s["d"], s["dh"], s["d_ff"], s["L"], s["S"], s["phase"],
                        s["tiling"], "x".join(map(str, r["grid"])), s["topology"], s["routing"], s["kappa"], s["bw"],
                        r["n_dies"], r["empty_slots"], r["strongest"], r["strongest_rule"], r["strongest_random"],
                        f"{r['T_base_s']*1e3:.3f}", f"{bo.get(5, 0)*1e3:.3f}", f"{bo.get(20, 0)*1e3:.3f}", f"{bo.get(100, 0)*1e3:.3f}",
                        f"{r['random_spread_pct']:.3f}", sr["steps"], sr["headline"], f"{sr['headline_T_s']*1e3:.3f}",
                        f"{sr['gain_median_pct']:.3f}", f"{sr['gain_min_pct']:.3f}", f"{sr['gain_max_pct']:.3f}", f"{sr['gain_best_pct']:.3f}",
                        f"{m['eta_comm']*100:.3f}", f"{m['r0']*100:.3f}", f"{(m['g_bw_eq'] or 0)*100:.3f}", f"{(m['B_eq_gbps'] or 0):.4f}",
                        f"{m['gain_vs_default_pct']:.3f}" if m['gain_vs_default_pct'] is not None else "", f"{m['dE_pct']:.3f}",
                        f"{b['rules']['B_minus']:.4f}", f"{b['rules']['B_plus']:.4f}", f"{(b['rules']['ratio'] or float('nan')):.3f}",
                        f"{(b['rules_plus_pool']['ratio'] or float('nan')):.3f}", r["ordering_invariant_over_grid"],
                        f"{t['full_score_ms']:.2f}", f"{t['ms_per_sa_step_median']:.3f}", f"{sr['wall_s']:.1f}", f"{t['config_wall_s']:.1f}", ""])
    with open(os.path.join(out, "runs.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["config_id", "run", "start", "start_layout", "sa_seed", "steps", "t0_norm", "start_T_ms", "T_ms", "H_ms",
                    "A_words", "E_J", "gain_vs_strongest_pct", "accepted", "proposed", "wall_s"])
        for r in recs:
            if r["status"] != "done":
                continue
            for n, x in r["search"]["runs"].items():
                w.writerow([r["config_id"], n, x["start"], x["start_layout"], x["sa_seed"], x["steps"], f"{x['t0_norm']:.7f}",
                            f"{x['start_T_s']*1e3:.3f}", f"{x['T_s']*1e3:.3f}", f"{x['H_s']*1e3:.3f}", f"{x['A_words']:.0f}",
                            f"{x['E_J']:.6f}", f"{x['gain_pct']:.3f}", x["accepted"], x["proposed"], f"{x['wall_s']:.2f}"])
    with open(os.path.join(out, "candidates.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["config_id", "layout", "T_ms", "H_ms", "prop_ms", "A_words", "words", "E_J", "E_comm_J"])
        for r in recs:
            if r["status"] != "done":
                continue
            for n, x in r["candidates"].items():
                w.writerow([r["config_id"], n, f"{x['T_s']*1e3:.3f}", f"{x['H_s']*1e3:.3f}", f"{x['prop_s']*1e3:.4f}",
                            f"{x['A_words']:.0f}", f"{x['words']:.0f}", f"{x['E_J']:.6f}", f"{x['E_comm_J']:.6f}"])
    with open(os.path.join(out, "cost_grid.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["config_id", "rate", "bw_gbps", "region", "strongest", "same_strongest", "T_base_ms", "T_sel_ms", "r_pct", "G_pct"])
        for r in recs:
            if r["status"] != "done":
                continue
            for p in r["cost_grid"]:
                w.writerow([r["config_id"], p["rate"], f"{p['bw']:.4f}", p["region"], p["strongest"], p["same_strongest"],
                            f"{p['T_base_s']*1e3:.3f}", f"{p['T_sel_s']*1e3:.3f}", f"{p['r']*100:.3f}", f"{p['G_pct']:.3f}"])


if __name__ == "__main__":
    main()

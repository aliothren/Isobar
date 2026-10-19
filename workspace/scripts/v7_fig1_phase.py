"""Fig. 1 data (Isobar_next_tasks section 3.1): the intra-die enumeration
(ffn die, 2x4 macro mesh, two FFN operators, 70 joint seatings) and the
package-level phase diagram of the Gemma-7B reference configuration
re-priced from the stored seven-rule candidates over device row rate x
mesh bandwidth, with the per-rule boundaries, the spread contour and the
hardware projection points under the current model.

    MPLBACKEND=Agg python3 scripts/v7_fig1_phase.py
      -> analysis/v7/intradie_phase_candidates.csv, intradie_phase_curves.csv,
         phase_grid.csv, phase_boundary_curves.csv, phase_projection_points.csv, phase_setup.json
"""
import math
import os
import sys

import numpy as np

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v7_common as V                      # noqa: E402
from scripts import v6_common as C                      # noqa: E402
from scripts import anchors as an                       # noqa: E402
from scripts import analyze_soft_lever as asl           # noqa: E402
from scripts import search_withindie as sw              # noqa: E402

S_LO, S_HI, NS = 0.02, 40.0, 121                        # Mrows/s, the standing figure's range
B_LO, B_HI, NB = 1e-2, 1e3, 121                         # GB/s per direction
S_REF = 1.0 / an.T_MVM_S / 1e6                          # NeuRRAM-class row rate, Mrows/s
LEVEL = 0.20


def s_axis():
    s = list(np.geomspace(S_LO, S_HI, NS))
    for extra in (S_REF,):
        if not any(abs(x - extra) / extra < 1e-9 for x in s):
            s.append(extra)
    return sorted(s)


def b_axis():
    b = list(np.geomspace(B_LO, B_HI, NB))
    for extra in (0.4, 12.5, 0.5215399465233344):
        if not any(abs(x - extra) / extra < 1e-9 for x in b):
            b.append(extra)
    return sorted(b)


def bisect(f, lo, hi, steps=80):
    """f decreasing; root of f = 0 between lo and hi (log bisection)."""
    for _ in range(steps):
        mid = math.sqrt(lo * hi)
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
    return math.sqrt(lo * hi)


# ------------------------------------------------------------ intra-die
def intra_die():
    J = sw.WithinDieJ("ffn", "prefill", sw.G_ACTIVE)
    w2 = asl.REF_WC / an.CYCLE_S
    ops = [n for n, _ in J.ops]
    comp = {n: J.recs[n]["compute_s"] for n in ops}
    write = {n: J.recs[n]["write_s"] for n in ops}
    prop = {n: J.recs[n]["latency_s"] - J.recs[n]["write_s"] - max(J.recs[n]["compute_s"], J.recs[n]["serial_s"]) for n in ops}
    fixed = sum(write[n] + prop[n] for n in ops)
    c_ref = max(comp.values())
    rows, seat_words = [], []
    for i, (_c, _m, seat) in enumerate(J.exhaustive()):
        ser = {n: J.a3_ser(n, seat[n]) * w2 for n in ops}
        A = max(ser.values())
        T_ref04 = fixed + sum(max(comp[n], ser[n] / 0.4e9) for n in ops)
        rows.append({"seating_id": i, **{f"{n}_macros": "|".join(map(str, seat[n])) for n in ops}, **{f"{n}_serialization_words": ser[n] for n in ops},
                     "A_words": A, **{f"{n}_compute_ref_s": comp[n] for n in ops}, **{f"{n}_write_s": write[n] for n in ops}, **{f"{n}_propagation_s": prop[n] for n in ops},
                     "fixed_s": fixed, "B_hide_all_ops_ref_gbps": A / c_ref / 1e9, "T_at_ref_rate_0.4gbps_s": T_ref04})
        seat_words.append(ser)
    A = [r["A_words"] for r in rows]
    a_min, a_max = min(A), max(A)
    # curves on the s axis: boundaries (per-op masking thresholds), spread contour
    curves = []
    for s in s_axis():
        cs = c_ref * (S_REF / s)
        lo_, hi_ = a_min / cs / 1e9, a_max / cs / 1e9

        def spread(B):
            Ts = [fixed + sum(max(cs, v / (B * 1e9)) for v in sw_.values()) for sw_ in seat_words]
            return max(Ts) / min(Ts) - 1.0
        b20 = bisect(lambda B: spread(B) - LEVEL, lo_ * 1e-3, hi_ * 1.5) if spread(hi_ * 1.5) <= LEVEL else ""
        curves.append({"s_mrows_per_s": s, "t_row_us": 1.0 / s, "compute_per_op_s": cs, "R_s": fixed + 2 * cs, "B_minus_gbps": lo_, "B_plus_gbps": hi_, "B_spread20_gbps": b20,
                       "spread_at_B_minus": spread(lo_), "spread_at_B_plus": spread(hi_), "n_seatings": len(rows),
                       "seating_min_A": int(np.argmin(A)), "seating_max_A": int(np.argmax(A))})
    setup = {"instance": "ffn die of the reference 2.7B account, 2x4 macro mesh, operators ffn1 and ffn2 co-resident, 70 legal joint seatings (exhaustive)",
             "model": "per op t = write + propagation + max(compute(s), serialization_words / B); boundary B_-(s) = A_min / c(s), B_+(s) = A_max / c(s) with c(s) = c_ref s_ref / s the per-op compute and A = max over ops of the serialization words; spread = (T_max - T_min) / T_min over the 70 seatings",
             "compute_ref_s_per_op": comp, "fixed_s": fixed, "A_min_words": a_min, "A_max_words": a_max, "s_ref_mrows_per_s": S_REF, "words_per_cycle_ref": asl.REF_WC, "cycle_s": an.CYCLE_S,
             "source_modules": ["scripts/search_withindie.py (WithinDieJ, exhaustive)", "scripts/fig_phase_isobar.py (intra_die_model, intra_die_curves)"]}
    return rows, curves, setup


# ------------------------------------------------------------ package
def package():
    rec = C.find_record(*V.GEMMA_REF)
    Ch = rec["attention"]["unit"]["link_bandwidth_gbps"] * 1e9
    N, F = rec["N_s"], rec["F_s"]
    lb = rec["attention"]["layer_breakdown_s"]; L = rec["spec"]["L"]
    names = {n: (n if n != "random" else "random_s0") for n in V.NAMED_RULES}
    present = {n: rec["candidates"][k] for n, k in names.items() if k in rec["candidates"]}
    failed = {n: rec["rule_failures"].get(n, "") for n in V.NAMED_RULES if names[n] not in rec["candidates"]}
    named5 = [n for n in present if n != "random"]
    sets = {"seven_rules": list(present), "named_rules": named5}
    grid, curves = [], []
    for s in s_axis():
        R = N * (S_REF / s) + F
        bc, lim, status = {}, {}, {}
        for n, row in present.items():
            lim[n] = V.H_limit(row, Ch)
            if abs(lim[n] - R) <= 1e-9 * R:
                status[n], bc[n] = "limit_equals_R", ""
            elif lim[n] > R:
                status[n], bc[n] = "no_finite_boundary", ""
            else:
                b = V.solve_B(row, R, Ch)
                status[n] = "finite" if B_LO <= b <= B_HI else "beyond_scan"
                bc[n] = b
        cur = {"s_mrows_per_s": s, "t_row_us": 1.0 / s, "R_s": R, "N_scaled_s": N * (S_REF / s), "F_fixed_s": F}
        for n in V.NAMED_RULES:
            cur[f"B_c_{n}_gbps"] = bc.get(n, ""); cur[f"status_{n}"] = status.get(n, "rule_construction_failed"); cur[f"lim_H_{n}_s"] = lim.get(n, "")
        for sid, members in sets.items():
            fin = {n: bc[n] for n in members if status[n] in ("finite", "beyond_scan")}
            cur[f"B_minus_{sid}_gbps"] = min(fin.values()) if fin else ""; cur[f"B_plus_{sid}_gbps"] = max(fin.values()) if fin else ""
            cur[f"B_minus_{sid}_rule"] = min(fin, key=fin.get) if fin else ""; cur[f"B_plus_{sid}_rule"] = max(fin, key=fin.get) if fin else ""
            cur[f"n_finite_{sid}"] = len(fin); cur[f"n_members_{sid}"] = len(members); cur[f"n_no_finite_{sid}"] = sum(1 for n in members if status[n] == "no_finite_boundary")

            def spread(B, members=members):
                Ts = [R + V.H_of(present[n], B, Ch) for n in members]
                return max(Ts) / min(Ts) - 1.0
            if spread(B_HI) > LEVEL:
                cur[f"B_spread20_{sid}_gbps"] = ""; cur[f"spread20_{sid}_status"] = "spread above 20% at B_HI (hub-limited terms differ)"
            elif spread(B_LO) < LEVEL:
                cur[f"B_spread20_{sid}_gbps"] = ""; cur[f"spread20_{sid}_status"] = "spread below 20% everywhere in range"
            else:
                cur[f"B_spread20_{sid}_gbps"] = bisect(lambda B: spread(B) - LEVEL, B_LO, B_HI); cur[f"spread20_{sid}_status"] = "solved"
            cur[f"spread_{sid}_at_B_HI"] = spread(B_HI); cur[f"spread_{sid}_at_B_LO"] = spread(B_LO)
        curves.append(cur)
        for B in b_axis():
            g = {"s_mrows_per_s": s, "B_mesh_gbps": B, "C_hub_gbps": Ch / 1e9, "R_s": R}
            Hs = {n: V.H_of(row, B, Ch) for n, row in present.items()}
            for n in V.NAMED_RULES:
                g[f"H_{n}_s"] = Hs.get(n, ""); g[f"T_{n}_s"] = (R + Hs[n]) if n in Hs else ""
            for sid, members in sets.items():
                Ts = {n: R + Hs[n] for n in members}
                nmin, nmax = min(Ts, key=Ts.get), max(Ts, key=Ts.get)
                Hmin, Hmax = min(Hs[n] for n in members), max(Hs[n] for n in members)
                g[f"T_min_{sid}_s"] = Ts[nmin]; g[f"T_max_{sid}_s"] = Ts[nmax]; g[f"spread_{sid}"] = Ts[nmax] / Ts[nmin] - 1.0
                g[f"T_min_{sid}_rule"] = nmin; g[f"T_max_{sid}_rule"] = nmax
                g[f"region_{sid}"] = "communication dominated (min_P H > R)" if Hmin > R else ("mapping-dependent dominance (min_P H <= R <= max_P H)" if Hmax >= R else "compute / fixed-cost dominated (max_P H < R)")
            grid.append(g)
    setup = {"config_id": rec["config_id"], "record": V.record_path(V.GEMMA_REF[0]), "protocol_id": V.protocol_id(rec),
             "candidate_set": {"seven_rules": {"members": list(present), "n": len(present), "failed": failed, "note": "'random' is the pool's random_s0, the seventh rule of the standing phase diagram"},
                               "named_rules": {"members": named5, "n": len(named5), "note": "the five constructible named rules (the band of the report: B- 1.7600, B+ 6.7868 GB/s at the reference rate)"}},
             "R_model": "R(s) = N s_ref / s + F; N = CIM compute of the static operators at the reference row rate (scales with the device rate), F = digital element-wise + unit attention compute + K/V memory time (held fixed across the rate scan)",
             "N_s": N, "F_s": F, "F_terms_per_layer_s": {k: v for k, v in lb.items()}, "n_layers": L, "s_ref_mrows_per_s": S_REF, "t_row_ref_us": 1e6 * an.T_MVM_S,
             "H_model": "H(B) = P + sum_j max(link_j / B, dieport_j / (kappa B), hub_j / C_hub) from the stored per-hand-off components; kappa = 2; C_hub = 12.5 GB/s per direction fixed; propagation 20 ns per hop",
             "axes": {"s_mrows_per_s": [S_LO, S_HI, NS, "log, plus s_ref"], "B_mesh_gbps": [B_LO, B_HI, NB, "log, plus 0.4, 12.5, B_eq 0.5215"]},
             "boundary_status": {"finite": "H(B_c) = R with B_c inside the scan", "beyond_scan": "finite B_c outside [B_LO, B_HI]", "no_finite_boundary": "lim_{B->inf} H = P + hub terms > R", "limit_equals_R": "lim H = R within 1e-9", "rule_construction_failed": "the rule has no legal layout on this grid"},
             "spread": "spread(s, B) = (T_max - T_min) / T_min over the declared set; the 20% contour is solved per s by bisection in B"}
    return grid, curves, setup, rec


# ------------------------------------------------------------ projections
def projections(intra_curves, pkg_curves):
    def region(curves, s, B, lo_key, hi_key):
        ss = np.array([c["s_mrows_per_s"] for c in curves])
        lo = np.array([c[lo_key] if c[lo_key] != "" else np.nan for c in curves], dtype=float)
        hi = np.array([c[hi_key] if c[hi_key] != "" else np.nan for c in curves], dtype=float)
        if s < ss[0] or s > ss[-1]:
            return "outside the rate range", "", ""
        bl, bh = float(np.exp(np.interp(np.log(s), np.log(ss), np.log(lo)))), float(np.exp(np.interp(np.log(s), np.log(ss), np.log(hi))))
        reg = "communication dominated" if B < bl else ("mapping-dependent dominance" if B <= bh else "compute / fixed-cost dominated")
        return reg, bl, bh
    pts = []

    def add(chip, panel, coord_kind, B, status, derivation, drawn, mode=""):
        s = (1.0 / chip.t_mvm_s / 1e6) if chip.t_mvm_s else ""
        row = {"chip_key": chip.key, "chip": chip.label, "paradigm": chip.paradigm, "mode": mode, "panel": panel, "coordinate_kind": coord_kind,
               "t_row_s": chip.t_mvm_s if chip.t_mvm_s else "", "t_row_status": chip.t_mvm_status, "t_row_derivation": chip.t_mvm_derivation, "s_mrows_per_s": s,
               "B_gbps": B, "B_status": status, "B_derivation": derivation, "source": chip.source, "fabric": chip.fabric, "drawn_in_standing_figure": drawn}
        if s != "" and B != "":
            for tag, curves, lo_k, hi_k in (("intra", intra_curves, "B_minus_gbps", "B_plus_gbps"), ("package_seven_rules", pkg_curves, "B_minus_seven_rules_gbps", "B_plus_seven_rules_gbps"), ("package_named_rules", pkg_curves, "B_minus_named_rules_gbps", "B_plus_named_rules_gbps")):
                reg, bl, bh = region(curves, s, B, lo_k, hi_k)
                row[f"region_{tag}"] = reg; row[f"B_minus_{tag}_at_s"] = bl; row[f"B_plus_{tag}_at_s"] = bh
        pts.append(row)
    neur = an.chip("neurram")
    for B in (0.4, 12.5):
        add(neur, "b", "evaluated bandwidth tier of this paper", B, "evaluated configuration (mesh per direction; die ports at kappa B; hub 12.5 GB/s)", "the reference device rate (NeuRRAM-class, 10.14 us per row) with the two evaluated mesh bandwidths", True)
    add(neur, "a", "evaluated bandwidth tier of this paper", 0.4, "evaluated configuration", "intra-die link rate of the evaluated instance", True)
    h = an.chip("hermes")
    for mode, t in (("1-phase", 133e-9), ("4-phase", 520e-9)):
        c = an.ChipPoint(**{**h.__dict__, "t_mvm_s": t, "t_mvm_derivation": h.t_mvm_derivation + (" (1-phase MVM, 133 ns)" if mode == "1-phase" else "; 4-phase mode 520 ns per row (the paper's 4-phase MVM operation)")})
        add(c, "a", "published per-physical-link rate", h.ondie_gbps_per_link, "published (spec table: max link data-rate 3.2 Gbit/s = 0.4 GB/s)", "per physical core-to-core link, no aggregation", True, mode)
    add(h, "a", "aggregated per-macro coordinate (alternative)", h.ondie_gbps, h.ondie_status, "(418 links / 64 cores) x 0.4 GB/s x 32 arrays", False, "1-phase")
    i = an.chip("isaac")
    add(i, "a", "published per-link rate (design point)", i.ondie_gbps_per_link, "design point: 32-bit link at 1 GHz (Sec. VIII-B)", "inter-tile c-mesh link", True)
    add(i, "b", "published off-chip link (design point)", i.d2d_gbps, i.d2d_status, "HyperTransport link, Table I, per link per direction", True)
    m = an.chip("mythic_m1076")
    add(m, "b", "I/O-matched projection", m.io_gbps / 2.0, m.io_status, "published 2 GB/s PCIe capability matched to the port capacity kappa B at kappa = 2 -> B = 1.0 GB/s (a model projection)", True)
    add(m, "b", "assumed on-die band (superseded)", "", "estimated band 0.4-8 GB/s (router width / clock not published)", "kept for the record; the standing figure uses the I/O-matched point", False)
    sb = an.chip("simba")
    add(sb, "b", "measured package link (max mode)", sb.d2d_gbps, sb.d2d_status, "GRS 25 Gb/s per pin x 4 lanes = 12.5 GB/s per direction (digital chip, not a device mark)", False)
    add(sb, "b", "measured package link (experiment mode)", 5.5, "measured operating point (MICRO'19 section 4.1: 11 Gb/s mode)", "4 lanes x 11 Gb/s = 5.5 GB/s per direction", False)
    add(sb, "a", "published per-physical-link rate", sb.ondie_gbps_per_link, "published (JSSC section II-C: 70 Gb/s per NoC link at 0.72 V)", "per physical NoC link", False)
    for key in ("mx100", "tsinghua_multichip"):
        c = an.chip(key)
        add(c, "b" if key == "tsinghua_multichip" else "a", "no rate coordinate", "", f"{c.ondie_status} / {c.d2d_status}", "device rate pending in the source registry; listed, not drawn", False)
    return pts


def main():
    os.makedirs(V.V7, exist_ok=True)
    print("intra-die enumeration ...", flush=True)
    irows, icurves, isetup = intra_die()
    print("package grid ...", flush=True)
    grid, pcurves, psetup, rec = package()
    pts = projections(icurves, pcurves)
    V.write_csv("intradie_phase_candidates.csv", irows)
    V.write_csv("intradie_phase_curves.csv", icurves)
    V.write_csv("phase_grid.csv", grid)
    V.write_csv("phase_boundary_curves.csv", pcurves)
    V.write_csv("phase_projection_points.csv", pts)
    V.write_json("phase_setup.json", {"intra_die": isetup, "package": psetup, "code_version": V.code_version()})
    ref = min(pcurves, key=lambda c: abs(c["s_mrows_per_s"] - S_REF))
    print("package at s_ref: named_rules B-/B+ = %.4f / %.4f (x%.3f); seven_rules B-/B+ = %.4f / %.4f; spread20 B = %s / %s" % (
        ref["B_minus_named_rules_gbps"], ref["B_plus_named_rules_gbps"], ref["B_plus_named_rules_gbps"] / ref["B_minus_named_rules_gbps"],
        ref["B_minus_seven_rules_gbps"], ref["B_plus_seven_rules_gbps"], ref["B_spread20_named_rules_gbps"], ref["B_spread20_seven_rules_gbps"]))
    iref = min(icurves, key=lambda c: abs(c["s_mrows_per_s"] - S_REF))
    print("intra at s_ref: B-/B+ = %.4f / %.4f, spread20 B = %s" % (iref["B_minus_gbps"], iref["B_plus_gbps"], iref["B_spread20_gbps"]))
    for p in pts:
        if p.get("s_mrows_per_s") != "" and p.get("B_gbps") != "":
            print(f"  {p['chip']:28s} {p['mode']:8s} panel {p['panel']} B {p['B_gbps']:>8.3g} s {p['s_mrows_per_s']:9.4g}  intra: {p.get('region_intra','')}; package: {p.get('region_package_seven_rules','')}")


if __name__ == "__main__":
    main()

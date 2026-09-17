"""S10 task B: the instance identity and work point of Fig. 1(a) (the
intra-die phase-diagram panel) against the A3 intra-die case of the text,
read from the code and the frozen artifacts; and how the local cost
enters the layer cost.

    python3 scripts/intra_die_correspondence.py -> analysis/intra_die_correspondence.json + .md
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import analyze_soft_lever as asl
from scripts import anchors as an
from scripts import fig_phase_isobar as fp
from scripts import llm_workload as lw
from scripts import search_eval as se
from scripts import search_withindie as sw

OUT = os.path.join(se.A, "intra_die_correspondence.json")
MD = os.path.join(se.A, "intra_die_correspondence.md")


def main():
    src = json.load(open(asl.SRC))
    cfg = lw.GptConfig()
    ii = json.load(open(os.path.join(se.A, "intra_die_integration.json")))
    a3 = ii["per_anchor"]["0.4"]
    pd = json.load(open(os.path.join(se.A, "phase_diagram_isobar_k2.json")))["within_die"]
    ops = {o.name: (o.P, o.C, o.M) for o in lw.block_ops(cfg, S=src["S"], phase="prefill") if hasattr(o, "P")}
    row_time = an.CYCLE_S * an.SLICES_PER_MVM
    # Fig. 1(a) constants (fig_phase_isobar.main): ffn die, 70 seatings
    fig = {"panel": "Fig. 1(a)", "instance": "A3 co-residency, ffn die", "model": f"{cfg.name}: d {cfg.d_model}, d_ff {cfg.d_ff}",
           "S": src["S"], "ops": {"ffn1": ops["ffn1"], "ffn2": ops["ffn2"]}, "macros": "8 slots, 2x4 macro mesh, glb centre",
           "placement_set": "all 70 joint seatings of ffn1 (4 slots) x ffn2 (4 slots), enumerated",
           "A_min_words": pd["a_min_words"], "A_max_words": pd["a_max_words"], "ratio": pd["ratio"],
           "R_model": "T = N/s + F + A/B: N = the ffn die's compute (10.383 ms at the NeuRRAM rate), F = 0.36 us (write + prop)",
           "device_row_time_s": row_time, "device_rate_Mrows_s": 1 / row_time / 1e6,
           "B_minus_gbps_at_ref": pd["B_minus_at_ref_gbps"], "B_plus_gbps_at_ref": pd["B_plus_at_ref_gbps"],
           "latency_object": "the ffn die's two co-resident operators (local sub-problem); the boundary criterion H vs R "
                             "is the max-model's masking switch: H < R <=> serialization hidden under compute"}
    # A3 text case: both dies + fixed rest + the chain's package hand-offs, at 0.4 GB/s
    scale = a3["scale"]
    dies = {}
    for die, J in ((d, sw.WithinDieJ(d, "prefill", sw.G_ACTIVE)) for d in sw.DIES):
        rec = {}
        for name, _k in sw.DIES[die]:
            r = J.recs[name]
            ser_ship = J.a3_ser(name, sw.SHIPPED[die][name]) * scale
            best_seat = {k: tuple(v) for k, v in a3["dies"][die]["best_seat"].items()}
            ser_best = J.a3_ser(name, best_seat[name]) * scale
            rec[name] = {"P_C_M": ops[name], "compute_s": r["compute_s"], "write_s": r["write_s"],
                         "ser_shipped_s": ser_ship, "ser_best_s": ser_best,
                         "exposed_shipped_s": max(0.0, ser_ship - r["compute_s"]),
                         "exposed_best_s": max(0.0, ser_best - r["compute_s"]),
                         "state_shipped": "serialization-bound" if ser_ship > r["compute_s"] else "compute-bound",
                         "state_best": "serialization-bound" if ser_best > r["compute_s"] else "compute-bound"}
        dies[die] = {"ops": rec, "shipped_seat": sw.SHIPPED[die], "best_seat": a3["dies"][die]["best_seat"],
                     "n_seatings": a3["dies"][die]["n_seatings"],
                     "C_shipped_s": a3["dies"][die]["shipped_s"], "C_best_s": a3["dies"][die]["best_s"]}
    text = {"instance": "A3 co-residency, attn die (qkv_proj 3 slots + out_proj 1) and ffn die (ffn1 4 + ffn2 4)",
            "model": fig["model"], "S": src["S"], "macros": fig["macros"],
            "placement_set": "attn 280 + ffn 70 joint seatings, enumerated (exhaustive optimum = ground truth)",
            "device_row_time_s": row_time, "B_gbps": 0.4, "scale_ref_wc_over_wc": scale,
            "local_state_at_0.4": ("below B- = %.3f GB/s: every seating has an exposed op (communication dominated)"
                                   % pd["B_minus_at_ref_gbps"] if 0.4 < pd["B_minus_at_ref_gbps"] else
                                   "inside the ffn die's band [%.3f, %.3f] GB/s" % (pd["B_minus_at_ref_gbps"], pd["B_plus_at_ref_gbps"])),
            "dies": dies,
            "fixed_rest_s": a3["fixed_rest_s"], "package_handoffs_s": a3["package_handoffs_per_layer_s_at_0.4"],
            "T_layer_shipped_s": a3["T_layer_shipped_incl_pkg_s"], "T_layer_best_s": a3["T_layer_best_incl_pkg_s"],
            "gain_pct": a3["beta_gain_incl_pkg_pct"], "gain_excl_pkg_pct": a3["beta_gain_pct"],
            "latency_object": "one layer = attn die + ffn die + fixed rest + its two one-flow package hand-offs; "
                              "layers identical, so the layer share is the stack share"}
    same = fig["model"] == text["model"] and fig["S"] == text["S"]
    out = {"note": __doc__.strip(), "fig_1a": fig, "text_A3": text,
           "same_instance": same,
           "relation": ("Fig. 1(a) is the ffn die of the A3 instance alone (70 seatings; the 2.67x is A_max/A_min of the "
                        "ffn ops' busiest macro-link words); the text's 9.02%% is the whole layer of the same instance "
                        "(both dies, fixed rest, package hand-offs). Local cost enters the layer as "
                        "write + prop + max(compute, serialization(beta) x scale) per op -- the max model -- so the "
                        "panel's H-vs-R boundaries are exactly the masking thresholds: above B+ every seating is "
                        "compute-bound (gain 0 at >= 2 GB/s, measured), below B- every seating is serialization-bound "
                        "(0.1, 0.2 GB/s), and 0.4 GB/s lies BELOW B- = %.3f GB/s: every one of the 70 seatings has an "
                        "exposed op there, and the seating decides how severe (the exhaustive best still has ffn1 "
                        "and ffn2 serialization-bound). The boundaries compare each op's serialization with ITS OWN "
                        "compute (5.19 ms), the max model's switch." % pd["B_minus_at_ref_gbps"])}
    json.dump(out, open(OUT, "w"), indent=1)
    L = ["# Fig. 1(a) vs the A3 intra-die case (S10 task B)", "",
         "| item | Fig. 1(a) | §4.3 A3 case |", "|---|---|---|",
         f"| model / d | {fig['model']} | same |",
         f"| co-resident operators (P, C, M at S = {src['S']}) | ffn1 {ops['ffn1']}, ffn2 {ops['ffn2']} | attn die: qkv_proj {ops['qkv_proj']}, out_proj {ops['out_proj']}; ffn die: ffn1, ffn2 |",
         f"| macros / geometry / legal set | 8 slots, 2×4 mesh, glb centre; 70 joint seatings (ffn1 4 + ffn2 4) | same geometry; attn 280 + ffn 70, enumerated |",
         f"| device row rate | {1/row_time/1e6:.4f} Mrows/s ({row_time*1e6:.2f} µs/row, NeuRRAM) | same |",
         f"| intra-die link bandwidth | the y axis; B₋ {pd['B_minus_at_ref_gbps']:.3f} / B₊ {pd['B_plus_at_ref_gbps']:.3f} GB/s at that rate (per-op masking thresholds) | 0.4 GB/s ({'below B₋: communication dominated' if 0.4 < pd['B_minus_at_ref_gbps'] else 'inside the band'}) |",
         f"| latency object | ffn die's local sub-problem; H vs R = masking switch of the max model | whole layer: attn + ffn dies + fixed rest ({a3['fixed_rest_s']*1e3:.2f} ms) + 2 package hand-offs ({a3['package_handoffs_per_layer_s_at_0.4']*1e3:.2f} ms) |",
         f"| envelope / gain | 2.67× = A_max {pd['a_max_words']/1e6:.3f}M / A_min {pd['a_min_words']/1e6:.3f}M words (busiest macro-link words over the 70 seatings) | {a3['beta_gain_incl_pkg_pct']:.2f}% = 1 − {a3['T_layer_best_incl_pkg_s']*1e3:.3f} / {a3['T_layer_shipped_incl_pkg_s']*1e3:.3f} ms (exhaustive best vs shipped contiguous, incl. package); {a3['beta_gain_pct']:.2f}% without the package term |",
         "", "## Per-op local state at 0.4 GB/s (A3), shipped → exhaustive best", "",
         "| die | op | compute (ms) | serialization shipped (ms) | serialization best (ms) | exposed shipped → best (ms) | state shipped → best |", "|---|---|---:|---:|---:|---|---|"]
    for die, dv in dies.items():
        for name, r in dv["ops"].items():
            L.append(f"| {die} | {name} | {r['compute_s']*1e3:.3f} | {r['ser_shipped_s']*1e3:.3f} | {r['ser_best_s']*1e3:.3f} | "
                     f"{r['exposed_shipped_s']*1e3:.3f} → {r['exposed_best_s']*1e3:.3f} | {r['state_shipped']} → {r['state_best']} |")
    L += ["", out["relation"], ""]
    open(MD, "w").write("\n".join(L) + "\n")
    print("same instance:", same)
    for die, dv in dies.items():
        for name, r in dv["ops"].items():
            print(f"  {die:4} {name:9} compute {r['compute_s']*1e3:6.3f} ser ship {r['ser_shipped_s']*1e3:6.3f} best {r['ser_best_s']*1e3:6.3f} ms | {r['state_shipped']} -> {r['state_best']}")
    print(f"  layer: fixed {a3['fixed_rest_s']*1e3:.2f} + pkg {a3['package_handoffs_per_layer_s_at_0.4']*1e3:.2f} ms; T ship {a3['T_layer_shipped_incl_pkg_s']*1e3:.3f} -> best {a3['T_layer_best_incl_pkg_s']*1e3:.3f} ms = {a3['beta_gain_incl_pkg_pct']:.2f}%")
    print(f"-> {OUT}\n-> {MD}")


if __name__ == "__main__":
    main()

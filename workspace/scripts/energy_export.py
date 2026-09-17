"""S10 section 6: dynamic energy of the frozen layouts, from the existing
model, exported by term with the counting rule and coefficients stated.

Package level (main configuration; energy is independent of B and kappa):
  E = n_layers x sum_ops E_op (per-op CiMLoop record: array compute and
      writes) + n_layers x E_elementwise (glb + arithmetic, digital unit)
    + E_d2d, with E_d2d = sum over flows of payload words x max(hops, 1) x
      10 pJ/word -- implemented as a flat 1-hop charge on every delivered
      word plus the surplus max(hops - 1, 0) (die_flow_surplus_energy);
      hops = XY route length on the die mesh; 10 pJ/word = the midpoint
      of Simba's measured GRS band (0.82-1.75 pJ/bit, Zimmer et al. JSSC
      2020). Static power is not modelled (fabric idle_power_w = None).
Intra-die level (A3): the macro link carries no pJ/word and the 355M-class
per-op records carry no energy, so no seating-dependent energy exists at
that level in the current model -- reported as 'not modelled', not zero.

    python3 scripts/energy_export.py -> analysis/energy_export.json + .md
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import kappa_geometry_sweep as kg
from scripts import llm_workload as lw
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_space as ss

OUT = os.path.join(se.A, "energy_export.json")
MD = os.path.join(se.A, "energy_export.md")
KAPPA, BW = 2.0, 0.4
LAYOUTS = ("default_A4", "sequential", "snake", "clustered", "nmap_greedy", "least_manhattan",
           "heaviest_first", "random", "random_s1", "random_s2", "random_s3", "random_s4")


def flows_all(W, pi):
    base = lw.block_chain(W.cfg, W.S, "prefill", on_chip=True,
                          max_dies=W.fab.level("die").per_parent)
    chain, seating = [], {}
    for li in range(W.cfg.n_layers):
        for e in base:
            n = f"{e['name']}@L{li}"
            chain.append({**e, "name": n})
            seating[n] = list(pi.seat[n])
    fb = lw.block_die_flows(chain, seating, W.fab)
    return [f for e in chain[1:] for f in fb[e["name"]]]


def main():
    W = kg.workload((24, 24))
    W.port_ratio = KAPPA
    sweep = json.load(open(os.path.join(se.A, "kappa_geometry_sweep.json")))
    cell = sweep["cells"]["24x24/k2"]
    cands = {"default_A4": ss.pi_from_a4_payload()}
    for n in LAYOUTS[1:]:
        cands[n] = sb.generate("random", W, seed=int(n.split("_s")[1])) if n.startswith("random_s") \
            else sb.generate(n, W, seed=0)
    for k, v in cell["runs"].items():
        cands[k] = ss.Pi.from_json(v["best_pi"])
    lk = W.fab.level("die").link
    pj, ref = lk.pj_per_word, lk.reference_hops
    E_layer_ops = W.n_layers() * sum(r["energy_J"] for r in W.ops["prefill"].values())
    E_elw = W.n_layers() * sum(lw.elementwise_cost(eo, W.fab.digital)["energy_J"]
                               for eo in lw.block_elementwise_ops(W.cfg, S=W.S, phase="prefill"))
    E_ops_total = W.n_layers() * W.layer_energy_J("prefill")
    assert abs(E_ops_total - (E_layer_ops + E_elw)) < 1e-9 * E_ops_total
    rows = {}
    for n, pi in cands.items():
        sc = se.score(pi, W, caliber="single", d2d_gbps=BW)
        d = sc.per_phase["prefill"]["decomp"]
        fl = flows_all(W, pi)
        m = W.die_ic
        words = sum(f["volume"] * f["width"] for f in fl)
        wh_energy = sum(f["volume"] * f["width"] * max(m.energy_hops(*f["nodes"]), 1.0) for f in fl)
        wh_route = sum(f["volume"] * f["width"] * m.hops(*f["nodes"]) for f in fl)
        e_comm_check = wh_energy * pj * 1e-12
        rows[n] = {"T_s": sc.t_opt_s, "E_total_J": sc.e_J,
                   "E_ops_J": E_layer_ops, "E_elementwise_J": E_elw,
                   "E_d2d_flat_J": d["d2d_flat_J"], "E_d2d_surplus_J": d["d2d_surplus_J"],
                   "E_comm_J": d["d2d_flat_J"] + d["d2d_surplus_J"],
                   "comm_share": (d["d2d_flat_J"] + d["d2d_surplus_J"]) / sc.e_J,
                   "payload_words": words, "word_hops_energy": wh_energy, "word_hops_route": wh_route,
                   "mean_hops": wh_route / words,
                   "E_comm_check_J": e_comm_check,
                   "check_gap_rel": abs(e_comm_check - d["d2d_flat_J"] - d["d2d_surplus_J"]) / (d["d2d_flat_J"] + d["d2d_surplus_J"])}
    ref_name = "random_s3"
    ends = [n for n in cands if n.startswith("sa_")]
    for n in rows:
        rows[n]["dT_vs_ref_pct"] = (1 - rows[n]["T_s"] / rows[ref_name]["T_s"]) * 100
        rows[n]["dE_vs_ref_pct"] = (1 - rows[n]["E_total_J"] / rows[ref_name]["E_total_J"]) * 100
        rows[n]["dEcomm_vs_ref_pct"] = (1 - rows[n]["E_comm_J"] / rows[ref_name]["E_comm_J"]) * 100
    e_best = min(rows, key=lambda n: rows[n]["E_total_J"])
    out = {"note": __doc__.strip(), "kappa": KAPPA, "bw_gbps": BW,
           "coefficients": {"pj_per_word": pj, "reference_hops": ref,
                            "source": "Simba GRS measured band 0.82-1.75 pJ/bit midpoint (Zimmer et al., JSSC 2020); 8-bit words",
                            "counting": "payload words delivered per flow (every consumer die counted) x max(XY route hops, 1)",
                            "hops": "XY route length on the die mesh (interconnect.energy_hops)",
                            "static_power": "not modelled (Level.idle_power_w = None)"},
           "seat_invariant_terms_J": {"E_ops": E_layer_ops, "E_elementwise": E_elw,
                                      "E_d2d_flat": rows[ref_name]["E_d2d_flat_J"]},
           "reference": ref_name, "E_best_layout": e_best, "rows": rows,
           "endpoints_dE_vs_ref_pct": {n: rows[n]["dE_vs_ref_pct"] for n in ends},
           "intra_die": {"status": "not modelled",
                         "why": "macro link pj_per_word = None (calibration DR-4 covers latency only); the 355M-class per-op records carry no energy; A3's cost model is latency-only, so no seating-dependent intra-die energy exists in the current model",
                         "what_would_be_needed": "a pJ/word (or CiMLoop router-component energy) on the glb<->macro link and a per-op energy record for the d=1024 instance"}}
    json.dump(out, open(OUT, "w"), indent=1)
    L = ["# Dynamic energy of the frozen layouts (S10 section 6)", "",
         f"Main configuration: 2.7B, S = 512 prefill, 544/576 dies on 24×24, XY; κ = {KAPPA:g}, {BW} GB/s (energy is independent of B and κ). "
         f"E = E_ops + E_elementwise + E_d2d; E_d2d = payload words × max(hops, 1) × {pj:g} pJ/word (flat 1-hop charge + surplus beyond {ref:g} hop); "
         "hops = XY route length; coefficient = midpoint of Simba's measured GRS band (0.82–1.75 pJ/bit). Static power not modelled. "
         f"Seat-invariant terms: E_ops {E_layer_ops:.3f} J, E_elementwise {E_elw:.4f} J, E_d2d flat {rows[ref_name]['E_d2d_flat_J']:.4f} J.", "",
         "| layout | T (ms) | E total (J) | E comm (J) | comm share | payload words (M) | word-hops (G) | mean hops | ΔT vs random_s3 | ΔE vs random_s3 | ΔE_comm vs random_s3 |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for n in cands:
        r = rows[n]
        L.append(f"| {n} | {r['T_s']*1e3:.1f} | {r['E_total_J']:.4f} | {r['E_comm_J']:.4f} | {r['comm_share']*100:.2f}% | "
                 f"{r['payload_words']/1e6:.1f} | {r['word_hops_route']/1e9:.2f} | {r['mean_hops']:.2f} | {r['dT_vs_ref_pct']:+.2f}% | "
                 f"{r['dE_vs_ref_pct']:+.2f}% | {r['dEcomm_vs_ref_pct']:+.2f}% |")
    L += ["", f"Check: E_comm recomputed from words × max(hops,1) × pJ matches the evaluator to {max(r['check_gap_rel'] for r in rows.values()):.1e} (relative).",
          f"E-best layout in this set: {e_best} ({rows[e_best]['E_total_J']:.4f} J, ΔT {rows[e_best]['dT_vs_ref_pct']:+.2f}%).", "",
          "**Intra-die (A3): not modelled** — the macro link carries no pJ/word (calibration DR-4 is latency-only) and the 355M-class per-op records carry no energy; "
          "the A3 seating changes latency only. A layer dynamic-energy change for the 9.02% latency gain cannot be reported from the current model; "
          "it would need a glb↔macro link energy coefficient and a per-op energy record for the d = 1024 instance."]
    open(MD, "w").write("\n".join(L) + "\n")
    print(f"seat-invariant: E_ops {E_layer_ops:.3f} J, E_elw {E_elw:.4f} J, E_d2d_flat {rows[ref_name]['E_d2d_flat_J']:.4f} J")
    for n in cands:
        r = rows[n]
        print(f"{n:16} T {r['T_s']*1e3:7.1f} E {r['E_total_J']:.4f} J comm {r['E_comm_J']:.4f} ({r['comm_share']*100:5.2f}%) wh {r['word_hops_route']/1e9:5.2f}G hops {r['mean_hops']:5.2f} | dT {r['dT_vs_ref_pct']:+6.2f}% dE {r['dE_vs_ref_pct']:+6.2f}% dEcomm {r['dEcomm_vs_ref_pct']:+6.2f}%")
    print(f"E-best: {e_best}; check gap {max(r['check_gap_rel'] for r in rows.values()):.1e}")
    print(f"-> {OUT}\n-> {MD}")


if __name__ == "__main__":
    main()

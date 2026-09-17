"""S9 task A: the paper's main configuration, frozen, and every layout
re-scored on it -- one table, one JSON, every number with its
denominator. See FIXLIST S9.

    python3 scripts/main_config_export.py -> analysis/main_config_results.json + .md
"""
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import kappa_geometry_sweep as kg
from scripts import llm_workload as lw
from scripts import search_baselines as sb
from scripts import search_eval as se
from scripts import search_space as ss

OUT = os.path.join(se.A, "main_config_results.json")
MD = os.path.join(se.A, "main_config_results.md")
KAPPA, GRID = 2.0, (24, 24)
BWS = (0.4, 12.5)
PHASES = ("prefill", "decode")
STARTS, SEEDS = ("clustered", "random", "snake"), (0, 1, 2)


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
    d = (sum((x - ma) ** 2 for x in ra) ** 0.5) * (sum((y - mb) ** 2 for y in rb) ** 0.5)
    return sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / d if d else float("nan")


def flows_by_boundary(W, pi, phase):
    base = lw.block_chain(W.cfg, W.S, phase, on_chip=True,
                          max_dies=W.fab.level("die").per_parent)
    chain, seating = [], {}
    for li in range(W.cfg.n_layers):
        for e in base:
            n = f"{e['name']}@L{li}"
            chain.append({**e, "name": n})
            seating[n] = list(pi.seat[n])
    fb = lw.block_die_flows(chain, seating, W.fab)
    return [fb[e["name"]] for e in chain[1:]], base


def loads(W, pi, phase, kappa):
    fls, base = flows_by_boundary(W, pi, phase)
    a = wire = floor = 0.0
    for fl in fls:
        a += se.busiest_link_words(fl, W.die_ic, kappa=kappa)
        wire += se.busiest_link_words(fl, W.die_ic, ports=False)
        inj, ej = {}, {}
        for f in fl:
            w = f["volume"] * f["width"]
            inj[f["nodes"][0]] = inj.get(f["nodes"][0], 0.0) + w
            ej[f["nodes"][1]] = ej.get(f["nodes"][1], 0.0) + w
        floor += max(max(inj.values()), max(ej.values())) / kappa
    return a, wire, floor, base


def main():
    W = kg.workload(GRID)
    W.port_ratio = KAPPA
    sweep = json.load(open(os.path.join(se.A, "kappa_geometry_sweep.json")))
    cell = sweep["cells"][f"{GRID[0]}x{GRID[1]}/k{KAPPA:g}"]
    cands = {"default_A4": ss.pi_from_a4_payload()}
    cands.update({n: sb.generate(n, W, seed=0) for n in kg.RULES})
    for s in (1, 2, 3, 4):
        cands[f"random_s{s}"] = sb.generate("random", W, seed=s)
    for k, v in cell["runs"].items():
        cands[k] = ss.Pi.from_json(v["best_pi"])
    baselines = [n for n in cands if not n.startswith("sa_")]
    ends = [n for n in cands if n.startswith("sa_")]

    # ---- config identity and real inputs
    comp, wr, elw = W.layer_terms_s("prefill")
    dcomp, dwr, delw = W.layer_terms_s("decode")
    base_chain = lw.block_chain(W.cfg, W.S, "prefill", on_chip=True, max_dies=576)
    lk = W.fab.level("die").link
    dev = W.fab.device
    config = {
        "workload": {"model": W.cfg.name, "d_model": W.cfg.d_model, "d_ff": W.cfg.d_ff,
                     "n_heads": W.cfg.n_heads, "n_layers": W.cfg.n_layers,
                     "batch": 1, "prefill_tokens_S": W.S,
                     "decode": "one new token attending over the S-token KV cache (P = 1)",
                     "weights": "resident (all layers on the package)"},
        "mapping": {e["name"]: {"n_dies": e["n_dies"], "split": e["split"]} for e in base_chain},
        "dies_occupied": sum(e["n_dies"] for e in base_chain) * W.cfg.n_layers,
        "slots": W.fab.level("die").per_parent, "geometry": f"{GRID[0]}x{GRID[1]} mesh",
        "routing": lk.params.get("routing"), "hub": lk.params.get("hub"),
        "link_bandwidth_gbps_per_direction": list(BWS),
        "kappa": KAPPA, "terminal_capacity": "injection and ejection each kappa x B, independent",
        "execution": "serial prefill, batch 1; hand-offs one boundary at a time (159 boundaries)",
        "objective": "whole-model latency T_single at 0.4 GB/s",
        "device": {"name": dev.name, "cycle_s": dev.cycle_seconds,
                   "input_slices_per_mvm": dev.input_slices_per_mvm,
                   "row_time_s": dev.cycle_seconds * dev.input_slices_per_mvm},
        "per_layer_terms_s": {"prefill": {"compute": comp, "write": wr, "elementwise": elw},
                              "decode": {"compute": dcomp, "write": dwr, "elementwise": delw}},
        "d2d_link": {"ns_per_hop": lk.ns_per_hop, "pj_per_word": lk.pj_per_word,
                     "word_bytes": 1, "packet": "not modelled analytically (packet-free weave)"},
        "search_protocol": {"objective": "T_single, 0.4 GB/s, kappa 2", "starts": list(STARTS),
                            "sa_seeds": list(SEEDS), "steps": 1200, "alpha": 0.996,
                            "t0_s": cell["t0_s"], "temperature_rule": "declared 20 ms "
                            "(search_linkage.SEATING_SCHED[0.4]); NOT span/20",
                            "wall_s_per_run": cell["wall_s"] / 9,
                            "incremental_step_ms_median": 1.34, "full_score_ms_median": 37.0},
        "headline_statistic": "median over the three SA seeds of (best over the three start "
                              "families); min/max beside it; best-of-nine labelled separately"}

    rows = {}
    for n, pi in cands.items():
        rows[n] = {"kind": "default" if n == "default_A4" else
                   ("rule" if n in kg.RULES else ("random" if n.startswith("random_s") else "endpoint"))}
        for ph in PHASES:
            a, wire, floor, _ = loads(W, pi, ph, KAPPA)
            rows[n][ph] = {"A_words": a, "wire_only_words": wire, "floor_words": floor,
                           "A_over_floor": a / floor,
                           "binding": kg.binding(a, wire, floor)}
            for bw in BWS:
                sc = se.score(pi, W, mu={ph: 1.0}, caliber="single", d2d_gbps=bw)
                d = sc.per_phase[ph]["decomp"]
                rows[n][ph][str(bw)] = {"T_s": sc.t_opt_s, "layers_s": d["layers_s"],
                                        "propagation_s": d["propagation_s"],
                                        "H_s": d["d2d_serial_s"], "words": d["d2d_words"],
                                        "comm_share": d["d2d_serial_s"] / sc.t_opt_s,
                                        "E_J": sc.e_J,
                                        "E_d2d_flat_J": d["d2d_flat_J"], "E_d2d_surplus_J": d["d2d_surplus_J"],
                                        "E_comm_J": d["d2d_flat_J"] + d["d2d_surplus_J"],
                                        "E_comm_share": (d["d2d_flat_J"] + d["d2d_surplus_J"]) / sc.e_J}
    out = {"note": __doc__.strip(), "config": config, "rows": rows, "stats": {}}

    for ph in PHASES:
        out["stats"][ph] = {}
        for bw in BWS:
            T = {n: rows[n][ph][str(bw)]["T_s"] for n in cands}
            strongest = min(baselines, key=lambda n: T[n])
            per_seed = {}
            for s in SEEDS:
                best_start = min(STARTS, key=lambda st: T[f"sa_{st}_s{s}"])
                per_seed[s] = {"start": best_start, "name": f"sa_{best_start}_s{s}",
                               "T_s": T[f"sa_{best_start}_s{s}"]}
            vals = [v["T_s"] for v in per_seed.values()]
            med = statistics.median(vals)
            best9 = min(ends, key=lambda n: T[n])
            sel = min(per_seed.values(), key=lambda v: abs(v["T_s"] - med))["name"]
            out["stats"][ph][str(bw)] = {
                "strongest_baseline": strongest, "T_strongest_s": T[strongest],
                "default_T_s": T["default_A4"],
                "per_seed_best_over_starts": per_seed,
                "headline_T_median_s": med, "headline_selected": sel,
                "T_min_s": min(vals), "T_max_s": max(vals),
                "G_headline_pct": (1 - med / T[strongest]) * 100,
                "G_min_pct": (1 - max(vals) / T[strongest]) * 100,
                "G_max_pct": (1 - min(vals) / T[strongest]) * 100,
                "G_best_of_nine_pct": (1 - T[best9] / T[strongest]) * 100,
                "best_of_nine": best9,
                "G_vs_default_pct": (1 - med / T["default_A4"]) * 100,
                "endpoint_spread_pct": (max(T[n] for n in ends) / min(T[n] for n in ends) - 1) * 100,
                "comm_share_strongest": rows[strongest][ph][str(bw)]["comm_share"],
                "comm_share_selected": rows[sel][ph][str(bw)]["comm_share"]}
    # ---- S10 / A1: the random sample's own statistics, and a ledger of every
    # paper percentage with its layout ids, numerator, denominator, statistic
    out["random_baseline_stats"] = {}
    rnd = ["random"] + [f"random_s{s}" for s in (1, 2, 3, 4)]
    for ph in PHASES:
        out["random_baseline_stats"][ph] = {}
        for bw in BWS:
            Ts = {n: rows[n][ph][str(bw)]["T_s"] for n in rnd}
            vals = sorted(Ts.values())
            out["random_baseline_stats"][ph][str(bw)] = {
                "n": len(rnd), "seeds": [0, 1, 2, 3, 4], "T_s": Ts,
                "median_s": statistics.median(vals), "min_s": vals[0], "max_s": vals[-1],
                "min_seed": min(Ts, key=Ts.get), "max_seed": max(Ts, key=Ts.get),
                "spread_pct": (vals[-1] / vals[0] - 1) * 100,
                "named_rules_T_s": {n: rows[n][ph][str(bw)]["T_s"] for n in kg.RULES if n != "random"}}
    led = []
    def entry(name, num_layout, num_s, den_layout, den_s, stat):
        led.append({"quantity": name, "numerator_layout": num_layout, "numerator_T_s": num_s,
                    "denominator_layout": den_layout, "denominator_T_s": den_s,
                    "value_pct": (1 - num_s / den_s) * 100, "statistic": stat})
    for ph in PHASES:
        for bw in BWS:
            st = out["stats"][ph][str(bw)]
            entry(f"G headline, {ph}, {bw} GB/s", st["headline_selected"], st["headline_T_median_s"],
                  st["strongest_baseline"], st["T_strongest_s"],
                  "median over 3 SA seeds of best-over-3-starts (the median seed's layout)")
            entry(f"G best-of-nine, {ph}, {bw} GB/s", st["best_of_nine"], rows[st["best_of_nine"]][ph][str(bw)]["T_s"],
                  st["strongest_baseline"], st["T_strongest_s"], "min over 9 runs (labelled apart)")
            entry(f"G vs default fill, {ph}, {bw} GB/s", st["headline_selected"], st["headline_T_median_s"],
                  "default_A4", st["default_T_s"], "same selected layout as the headline")
    for ph in PHASES:
        st = out["stats"][ph]["0.4"]
        sel, ref = st["headline_selected"], st["strongest_baseline"]
        led.append({"quantity": f"dE dynamic energy, {ph}, headline layout vs strongest baseline",
                    "numerator_layout": sel, "numerator_E_J": rows[sel][ph]["0.4"]["E_J"],
                    "denominator_layout": ref, "denominator_E_J": rows[ref][ph]["0.4"]["E_J"],
                    "value_pct": (1 - rows[sel][ph]["0.4"]["E_J"] / rows[ref][ph]["0.4"]["E_J"]) * 100,
                    "statistic": "same layouts as the headline G; energy is B- and kappa-independent"})
    out["ledger"] = led
    # ranking prefill vs decode (0.4)
    names = list(cands)
    out["stats"]["rank_prefill_vs_decode_0.4"] = spearman(
        [rows[n]["prefill"]["0.4"]["T_s"] for n in names],
        [rows[n]["decode"]["0.4"]["T_s"] for n in names])
    out["stats"]["selected_prefill_rank_in_decode_0.4"] = sorted(
        names, key=lambda n: rows[n]["decode"]["0.4"]["T_s"]).index(
        out["stats"]["prefill"]["0.4"]["headline_selected"]) + 1
    # sensitivity from S8-A (same protocol), labelled
    out["sensitivity_S8A"] = {k: {bw: {"gain_vs_strongest_pct": v["per_bw"][bw]["gain_vs_strongest_pct"],
                                       "strongest": v["per_bw"][bw]["strongest_baseline"],
                                       "endpoint_binding": v["per_bw"][bw]["endpoint_binding"]}
                                  for bw in ("0.4", "12.5")}
                             for k, v in sweep["cells"].items()}
    json.dump(out, open(OUT, "w"), indent=1)

    # ---- markdown table
    L = ["# Main configuration results (S9 task A)", "",
         f"2.7B-class ({W.cfg.d_model} / {W.cfg.d_ff} / {W.cfg.n_layers} layers), batch 1, S = {W.S}; "
         f"{config['dies_occupied']} of {config['slots']} dies on a {config['geometry']}, XY; "
         f"NeuRRAM-derived row time {config['device']['row_time_s']*1e6:.2f} µs; "
         f"κ = {KAPPA:g} (injection and ejection each κ·B, independent); serial prefill. "
         f"Search: {len(STARTS)} starts × {len(SEEDS)} seeds, 1200 steps, α 0.996, t₀ = {cell['t0_s']*1e3:.0f} ms, "
         f"objective T_single at 0.4 GB/s, {cell['wall_s']/9:.1f} s per run.", "",
         "| layout | kind | T prefill 0.4 (ms) | H 0.4 (ms) | comm share (T) | A (M words) | A/floor | binding | T prefill 12.5 (ms) | T decode 0.4 (ms) | E dynamic (J) | E comm (J) | comm share (E) |",
         "|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|"]
    for n in sorted(cands, key=lambda n: rows[n]["prefill"]["0.4"]["T_s"]):
        r = rows[n]
        p4 = r["prefill"]["0.4"]
        L.append(f"| {n} | {r['kind']} | {p4['T_s']*1e3:.2f} | {p4['H_s']*1e3:.2f} | {p4['comm_share']*100:.1f}% | "
                 f"{r['prefill']['A_words']/1e6:.1f} | {r['prefill']['A_over_floor']:.3f} | {r['prefill']['binding']} | "
                 f"{r['prefill']['12.5']['T_s']*1e3:.2f} | {r['decode']['0.4']['T_s']*1e3:.3f} | "
                 f"{p4['E_J']:.4f} | {p4['E_comm_J']:.4f} | {p4['E_comm_share']*100:.2f}% |")
    L += ["", "## Headline statistics", "",
          "| phase | B (GB/s) | strongest baseline | T_strongest (ms) | headline T (median of 3 seeds, ms) | G headline | G range (seeds) | G best-of-9 | G vs default fill | comm share (strongest → selected) |",
          "|---|---:|---|---:|---:|---:|---|---:|---:|---|"]
    for ph in PHASES:
        for bw in BWS:
            st = out["stats"][ph][str(bw)]
            L.append(f"| {ph} | {bw} | {st['strongest_baseline']} | {st['T_strongest_s']*1e3:.2f} | "
                     f"{st['headline_T_median_s']*1e3:.2f} ({st['headline_selected']}) | **{st['G_headline_pct']:.2f}%** | "
                     f"{st['G_min_pct']:.2f}–{st['G_max_pct']:.2f}% | {st['G_best_of_nine_pct']:.2f}% ({st['best_of_nine']}) | "
                     f"{st['G_vs_default_pct']:.1f}% | {st['comm_share_strongest']*100:.1f}% → {st['comm_share_selected']*100:.1f}% |")
    L += ["", "## Random sample and search statistics (task A1)", "",
          "| phase | B | random seeds (n=5) T (ms) | median | min (seed) | max (seed) | spread | search per-seed best-over-starts (ms) | median | range |",
          "|---|---:|---|---:|---|---|---:|---|---:|---|"]
    for ph in PHASES:
        for bw in BWS:
            rb = out["random_baseline_stats"][ph][str(bw)]
            st = out["stats"][ph][str(bw)]
            ps = st["per_seed_best_over_starts"]
            L.append(f"| {ph} | {bw} | " + ", ".join(f"{rb['T_s'][n]*1e3:.2f}" for n in rnd) +
                     f" | {rb['median_s']*1e3:.2f} | {rb['min_s']*1e3:.2f} ({rb['min_seed']}) | {rb['max_s']*1e3:.2f} ({rb['max_seed']}) | {rb['spread_pct']:.2f}% | " +
                     ", ".join(f"{v['T_s']*1e3:.2f} ({v['name']})" for v in ps.values()) +
                     f" | {st['headline_T_median_s']*1e3:.2f} | {st['T_min_s']*1e3:.2f}–{st['T_max_s']*1e3:.2f} |")
    L += ["", "## Ledger: every paper percentage from absolute values (task A1)", "",
          "| quantity | numerator layout (ms) | denominator layout (ms) | value | statistic |", "|---|---|---|---:|---|"]
    for e in led:
        if "numerator_T_s" in e:
            L.append(f"| {e['quantity']} | {e['numerator_layout']} ({e['numerator_T_s']*1e3:.2f}) | {e['denominator_layout']} ({e['denominator_T_s']*1e3:.2f}) | {e['value_pct']:.2f}% | {e['statistic']} |")
        else:
            L.append(f"| {e['quantity']} | {e['numerator_layout']} ({e['numerator_E_J']:.4f} J) | {e['denominator_layout']} ({e['denominator_E_J']:.4f} J) | {e['value_pct']:+.2f}% | {e['statistic']} |")
    L += ["", f"Ranking prefill vs decode at 0.4 GB/s (Spearman over {len(names)} layouts): "
          f"{out['stats']['rank_prefill_vs_decode_0.4']:.3f}; the prefill-selected layout ranks "
          f"#{out['stats']['selected_prefill_rank_in_decode_0.4']} in decode.", "",
          "## Sensitivity (S8-A, same protocol; gain vs the strongest baseline of that cell)", "",
          "| cell | 0.4 GB/s | 12.5 GB/s | endpoint binding |", "|---|---:|---:|---|"]
    for k, v in out["sensitivity_S8A"].items():
        L.append(f"| {k} | {v['0.4']['gain_vs_strongest_pct']:.2f}% | {v['12.5']['gain_vs_strongest_pct']:.2f}% | {v['0.4']['endpoint_binding']} |")
    open(MD, "w").write("\n".join(L) + "\n")
    for ph in PHASES:
        for bw in BWS:
            st = out["stats"][ph][str(bw)]
            print(f"[{ph} {bw}] strongest {st['strongest_baseline']} {st['T_strongest_s']*1e3:.2f} ms | headline "
                  f"median {st['headline_T_median_s']*1e3:.2f} ms ({st['headline_selected']}) G {st['G_headline_pct']:.2f}% "
                  f"[{st['G_min_pct']:.2f}..{st['G_max_pct']:.2f}] best-of-9 {st['G_best_of_nine_pct']:.2f}% | vs default "
                  f"{st['G_vs_default_pct']:.1f}% | comm share {st['comm_share_strongest']*100:.1f}% -> {st['comm_share_selected']*100:.1f}%")
    print(f"rank prefill vs decode (0.4): {out['stats']['rank_prefill_vs_decode_0.4']:.3f}; selected prefill layout "
          f"is #{out['stats']['selected_prefill_rank_in_decode_0.4']} in decode")
    print(f"-> {OUT}\n-> {MD}")


if __name__ == "__main__":
    main()

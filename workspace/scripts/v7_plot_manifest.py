"""The per-figure data index (Isobar_next_tasks section 2.1): one row per
(panel, dataset role) with the actual path, the source record, the config /
protocol / candidate-set ids, the status and the next action; plus the data
dictionary of every delivered file (rows, columns, primary key).

    python3 scripts/v7_plot_manifest.py -> analysis/v7/plot_data_manifest.csv, plot_data_dictionary.md
"""
import csv
import json
import os
import sys

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WS)
from scripts import v7_common as V                      # noqa: E402

GEMMA = "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1"
P500 = "pool500_seeds5-14_objh_norm"; P100 = "pool100_seeds0-4_objt_norm"
E9C = "analysis/v4/e9_confirm/configs.jsonl"; E9R = "analysis/v4/e9_ref/configs.jsonl"
NINE = "opt6.7b|gemma7b|opt13b x {ref K1 (e9_confirm), m16 K1 (e10_confirm_cap), K4TH (e10_confirm)}"

ROWS = [
    # figure, panel, role, path, source, config, protocol, candidate set, status, missing, next action, key
    ("Fig1", "a", "intra-die enumeration: 70 joint seatings, per-op serialization words, compute, fixed terms", "analysis/v7/intradie_phase_candidates.csv", "scripts/search_withindie.py WithinDieJ('ffn','prefill').exhaustive() on the reference 2.7B ffn die account", "ffn die, 2x4 macro mesh, ffn1+ffn2, prefill 512", "exhaustive (no search)", "all 70 legal joint seatings", "ready", "", "", "seating_id"),
    ("Fig1", "a", "intra-die boundary and 20% spread curves over the row-rate axis", "analysis/v7/intradie_phase_curves.csv", "same enumeration; per-op masking model", "same", "exhaustive", "all 70 seatings", "ready", "", "", "s_mrows_per_s"),
    ("Fig1", "b", "package grid: R, per-rule H and T, T_min/T_max, spread, region over device rate x mesh bandwidth", "analysis/v7/phase_grid.csv", E9C, GEMMA, P500, "seven_rules (6 constructible + clustered failed) and named_rules (5)", "ready", "", "", "(s_mrows_per_s, B_mesh_gbps)"),
    ("Fig1", "b", "package boundaries: per-rule B_c with status, B-/B+, lim H, R, 20% spread contour per rate", "analysis/v7/phase_boundary_curves.csv", E9C, GEMMA, P500, "seven_rules / named_rules", "ready", "", "", "s_mrows_per_s"),
    ("Fig1", "a+b", "hardware projection points: published parameters, derivations, coordinates and regions under both panels", "analysis/v7/phase_projection_points.csv", "scripts/anchors.py CHIPS / ANCHORS registry (sources inside)", "", "", "", "ready", "MX100 and the Tsinghua multi-chip have no published rate (listed, not drawn)", "", "(chip_key, panel, coordinate_kind, mode)"),
    ("Fig1", "a+b", "setup: models of both panels, axes, status definitions", "analysis/v7/phase_setup.json", "", GEMMA, P500, "", "ready", "", "", ""),
    ("Fig1", "b", "supporting: rule-wise boundary candidates and status of every offload configuration (reference rate)", "analysis/v6/boundary_candidates.csv; analysis/v6/boundary_status.csv", "analysis/v4/e9_*/configs.jsonl", "all e9 configurations", "mixed", "named rules + pool", "ready", "", "", "(config_id, candidate)"),
    ("Fig2", "a", "platform flow chart (concept): module names, billing paths and inputs/outputs", "analysis/v7/pipeline_example.json (keys billing_paths, resources, R_terms, H, T)", E9C, GEMMA, P500, "", "ready", "no numeric input besides the example", "", ""),
    ("Fig2", "b", "traceable offload example: operator shapes -> account -> tiling -> seats -> stages of layer 0", "analysis/v7/pipeline_example.json", E9C + " (layout sa_random_best_s5)", GEMMA, P500, "representative search layout", "ready", "", "", "layer_shown"),
    ("Fig2", "b", "example flows with physical routes", "analysis/v7/example_flows.csv", "same", GEMMA, P500, "", "ready", "", "", "flow_id"),
    ("Fig2", "b", "example resource loads: resource id, kind, direction, payload, capacity, service time, stage maximum", "analysis/v7/example_resource_loads.csv", "same", GEMMA, P500, "", "ready", "", "", "(into, resource_id)"),
    ("Fig2", "b", "legacy FFN 4x4 resource example (kept): topology, assignment, link loads, port bound", "analysis/figures_dac2027/20260921_v2/data/fig2b_placement_to_costs.json; fig5_small_mesh_instance.json", "scripts/plot_dac2027_v2.py", "4x4 mesh, ffn1->ffn2, kappa 2, 0.4 GB/s", "", "compact_fill / random / search", "ready", "", "", ""),
    ("Fig3", "a", "silicon seating reference: measured, resource lower bound, protocol estimate (raw and normalised)", "analysis/v7/silicon_reference.csv", "analysis/simba_t1.json; MICRO'19 section 4.6 Fig. 9 readings", "Simba res4a_branch1, 4 chiplets, 5 seatings", "SIMBA_PREREG T1", "", "ready", "", "", "seating_index"),
    ("Fig3", "b", "per-candidate analytic vs BookSim with a common baseline per library (three offload libraries + five on-chip libraries)", "analysis/v7/booksim_candidate_costs.csv", "analysis/v3/e3_offload/library_*.json; analysis/v3/e3_k2/library_*.json", "offload6x6 / offload_decode6x6 / offload2_8x8 (+ layer6x6, layers2_8x8, layer12x12, decode6x6, mech4x4)", "library protocol (validation_protocols.json)", "73 / 73 / 74 (+72 / 74 / 72 / 72 / 69)", "ready", "", "", "(scenario_id, candidate_id)"),
    ("Fig3", "b", "library summary: Spearman, inversions, BookSim/bound range, baseline id", "analysis/v7/booksim_library_summary.csv", "same", "", "", "", "ready", "", "", "scenario_id"),
    ("Fig3", "b", "protocols: BookSim settings, kappa alignment, baseline definition", "analysis/v7/validation_protocols.json", "analysis/v6/validation_protocols.json + this round", "", "", "", "ready", "", "", ""),
    ("Fig3", "c", "runtime summary per configuration (512 / 768 / 1232 / 2200 CIM dies): init, full, incremental, repricing, search", "analysis/v7/runtime_summary.csv", "analysis/v6/runtime_summary.csv (scripts/v6_timing.py, load 7.2)", "ref2p7b / opt6.7b / gemma7b / opt13b prefill 512 K1", P500, "", "ready", "", "column renamed incremental_relative_error; speed-up as its own column", "config_id"),
    ("Fig3", "c", "runtime samples (repeats, search runs)", "analysis/v7/runtime_samples.csv", "same", "", "", "", "ready", "", "", "(config_id, repeat)"),
    ("Fig3", "c", "runtime environment", "analysis/v7/runtime_environment.json", "same", "", "", "", "ready", "", "", ""),
    ("Fig4", "a", "exact word-hops equivalence groups with BookSim times (the 81.8% group = layer6x6:wh1)", "analysis/v7/equivalent_candidate_groups.csv", "analysis/v3/e3_k2/library_layer6x6.json and the other libraries", "layer6x6 (6x6 mesh, one 2.7B layer, kappa 2 / c 4)", "library protocol", "exact word-hops + identical payload", "ready", "", "", "(group_id, candidate_id)"),
    ("Fig4", "a+b", "per-stage tie diagnostics (analytic resources + BookSim per stage, re-run)", "analysis/v7/booksim_tie_diagnostics.csv", "libraries + targeted BookSim re-runs (totals match the records)", "offload_decode6x6 tie set; mech4x4 tie set; layer6x6:wh1", "", "", "ready", "", "", "(scenario_id, candidate_id, into)"),
    ("Fig4", "b", "selection by objective with the stable-id rule: selected id, tie set, BookSim best, regret", "analysis/v7/booksim_selection_by_objective.csv", "libraries", "all 8 libraries", "", "", "ready", "", "", "(scenario_id, objective)"),
    ("Fig4", "b", "earlier audit and tie sets (exact / tolerance ties, endpoint regrets)", "analysis/v6/booksim_selection_audit.csv; analysis/v6/booksim_tie_sets.csv", "libraries", "", "", "", "ready", "", "", "(library, objective[, tie_definition])"),
    ("Fig4", "ablation (optional)", "matched-budget search endpoints under Full / Links-only / Word-hops / Max-hops (registered, in the candidate files)", "analysis/v7/booksim_candidate_costs.csv (candidate_class 'search endpoint (...)'); analysis/v3/e3_k2/ablation_*.json", "libraries; scripts/v3_discrim.py ablation", "", "", "", "ready", "the offload matched-budget ablation on the full system model is not run", "run only if the panel is adopted", ""),
    ("Fig5", "a", "communication bars: default, named rules, strongest random, best baseline, search (H / H_best, seed range)", "analysis/v7/gemma_panel_a.csv", E9C, GEMMA, P500, "rules + 500 random + 30 endpoints", "ready", "", "", "layout"),
    ("Fig5", "a", "all candidates with R / H / T and R terms", "analysis/v6/gemma_candidates.csv", E9C, GEMMA, P500, "", "ready", "", "", "layout"),
    ("Fig5", "a", "seed statistics (per run and per seed)", "analysis/v6/gemma_seed_statistics.csv", E9C, GEMMA, P500, "", "ready", "", "", "run"),
    ("Fig5", "b", "per-hand-off delta H of the actual pair (random_s209 -> sa_random_best_s5) with category block", "analysis/v6/gemma_stage_delta.csv", E9C, GEMMA, P500, "", "ready", "", "", "into"),
    ("Fig5", "b", "per-hand-off breakdown and resource loads of both layouts", "analysis/v6/gemma_stage_breakdown.csv; analysis/v6/gemma_resource_loads.csv", E9C, GEMMA, P500, "", "ready", "", "", "(layout, into)"),
    ("Fig5", "c", "bandwidth curve of the frozen pair, 0.3-0.65 GB/s, dense near B_eq", "analysis/v7/gemma_bandwidth_curve.csv", E9C, GEMMA, P500, "", "ready", "", "", "B_mesh_gbps"),
    ("Fig5", "c", "B_eq root and reachability", "analysis/v6/gemma_bandwidth_equivalence.csv", E9C, GEMMA, P500, "", "ready", "", "", ""),
    ("Fig5", "supplement", "energy breakdown of the pair; consistency checks (stage sum, seed median, B_eq)", "analysis/v6/gemma_energy_breakdown.csv; analysis/v7/gemma_checks.json", E9C, GEMMA, P500, "", "ready", "", "", ""),
    ("Fig6", "a/b/c", "nine-cell configurations (ids, dies, grid, unit position, resources, candidate identities)", "analysis/v7/ninecell_configurations.csv", "analysis/v4/e9_confirm, e10_confirm_cap, e10_confirm", NINE, P500, "rules + 500 random + 30 endpoints", "ready", "", "", "(family, model)"),
    ("Fig6", "a/b/c", "per cell: default / strongest rule / strongest random / best baseline / search with R, H, T, speed-up, eta, G, B_eq", "analysis/v7/ninecell_candidates.csv", "same", NINE, P500, "", "ready", "", "", "(family, model, role)"),
    ("Fig6", "a/b/c", "per seed best-of-three: H, T, comm speed-up, eta, G", "analysis/v7/ninecell_seed_statistics.csv", "same", NINE, P500, "", "ready", "", "", "(family, model, seed)"),
    ("Fig6", "a/b/c", "display quantities in long form with statistic = actual_pair / seed_median / seed_min / seed_max / deterministic", "analysis/v7/ninecell_metrics.csv", "same", NINE, P500, "", "ready", "", "", "(family, model, quantity, statistic)"),
    ("Fig6", "expanded", "OPT-13B K=4 per-unit layer groups, column-split QKV, K=4 fixed-total layer groups (exploration)", "analysis/v7/ninecell_candidates.csv; ninecell_seed_statistics.csv; ninecell_metrics.csv; ninecell_configurations.csv (rows with family 'expanded: ...')", "analysis/v4/e10_confirm, e9_hub", "opt13b expanded", "P500 / P100", "", "ready", "", "", ""),
    ("Fig7", "a", "capacity axis 4 / 8 / 16 / 32 macros per die, three models, natural grids (exploration and confirmation groups), with flow structure", "analysis/v7/offload_capacity.csv", "analysis/v4/e10_cap_m4, e9_ref, e9_confirm, e10_cap_m16, e10_confirm_cap, e10_cap_m32", "{model}_prefill512_..._m{4,16,32}_offcenterK1", "P100 (cap) / P500 (confirm)", "", "ready", "", "", "(model, die_macros, unit)"),
    ("Fig7", "a", "Gemma common grid 36x36 at 8 / 16 / 32 macros vs natural grids", "analysis/v7/offload_capacity_common_grid.csv", "analysis/v4/e10_cap_common_m16, e10_cap_common_m32, e9_ref, e9_confirm, e10_cap_m16, e10_cap_m32", "gemma7b ... 36x36 ... m16 / m32", "P100 / P500", "", "ready", "", "", "(die_macros, grid_kind, unit)"),
    ("Fig7", "b", "resource organisation: K=1, K=2/4 layer groups (per-unit and fixed-total), K=2/4 head groups; per-unit and total resources; strongest / search R, H, T", "analysis/v7/resource_organization_comparison.csv", "analysis/v4/e9_hub, e9_head, e10_head, e9_confirm, e10_confirm", "gemma7b / opt13b / opt6.7b, prefill and decode 512", "P100 (triple K1 / K4T / K4TH same protocol); P500 for K1 and K4TH", "", "ready", "a confirmed K=4 fixed-total layer-group point (Gemma) if the panel uses confirmation statistics", "optional run_needed: e10_confirm-style run of gemma7b ..._offcenterK4T", "(model, phase, organisation, unit)"),
    ("Fig7", "c", "Gemma decode / prefill length sweep S = 128 ... 4096, eta / r0 / G and R terms (exploration)", "analysis/v7/workload_length_sweep.csv", E9R, "{model}_{phase}{S}_..._offcenterK1", P100, "", "ready", "opt6.7b / opt13b at 4096 not supported by the model (positions); recorded", "", "(model, phase, S)"),
    ("Fig7", "c", "workspace thresholds: S = 512 / 1024 / 2048, K=1 vs K=4 head groups, algorithm, tiles, workspace, K/V reads", "analysis/v7/workspace_thresholds.csv", "analysis/v4/e10_ws, e9_head, e9_ref", "gemma7b ... K1T / K4TH", P100, "", "ready", "", "", "(config_id, unit)"),
    ("TableI", "", "machine-readable evaluation setup: models, CIM, interconnect, digital unit, protocols, metrics, scope", "analysis/v7/evaluation_setup.json", "records + accounts + fabric + code constants", "reference configurations of 4 models", P500, "", "ready", "", "", ""),
    ("TableI", "", "parameter provenance (value, unit, code location, source, evidence class)", "analysis/v7/parameter_provenance.csv", "scripts/offload.py REF_UNIT, fabric.py, search_eval.py, analysis/v5/parameter_sources.md, ANCHORS.md", "", "", "", "ready", "", "", "(block, parameter)"),
    ("TableI", "", "protocols and the configuration manifest of every record", "analysis/v6/protocols.json; analysis/v6/configuration_manifest.csv", "analysis/v4/*/configs.jsonl", "all", "", "", "ready", "", "", "config_id"),
    ("Fig6", "supplement: small models", "OPT-1.3B / Qwen2.5-1.5B batches A (8 macros, prefill / decode 512) and B (16 macros): structure, comparison, seeds, stage breakdown", "analysis/v7/small_model_manifest.csv; small_model_comparison.csv; small_model_seed_statistics.csv; small_model_operator_accounts.csv; small_model_stage_breakdown.csv; small_model_stage_delta.csv", "analysis/v4/e11_small/configs.jsonl; analysis/v4/e11_small_cap/configs.jsonl; accounts opt1.3b_S512*.json, qwen2.5-1.5b_S512*.json", "{opt1.3b,qwen2.5-1.5b}_{prefill,decode}512_colrow_sq_mesh_xy_k2_b0.4[_m16]_offcenterK1", P500, "rules + 500 random + 30 endpoints", "ready", "", "", "(config_id, role)"),
    ("Fig7", "c supplement: small-model lengths", "batch C: S 128 / 2048, prefill and decode, exploration with H / H_base", "analysis/v7/small_model_manifest.csv (batch C rows); small_model_comparison.csv", "analysis/v4/e11_small_len/configs.jsonl", "{model}_{phase}{128,2048}_..._offcenterK1", "pool100_seeds0-4_objh_norm", "rules + 100 random + 15 endpoints", "ready", "", "", "(config_id, role)"),
    ("Fig7", "a supplement: QKV split on a common grid", "OPT-13B row-split natural 47x47, row-split 49x49, column-split 49x49 (confirmation): costs, metrics, flow structure, per-stage loads", "analysis/v7/qkv_common_grid_comparison.csv; qkv_common_grid_stage_loads.csv", "analysis/v4/e9_confirm, e11_qkv_common, e10_confirm", "opt13b_prefill512_{colrow_sq, colrow_49x49, col_sq_tlcol}_..._offcenterK1", P500, "", "ready", "", "", "(configuration, layout, stage)"),
    ("Fig7", "supplement: hub x mesh points", "six selected hub x mesh points with frozen pair / reselected pool / fresh search; per-seed fresh-search results", "analysis/v7/hub_mesh_selected_checks.csv; hub_mesh_fresh_search.csv; analysis/v6/hub_mesh_grid.csv; hub_mesh_search_checks.csv", "analysis/v4/e9_ref (reference), analysis/v4/e11_hubmesh (fresh)", "gemma7b_{prefill,decode}512_..._b{B}_offcenterK1_lin{C_hub}", "pool100_seeds0-4_objh_norm (fresh); P100 t_norm (reference)", "", "ready", "", "", "(phase, C_hub_gbps, B_mesh_gbps, source)"),
    ("Fig7", "a: OPT-13B 4-macro point", "the previously blocked OPT-13B 4-macro capacity point (account measured after the container was recreated with /data mounted)", "analysis/v7/offload_capacity.csv (row opt13b m4)", "analysis/v4/e10_cap_m4/configs.jsonl; accounts/opt13b_S512_m4.json", "opt13b_prefill512_colrow_sq_mesh_xy_k2_b0.4_m4_offcenterK1", P100, "", "ready", "", "", ""),
]


DESC = {"intradie_phase_candidates.csv": "one row per legal joint seating of the ffn die (macros per op, serialization words per op, A = max, compute at the reference rate, fixed terms, hide-all threshold, T at the reference point)",
        "intradie_phase_curves.csv": "per row rate: per-op compute, R, B-, B+, the 20% spread contour, spreads at the boundaries, the seating ids of A_min / A_max",
        "phase_grid.csv": "per (row rate, mesh bandwidth): R, H and T of every rule (empty = not constructible), T_min / T_max / spread / region for the two candidate sets",
        "phase_boundary_curves.csv": "per row rate: per-rule B_c and status (finite / beyond_scan / no_finite_boundary / limit_equals_R / rule_construction_failed), lim H, B- / B+ and their rules, member counts, 20% spread contour and its status, for the two sets",
        "phase_projection_points.csv": "hardware points: chip, mode, panel, coordinate kind, row time and its status / derivation, bandwidth and its status / derivation, source, regions under the intra-die model and under both package sets",
        "booksim_candidate_costs.csv": "per library candidate: class, analytic scores (words) and hand-off time, T / H, word-hops, hops, payload, BookSim cycles / bound / packets, baseline id and both normalisations",
        "booksim_library_summary.csv": "per library: grid, phase, kappa alignment, counts, baseline, Spearman and inversions vs BookSim, BookSim / bound range, candidate classes",
        "equivalent_candidate_groups.csv": "per member of an exact word-hops group: group id, payload, group size, analytic score and BookSim cycles relative to the group minimum, group spans, topology",
        "booksim_selection_by_objective.csv": "per (library, objective): selected id under the stable-id rule, tie set, BookSim best, regret of the selection and of the tie set, Full endpoint regrets",
        "booksim_tie_diagnostics.csv": "per (candidate, hand-off): busiest / second resource and kind, link concentration, hops, word-hops, propagation, BookSim per stage (re-run) and the recorded total check",
        "silicon_reference.csv": "per seating: hops, measured / bound / protocol series raw and normalised, the raw cost terms, sources",
        "runtime_summary.csv": "per configuration: dies, flows, stages, init, full / incremental medians and p10 / p90, incremental_relative_error, speed-up, repricing, search steps / wall / evaluations, load",
        "gemma_panel_a.csv": "the panel-(a) bars: layout, role, H, H / H_best, H_default / H, T, R, P, E, seed H range of the search",
        "gemma_bandwidth_curve.csv": "per mesh bandwidth: H and T of the frozen baseline and search layouts, target, reachability flags, binding counts of the baseline",
        "ninecell_configurations.csv": "per cell: ids, phase / S, tiling, macros, dies, grid, empty slots, unit slots and xy, grouping / resource mode, kappa / B / C_hub, unit resources, algorithm, R terms, pool size, candidate identities",
        "ninecell_candidates.csv": "per (cell, role): layout, class, R / H_full / H_service / P / T / E, H / H_default, H_default / H, eta vs best baseline, G vs best baseline, r0, B_eq (search)",
        "ninecell_seed_statistics.csv": "per (cell, seed): best run, start, H, T, speed-up, eta, G, representative flag",
        "ninecell_metrics.csv": "long form: (cell, quantity, statistic) -> value; statistic in actual_pair / seed_median / seed_min / seed_max / deterministic",
        "offload_capacity.csv": "per (model, macros, unit): status, protocol group, tiling per operator, dies, grid, unit, resources, R terms, default / best baseline / search costs, eta / r0 / G (+ seed G), B_eq, hub words, flow structure per stage type",
        "offload_capacity_common_grid.csv": "same columns for the Gemma 36x36 common grid and the natural grids",
        "resource_organization_comparison.csv": "same base columns + organisation label, for K = 1 / 2 / 4 layer and head groupings under per-unit and fixed-total resources",
        "workspace_thresholds.csv": "same base columns + K/V words per layer, MACs per layer, workspace per head, P_tile, spill",
        "workload_length_sweep.csv": "same base columns per (model, phase, S); unsupported points carry status and reason",
        "example_flows.csv": "per flow of layer 0's hand-offs: source / destination entries and slots (xy), unit flags, elements, width, words, hops, directed route",
        "example_resource_loads.csv": "per loaded resource of each hand-off: id, kind (mesh link / die port / hub port), direction, payload, capacity, service time, stage-maximum flag",
        "parameter_provenance.csv": "per parameter: block, value, unit, code location, source, evidence class, note",
        "small_model_manifest.csv": "per small-model configuration: batch, structure (dims, heads, K/V heads, gated FFN), account, tiling per operator, dies, grid, unit, resources, R terms, costs, metrics, boundaries, flow structure",
        "small_model_operator_accounts.csv": "per (configuration, operator): shapes, dies, split, compute / write / energy per layer, die flow words",
        "small_model_comparison.csv": "per (configuration, role): default / strongest named / strongest random / best baseline / search representative with R, H, T, E, speed-up, eta, G, r0, B_eq",
        "small_model_seed_statistics.csv": "per (configuration, seed): best-of-three run, H, T, speed-up, eta, G",
        "small_model_stage_breakdown.csv": "per (configuration, layout, hand-off): payload, resource maxima, service times, binding (best baseline and search representative)",
        "small_model_stage_delta.csv": "per (configuration, hand-off): H of both layouts and the delta (negative = saving)",
        "qkv_common_grid_comparison.csv": "the three OPT-13B QKV configurations: ids, dies, grid, empty slots, unit xy, tiling, costs, metrics, hub words, qkv->unit payload, max link loads, flow structure",
        "qkv_common_grid_stage_loads.csv": "per (configuration, layout, stage type): hand-offs, payload, H, busiest link / hub port words, binding counts",
        "hub_mesh_selected_checks.csv": "per (point, source): baseline and search identities, H / T, eta / r0 / G, bindings, B_eq; fresh search adds seed statistics and the frozen-vs-fresh H ratio",
        "hub_mesh_fresh_search.csv": "per (point, seed) of the fresh searches",
        "plot_data_manifest.csv": "this index"}


def main():
    rows = []
    cv = V.code_version()
    for fig, panel, role, path, src, cid, prot, cset, status, missing, nxt, key in ROWS:
        n = ""
        first = path.split(";")[0].split(" (")[0].strip()
        p = os.path.join(WS, first)
        if first.endswith(".csv") and os.path.exists(p):
            n = sum(1 for _ in open(p)) - 1
        elif not os.path.exists(p) and status == "ready":
            status = "export_needed"; nxt = (nxt + "; " if nxt else "") + f"file missing: {first}"
        rows.append({"figure_id": fig, "panel_id": panel, "dataset_role": role, "actual_path": path, "source_record_path": src, "config_id": cid, "protocol_id": prot, "candidate_set_id": cset, "status": status, "missing_fields": missing, "next_action": nxt, "code_version": cv, "n_rows": n, "primary_key": key})
    V.write_csv("plot_data_manifest.csv", rows)
    # dictionary
    lines = ["# Figure data dictionary (analysis/v7)", "", f"Code version: {cv}. Units: seconds unless a column says ms / us; bandwidths in GB/s per direction (1 GB/s = 1e9 bytes/s); words = bytes (8-bit activations; partial sums carry width 2); capacities in bytes (decimal GB).", "",
             "Statistics: `actual_pair` = the stored representative layout against the stored best baseline; `seed_*` = per seed the best of the three starts (named rule, strongest random, random seed 0), then median / min / max over the ten confirmation seeds (5-14) or five exploration seeds (0-4).", ""]
    for f in sorted(os.listdir(V.V7)):
        p = os.path.join(V.V7, f)
        if f.endswith(".csv"):
            with open(p) as fh:
                hdr = next(csv.reader(fh)); n = sum(1 for _ in fh)
            lines += [f"## {f}", "", f"{n} rows. {DESC.get(f, '')}", "", "Columns: " + ", ".join(f"`{c}`" for c in hdr), ""]
        elif f.endswith(".json"):
            o = json.load(open(p)); keys = list(o.keys()) if isinstance(o, dict) else []
            lines += [f"## {f}", "", DESC.get(f, "") or ("top-level keys: " + ", ".join(f"`{k}`" for k in keys)), ""]
    open(os.path.join(V.V7, "plot_data_dictionary.md"), "w").write("\n".join(lines))
    print("  analysis/v7/plot_data_dictionary.md")
    # the one-page summary table with repository-root-relative paths
    root = os.path.dirname(WS)
    def rel(p):
        return "; ".join(os.path.relpath(os.path.join(WS, x.strip().split(" (")[0]), root) + ((" (" + x.strip().split(" (", 1)[1]) if " (" in x else "") if x.strip().startswith("analysis") else x.strip() for x in p.split(";"))
    tab = ["# Figure data summary (paths relative to the repository root `cimloop/`)", "", f"Code version {cv}. Every file is data (CSV / JSON / MD); no figures are rendered in this round. Full index with record paths, protocol ids and candidate sets: `workspace/analysis/v7/plot_data_manifest.csv`; column dictionary: `workspace/analysis/v7/plot_data_dictionary.md`.", "",
           "| Figure | Panel | Data | Path(s) | Rows | Status |", "| --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        tab.append(f"| {r['figure_id']} | {r['panel_id']} | {r['dataset_role']} | {rel(r['actual_path'])} | {r['n_rows']} | {r['status']} |")
    open(os.path.join(V.V7, "plot_data_summary.md"), "w").write("\n".join(tab) + "\n")
    print("  analysis/v7/plot_data_summary.md")
    from collections import Counter
    print(Counter(r["status"] for r in rows))


if __name__ == "__main__":
    main()

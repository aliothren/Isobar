# Numbers of the paper

Every number of the final paper, with its workload, configuration, denominator, statistic and the file it is read from. Paths are relative to `workspace/analysis/`. The reference configuration is:

- links at 0.4 GB/s per direction, CIM die ports at κ = 2 (0.8 GB/s);
- XY routing, 20 ns per hop;
- 8 macros per die, NeuRRAM row time 10.14 µs;
- one central digital unit: 2 TMAC/s, K/V memory 2 GB at 25.6 GB/s, 12.5 GB/s interface, 8 MB workspace;
- batch 1, 512-token prefill.

## Gemma-7B main case (Fig. 5)

Gemma-7B, 1,232 dies on a 36 × 36 mesh. Confirmation protocol: 500 random layouts, seeds 5–14, objective H / H_b. The best baseline is `random_s209`; the search representative is `sa_random_best_s5`, the median seed's best run.

| number | meaning | denominator | file |
|---|---|---|---|
| −23.3% | communication time of the representative | best baseline, H 2.623 s | `v7/gemma_checks.json` (`pair.eta_comm`) |
| −18.6% | end-to-end latency | best baseline, T 3.290 s | same (`pair.G_actual_pair`) |
| 77.7% | latency below the default fill (12.00 → 2.68 s) | default fill | `v7/gemma_panel_a.csv` |
| −0.65% | dynamic energy | best baseline | `v7/gemma_checks.json` (`energy.dE_pair`) |
| 81.8% | share of the saving in the out_proj→FFN1 and FFN1→FFN2 hand-offs | total saving 611 ms | `v6/gemma_stage_delta.csv` |
| 0.52 GB/s (+30.4%) | bandwidth the best baseline needs to match the representative's H at 0.4 GB/s | 0.4 GB/s | `v6/gemma_bandwidth_equivalence.csv` |
| −14.4% E, +29.1% T | least-Manhattan rule | best random layout | `v6/gemma_candidates.csv` |

## Across models and configurations (Fig. 6)

OPT-1.3B, OPT-6.7B, Gemma-7B and OPT-13B, prefill 512, confirmation protocol, in three configurations:

- (a) 8 macros per die, central unit;
- (b) 16 macros per die, central unit;
- (c) 8 macros per die, four head-group units sharing the reference resources.

| number | meaning | statistic | file |
|---|---|---|---|
| 14.8–24.0% | communication saving vs. the best baseline, OPT-6.7B / Gemma-7B / OPT-13B, nine cells | seed median | `v7/ninecell_metrics.csv` |
| 10.6–18.7% | end-to-end saving, same cells | seed median | same |
| bar labels (+22.1 … +33.3%; OPT-1.3B 26.5%, 0.0%, 26.8%) | communication saving of the search median over the random-pool median | medians | `figures_dac2027/20261019_v3/data/fig6_ninecell.csv` |

## Phase diagram (Fig. 1)

| number | meaning | file |
|---|---|---|
| 2.67× | intra-die envelope B₊/B₋ over the 70 macro assignments of the FFN die at the reference rate | `v7/intradie_phase_curves.csv` |
| 4.17× | package envelope over six Gemma-7B layouts at the reference rate | `v7/phase_boundary_curves.csv` |
| 20% contour | total-latency spread across the evaluated layouts | `v7/phase_grid.csv` |
| projected designs | ISAAC, HERMES (1- and 4-phase), NeuRRAM at 0.4 and 12.5 GB/s, Mythic M1076, Simba | `v7/phase_projection_points.csv` |

## Validation and cost (Figs. 3, 4)

| number | meaning | file |
|---|---|---|
| 2.40× vs. 2.53×, 5.1% error | Simba seating: protocol estimate vs. measured latency ratio, farthest / adjacent seating; resource bound 1.007× | `v7/silicon_reference.csv` |
| ρ 0.966 / 0.984 / 0.973 | Spearman rank correlation with BookSim: one-layer prefill, one-layer decode, two-layer prefill | `v7/booksim_library_summary.csv` |
| 1.94 vs. 1.82 | B/A communication-time ratio of two equal-word-hops layouts: Isobar vs. BookSim | `v7/equivalent_candidate_groups.csv` |
| 0.3–12.2% vs. 40.4–51.7% | BookSim time of the layout selected by Isobar vs. by word-hops, above the library minimum | `v7/booksim_selection_by_objective.csv` |
| 1.4–15.9 ms, 26–38× | incremental update per move and speed-up over a full evaluation, 512–2,200 dies | `v7/runtime_summary.csv` |
| 2.5 / 8.1 / 43.9 / 127.7 s | one representative search: 2.7B reference, OPT-6.7B, Gemma-7B, OPT-13B | `v7/search_trajectories.json` |

## Configuration dependence (Fig. 7, Table II)

Fig. 7 uses the exploration protocol: 100 random layouts, seeds 0–4.

| number | meaning | file |
|---|---|---|
| η 23.3%, r₀ 79.7%, G 18.6% at 0.4 GB/s | bandwidth response of the fixed Gemma pair; the crossover envelope 1.63–6.79 GB/s | `v7/gemma_bandwidth_response.csv` |
| 3.33 / 3.46 / 3.03 s → 2.68 / 2.88 / 2.46 s | Gemma-7B backbone time, baseline → search: one unit, four layer-group units, four head-group units | `v7/resource_organization_comparison.csv` |
| 17.5% (prefill), 2.6% (decode) | Gemma-7B backbone saving at 4096 tokens | `v7/workload_length_sweep.csv` |
| Row: 2,200 dies, 6.29 GB, 13.39 → 11.22 s, η 17.5%; Column: 2,400 dies, 0.315 GB, 5.16 → 4.10 s, η 25.1% | OPT-13B QKV split on a 49 × 49 mesh (confirmation protocol) | `v7/qkv_common_grid_comparison.csv` |

## GPU comparison (Table III)

Modeled CIM dynamic energy per request against reported GPU energy, at batch 1 with a 16-bit K/V cache. OPT-13B is compared with one A100 (64 input : 1024 output tokens, 5473.7 J); Gemma-7B with a Jetson AGX Thor board (13–345 input : 500 output tokens, mean 1898.7 J).

| configuration | CIM energy | GPU / CIM | file |
|---|---|---|---|
| OPT-13B, 8 macros | 58.61 J | 93× | `../gpu_comparison/comparison_summary.csv` (`A0_ref_kv16`) |
| OPT-13B, 16 macros | 48.53 J | 113× | same (`A1_m16_kv16`) |
| Gemma-7B, 8 macros | 11.45 J | 166× | same (`B0_ref_kv16`) |
| Gemma-7B, 16 macros | 9.85 J | 193× | same (`B1_m16_kv16`) |

# 02 The final pipeline on this branch

The commands below produced the data behind every figure and table of the paper. Run them from `workspace/`. The `release` branch reorganises the same stages under plain script names (`run_experiments.py --experiment reference`, ...) with one results folder. Its `docs/06_reproduce_paper.md` lists the correspondence, and its exports reproduce this branch's `v6/` and `v7/` tables number for number.

Python on the host: `PY=/home/yuxinr/miniforge3/envs/far/bin/python`. Container: `python3`.

## Stage 1 — CiMLoop measurements (container)

| output | command |
|---|---|
| `analysis/scale_2p7b_per_op.json` (2.7B-class reference account) | `python3 scripts/run_2p7b_block.py` |
| `analysis/contention_system.json` (intra-die instance, Fig. 1(a)) | `python3 scripts/analyze_contention_system.py --shares` |
| `analysis/v4/accounts/<model>_S<S>[_m<N>|_attn<N>|_tl<t>].json` | `python3 scripts/v4_measure_accounts.py [--die-macros N | --attention-die-macros N | --tiling t] <model> <S> ...` |
| `analysis/v4/models/model_end_costs.json` (LM head, embedding) | `python3 scripts/v4_model_end.py` |
| `models/fabric/variants/mlx300_multidie_m{4,16,32}.yaml` | `python3 scripts/v4_fabric_variants.py` |
| `models/workloads/opt_2p7b/` (value histograms) | `python3 scripts/extract_opt2p7b_hists.py` |

## Stage 2 — reference instances and validation libraries

| output | command |
|---|---|
| `analysis/soft_lever.json` (intra-die levers) | `$PY scripts/analyze_soft_lever.py` |
| `analysis/search_withindie.json` | `$PY scripts/search_withindie.py` |
| `analysis/simba_t1.json` (Simba seating reference) | `$PY scripts/simba_targets.py` |
| `analysis/v3/e3_offload/library_offload*.json` | `E3_DIR=e3_offload E3_KAPPA_AN=4 $PY scripts/v3_discrim.py libraries --scenarios offload6x6,offload_decode6x6,offload2_8x8` |
| `analysis/v3/e3_k2/library_layer6x6.json` | `$PY scripts/v3_discrim.py libraries --scenarios layer6x6` |

## Stage 3 — deployment experiments (`analysis/v4/<unit>/`)

Confirmation protocol: `--n-random 500 --seeds 5,6,7,8,9,10,11,12,13,14 --objective h_norm`. Exploration protocol: the defaults (100 random layouts, seeds 0–4, `t_norm`). For a die variant, set `CIMSIM_FABRIC=models/fabric/variants/mlx300_multidie_m<N>.yaml` and pass `--macros N`.

| units | protocol | content | paper |
|---|---|---|---|
| `e9_confirm`, `e11_small` | confirmation | 8 macros per die, central unit: the 2.7B-class reference and OPT-6.7B / Gemma-7B / OPT-13B (`e9_confirm`), OPT-1.3B (`e11_small`), prefill and decode at 512 | Figs. 1(b), 2, 3(c,d), 5, 6(a); Table I |
| `e10_confirm_cap` (16-macro fabric), `e11_small_cap` | confirmation | 16 macros per die | Fig. 6(b); Table III |
| `e10_confirm` (K = 4 head groups), `e11_small_head` | confirmation | four head-group units sharing the reference resources | Fig. 6(c) |
| `e10_confirm` (column-split QKV), `e11_qkv_common` | confirmation | OPT-13B QKV split on a 49 × 49 mesh | Table II |
| `e10_cap --macros 4/16/32`, `e9_ref`, `e10_cap_common`, `e11_small_expl`, `e11_small_cap_expl` | exploration | capacity 4 / 8 / 16 / 32 macros per die; Gemma-7B on the 36 × 36 mesh | Fig. 7(a) |
| `e9_head` | exploration | Gemma-7B with one unit, four layer-group units, four head-group units | Fig. 7(b) |
| `e9_ref` | exploration | Gemma-7B prefill and decode at 128–4096 tokens | Fig. 7(d) |

```bash
$PY -u scripts/v4_deploy.py --unit e9_confirm --objective h_norm --n-random 500 --seeds 5,6,7,8,9,10,11,12,13,14
CIMSIM_FABRIC=models/fabric/variants/mlx300_multidie_m16.yaml \
  $PY -u scripts/v4_deploy.py --unit e10_confirm_cap --macros 16 --objective h_norm --n-random 500 --seeds 5,6,7,8,9,10,11,12,13,14
CIMSIM_FABRIC=models/fabric/variants/mlx300_multidie_m4.yaml $PY -u scripts/v4_deploy.py --unit e10_cap --macros 4
$PY -u scripts/v4_deploy.py --unit e9_head
```

Timing and search progress: `$PY scripts/v6_timing.py` (`analysis/v6/runtime_*`) and `$PY scripts/v7_search_trajectory.py` (`analysis/v7/search_trajectories.*`). The latter re-runs each representative search and checks that it reproduces the recorded endpoint.

## Stage 4 — exports and figures

| tables | command |
|---|---|
| `analysis/v6/gemma_*` (Gemma-7B main case) | `$PY scripts/v6_gemma_pair.py` |
| `analysis/v7/phase_*`, `intradie_phase_*` (Fig. 1) | `$PY scripts/v7_fig1_phase.py` |
| `analysis/v7/pipeline_example.json`, `example_*` (Fig. 2) | `$PY scripts/v7_fig2_pipeline.py` |
| `analysis/v7/silicon_reference.csv`, `booksim_*`, `equivalent_candidate_groups.csv`, `runtime_*` (Figs. 3, 4) | `$PY scripts/v7_fig3_fig4_validation.py` |
| `analysis/v7/gemma_panel_a.csv`, `gemma_bandwidth_curve.csv`, `gemma_checks.json`, `ninecell_*` (Figs. 5, 6) | `$PY scripts/v7_fig5_fig6_results.py` |
| `analysis/v7/small_model_*`, `offload_capacity_small.csv` (OPT-1.3B in Figs. 6, 7) | `$PY scripts/v7_small_models.py`, `$PY scripts/v7_small_capacity_points.py` |
| `analysis/v7/offload_capacity*.csv`, `resource_organization_comparison.csv`, `workload_length_sweep.csv` (Fig. 7(a,b,d)) | `$PY scripts/v7_fig7_mechanisms.py` |
| `analysis/v7/gemma_bandwidth_response.*` (Fig. 7(c)) | `$PY scripts/v7_fig7_bandwidth_response.py` |
| `analysis/v7/qkv_common_grid_*` (Table II) | `$PY scripts/v7_qkv_common.py` |
| `analysis/v7/evaluation_setup.json`, `parameter_provenance.csv` (Table I) | `$PY scripts/v7_table1_setup.py` |
| the figures, `analysis/figures_dac2027/20261019_v3/` | `$PY scripts/plot_dac2027_v3.py --run-id 20261019_v3` |
| Table III, `gpu_comparison/` | `bash gpu_comparison/scripts/run_all.sh`, then `$PY gpu_comparison/scripts/summarize.py` and `$PY gpu_comparison/scripts/energy_audit.py`; the paper's rows are the `_kv16` configurations |

`analysis/v7/plot_data_dictionary.md` describes every column of the exported tables. `analysis/v7/plot_data_summary.md` summarises their values.

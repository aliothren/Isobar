# 08 Reproducing the paper

This page lists, in order, the commands that regenerate the data behind every figure and table of the paper, and where each result lands. Stage 1 runs in the container (`/home/workspace`); everything else runs on the host from `workspace/` or in the container. The scripts produce data tables; the paper's figures are included as final images in `figures/`, and the repository contains no plotting code.

## What each stage needs

| stage | needs | produces |
|---|---|---|
| 1. operator costs | the container (CiMLoop) | `results/accounts/`, `results/reference/reference_2p7b_S512.json`, `results/reference/intradie_instance.json` |
| 2. reference instances, validation | Stage 1; BookSim at the pinned commit ([workspace/tools/README.md](../workspace/tools/README.md)) | `results/reference/`, `results/booksim/` |
| 3. deployments | Stage 1 | `results/records/` |
| 4. tables | Stages 1–3; `export_fig7_bandwidth.py` after `export_fig1_phase.py`, `export_fig5_fig6.py` after `export_gemma_pair.py`; Table III also needs `model_end_costs.json` | `results/exports/`, `results/gpu_comparison/` |

## Stage 1: operator costs (container)

```bash
# container, from /home/workspace
python3 scripts/measure_reference_account.py           # 2.7B-class reference
python3 scripts/measure_intradie_instance.py --shares  # intra-die instance of Fig. 1(a)

for m in opt1.3b opt6.7b opt13b; do python3 scripts/measure_accounts.py $m 512; done
python3 scripts/measure_accounts.py gemma7b 128 256 512 1024
python3 scripts/measure_accounts.py --attention-die-macros 16 gemma7b 2048
python3 scripts/measure_accounts.py --attention-die-macros 32 gemma7b 4096
for n in 4 16 32; do for m in opt1.3b opt6.7b gemma7b opt13b; do
    python3 scripts/measure_accounts.py --die-macros $n $m 512; done; done
python3 scripts/measure_accounts.py --tiling col opt13b 512
python3 scripts/measure_model_end.py                   # LM head, for Table III
```

The value histograms (`models/workloads/opt_2p7b/`) and the die variants (`models/fabric/variants/`) are already in the repository.

## Stage 2: reference instances and validation libraries

```bash
# host, from workspace/ (or the container)
python3 scripts/intradie_levers.py
python3 scripts/search_withindie.py
python3 scripts/run_simba_reference.py
python3 scripts/run_booksim_libraries.py    # needs BookSim
```

## Stage 3: deployments

```bash
# host, from workspace/ (or the container)
python3 scripts/run_experiments.py --experiment reference
python3 scripts/run_experiments.py --experiment capacity16
python3 scripts/run_experiments.py --experiment distributed
python3 scripts/run_experiments.py --experiment qkv_split
for n in 4 8 16 32; do python3 scripts/run_experiments.py --experiment capacity_sweep --macros $n; done
python3 scripts/run_experiments.py --experiment organisation
python3 scripts/run_experiments.py --experiment context_length

python3 scripts/run_timing.py                # Fig. 3(c), on an idle machine
python3 scripts/run_search_trajectories.py   # Fig. 3(d)
```

The deployments take about 20 hours on one core. Experiments are independent and can run in parallel processes. The largest single configuration, OPT-13B on 4,400 dies at 4 macros per die, takes about 5 hours.

## Stage 4: tables behind the figures

```bash
# host, from workspace/ (or the container)
python3 scripts/export_fig1_phase.py
python3 scripts/export_fig2_pipeline.py
python3 scripts/export_gemma_pair.py        # before export_fig5_fig6.py
python3 scripts/export_fig3_fig4.py
python3 scripts/export_fig5_fig6.py
python3 scripts/export_fig7_bandwidth.py    # after export_fig1_phase.py
python3 scripts/export_fig7_mechanisms.py
python3 scripts/export_table1_setup.py
python3 scripts/export_table2_qkv.py
bash gpu_comparison/scripts/run_all.sh      # Table III
```

All tables are written to `results/exports/`; Table III goes to `results/gpu_comparison/`.

| figure / table | files |
|---|---|
| Fig. 1 phase diagrams | `phase_boundary_curves.csv`, `phase_grid.csv`, `intradie_phase_curves.csv`, `intradie_phase_candidates.csv`, `phase_projection_points.csv`, `phase_setup.json` |
| Fig. 2 worked example | `pipeline_example.json`, `example_flows.csv`, `example_resource_loads.csv` |
| Fig. 3(a) Simba | `silicon_reference.csv` |
| Fig. 3(b), Fig. 4 BookSim | `booksim_candidate_costs.csv`, `booksim_library_summary.csv`, `equivalent_candidate_groups.csv`, `booksim_selection_by_objective.csv`, `validation_protocols.json` |
| Fig. 3(c) evaluation cost | `runtime_summary.csv`, `runtime_samples.csv`, `runtime_environment.json` |
| Fig. 3(d) search progress | `search_trajectories.csv`, `search_trajectories.json` |
| Fig. 5 Gemma-7B | `gemma_panel_a.csv`, `gemma_candidates.csv`, `gemma_stage_breakdown.csv`, `gemma_stage_delta.csv`, `gemma_bandwidth_equivalence.csv`, `gemma_bandwidth_curve.csv`, `gemma_energy_breakdown.csv`, `gemma_checks.json` |
| Fig. 6 four models, three configurations | `ninecell_configurations.csv`, `ninecell_metrics.csv`, `ninecell_seed_statistics.csv`, `ninecell_candidates.csv` |
| Fig. 7(a) CIM capacity | `offload_capacity.csv`, `offload_capacity_common_grid.csv` |
| Fig. 7(b) resource organisation | `resource_organization_comparison.csv` |
| Fig. 7(c) bandwidth response | `gemma_bandwidth_response.csv`, `gemma_bandwidth_response.json` |
| Fig. 7(d) context length | `workload_length_sweep.csv` |
| Table I | `evaluation_setup.json`, `parameter_provenance.csv` |
| Table II | `qkv_common_grid_comparison.csv` |
| Table III | `results/gpu_comparison/comparison_summary.csv` |

## Numbers to check

| number | where | paper |
|---|---|---|
| Gemma-7B communication / end-to-end saving | `gemma_checks.json`, `pair.eta_comm` and `pair.G_actual_pair` | 23.3% / 18.6% |
| bandwidth the Gemma baseline needs to match the search | `gemma_bandwidth_equivalence.csv` | 0.52 GB/s |
| envelope ratio at the reference speed, intra-die / package | `intradie_phase_curves.csv`, `phase_boundary_curves.csv` | 2.67× / 4.17× |
| Simba farthest / adjacent seating | `silicon_reference.csv` | 2.40×, measured 2.53× |
| rank correlation with BookSim | `booksim_library_summary.csv` | 0.966 / 0.984 / 0.973 |
| OPT-13B row / column QKV split | `qkv_common_grid_comparison.csv` | 13.39 → 11.22 s / 5.16 → 4.10 s |
| energy per request, GPU / CIM | `comparison_summary.csv` | 93×, 113×, 166×, 193× |

## When the numbers match exactly

Stages 2–4 are deterministic, except the timings of Fig. 3(c, d). They reproduce the numbers above exactly if:

- they run on the same accounts;
- they use this repository's code, fabric files and experiment definitions, which fix the random seeds and the annealer settings;
- they use BookSim at the pinned commit with the two patches, for the validation tables.

We checked this by regenerating every table of the paper, the four BookSim libraries and Table III from the paper's accounts. Stage 1 runs CiMLoop. New accounts are expected to match as long as the CiMLoop image, the model files in `models/` and the value distributions are unchanged.

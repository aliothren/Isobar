# scripts: the framework and the analyses

The scripts run from `workspace/`, as `python3 scripts/<name>.py`. The CiMLoop measurements run in the container; everything else runs on the host or in the container. The docstring at the top of each file states what it computes, its inputs and outputs, and how to run it. [`../../docs/02_final_pipeline.md`](../../docs/02_final_pipeline.md) gives the commands that produced the paper.

## The platform

| module | role |
|---|---|
| `fabric.py` | the physical fabric: schema and loader of `models/fabric/*.yaml` (levels, grids, links, ports, device, digital units) |
| `placement.py`, `interconnect.py` | slot tables; the interconnect schemes (star, mesh, torus, ring, tree, bus, concentrated and express meshes) with their routes and loaded resources |
| `mlx_system.py`, `llm_workload.py` | the CiMLoop die configuration and the runner of one operator; transformer operators, legal tilings, die chains, the attention write cost |
| `traffic.py`, `crossbar_stats.py`, `crossbar_comm.py`, `crossbar_value.py`, `value_stats.py`, `placement_aware.py` | the communication structure derived from the mapping, on-die flows and link occupancy, value-dependent energy |
| `offload.py` | the digital attention units: positions, count, layer or head grouping, per-unit or divided resources, attention and K/V cost per layer |
| `anchors.py` | the registry of published hardware reference points (phase-diagram projections, Simba) |
| `v4_models.py` | the model registry (OPT-1.3B / 6.7B / 13B, Gemma-7B, Qwen2.5-1.5B, the 2.7B-class reference) |

## Evaluation and search

| module | role |
|---|---|
| `search_space.py` | the mapping (layer groups, die seats, macro assignment), its legality and serialisation |
| `search_eval.py` | the package evaluator: hand-off flows, routing, resource loads over links, die ports and unit interfaces, latency and energy |
| `v3_sweep.py` | the account-priced workload and the evaluation of one configuration: baseline pool, annealer runs, metrics, envelope, cost grid |
| `cimsim_cli.py` | the incremental objective (`Objective`, re-scoring only the touched hand-offs) and the command-line entry |
| `search_sa.py`, `search_dp.py`, `search_baselines.py`, `search_withindie.py` | annealing over die seats; the interval DP over layer groups; the default fill and the prescribed rules; exhaustive intra-die search |

## The final pipeline

| stage | scripts |
|---|---|
| CiMLoop measurements | `run_2p7b_block.py`, `v4_measure_accounts.py`, `v4_model_end.py`, `analyze_contention_system.py`, `extract_opt2p7b_hists.py`, `v4_fabric_variants.py` |
| reference instances and validation | `analyze_soft_lever.py`, `search_withindie.py`, `simba_targets.py` (+ `simba_workload.py`), `v3_discrim.py` (+ `booksim_bridge.py`, `booksim_patches/`) |
| deployment experiments | `v4_deploy.py` (units `e9_*`, `e10_*`, `e11_*`), `v6_timing.py`, `v7_search_trajectory.py` |
| exports | `v6_gemma_pair.py`, `v7_fig1_phase.py`, `v7_fig2_pipeline.py`, `v7_fig3_fig4_validation.py`, `v7_fig5_fig6_results.py`, `v7_small_models.py`, `v7_small_capacity_points.py`, `v7_fig7_mechanisms.py`, `v7_fig7_bandwidth_response.py`, `v7_qkv_common.py`, `v7_table1_setup.py` (helpers `v6_common.py`, `v7_common.py`, `v7_stage_worker.py`) |
| figures | `plot_dac2027_v3.py --run-id 20261019_v3` |

## Earlier stages

The remaining scripts belong to earlier stages of the work. They include:

- the single-model main configuration: `kappa_geometry_sweep.py`, `main_config_export.py`, `mechanism_table.py`, `energy_export.py`, `objective_ablation.py`, `bw_slice_k2.py`;
- the earlier phase-diagram and probe scripts (`fig_phase_isobar*.py`, `sweep_axes.py`, `analyze_*.py`);
- the earlier BookSim ranking checks (`b*_*.py`);
- the earlier figure generators (`plot_dac2027_v1.py`, `plot_dac2027_v2.py`, `make_figures.py`);
- the stage experiments named in `analysis/FIXLIST.en.md`.

Their outputs are not part of the paper's final numbers.

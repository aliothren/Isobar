# scripts: the platform and the analyses

All scripts run inside the container from `/home/workspace`
(`python3 scripts/<name>.py`). Each writes its outputs under `analysis/`
with the same base name and prints where. The docstring at the top of each
file states what it does and, for an experiment, the pre-registration it
follows.

## The command line

`cimsim_cli.py` is the user entry: `baseline`, `evaluate`, `search`,
`phase` and `booksim` subcommands on any fabric file and any per-operator
account, wrapping the modules below without adding a model. The user
guide at the repository root (`docs/`) documents it page by page.

## The platform

| module | role |
|---|---|
| `fabric.py` | the physical fabric: the schema and loader for `models/fabric/*.yaml`, the single source of truth for levels, grids, links and ports |
| `placement.py` | the placement object: who occupies which slot at every level, serializable, verified |
| `interconnect.py` | the interconnect schemes (star, mesh, torus, ring, tree, bus, switch, concentrated and express meshes): how data physically travels and which links it loads |
| `traffic.py` | the communication structure derived from the mapping: multicast, reduction and hand-off flows |
| `llm_workload.py` | the GPT-style workload generator, the block chain of operators, and the attention write-cost overlay |
| `anchors.py` | the registry of published bandwidths, device row times and chip reference points, with sources and statuses |
| `crossbar_stats.py`, `crossbar_comm.py`, `crossbar_value.py`, `crossbar_value_real.py`, `value_stats.py` | crossbar-level statistics, per-pair communication and value-dependent energy |
| `mlx_system.py`, `placement_aware.py`, `op_breakdown.py` | the system model, the placement-aware cost overlay and the per-operator ledger |
| `figstyle.py`, `make_figures.py` | figure rules and the driver that regenerates the standing figures |

## The search

| module | role |
|---|---|
| `search_space.py` | the deployment (partition, die placement), its legality and serialization |
| `search_eval.py` | the evaluator: full and incremental scoring with the hand-off term over links and ports |
| `search_dp.py` | the exact interval dynamic program over block cuts and group sizes |
| `search_sa.py` | the annealer: move families, schedule, multistart |
| `search_baselines.py` | the seven named placement rules and the random fills |
| `search_withindie.py` | the intra-die instance: exhaustive macro assignment and its annealer |
| `search_linkage.py` | the DP plus SA linkage on the whole-model payload |
| `search_ordering.py`, `search_referee.py`, `search_s6.py` | the referee experiment: five objectives searched from the same starts and judged under the true cost |

## The frozen results

| script | output |
|---|---|
| `kappa_geometry_sweep.py` | the search in six cells (two geometries, three port ratios); the runs behind the main configuration |
| `main_config_export.py` | the main-configuration table and the ledger of every published percentage |
| `rerun_seating_seeds.py` | the search's budget curves per start family and seed (`SEAT_KAPPA=2`) |
| `mechanism_table.py` | per-boundary resource loads, hotspots and the ranking's mechanism |
| `energy_export.py` | dynamic energy of the frozen layouts by term |
| `objective_ablation.py` | the same-budget objective ablation |
| `bw_slice_k2.py` | the frozen pair re-scored across bandwidth; the identity G = eta r |
| `intra_die_integration.py`, `intra_die_correspondence.py` | the intra-die layer objective and its identity with the phase-diagram panel |
| `pipe_caliber_search.py` | the pipeline caliber as an objective (project record) |
| `timing_probe.py` | evaluator and search timings |

## The phase diagram and its inputs

| script | output |
|---|---|
| `fig_phase_isobar.py`, `fig_phase_isobar_print.py` | the phase diagram at the main configuration (`ISOBAR_KAPPA=2`), large and print versions, PNG and PDF |
| `sweep_axes.py`, `analyze_phase_diagram.py`, `certified_regions.py` | the per-axis bandwidth sweeps, the device plane and the region classification behind it |
| `run_scaling_probes.py`, `analyze_scaling_law.py` | the mapper-measured width law and its flip |
| `analyze_anchored_sweep.py`, `analyze_soft_lever.py` | readouts at the published anchors |

## External references

| script | output |
|---|---|
| `simba_workload.py`, `simba_targets.py`, `analyze_simba_validation.py`, `fig_simba_validation_color.py` | the Simba silicon reproduction and its figure |
| `booksim_bridge.py`, `analyze_booksim_slack.py` | the BookSim bridge with its conversion table and identity gates |
| `b7_handoff_probe.py`, `b7_s6_rerank.py`, `b3_shrunk_rerank.py`, `b_fanout_24x24_rerank.py`, `b_fanout_search.py`, `b_shrunk_fanout_rerank.py`, `b3_booksim_cost_probe.py` | the ranking checks of the hand-off term against the packet simulator |
| `b5_joint_exact.py` | the two-stage solve against a certified joint optimum |

## Paper figures

`plot_dac2027_v2.py` (current) and `plot_dac2027_v1.py` write complete
figure sets into `analysis/figures_dac2027/<run-id>/`; `fig_mechanism_ablation.py`,
`fig_condition_axes.py`, `fig_weave_inversion.py`, `ladder_v0.py` and
`check_c_crosstraffic.py` draw the standing exhibit figures.

## Earlier analyses

The `analyze_*.py` scripts not listed above (contention, offload, K/V
write, sequence scaling, scale tiers, weaves, routing parameters, static
energy, lower-link prices, robustness) are the studies that built and
validated the platform level by level; their results are in
`analysis/SUMMARY.en.md` and their standing figures in `analysis/`. The
`a2_*`, `run_a2_row_split.py`, `rerun_a4_column.py`, `derive_lower_link_prices.py`,
`tie_features.py`, `band_energy.py` and `a_bandwidth_slices.py` scripts are
the stage experiments named in the record.

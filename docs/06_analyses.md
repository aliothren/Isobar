# 06 Analyses

This page shows how to answer three questions:

| question | script | reads | writes |
|---|---|---|---|
| Where does the search's saving come from? | `export_gemma_pair.py` | a record from `run_experiments.py` | `results/exports/` |
| At which CIM speeds and link bandwidths does the placement matter at all? | `export_fig1_phase.py` | a record, plus the intra-die results | `results/exports/` |
| How much does placement matter inside one die? | `measure_intradie_instance.py`, `intradie_levers.py`, `search_withindie.py` | a CiMLoop run of one block | `results/reference/` |

All scripts produce data tables (CSV, JSON), not figures. The paper's figures are included as final images in `figures/`. Plotting from the tables is left to the user; the repository contains no plotting code.

## Where the saving comes from

`export_gemma_pair.py` compares the best baseline of a record with its search representative, hand-off by hand-off and resource by resource. Despite its name, it works on any record; its default is the Gemma-7B case of Fig. 5.

```bash
python3 scripts/export_gemma_pair.py --experiment custom --config <config id> --prefix mine
```

It prints the two latencies, η, r₀, G and the time saved per hand-off kind. It writes:

| file | content |
|---|---|
| `mine_candidates.csv` | every placement of the record: T split into CIM, digital, K/V and communication time; traffic; energy |
| `mine_stage_breakdown.csv` | for both placements, every hand-off: traffic, load on the busiest link, die port and unit port, the binding resource, service time |
| `mine_stage_delta.csv` | per hand-off, the time the search saves |
| `mine_resource_loads.csv` | per hand-off, the busiest links and their loads |
| `mine_bandwidth_equivalence.csv` | the link bandwidth the baseline would need to match the search's communication time (`B_eq_gbps`), with the unit interface held fixed |
| `mine_energy_breakdown.csv` | dynamic energy of each placement by component |
| `mine_seed_statistics.csv` | every annealer run, and the best run of each seed |
| `mine_pair_layouts.json` | the two placements, slot by slot |

## Where the placement matters: phase diagrams

`export_fig1_phase.py` scans CIM speed (row rate) against mesh link bandwidth. It does not search again. It takes the default fill, the built-in heuristics and random placement 0 from the record, and re-evaluates them at every point. For every point it computes:

- the latency of the default fill and of each built-in heuristic;
- where communication time falls below the rest of the latency (the boundary bandwidth B_c of each placement);
- the envelope B₋ to B₊ of these boundaries;
- where the latency spread between placements reaches 20%.

Below B₋, every placement is limited by communication. Above B₊, none is. In between, the placement decides.

```bash
python3 scripts/export_fig1_phase.py                                                 # the paper's Fig. 1 (Gemma-7B)
python3 scripts/export_fig1_phase.py --experiment custom --config <config id> --tag mine
```

| file | content |
|---|---|
| `mine_phase_boundary_curves.csv` | per row rate: R, the boundary B_c of every placement (`B_c_<rule>_gbps`), the envelope over the seven placements, i.e. the default fill, five heuristics and random placement 0 (`B_minus_seven_rules_gbps`, `B_plus_seven_rules_gbps`), and the 20% contour |
| `mine_phase_grid.csv` | per (row rate, bandwidth): T of every placement, the spread, and the region |
| `mine_phase_projection_points.csv` | published chips (ISAAC, HERMES, NeuRRAM, Mythic M1076, Simba) placed on the diagram, with their region |
| `mine_intradie_phase_curves.csv`, `mine_intradie_phase_candidates.csv` | the intra-die diagram (below) |
| `mine_phase_setup.json` | the model and axes |

To place your own chip on the diagram, take its row time t (µs per input row) and its link bandwidth B (GB/s per direction). Find the row of `phase_boundary_curves.csv` whose `t_row_us` is closest to t. The chip is communication-bound if B < `B_minus_seven_rules_gbps`, mapping-dependent if B lies between the two envelope columns, and not communication-bound above `B_plus_seven_rules_gbps`. The scan covers 0.02–40 M rows/s and 0.01–1000 GB/s; change `S_LO`, `S_HI`, `B_LO` and `B_HI` at the top of the script for other ranges.

`cost_grid.csv` in every record directory re-evaluates the best baseline and the search representative in the same way, on a coarser grid, without running this script.

## Placement inside one die

The intra-die analysis uses one FFN die: two operators on 8 macro slots, 70 possible assignments. It runs in three steps:

```bash
python3 scripts/measure_intradie_instance.py --shares   # container: CiMLoop run of one GPT-2-medium-class block, on-die traffic of every operator
python3 scripts/intradie_levers.py                      # per-macro traffic fitted to the measurement; worst/best assignment ratios
python3 scripts/search_withindie.py                     # exhaustive search of all assignments, and the annealer for comparison
```

Results go to `results/reference/` (`intradie_instance.json`, `intradie_levers.json`, `intradie_search.json`). `export_fig1_phase.py` turns them into the intra-die diagram's tables (`intradie_phase_*.csv`).

The measurement evaluates five on-die networks between the global buffer and the macros: a star, a mesh with the buffer at the centre or in a corner, an H-tree and a bus (`SCHEMES` in `intradie_levers.py`). The search and the diagram use the one named by `PROD`, the mesh with the buffer at the centre. Set `PROD` to another scheme label to analyse that network instead.

# cimsim: a placement-aware system-level simulator for LLM inference on ReRAM compute-in-memory

cimsim models an LLM inference machine built from ReRAM compute-in-memory
(CIM) dies as a **system**: package, die, macro, core, crossbar, with the
weights resident in the crossbars and only activations and partial sums
moving at run time. Its central object is the **physical placement** of the
mapped operators on that hierarchy, the level that macro-level CIM modelling
stops short of. The simulator prices what placement changes, the loads on
shared links and ports, and combines them with the compute, write and
digital costs into whole-model latency and dynamic energy. A phase diagram
says under which device and link conditions placement decides the cost, and
a deployment search chooses a placement when it does.

The simulator is built on [CiMLoop](https://github.com/mit-emze/cimloop)
(Timeloop + Accelergy + CIM extensions), whose per-operator mapping and
calibrated macro model are used unchanged as the lower layer. Everything
above it is an overlay in `workspace/`.

## Results, frozen 2026-09-22

Main configuration: a 2.7B-class model (d 2560, 32 layers), 512-token
serial prefill, 544 of 576 dies on a 24x24 mesh with XY routing, the
NeuRRAM row time of 10.14 us, ports at twice the link rate (kappa = 2),
0.4 GB/s per link direction (12.5 GB/s as the contrast).

| quantity | value | against |
|---|---|---|
| placement-search latency reduction, prefill | **9.91 %** (range over seeds 9.66 to 10.12 %) | the strongest evaluated baseline, a random fill at 2118.71 ms |
| the same, against the default stacked fill | 54.5 % | 4192.54 ms |
| the same at 12.5 GB/s | 0.70 % | strongest baseline at that bandwidth |
| decode, re-scored, no separate search | 1.57 % | strongest baseline |
| dynamic energy of the selected layout | -0.26 % | strongest baseline, 2.5229 J |
| objective ablation: distance and hop proxies select layouts | 11.4 % / 11.2 % slower | the resource-aware objective's best endpoint |
| intra-die assignment, GPT-2-medium class layer | 9.02 % lower layer latency | the contiguous assignment |
| placement-dependent bandwidth band, package level | 0.535 to 1.421 GB/s (2.66x) | seven named seating rules at the NeuRRAM rate |
| placement-dependent band, intra-die level | 0.606 to 1.616 GB/s (2.67x) | all 70 macro seatings, exhaustive |

Every number has a ledger row with its numerator, denominator and
statistic in [`workspace/analysis/main_config_results.md`](workspace/analysis/main_config_results.md)
and a one-line entry in [`workspace/analysis/paper_numbers.md`](workspace/analysis/paper_numbers.md).
The test suite pins them (443 tests).

## What the platform computes

- **Inputs.** The workload, the operator tiling with its tensor
  dependencies (produced by CiMLoop's mapper, taken as given), and the
  hardware and execution configuration (fabric geometry, link and port
  capacities, device row time, execution mode).
- **One evaluation of a candidate deployment.** The block partition fixes
  the logical communication; the die and macro placements fix the routed
  paths under the fixed XY rule; the loads on every link direction and every
  die port are accumulated per hand-off; the busiest resource of each
  hand-off, in link-time units with ports at the declared ratio, is
  combined with the execution relation (maximum within a stage, sum over
  stages for the package; overlap with compute inside a die) and with the
  compute, write and digital-unit costs into latency and dynamic energy.
  The cost model is written out in [`formulation.md`](formulation.md).
- **Phase analysis.** The same evaluation swept over device rate and link
  bandwidth over a set of placements gives the placement phase diagram,
  whose boundaries are the placement extrema of the communication cost.
- **Deployment search.** A dynamic program over block cuts, simulated
  annealing over die placement, and enumeration inside a die, all scoring
  candidates with the same evaluation, incrementally.
- **External references.** Published silicon placement measurements
  (Simba), a cycle-level router simulator (BookSim) on the same candidate
  placements, and the published link rates of HERMES and ISAAC projected
  onto the instance.

## Getting started

The simulator runs inside the CiMLoop container.

```bash
docker compose up -d                       # container cimloop-tutorial-1
docker exec cimloop-tutorial-1 bash -c "cd /home/workspace && python3 tests/run_tests.py"
```

Regenerating the frozen results, from `/home/workspace` inside the container:

```bash
python3 scripts/kappa_geometry_sweep.py     # the search per port ratio and geometry
python3 scripts/main_config_export.py       # the main-configuration table and ledger
python3 scripts/mechanism_table.py          # resource loads behind the ranking
python3 scripts/energy_export.py            # dynamic energy of the frozen layouts
ISOBAR_KAPPA=2 python3 scripts/fig_phase_isobar.py        # the phase diagram
python3 scripts/plot_dac2027_v2.py --run-id 20260921_v2   # the paper figure set
```

Container-written files are owned by root; change ownership before editing
them on the host. Clear `__pycache__` in the container before running a
script edited on the host.

## Repository map

| path | what it holds | guide |
|---|---|---|
| `workspace/analysis/` | results, records, figures and the documents that carry them | [README](workspace/analysis/README.md) |
| `workspace/scripts/` | the platform (fabric, placement, interconnect, workload, evaluator, search) and every analysis script | [README](workspace/scripts/README.md) |
| `workspace/models/` | CiMLoop's device, circuit, architecture and workload models, plus the fabric descriptions of this work | [README](workspace/models/README.md) |
| `workspace/tests/` | the guardrail suite that pins every published number | [README](workspace/tests/README.md) |
| `workspace/tools/` | BookSim, the router simulator used as an external reference | [README](workspace/tools/README.md) |
| `workspace/tutorials/` | CiMLoop's tutorial notebooks | [README](workspace/tutorials/README.md) |
| `workspace/outputs/` | Timeloop mapper output directories, regenerated by the runs | [README](workspace/outputs/README.md) |
| `io_study/` | the upstream CiMLoop tree kept for reference | [README](io_study/README.md) |
| `formulation.md` | the cost model as frozen | |
| `EXTERNAL_DEPENDENCIES.md` | external tools pinned by version, not committed | |

## Documents

- [`docs/`](docs/README.md): the user guide: setup, the fabric file, the workload account, evaluating a deployment, running the search, the phase diagram, BookSim checks, regenerating results.
- [`workspace/analysis/SUMMARY.en.md`](workspace/analysis/SUMMARY.en.md): the account of the platform and its results, written to the stance the paper takes.
- [`workspace/analysis/main_config_results.md`](workspace/analysis/main_config_results.md), [`paper_numbers.md`](workspace/analysis/paper_numbers.md), [`METRICS.md`](workspace/analysis/METRICS.md): the frozen numbers, their denominators and statistics.
- [`workspace/analysis/ANCHORS.md`](workspace/analysis/ANCHORS.md): every published bandwidth and device figure used as a reference, with its source and status.
- [`workspace/analysis/SEARCH_SPEC.en.md`](workspace/analysis/SEARCH_SPEC.en.md): the search's specification as implemented.
- [`workspace/analysis/FIXLIST.en.md`](workspace/analysis/FIXLIST.en.md): the chronological record of every model change and correction.
- [`workspace/analysis/figures_dac2027/`](workspace/analysis/figures_dac2027/README.md): the paper figure sets with their data and captions.

## Relation to CiMLoop, dependencies, license

cimsim is a fork of CiMLoop and keeps its structure, models and license.
CiMLoop's own tutorials and model guides remain under `workspace/tutorials/`
and `workspace/models/`. External tools that are not committed (NeuroSim,
BookSim sources) are listed with pinned versions in
[`EXTERNAL_DEPENDENCIES.md`](EXTERNAL_DEPENDENCIES.md). The license is in
[`LICENSE`](LICENSE); the upstream citations are in
[`citations.bib`](citations.bib).

# cimsim — System-Level CIM Simulator for LLM Inference (fork of CiMLoop)

This is a **fork of [CiMLoop](https://github.com/mit-emze/cimloop)** used as the
baseline for a system-level Compute-In-Memory (CIM) simulator targeting LLM
inference. We keep CiMLoop's per-op mapping / macro modeling untouched as the
lower layer, and add decoupled **overlays** on top for what CiMLoop abstracts
away: physical **placement / distance**, **latency** (incl. ReRAM write),
**crossbar-level** stats + per-pair communication, an **LLM workload** model
(sequence scaling + attention K/V write + KV-cache), and **value-dependent**
energy correction — plus a corrected **resident multi-die** hardware hierarchy.

> **Start here:** [`workspace/analysis/SUMMARY.en.md`](workspace/analysis/SUMMARY.en.md)
> is the full feature/results writeup (with charts). This section is a code map.

### What this fork adds

**Hardware model — resident multi-die `package → die → macro → core → crossbar`:**

- **`models/arch/3_chip/mlx_die.yaml`** — a DIE: 8 MB on-chip SRAM (`glb`) +
  8 macros + inter-macro `router` + 4 cores/macro.
- **`models/arch/2_tile/mlx_core.yaml`** — a CORE: local I/O buffers +
  8 crossbars (≈ 2 Mbit/core). Crossbar = the 256×256 4-bit ReRAM macro
  `wan_nature_2022` (reused) → 256 crossbars/die.
- **Weights are RESIDENT** (ReRAM is non-volatile / weight-stationary): the top
  level is `4_system/ws_chip2chip_link` (dies + die-to-die link, weights
  programmed once), **not** `fetch_weights_lpddr4` (which re-streams weights every
  inference — correct for volatile SRAM CiM, WRONG for ReRAM). GPT-2 medium is
  resident across ~18–36 dies. The only per-inference writes are attention K/V.

**Scripts (`workspace/scripts/`):**

- **`fabric.py`** + **`models/fabric/*.yaml`** — the physical fabric config:
  N-level generic (per-level counts, grid meshes, link params with DR
  calibration tags), the single source of truth for physical structure; stats
  parsing is demoted to a consistency sentinel. `CIMSIM_FABRIC=<yaml>` selects a
  variant for a whole run (e.g. the 2x4 macro-layout study ran with zero code
  changes).
- **`placement.py`** — the explicit, JSON-serializable Placement (per-level slot
  tables + verify()); `sequential_fill` reproduces the legacy floorplan bit for
  bit; `run_op(op, placement=p)` swaps a whole layout.
- **`traffic.py`** — TrafficExtraction: real multicast/reduction structure from
  the mapping (multicast trunks counted once, idle instances zero), tied to
  Timeloop's own counters by a divisibility guard. `build_flows` uses it by
  default; the uniform model survives only as the v0 comparison baseline.
- **`make_figures.py`** — one driver for every figure (7 stages); `--tag` runs
  config variants without clobbering canonical outputs.

- **`mlx_system.py`** — hardware config + physical `LAYOUT` / `HOP_LATENCY_NS`.
  `MLX_DIE_CONFIG`/`mlx_die_callfunc` (resident die hierarchy),
  `MLX_DIE_STREAMING_CONFIG` (old weight-streaming, kept for A/B only),
  `run_mlx_layer()` / `run_mlx_dnn()`, `n_dies_for_weights()`.
- **`placement_aware.py`** — topology overlay: `perceive → placement prior →
  distance model → re-aggregate`, for **energy** (`position_aware_cost`) and
  **latency** (`position_aware_latency`). Priors (`place_grid`/`place_linear`) and
  patterns (`to_center`/`tree`/`all_to_all`/`neighbor`) are pluggable. Key
  explicit assumption `reference_hops`; **relative** comparisons are robust.
- **`crossbar_stats.py`** — per-crossbar compute/weight/I-O (avg), per-level bus
  traffic, communication STRUCTURE (multicast/reduction/bit-slice) + `hierarchy()`.
- **`crossbar_comm.py`** — per-PAIR (node↔node) flows on a nested floorplan:
  `(src→dst, volume, distance)`, per-crossbar cost that **varies by position**,
  floorplan heatmap, geometry `level_max_hops`, and **`save_flows()`** which
  auto-dumps the detailed per-pair CSV+JSON to `analysis/comm/` on every run.
- **`llm_workload.py`** — GPT workload generator: sequence/phase scaling,
  attention **write cost + write latency** (ReRAM SET), **KV-cache**,
  **die-to-die** activation, and model-matched **histogram injection**.
  `run_op` returns energy + latency breakdown; `report_block` prints both tables.
- **`value_stats.py`** — general operand value-distribution loader (per model /
  layer type) for CiMLoop's data-value-dependent energy.
- **`crossbar_value.py`** — per-crossbar value-dependent energy MODE
  (`run_op(value_mode="uniform"|"per_crossbar")`): splits energy into a fixed
  floor + a value-dependent part, then scales the value part by each crossbar's
  own distribution activity (total conserved). Distribution source is pluggable
  (`synthetic` placeholder now, `weights` interface for real weight tiles).
- **`crossbar_value_real.py`** — the REAL per-crossbar value pipeline: real
  weights + real forward activations, tiled onto crossbars, each tile re-simulated
  with its own distributions (two stages — torch-only extract, cimloop-only
  simulate — to avoid an OpenMP segfault).
- **`analyze_system_gpt2.py`** — whole GPT-2 system-level three-way comparison
  (baseline / +overlays / offload) for a given `[S] [phase]`; dumps searched
  mappings + comparison chart.
- **`analyze_energy_vs_latency.py`** / **`analyze_seqlen_kv.py`** /
  **`analyze_region_locality.py`** / **`analyze_position_aware.py`** /
  **`analyze_crossbar_value_compare.py`** — the energy-vs-latency,
  sequence-scaling + KV-cache, region-placement (17.8%), placement×pattern, and
  device×workload per-crossbar-value case studies (charts to `analysis/`; every
  figure in the writeup has one of these as its committed source, and
  `make_figures.py` drives them all).
- **`analyze_contention_system.py`** / **`analyze_anchored_sweep.py`** /
  **`analyze_d2d.py`** / **`analyze_offload_contention.py`** /
  **`analyze_scale_tiers.py`** — the system-level contention study (whole-stack
  multipliers vs link bandwidth, both overlap ends, four wire accountings),
  its readout at published NoC bandwidths, the die-to-die single-pass /
  pipelined modes on the 48-die configuration, the attention-offloaded
  condition, and the 355M → 2.7B scale tiers.
- **`analyze_digital_sensitivity.py`** — how much of the model's time the
  digital vector unit (softmax / GELU / LayerNorm / residual) takes, swept over
  lanes × clock.
- **`op_breakdown.py`** — the per-operator cost ledger: one entry point, every
  cost item on its own row (all CiMLoop components, re-pricing, writes,
  die-to-die, digital unit), operator-type shares of the whole model under both
  conditions; outputs under `analysis/op_breakdown/`.
- **`utils.py`** — one-line change so `run_mapper` exposes its Timeloop output dir.

- **`EXTERNAL_DEPENDENCIES.md`** — pinned versions of external tools (e.g. the
  standalone NeuroSim) that are intentionally not committed.

Progress and per-fix details (motivation / what was done / result) are tracked
in [`workspace/analysis/FIXLIST.en.md`](workspace/analysis/FIXLIST.en.md).

### Local setup notes (differ from upstream)

- Use **`docker compose`** (v2 plugin), not the obsolete `docker-compose`.
- UID/GID are overridable via a local `.env` (`USER_UID` / `USER_GID` /
  `DOCKER_ARCH`); `.env` is git-ignored.
- Upstream CiMLoop is kept as the `upstream` git remote for pulling updates.
- ⚠️ The analysis scripts run mappers; keep them **sequential / 1 core**
  (`run_mlx_dnn` already does) so they don't starve other workloads.

### Quick examples (run inside the container)

```python
from scripts import mlx_system as mlx
from scripts import placement_aware as pa
from scripts import crossbar_stats as cbs
from scripts import crossbar_comm as cc
from scripts import llm_workload as lw

# 1) one layer on the resident die hierarchy, with position-aware cost
layer = mlx.list_layers("resnet18")[0]
r = mlx.run_mlx_layer(layer, config=mlx.MLX_DIE_CONFIG, callfunc=mlx.mlx_die_callfunc)
pa.print_report(r["analysis"], title="die / grid / to_center")

# 2) per-crossbar stats + per-pair (node↔node) flows + heatmap
cbs.report(r["result"].output_dir)
cc.summarize_and_plot(r["result"].output_dir, layer_name="00")

# 3) an LLM transformer block: energy + latency tables (prefill or decode).
#    every run auto-saves per-pair comm to analysis/comm/<op>_<phase>_comm.{csv,json}
res = lw.run_block(lw.GptConfig(), S=512, phase="prefill")
lw.report_block(res, title="prefill S=512")
```

Whole-model / whole-DNN studies (charts + CSV to `analysis/`):

```bash
python3 scripts/analyze_system_gpt2.py 512 prefill   # GPT-2 system-level (or: 512 decode)
python3 scripts/analyze_position_aware.py resnet18    # placement × pattern comparison
python3 scripts/analyze_contention_system.py 512 --shares   # contention at the system denominator
python3 scripts/analyze_anchored_sweep.py && python3 scripts/analyze_d2d.py \
  && python3 scripts/analyze_offload_contention.py && python3 scripts/analyze_scale_tiers.py
CIMSIM_FABRIC=models/fabric/mlx300_multidie48.yaml python3 scripts/op_breakdown.py   # per-operator ledger
```

### Tests

```bash
python3 tests/run_tests.py            # fast guardrail suite (165 tests, ~4 min)
python3 tests/run_tests.py --slow     # plus one real mapper run
```

The suite checks that the code matches the documented model (stats parsing
against an independent extraction, write/distance geometry against hand-derived
formulas, frozen goldens against silent changes) — it does not claim physical
accuracy, which waits for calibration data. `xfail_*` tests are the known-gap
list: each turns green when its gap (lower-level link energy, placement-aware
propagation, D2D) is closed. See `workspace/analysis/SUMMARY.en.md` §10.

See [`workspace/analysis/SUMMARY.en.md`](workspace/analysis/SUMMARY.en.md) for the full
results, charts, and the modeling-assumptions / limitations writeup.

---

The original CiMLoop README follows.

# CiMLoop (Timeloop+Accelergy v4)

Welcome to the repository for "CiMLoop: A Flexible, Accurate, and Fast
Compute-In-Memory Modeling Tool" by Tanner Andrulis, Vivienne Sze, and Joel S.
Emer. CiMLoop is a full-stack CiM modeling tool with flexible user-defined
systems and fast, accurate statistical energy modeling.

This repository contains tutorials, examples, documentation, and an artifact for
the CiMLoop paper. All are accessible through the Docker container.

For the paper or presentations relating to CiMLoop, please visit the [project website](https://emze.csail.mit.edu/cimloop).

## Quick Start

```bash
git clone https://github.com/mit-emze/cimloop.git
cd cimloop
export DOCKER_ARCH=<your processor architecture. supported: amd64>
# arm64 is also supported, BUT IS NOT STABLE. Use at your own risk.
# It is recommended to build Timeloop and Accelergy from source if you're
# using an ARM machine.
docker-compose pull
docker-compose up
# Connect to the container and explore CiMLoop! The README.md file
# in the workspace directory contains more information.

# If you have permission issues, please see the instructions in the
# docker-compose.yaml file on how to set the UID and GID.
```

The [README.md in the workspace](workspace/README.md) directory contains more
information on how to use CiMLoop.

## Tutorials
The [Timeloop and Accelergy tutorials]
(https://github.com/Accelergy-Project/timeloop-accelergy-exercises) are a
prerequisite for using CiMLoop as well, so please complete those first. CiMLoop
tutorials are available in the `workspace/tutorials` directory.

## CiMLoop Artifact
CiMLoop published results can be reproduced by running the
`models/arch/1_macro/*/_guide.ipynb` notebooks and the
`tutorials/demo_speed_accuracy.ipynb` notebook in the workspace.

## CiMLoop for Photonic Accelerators
CiMLoop includes a model of the [Albireo silicon photonic
accelerator](workspace/models/arch/1_macro/albireo_isca_2021) as described in
"Architecture-Level Modeling of Photonic Deep Neural Network Accelerators"
(Andrulis et al., ISPASS 2024).

## Documentation
Documentation can be found at the following locations:

- [CiMLoop Paper](CiMLoop.pdf)
- [Timeloop+Accelergy Documentation](https://timeloop.csail.mit.edu/)
- [Timeloop+Accelergy Exercises](https://github.com/Accelergy-Project/timeloop-accelergy-exercises)
- [Timeloop Front-End Documentation](https://accelergy-project.github.io/timeloopfe/)

## Contributing
If you would like to contribute models of memory cells, components,
architectures, workloads, or anything else, please submit a pull request. We
welcome contributions!

## Citation
If you use CiMLoop in your research, please cite the papers in
[citations.bib](citations.bib).


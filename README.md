# cimsim — System-Level CIM Simulator for LLM Inference (fork of CiMLoop)

This is a **fork of [CiMLoop](https://github.com/mit-emze/cimloop)** used as the
baseline for a system-level Compute-In-Memory (CIM) simulator targeting LLM
inference. We keep CiMLoop's mapping / architecture / macro modeling untouched as
the lower layer, and add a thin, decoupled **placement / topology-aware** layer
on top so that physical layout (where tiles/cores/dies sit, and how far data
travels) becomes a first-class, configurable cost — something CiMLoop abstracts
away.

### What this fork adds

**Hardware model (the company chip as CiMLoop arch files; package level TBD):**

- **`models/arch/3_chip/mlx_die.yaml`** — a DIE: 8 MB on-chip SRAM (`glb`) +
  8 macros + inter-macro `router` + 4 cores/macro.
- **`models/arch/2_tile/mlx_core.yaml`** — a CORE: local input/output buffers +
  N crossbars (default 8 ≈ 2 Mbit/core).
- A crossbar = the 256×256 4-bit ReRAM macro `wan_nature_2022` (reused).
  So the hierarchy is `die → macro → core → crossbar`.

**Scripts (`workspace/scripts/`):**

- **`mlx_system.py`** — single source of truth for the hardware config + the
  assumed physical `LAYOUT`. `MLX_CONFIG`/`mlx_callfunc` (Phase-1, reuses verified
  generic levels) and `MLX_DIE_CONFIG`/`mlx_die_callfunc` (explicit die hierarchy
  above). `run_mlx_layer()` / `run_mlx_dnn()` run a layer and return the CiMLoop
  result + position-aware analysis.
- **`placement_aware.py`** — the decoupled topology-aware overlay:
  `perceive(stats) → placement prior → distance model → re-aggregate`. Placement
  priors (`place_grid`, `place_linear`) and communication patterns
  (`DISTANCE_MODELS`: `to_center` / `tree` / `all_to_all` / `neighbor`) are
  **pluggable**. The key explicit assumption is `reference_hops` (how many hops
  CiMLoop's fixed per-word interconnect energy already represents); absolute
  multipliers depend on it, but **relative** placement/pattern comparisons do
  not. Distance is applied ONLY to true interconnect, never compute/storage.
- **`crossbar_stats.py`** — per-CROSSBAR statistics: compute / weight / input /
  output per crossbar (average), per-level bus traffic (NoC / SRAM / DRAM), and
  the communication STRUCTURE per spatial level (multicast vs reduction vs
  bit-slice, parsed from the mapping).
- **`crossbar_comm.py`** — per-PAIR (node↔node) communication: lays the crossbars
  on a nested floorplan, walks the multicast/reduction tree to produce
  `(src → dst, volume, distance)` flows, and reports per-crossbar communication
  **cost that varies by physical position** (same volume, different cost) + a
  floorplan heatmap. This is the bridge from aggregate bus traffic to "which
  crossbar talks to which, how much, how far."
- **`analyze_position_aware.py`** — real-DNN case study: runs a DNN layer-by-layer
  (sequential, 1 core), caches per-layer perceived data, and compares
  communication cost across placements × patterns (relative, with charts/CSV).
- **`utils.py`** — one-line change so `run_mapper` exposes its Timeloop output
  directory (the overlay/stats parse `timeloop-mapper.stats.txt`).

- **`EXTERNAL_DEPENDENCIES.md`** — pinned versions of external tools (e.g. the
  standalone NeuroSim) that are intentionally not committed.

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

layer = mlx.list_layers("resnet18")[0]

# 1) one layer on the explicit die hierarchy, with position-aware cost
r = mlx.run_mlx_layer(layer, config=mlx.MLX_DIE_CONFIG, callfunc=mlx.mlx_die_callfunc)
pa.print_report(r["analysis"], title="die / grid / to_center")

# 2) per-crossbar stats + communication structure
cbs.report(r["result"].output_dir)

# 3) per-pair (node↔node) flows + per-crossbar position cost + heatmap
cc.summarize_and_plot(r["result"].output_dir, layer_name="00")
```

Whole-DNN placement/pattern comparison (writes charts/CSV to `analysis/`):

```bash
python3 scripts/analyze_position_aware.py resnet18
```

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


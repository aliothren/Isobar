# cimsim — System-Level CIM Simulator for LLM Inference (fork of CiMLoop)

This is a **fork of [CiMLoop](https://github.com/mit-emze/cimloop)** used as the
baseline for a system-level Compute-In-Memory (CIM) simulator targeting LLM
inference. We keep CiMLoop's mapping / architecture / macro modeling untouched as
the lower layer, and add a thin, decoupled **placement / topology-aware** layer
on top so that physical layout (where tiles/cores/dies sit, and how far data
travels) becomes a first-class, configurable cost — something CiMLoop abstracts
away.

### What this fork adds

- **`workspace/scripts/placement_aware.py`** — a decoupled overlay on top of a
  CiMLoop run: `perceive(stats) → placement prior → distance model → re-aggregate`.
  It reads the per-component data movement CiMLoop already produced, assigns
  physical coordinates to instances, and reports a position-aware communication
  cost next to the position-blind baseline. Placement priors (`place_grid`,
  `place_linear`, ...) and communication patterns (`DISTANCE_MODELS`:
  `to_center` / `tree` / `all_to_all` / `neighbor`) are **pluggable** so we can
  explore different settings before the real topology is confirmed. Distance is
  applied ONLY to true interconnect (router / `inter_*_spatial`), never to
  compute or storage.
- **`workspace/scripts/mlx_system.py`** — pins the hardware we currently model
  (a 256×256 4-bit ReRAM crossbar, `wan_nature_2022`, placed in a tile/chip/DRAM
  system), documents the company-chip → CiMLoop level mapping, holds the assumed
  physical `LAYOUT`, and provides `run_mlx_layer()` / `run_mlx_dnn()` that run a
  layer and return baseline + position-aware cost.
- **`workspace/scripts/utils.py`** — one-line change so `run_mapper` exposes its
  Timeloop output directory (the overlay parses `timeloop-mapper.stats.txt`).
- **`EXTERNAL_DEPENDENCIES.md`** — pinned versions of external tools (e.g. the
  standalone NeuroSim) that are intentionally not committed.

### Local setup notes (differ from upstream)

- Use **`docker compose`** (v2 plugin), not the obsolete `docker-compose`.
- UID/GID are overridable via a local `.env` (`USER_UID` / `USER_GID` /
  `DOCKER_ARCH`); `.env` is git-ignored.
- Upstream CiMLoop is kept as the `upstream` git remote for pulling updates.

### Quick example

```python
from scripts import mlx_system as mlx
from scripts import placement_aware as pa

layer = mlx.list_layers("resnet18")[0]
r = mlx.run_mlx_layer(layer, place_fn=pa.place_grid)     # one mapper run
pa.print_report(r["analysis"], title="grid / to_center")
# swap placement prior or LAYOUT["router"]["pattern"] to compare settings.
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


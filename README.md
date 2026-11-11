# Isobar

Isobar is a simulation framework for **topology-aware mapping in analog compute-in-memory (CIM) chiplet systems**. A large language model deployed on analog CIM spreads its weight matrices over hundreds or thousands of dies. Where each block is placed decides which links and ports the data compete for. Isobar estimates the resulting latency and dynamic energy for a given model, hardware configuration and placement, and searches for better placements.

This repository contains the framework, the experiment scripts, and instructions for reproducing the results of the paper

> **Scaling Up Analog CIM: A Simulation Framework for Topology-Aware Mapping**
>
> [[arXiv](https://arxiv.org/abs/2611.08399)] [[PDF](paper/Isobar_Arxiv.pdf)]

## What you can do with it

| task | how | guide |
|---|---|---|
| describe a CIM chip and package | edit a fabric file in `workspace/models/fabric/` | [03 Hardware](docs/03_hardware.md) |
| add a model and measure its operator costs with CiMLoop | `measure_accounts.py` | [04 Models](docs/04_models.md) |
| evaluate a deployment and search for a better placement | `run_experiments.py --custom ...` | [05 Deployments](docs/05_deployments.md) |
| see where the savings come from, and how bandwidth or CIM speed changes the picture | `export_gemma_pair.py`, `export_fig1_phase.py` | [06 Analyses](docs/06_analyses.md) |
| check the communication model against BookSim or silicon data | `run_booksim_libraries.py`, `run_simba_reference.py` | [07 Validation](docs/07_validation.md) |
| regenerate every number of the paper | the stages in order | [08 Reproducing the paper](docs/08_reproduce_paper.md) |
| compare energy per request with GPUs | `gpu_comparison/scripts/run_all.sh` | [09 GPU comparison](docs/09_gpu_comparison.md) |

New users should read [01 Setup](docs/01_setup.md) and [02 How Isobar works](docs/02_how_isobar_works.md) first.

## Quick start

Everything below runs in the CiMLoop container, so nothing has to be installed on the host except Docker. [01 Setup](docs/01_setup.md) shows how to run everything except the CiMLoop measurements on the host instead.

```bash
# in the repository root: start the container and open a shell in it as your own user
USER_UID=$(id -u) USER_GID=$(id -g) docker compose up -d       # add DOCKER_ARCH=arm64 on Apple silicon
docker exec -it -u $(id -u):$(id -g) isobar bash

# in the container
cd /home/workspace
python3 scripts/measure_accounts.py opt1.3b 512                                   # per-operator costs of OPT-1.3B (CiMLoop)
python3 scripts/run_experiments.py --custom --model opt1.3b --n-random 20 --seeds 0   # evaluate and search, a few seconds
```

The last command prints the best baseline placement, the searched placement and the savings. The full record is in `workspace/results/records/custom/`.

## Repository layout

```
paper/            the paper
figures/          the seven paper figures (PDF, PNG preview)
docs/             the user guide
workspace/
  scripts/        the framework and every experiment and analysis script
  models/         CiMLoop models of the CIM macro and die, and the fabric files
  gpu_comparison/ energy per request against GPU baselines
  tools/          how to build BookSim 2 (used for validation)
  results/        results of every stage: costs, records, analysis tables (created on first run, not tracked)
  outputs/        temporary CiMLoop run folders of the measurements (not tracked)
```

## Citation

If you use Isobar, please cite the paper; the BibTeX entry is in [CITATION.bib](CITATION.bib). Isobar builds on CiMLoop, Timeloop and Accelergy and uses BookSim 2 for validation; their references are in the same file.

## Acknowledgment

We thank TetraMem, Inc. for the research collaboration grant and the computation resources that supported this work.

## License

MIT license, see [LICENSE](LICENSE).

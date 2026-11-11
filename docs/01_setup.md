# 01 Setup

This page gets you from a fresh checkout to a first completed evaluation. It covers what to install, where each command is run, and how to check that the result is complete.

## Where commands are run

This guide uses three locations. Each code block says which one it expects.

| label | location | used for |
|---|---|---|
| **repo** | the repository root (the folder with `docker-compose.yaml`) | starting the container, building BookSim |
| **host** | `workspace/` on your machine | every Python script that does not need CiMLoop |
| **container** | `/home/workspace` inside the container (the same folder, mounted) | the CiMLoop measurements (`measure_*.py`) |

## What you need

| purpose | requirement |
|---|---|
| evaluation, search, analyses, validation, GPU comparison | Python 3.10 or newer with **numpy** and **pyyaml**; nothing else |
| measuring per-operator costs with CiMLoop | Docker; the public CiMLoop image (Timeloop, Accelergy, CiMLoop, pytimeloop), pulled on first start |
| BookSim validation (optional) | g++, flex and bison to build BookSim 2 |
| regenerating the value histograms (optional) | torch and transformers, plus a download of facebook/opt-2.7b |

The repository does **not** include measured per-operator costs (the *accounts*, see [04 Models](04_models.md)). The first run therefore measures one account in the container and then evaluates it on the host.

## Install

```bash
# repo: start the container (DOCKER_ARCH defaults to amd64; set DOCKER_ARCH=arm64 on Apple silicon)
USER_UID=$(id -u) USER_GID=$(id -g) docker compose up -d

# host: Python environment
conda create -n isobar python=3.11 numpy pyyaml
conda activate isobar
```

`docker-compose.yaml` mounts `workspace/` at `/home/workspace` inside a container named `isobar`. To open a shell in it:

```bash
# repo or host
docker exec -it -u $(id -u):$(id -g) isobar bash
cd /home/workspace
```

`USER_UID` and `USER_GID` tell the image which user ids its own processes use (default 1000). `-u $(id -u):$(id -g)` makes the shell run as you, so the files the container writes in `workspace/` are owned by you; without it they belong to root. Use the same `-u` with every `docker exec`, including one-off commands such as `docker exec -u $(id -u):$(id -g) isobar bash -c "cd /home/workspace && python3 scripts/measure_accounts.py opt1.3b 512"`.

## First run

```bash
# container: measure the per-operator costs of OPT-1.3B at 512 tokens
python3 scripts/measure_accounts.py opt1.3b 512
```

This runs CiMLoop once per operator and phase. It writes `results/accounts/opt1.3b_S512.json`.

```bash
# host: evaluate OPT-1.3B prefill on the reference hardware, with a small search budget
python3 scripts/run_experiments.py --custom --model opt1.3b --n-random 20 --seeds 0
```

This takes a few seconds. It prints one line:

```
[opt1.3b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1] 168 dies on 13x13 | strongest random_s7 1061.3 ms (rule nmap_greedy, random best-of-20) | G median 13.2% ... | eta 23.3% r 56.7% | ...
```

The line reports the best baseline placement and its latency. It also reports the end-to-end saving (G) and communication saving (eta) of the searched placement; [05 Deployments](05_deployments.md) explains every field. The run creates `results/records/custom/` with `configs.jsonl`, `summary.csv`, `candidates.csv`, `runs.csv`, `cost_grid.csv` and `manifest.json`. If these files exist and `summary.csv` has a row with status `done`, the installation works end to end.

## BookSim 2 (optional)

BookSim is needed only to rerun the validation against packet-level simulation ([07 Validation](07_validation.md)). [workspace/tools/README.md](../workspace/tools/README.md) describes how to fetch, patch and build it (repo). The binary goes to `workspace/tools/booksim2/src/booksim`. If it only runs inside the container, the scripts call it through `docker exec isobar`; set `ISOBAR_CONTAINER` if your container has another name.

## Where results go

Everything is written under `workspace/results/`; set `ISOBAR_RESULTS=/path/to/results` to use another location.

| folder | content | written by |
|---|---|---|
| `results/accounts/` | per-operator costs of each model, LM-head costs | `measure_accounts.py`, `measure_model_end.py` |
| `results/reference/` | the 2.7B-class reference costs, the intra-die instance, the Simba reference | `measure_reference_account.py`, `measure_intradie_instance.py`, `intradie_levers.py`, `search_withindie.py`, `run_simba_reference.py` |
| `results/records/<name>/` | one record per evaluated deployment, plus summary tables | `run_experiments.py` |
| `results/booksim/` | BookSim candidate libraries | `run_booksim_libraries.py` |
| `results/exports/` | analysis tables, including those behind the paper's figures | `export_*.py`, `run_timing.py`, `run_search_trajectories.py` |
| `results/gpu_comparison/` | energy per request | `gpu_comparison/scripts/` |

CiMLoop's temporary run folders go to `workspace/outputs/`.

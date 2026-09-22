# cimsim user guide

This guide covers running the simulator on your own hardware
description, workload or deployment: which feature answers which
question, where the inputs go, which script or function is the entry
point, and what command to run. Every command and snippet here was run
as written on the frozen tree of 2026-09-22.

Read in order the first time. Afterwards each page stands on its own.

| page | question it answers |
|---|---|
| [01 Setup](01_setup.md) | how to get a working container and confirm it with the test suite |
| [02 Concepts](02_concepts.md) | the five objects every run touches: fabric, workload account, deployment, hand-off term, score |
| [03 Hardware](03_hardware.md) | how to describe a chip or package in a fabric file, and which numbers the evaluator takes from elsewhere |
| [04 Workload](04_workload.md) | how the per-operator account of a model is produced and what changing the model involves |
| [05 Evaluate](05_evaluate.md) | how to price one given deployment: latency, energy, per-hand-off loads, the binding resource |
| [06 Search](06_search.md) | how to run the placement search on your configuration and how to read its statistics |
| [07 Phase diagram](07_phase_diagram.md) | when placement matters on your hardware, and how to add your own reference chip |
| [08 External checks](08_external_checks.md) | how to judge a hand-off with BookSim, and what that check can and cannot say |
| [09 Results and figures](09_results_and_figures.md) | where the frozen numbers live, how to regenerate them, and how the tests guard them |
| [10 Scope and FAQ](10_scope_and_faq.md) | what the model does not price, and the errors people meet first |

## Ten minutes

```bash
# on the host, in the repository root
DOCKER_ARCH=amd64 USER_UID=$(id -u) USER_GID=$(id -g) docker compose up -d
docker exec cimloop-tutorial-1 bash -c "cd /home/workspace && python3 tests/run_tests.py"
```

The last line prints one row per test and ends with a summary line
beginning `443 passed, 0 failed`.
From here on every command is given as it is typed inside the container,
from `/home/workspace`:

```bash
docker exec -it cimloop-tutorial-1 bash
cd /home/workspace
```

Generate a baseline deployment, price it, and run a short search, all
on the main configuration:

```bash
python3 scripts/cimsim_cli.py baseline --rule clustered --out analysis/clustered.json
python3 scripts/cimsim_cli.py evaluate --deployment analysis/clustered.json --bandwidth 0.4
python3 scripts/cimsim_cli.py search --bandwidth 0.4 --starts random --seeds 0 --steps 200 --out-dir analysis/quick_search
```

The one command that reproduces every number in the top-level README is
`python3 scripts/main_config_export.py`; it writes
`analysis/main_config_results.md` and prints the ledger rows.

## The three things you will change

1. **The hardware.** A fabric file under `models/fabric/` (page 03).
2. **The deployment or the search setting.** A deployment is a JSON file
   with the block cuts and the die seats of every operator set (pages 05
   and 06).
3. **The workload.** A per-operator account produced by one mapper run
   (page 04).

Everything else (the port ratio, the link bandwidth, the device speed
scale, the execution phase, the package-link constants) is a command-line
option of `scripts/cimsim_cli.py`, which wraps the evaluator, the
baselines, the search, the phase band and the BookSim check for any
fabric file and any account. The frozen experiments set the same knobs at
the top of their scripts.

## Where the entry points are

| task | command | notes |
|---|---|---|
| tests | `python3 tests/run_tests.py` | `--slow` adds the mapper run and the BookSim gates |
| validate a fabric file | `python3 scripts/cimsim_cli.py phase --fabric F --out x.json` | any subcommand loads and validates `--fabric`; `CIMSIM_FABRIC=<file>` selects the mapper-side default |
| per-operator account of a model | `python3 scripts/run_2p7b_block.py [hist]` | the model shape is a constant at the top; a mapper run |
| a named baseline deployment | `python3 scripts/cimsim_cli.py baseline --rule R --out pi.json` | seven rules |
| price one deployment | `python3 scripts/cimsim_cli.py evaluate --deployment pi.json --bandwidth B` | latency, energy, per-hand-off loads and binding resource |
| placement search | `python3 scripts/cimsim_cli.py search --bandwidth B --out-dir D` | the frozen protocol scripts are `kappa_geometry_sweep.py` and `main_config_export.py` |
| intra-die assignment | `python3 scripts/search_withindie.py` | exhaustive on the shipped instance |
| placement band of a fabric | `python3 scripts/cimsim_cli.py phase --bandwidths B1,B2` | the full phase diagram: `ISOBAR_KAPPA=2 python3 scripts/fig_phase_isobar.py` |
| BookSim check of a hand-off | `python3 scripts/cimsim_cli.py booksim --deployment pi.json --handoff ffn2@L3` | needs the built binary |
| the frozen tables and figure set | `python3 scripts/main_config_export.py`, `python3 scripts/plot_dac2027_v2.py --run-id <id>` | |

The common options of every `cimsim_cli.py` subcommand: `--fabric`,
`--workload` (the account JSON), `--kappa` (default: the fabric's
`ports: {ratio}` on the die level), `--phases`, `--device-scale`,
`--d2d-pj-per-word`, `--d2d-ns-per-hop`. `python3 scripts/cimsim_cli.py
<subcommand> --help` lists the rest.

## Conventions used in this guide

- Paths are relative to `/home/workspace` inside the container unless they
  start with `docs/`, which is at the repository root on the host.
- The command line covers the everyday tasks. The Python snippets that
  remain in the guide are for what the command line does not expose;
  save one as a file under `analysis/` (an ignored folder) and run it
  with `python3 <file>`. Each starts with the two lines that put the
  repository on the import path.
- Files written by the container belong to root on the host. Run
  `chown -R $(id -u):$(id -g) .` inside the container before editing them
  on the host.
- Python caches bytecode. After editing a script on the host, run
  `find scripts -name __pycache__ -exec rm -rf {} +` inside the container
  before running it.

# workspace: the simulator and its results

Everything cimsim adds on top of CiMLoop lives here. The folders:

| folder | content | guide |
|---|---|---|
| `analysis/` | results, records and figures: the frozen tables, the documents, the figure sets, and the JSON artifacts the scripts write | [analysis/README.md](analysis/README.md) |
| `scripts/` | the platform (fabric, placement, interconnect, workload, evaluator, search) and the analysis scripts that produce every result | [scripts/README.md](scripts/README.md) |
| `models/` | CiMLoop's device, circuit, architecture and workload models, and the fabric descriptions of this work in `models/fabric/` | [models/README.md](models/README.md) |
| `tests/` | the guardrail suite; every published number is pinned here | [tests/README.md](tests/README.md) |
| `tools/` | BookSim, the cycle-level router simulator used as an external reference | [tools/README.md](tools/README.md) |
| `tutorials/` | CiMLoop's tutorial notebooks | [tutorials/README.md](tutorials/README.md) |
| `outputs/` | Timeloop mapper output directories, one per run | [outputs/README.md](outputs/README.md) |

## Running

All scripts run inside the container, from `/home/workspace`:

```bash
docker exec cimloop-tutorial-1 bash -c "cd /home/workspace && python3 tests/run_tests.py"
docker exec cimloop-tutorial-1 bash -c "cd /home/workspace && python3 scripts/main_config_export.py"
```

Two practical rules. Files the container writes are owned by root, so
change their ownership before editing them on the host. Python caches
bytecode; clear `__pycache__` inside the container before running a script
you edited on the host.

## Where to read

Start with [`analysis/SUMMARY.en.md`](analysis/SUMMARY.en.md) for the
platform and its results, [`analysis/main_config_results.md`](analysis/main_config_results.md)
for the frozen main-configuration numbers with their denominators, and
[`analysis/FIXLIST.en.md`](analysis/FIXLIST.en.md) for the chronological
record of every change. The cost model is written out in
[`../formulation.md`](../formulation.md).

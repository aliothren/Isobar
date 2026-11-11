# workspace: the framework and its results

Everything Isobar adds on top of CiMLoop lives here.

| folder | content | guide |
|---|---|---|
| `scripts/` | the framework (fabric, interconnect, workload, evaluator, search) and every analysis script | [scripts/README.md](scripts/README.md) |
| `analysis/` | the records, exports and figure sets, and the documents that carry the results | [analysis/README.md](analysis/README.md) |
| `gpu_comparison/` | full-request energy against GPU baselines (Table III) | `gpu_comparison/REPORT_gpu_comparison.md` |
| `models/` | CiMLoop's device, circuit, architecture and workload models, and the fabric files in `models/fabric/` | [models/fabric/README.md](models/fabric/README.md) |
| `tests/` | the guardrail suite of the platform modules | [tests/README.md](tests/README.md) |
| `tools/` | BookSim 2, the packet-level reference | [tools/README.md](tools/README.md) |
| `tutorials/` | CiMLoop's tutorial notebooks | |
| `outputs/` | Timeloop mapper run directories (→ `/data`) | |

## Running

The CiMLoop measurements run in the container, from `/home/workspace` (`docker exec -it -u $(id -u):$(id -g) cimloop-tutorial-1 bash`). Everything else also runs on the host from `workspace/` with the `far` environment. Clear `__pycache__` in the container before running a script edited on the host. [`../docs/02_final_pipeline.md`](../docs/02_final_pipeline.md) gives the commands of every stage.

## Where to read

- [`analysis/SUMMARY.en.md`](analysis/SUMMARY.en.md): the framework and its results.
- [`analysis/paper_numbers.md`](analysis/paper_numbers.md): every number of the paper with its source.
- [`../formulation.md`](../formulation.md): the cost model.

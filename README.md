# Isobar: a simulation framework for topology-aware mapping on analog CIM chiplet systems

This repository is the development tree of **Isobar**, the framework of the paper

> **Scaling Up Analog CIM: A Simulation Framework for Topology-Aware Mapping**
> Yuxin Ren, Danella Zhao, Huanrui Yang — The University of Arizona
> ([Isobar_Arxiv.pdf](Isobar_Arxiv.pdf))

It keeps the full history of the work: every script, record and figure set. The **`release` branch** holds the same final code reorganised for distribution, together with its documentation, the final figures and the paper; nothing in it depends on this branch's history.

Isobar models LLM inference on ReRAM compute-in-memory (CIM) chiplet systems. The system has a package of CIM dies on a 2-D mesh, macros of RRAM crossbars on each die, and digital units with their own K/V memory for the input-dependent attention. Weights are resident, so only activations and partial sums move. The framework derives every hand-off between operators from the legal CIM decompositions and routes it onto links, die ports and digital-unit interfaces. It prices each mapping p = (γ, α, β) as T = R + H and searches over the mapping. Per-operator costs come from CiMLoop (Timeloop + Accelergy) runs of a NeuRRAM-class macro.

## Final results (paper)

| result | value |
|---|---|
| Gemma-7B prefill, 1,232 dies, 0.4 GB/s links: searched mapping vs. the strongest baseline (prescribed rules + 500 random layouts) | communication −23.3%, end-to-end latency −18.6%, dynamic energy −0.65% |
| the same against the default fill | 77.7% lower latency |
| bandwidth the strongest baseline needs to match the searched mapping's communication time | 0.52 GB/s (+30.4%) |
| OPT-6.7B / Gemma-7B / OPT-13B in three resource configurations (8 macros, 16 macros, four head-group units) | communication −14.8 to −24.0%, end-to-end −10.6 to −18.7% (seed medians) |
| bandwidth envelope B₊/B₋ at the reference CIM speed | 2.67× over 70 intra-die macro assignments, 4.17× over six Gemma-7B package layouts |
| silicon reference (Simba seating experiment) | 2.40× predicted vs. 2.53× measured, 5.1% error |
| BookSim rank agreement (three candidate libraries) | Spearman ρ 0.966 / 0.984 / 0.973 |
| selection quality against BookSim | Isobar 0.3–12.2% above the library optimum, word-hops 40.4–51.7% |
| incremental evaluation / full search, 512–2,200 dies | 1.4–15.9 ms per move (26–38× faster than a full evaluation); 2.5–127.7 s per search |
| OPT-13B QKV split on a 49 × 49 mesh, row vs. column | 13.39 → 11.22 s (η 17.5%) vs. 5.16 → 4.10 s (η 25.1%); QKV-to-unit traffic 6.29 vs. 0.315 GB |
| modeled CIM dynamic energy per request vs. GPU | OPT-13B 58.61 J (93×) / 48.53 J (113×) vs. A100; Gemma-7B 11.45 J (166×) / 9.85 J (193×) vs. Jetson AGX Thor |

[`workspace/analysis/paper_numbers.md`](workspace/analysis/paper_numbers.md) gives every number with its workload, configuration, denominator, statistic and source file. [`workspace/analysis/SUMMARY.en.md`](workspace/analysis/SUMMARY.en.md) is the account of the framework and the results.

## Where the final data and figures are

| what | where |
|---|---|
| per-operator accounts | `workspace/analysis/scale_2p7b_per_op.json` (2.7B-class reference), `workspace/analysis/v4/accounts/` (models), `workspace/analysis/v4/models/model_end_costs.json` (LM head) |
| deployment records | `workspace/analysis/v4/<unit>/configs.jsonl` (`analysis/v4` links to `/data/yuxinr/cimloop/analysis_v4`) |
| BookSim libraries | `workspace/analysis/v3/e3_offload/`, `workspace/analysis/v3/e3_k2/` |
| the tables behind the figures and tables | `workspace/analysis/v7/` and `workspace/analysis/v6/` (described in `v7/plot_data_dictionary.md`) |
| the final figures | `workspace/analysis/figures_dac2027/20261019_v3/composites/` ([README](workspace/analysis/figures_dac2027/README.md)) |
| the GPU energy comparison (Table III) | `workspace/gpu_comparison/` (`REPORT_gpu_comparison.md`, `AUDIT_energy.md`) |

[`docs/02_final_pipeline.md`](docs/02_final_pipeline.md) lists the commands that produced each of them.

## Repository map

| path | content | guide |
|---|---|---|
| `docs/` | setup and the final pipeline on this branch | [README](docs/README.md) |
| `formulation.md` | the cost model | |
| `workspace/scripts/` | the framework and every analysis script | [README](workspace/scripts/README.md) |
| `workspace/analysis/` | records, exports, figures and the documents that carry them | [README](workspace/analysis/README.md) |
| `workspace/models/` | CiMLoop models and the fabric files of this work | [fabric README](workspace/models/fabric/README.md) |
| `workspace/gpu_comparison/` | full-request energy against GPU baselines | `REPORT_gpu_comparison.md` |
| `workspace/tests/` | the guardrail suite of the platform modules | [README](workspace/tests/README.md) |
| `workspace/tools/` | BookSim 2 (built locally, patched) | [README](workspace/tools/README.md) |
| `workspace/tutorials/`, `io_study/` | CiMLoop's tutorials and the upstream tree, for reference | |

## Relation to CiMLoop, dependencies, license

Isobar is a fork of [CiMLoop](https://github.com/mit-emze/cimloop) and keeps its structure, models and MIT license; CiMLoop's per-operator mapping and calibrated macro model are used unchanged as the lower layer. External tools that are not committed (BookSim sources, NeuroSim) are listed in [`EXTERNAL_DEPENDENCIES.md`](EXTERNAL_DEPENDENCIES.md). Upstream citations: [`citations.bib`](citations.bib).

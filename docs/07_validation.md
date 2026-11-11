# 07 Validation

This page shows how to check Isobar's communication model against measured silicon and against the BookSim cycle-level network simulator, how to run BookSim on your own traffic, and how to measure the framework's own speed. Commands run from `workspace/` (host) unless marked otherwise.

## Which communication model is used where

Isobar has two ways to estimate the time of a transfer between dies:

| model | what it counts | used by |
|---|---|---|
| **resource bound** | load on the busiest link or port divided by its bandwidth, plus the hop delay of the longest route, once per hand-off | every deployment evaluation and search (`search_eval.py`) |
| **packet estimate** | the data split into 128-byte packets; each source sends its packets one after another, and each packet pays the hop delay of its route | the Simba reference only (`run_simba_reference.py`) |

The resource bound assumes that packets stream back to back. That holds when a transfer moves much more data than one packet, as the LLM hand-offs do: megabytes per hand-off.

BookSim confirms this. On the candidate libraries below, BookSim's completion times are 1.01–1.46 times the resource bound, and its ranking of the placements agrees with Isobar's.

Simba's seating experiment is the opposite case. A small layer is spread over four chiplets, so per-packet latency dominates and grows with distance. Only the packet estimate captures that.

## Silicon: the Simba seating experiment

Simba (Shao et al., MICRO'19) ran one ResNet-50 layer on four chiplets. It moved the chiplets from adjacent positions to the package corners, and the measured latency rose to 2.53×. `run_simba_reference.py` rebuilds this experiment from Simba's published parameters (`models/fabric/simba.yaml`, closed form, no simulator):

```bash
python3 scripts/run_simba_reference.py      # -> results/reference/simba_seating.json, a few seconds
```

It prints, for each of the five seatings, the measured ratio and both estimates. The last line compares the farthest seating with the adjacent one:

| | farthest / adjacent |
|---|---|
| resource bound | 1.007× (the busiest link carries the same data at any distance) |
| packet estimate | 2.40× |
| measured | 2.53× |

## BookSim: candidate libraries

`run_booksim_libraries.py` builds small instances of one or two transformer layers of the 2.7B-class reference, on 6 × 6 or 8 × 8 meshes. Each instance gets about 70 placements:

- the default fill and the built-in heuristics;
- 50 random placements;
- the results of searches under four objectives.

Every placement is timed both by Isobar's resource bound and by BookSim. The script needs the reference account ([04 Models](04_models.md)) and the BookSim binary. Build BookSim and check it with `python3 scripts/booksim_bridge.py --check`, as described in [workspace/tools/README.md](../workspace/tools/README.md).

```bash
python3 scripts/run_booksim_libraries.py                   # all four libraries, about 20 minutes
python3 scripts/run_booksim_libraries.py --set onchip      # only the on-chip library, about 3 minutes
python3 scripts/run_booksim_libraries.py --no-booksim      # Isobar's times only
python3 scripts/run_booksim_libraries.py --redo            # rebuild libraries that already exist
```

| set | instances | used in |
|---|---|---|
| `offload` | one layer prefill (6 × 6), one layer decode (6 × 6), two layers prefill (8 × 8); attention on a digital unit | Fig. 3(b), Fig. 4(b) |
| `onchip` | one layer prefill (6 × 6), attention on a CIM die | Fig. 4(a) |

Each library is written to `results/booksim/<set>/library_<instance>.json`, and the script prints its rank correlation between Isobar and BookSim. `export_fig3_fig4.py` turns the libraries into tables:

- the correlation and the BookSim / bound ratio per library;
- groups of placements with equal word-hops but different BookSim times;
- the BookSim quality of the placement that each metric would select.

The BookSim settings follow Simba's network; [workspace/tools/README.md](../workspace/tools/README.md) lists them.

## BookSim on your own traffic

Run from `workspace/`, on the machine where BookSim was built:

```python
import sys; sys.path.insert(0, ".")
from scripts import booksim_bridge as bb

# (source node, destination node, packets); node = y * k + x on a k x k mesh
flows = [(0, 14, bb.packets_for(64 * 1024)),     # 64 KB from node 0 to node 14
         (1, 14, bb.packets_for(64 * 1024)),
         (6, 20, bb.packets_for(32 * 1024))]
result = bb.run_batch(flows, k=6, kappa=4)        # simulate the whole batch
bounds = bb.flit_bounds(flows, k=6, kappa=4)      # the resource bound of the same batch, in cycles
print(result["cycles"], bounds)                   # 21813 {'channel_bound_cycles': 21760, ...}
```

`run_batch` returns the cycles until the last packet arrives, and the average packet latency. `flit_bounds` returns the busiest-channel, injection-port and ejection-port bounds that the resource bound is built from. One cycle is 8 bytes on one channel, 1.45 ns at Simba's link rate.

## Speed of the framework

```bash
python3 scripts/run_timing.py                   # full vs. incremental evaluation, re-evaluation of stored placements, one search
python3 scripts/run_timing.py --repeats 3       # fewer repeats
python3 scripts/run_search_trajectories.py      # best latency found so far against time, one search per model
```

Both use the four `reference` deployments (512 to 2,200 dies) and write to `results/exports/`. `run_search_trajectories.py` re-runs each recorded search with its recorded start, seed and budget. It stops with an error if the result differs from the record. The timings are single-threaded wall-clock times; run them on an idle machine.

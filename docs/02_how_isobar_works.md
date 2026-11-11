# 02 How Isobar works

This page explains how the code turns a model and a hardware description into latency, energy and a searched placement. It follows one small deployment through every step and names the code that does each step. Read it before changing the implementation; to only run the tools, the later pages are enough. The model itself is described in Section II of the paper.

## The pipeline at a glance

| step | code | reads | produces |
|---|---|---|---|
| 1. per-operator costs | `measure_accounts.py` (CiMLoop, container) | model shapes, the die's fabric file | an **account**: per operator and phase, compute time, write time, energy |
| 2. split operators over dies | `llm_workload.block_chain` | model shapes, die capacity, tiling choice | per operator: number of dies, split direction, data in and out |
| 3. build the deployment | `experiment.AccountWorkload`, `offload.build` | account, mesh size, digital-unit settings | the workload object `W`: dies, mesh, unit slots |
| 4. place the dies | `search_baselines.generate`, `search_space.Pi` | `W` | a placement: mesh slots of every operator's dies |
| 5. traffic of every hand-off | `llm_workload.boundary_flows` | placement, split directions | flows: (source die, destination die, bytes) |
| 6. load on shared resources | `search_eval.resource_loads` | flows, XY routes | load on every link, die port and unit interface |
| 7. latency and energy | `search_eval.score` | loads, account, unit model | T = R + H, dynamic energy |
| 8. search | `experiment.evaluate_config`, `search_sa.anneal`, `objective.Objective` | `W`, baseline placements | the searched placements and the record |

`run_experiments.py` drives steps 2–8 for one or many configurations.

## A worked example

OPT-1.3B, prefill of 512 tokens, reference hardware: 8 macros per die, 0.4 GB/s links, die ports at κ = 2 (0.8 GB/s), one digital unit at the centre.

**Step 1, account.** `results/accounts/opt1.3b_S512.json` lists the operators of one transformer block. For example, the first FFN layer (`ffn1`, 2048 × 8192 weights, 512 input rows) takes 5.19 ms of CIM compute and 8.77 mJ per layer. The account is measured once; the evaluation never runs CiMLoop.

**Step 2, split over dies.** One die holds 256 arrays of 256 × 256 cells. The tiler finds the smallest legal split of each weight matrix:

| operator | dies |
|---|---|
| QKV projection | 2 |
| output projection | 1 |
| FFN layer 1 | 2 |
| FFN layer 2 | 2 |

That is 7 dies per layer and 168 dies for 24 layers. With the default tiling (`colrow`), a matrix is split by output columns where possible, so each die produces a slice of the output. Where a column split is not legal, it is split by input rows, so each die produces partial sums of the whole output. Attention runs on the digital unit.

**Step 3, deployment.** 168 dies plus one unit fit a 13 × 13 mesh. Slot 84, the centre, is reserved for the unit.

**Step 4, placement.** A placement assigns mesh slots to every operator of every layer, e.g. `ffn1@L0 → (20, 51)`, `ffn2@L0 → (55, 141)`. Slots are numbered row by row (slot = y × 13 + x).

**Step 5, traffic of a hand-off.** Take the hand-off from `ffn1` to `ffn2` in layer 0:

- `ffn1` outputs 512 × 8192 values (1 byte each); each of its two dies holds half the columns, 2.1 MB.
- `ffn2` is also split by columns, so each of its two dies needs the whole input.
- That gives four flows of 2.1 MB, from each `ffn1` die to each `ffn2` die.

The other cases follow the same rule:

- A consumer split by rows needs only its slice of the input.
- A producer split by rows sends partial sums, at 2 bytes per value.
- Hand-offs into and out of the digital unit send the attention inputs and outputs.

**Step 6, loads.** Each flow follows its XY route. Its bytes are added to every directed link on the route, to the injection port of its source die, and to the ejection port of its destination die. A unit's interface counts against the unit's own bandwidth (12.5 GB/s). In this hand-off:

| resource | load | capacity |
|---|---|---|
| busiest link | 4.2 MB | 0.4 GB/s |
| busiest die port | 4.2 MB | 0.8 GB/s |

**Step 7, latency and energy.** A hand-off takes as long as its busiest resource needs, plus the hop delay of its longest route:

```
time = max(link load / B, die-port load / (κ B), unit-interface load / C_unit) + max hops × 20 ns
     = 4.2 MB / 0.4 GB/s + 13 × 20 ns ≈ 10.5 ms
```

The resource that sets this maximum is the hand-off's **binding resource**, its bottleneck (here a link). Hand-offs run one after another, so the communication time H is their sum over the whole model. The rest of the latency, R, is:

- CIM compute and writes from the account;
- the digital element-wise work (norms, activations, residual adds; the `digital` block of the fabric file);
- the unit's attention compute and K/V memory time (`offload.unit_layer_cost`).

For this placement, R = 0.46 s, H = 0.60 s and T = R + H = 1.06 s. Dynamic energy adds:

- the account's energies;
- the element-wise and unit energies;
- 10 pJ per byte per hop on the mesh.

**Step 8, search.** The evaluation scores the default fill, five built-in heuristics and the random pool, then anneals. Here the best baseline is a random placement at 1.06 s, and the search finds 0.92 s: a 13% end-to-end and 23% communication saving.

## How the evaluation is implemented

- **Prefill and decode.** Accounts store both phases. Prefill processes S query rows, decode one row, and the hand-off volumes scale with the rows. In decode, the unit reads the K/V cache of the whole context.
- **Only static operators run on the CIM dies.** With attention on the digital unit, the account's attention entries are not used; `offload.unit_layer_cost` computes attention from the model shapes and the unit's parameters.
- **Incremental evaluation.** A move changes the slots of one or two operators. `objective.Objective` (via `search_eval.ScoreSession`) re-evaluates only the hand-off into each moved operator and the hand-off out of it, and reuses the rest. The result equals a full evaluation; one move costs 1.4–15.9 ms on 512–2,200 dies instead of 26–38 times more.
- **Constants.** The hop delay (`NS_PER_HOP_D2D`) and the link energy (`PJ_D2D`) are in `search_eval.py`. The unit's parameters are in `offload.REF_UNIT`; the digital element-wise unit is in the fabric file.

## How the search is implemented

1. **Baselines** (`search_baselines.py`):
   - the default fill, which places operators in model order onto slots row by row;
   - five built-in heuristics from prior work: snake, least Manhattan distance, rectangular clustering, NMAP, heaviest first;
   - a pool of random placements.

   The fastest of all of these is the **best baseline** (field `strongest`).
2. **Starts.** For every seed, the annealer starts three times: from the fastest heuristic, from the fastest random placement, and from random placement 0.
3. **Moves** (`search_sa.py`):
   - exchange two dies of different operators;
   - move a die to a free slot, or to an occupied one, whose die then takes the vacated slot;
   - swap two whole operators of equal size.

   Every move keeps each operator's die count and keeps slots distinct, so every visited placement is legal. The unit's slots are never used.
4. **Acceptance.** Simulated annealing with geometric cooling. The budget is max(1200, ⌈1200 n / 544⌉) moves for n dies.
5. **Result.** For each seed, the best of its three runs (by end-to-end latency T) is kept. The seeds are then sorted by that latency. The **search representative** (field `headline`) is the seed at the middle position, the 3rd of 5 or 6th of 10. The record also reports the median, minimum and maximum saving over the seeds.

`search_dp.py` searches the grouping of layers into pipeline stages. In the paper's experiments every layer is its own group: the package is one mesh, and serial latency does not depend on the grouping. The DP is a standalone tool for pipelined deployments (`python3 scripts/search_dp.py`).

## Words used in this guide

| term | meaning | field in the records |
|---|---|---|
| account | per-operator cost table of one model, measured with CiMLoop | file in `results/accounts/` |
| deployment, configuration | one model on one hardware setting; named by its configuration id | `config_id` |
| default fill | operators in model order onto slots row by row | `sequential` |
| built-in heuristics | placement rules from prior work | `snake`, `least_manhattan`, `clustered`, `nmap_greedy`, `heaviest_first` |
| best baseline | fastest of the default fill, the heuristics and the random placements | `strongest` |
| search representative | the searched placement of the middle seed | `headline` |
| binding resource | the resource that limits a hand-off's time | `binding` |
| η, communication saving | 1 − H_search / H_best-baseline | `eta_comm` |
| G, end-to-end saving | 1 − T_search / T_best-baseline | `G_median_pct` (median over seeds) |
| κ | die port bandwidth / link bandwidth | `kappa` |

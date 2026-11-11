# 05 Deployments and placement search

This page shows how to evaluate a model on a chosen hardware configuration, search for a better placement, and read the result. The entry point is `scripts/run_experiments.py`. It needs the model's account ([04 Models](04_models.md)) and runs on the host or in the container, from `workspace/` (or `/home/workspace` in the container).

## In short

```bash
python3 scripts/run_experiments.py --custom --model gemma7b                  # prefill, 512 tokens, reference hardware
python3 scripts/run_experiments.py --custom --model gemma7b --bw 1.6         # faster mesh links
python3 scripts/run_experiments.py --custom --model gemma7b --phase decode --S 1024
```

For each configuration, the script evaluates the default fill, the built-in heuristics and a pool of random placements. It then runs the search, prints one line, and writes the record to `results/records/custom/`.

## Choosing the configuration

| option | default | meaning |
|---|---|---|
| `--model` | `gemma7b` | a key of the model registry ([04 Models](04_models.md)) |
| `--phase` | `prefill` | `prefill`, or `decode` (one new token against a cache of `--S` tokens) |
| `--S` | 512 | prefill length, or decode context length |
| `--macros` | 8 | macros per die: 4, 8, 16 or 32 (needs the `_m<N>` account) |
| `--tiling` | `colrow` | how matrices are split over dies (needs the `_tl<name>` account unless `colrow`) |
| `--bw` | 0.4 | mesh link bandwidth per direction, GB/s |
| `--kappa` | 2 | die port bandwidth / link bandwidth |
| `--grid X,Y` | smallest near-square | mesh size |
| `--routing` | `xy` | `xy` or `yx` |
| `--units` | 1 | digital units: 1, 2 or 4 |
| `--position` | `center` | slot of a single unit: `center`, `edge` or `corner` |
| `--split` | `layer` | units serve groups of layers (`layer`) or groups of heads of every layer (`head`) |
| `--resources` | `per_unit` | each unit has the full reference resources (`per_unit`), or the reference total is divided among the units (`total`) |
| `--unit-param NAME=VALUE` | | override one digital-unit parameter ([03 Hardware](03_hardware.md)); repeatable |

Examples:

```bash
# four units on head groups, sharing the reference resources
python3 scripts/run_experiments.py --custom --model gemma7b --units 4 --split head --resources total
# 16-macro dies (after measuring gemma7b_S512_m16.json)
python3 scripts/run_experiments.py --custom --model gemma7b --macros 16
# a faster K/V memory and a wider unit interface
python3 scripts/run_experiments.py --custom --model opt13b --unit-param kv_words_per_second=51.2e9 --unit-param link_bandwidth_gbps=25
# column-split QKV projection (needs opt13b_S512_tlcol.json)
python3 scripts/run_experiments.py --custom --model opt13b --tiling col
```

The **configuration id** encodes every hardware choice. For example, `gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK4TH` reads as:

- model, phase and length;
- tiling and mesh (`sq` = near-square);
- topology, routing, κ and bandwidth;
- the units: `K4` = four units, `T` = total resources divided, `H` = head groups.

Unit overrides are appended, e.g. `_kv_words_per_second5.12e+10`. `--list` prints the ids without running anything.

## Choosing the search effort

| option | exploration (default) | confirmation | meaning |
|---|---|---|---|
| `--protocol` | `exploration` | `confirmation` | preset |
| `--n-random` | 100 | 500 | random placements in the baseline pool |
| `--seeds` | `0,1,2,3,4` | `5,...,14` | annealer seeds; each seed runs three times, from three starts |
| `--objective` | `t_norm` | `h_norm` | minimise the end-to-end latency T, or the communication time H |

The annealing budget grows with the number of dies: max(1200, ⌈1200 n / 544⌉) moves for n dies.

- For a first look, `--n-random 20 --seeds 0` takes seconds for small models.
- The paper's main results use the confirmation preset.
- On one core, a configuration takes from seconds (OPT-1.3B, exploration) to about an hour (OPT-13B, confirmation).

## Running again: what is reused

Each record directory (`results/records/custom/` by default) holds one record per configuration id. When you run again:

| situation | what happens |
|---|---|
| a configuration finished earlier with the **same** `--n-random`, `--seeds` and `--objective` | it is skipped, and the script says so |
| it finished with **other** search settings | the script stops and asks for `--name` or `--redo` |
| it did not finish (e.g. `no account`) | it is computed again and its old record is replaced |
| `--redo` | every selected configuration is computed again and replaces its record |
| `--name NAME` | the records go to `results/records/NAME/`, so results with different search settings can be kept side by side |

The reuse check looks only at the configuration id and the search settings. If you change a fabric file, a constant in the code or an account, use `--redo` or a new `--name`.

## Reading the result

The printed line:

```
[opt1.3b_prefill512_...] 168 dies on 13x13 | strongest random_s7 1061.3 ms (rule nmap_greedy, random best-of-100)
  | G median 13.22% [13.22, 13.22] | eta 23.3% r 56.7% | band 0.542-0.822 | 2 s
```

| part | meaning |
|---|---|
| `strongest random_s7 1061.3 ms` | the **best baseline**: the fastest of the default fill, the built-in heuristics and the random placements, with its latency |
| `rule nmap_greedy` | the fastest built-in heuristic |
| `G median [min, max]` | end-to-end saving of the search over the best baseline: median, minimum and maximum over the seeds |
| `eta` | communication saving of the search representative over the best baseline |
| `r` | share of communication in the best baseline's latency |
| `band` | the lowest and highest link bandwidth (GB/s) at which a built-in heuristic's communication time drops to the rest of its latency |

The **search representative** is chosen as follows. For each seed, the fastest of its three runs (by end-to-end latency) is kept. The seeds are then sorted by that latency, and the representative is the one at the middle position: the 3rd of 5, or the 6th of 10. Its placement is stored in the record.

Files in `results/records/<name>/`:

| file | content |
|---|---|
| `summary.csv` | one row per configuration (columns below) |
| `candidates.csv` | every baseline placement: latency T, communication time H, propagation, traffic, energy |
| `runs.csv` | every annealer run: start, seed, result, accepted moves, wall time |
| `cost_grid.csv` | the best baseline and the representative re-evaluated over CIM speed × link bandwidth |
| `configs.jsonl` | the full record, one JSON per configuration, including every placement |
| `manifest.json` | the search settings of the last run |

The main columns of `summary.csv`:

| column | meaning |
|---|---|
| `n_dies` | number of CIM dies |
| `strongest`, `T_base_ms` | the best baseline and its latency |
| `headline_run`, `headline_T_ms` | the search representative and its latency |
| `G_median_pct`, `G_min_pct`, `G_max_pct` | end-to-end saving over the seeds |
| `eta_comm_pct` | communication saving of the representative |
| `r0_pct` | communication share of the best baseline |
| `B_eq_gbps` | the link bandwidth at which the best baseline would match the representative's communication time |
| `gain_vs_default_pct` | saving over the default fill |
| `dE_pct` | change in dynamic energy |

## Working with a record in Python

`scripts/records.py` rebuilds a deployment from its record. A stored placement can then be re-evaluated under other settings, inspected hand-off by hand-off, or modified. Run from `workspace/`:

```python
import sys; sys.path.insert(0, ".")
from scripts import records as C, search_space as ss

rec = C.find_record("custom", "opt1.3b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1")
W = C.workload_from_record(rec)                    # the deployment, as evaluated
phase = rec["spec"]["phase"]
best = C.candidate_layout(W, rec["strongest"])     # the best baseline
rep = ss.Pi.from_json(rec["search"]["runs"][rec["search"]["headline"]]["best_pi"])   # the search representative

# latency of both placements at other link bandwidths
for bw in (0.4, 1.6, 12.5):
    t_b = C.evaluate(W, best, phase, bw)[0].t_opt_s
    t_s = C.evaluate(W, rep, phase, bw)[0].t_opt_s
    print(f"{bw} GB/s: baseline {t_b*1e3:.1f} ms, search {t_s*1e3:.1f} ms")

# every hand-off: its time and the resource that limits it
score, handoffs = C.evaluate(W, rep, phase, 0.4)
for row in C.stage_rows(W, handoffs, 0.4, rec["spec"]["kappa"]):
    print(row["into"], row["stage"], f"{row['service_s']*1e3:.3f} ms", row["binding"])
```

A placement (`search_space.Pi`) maps every operator of every layer, e.g. `"ffn1@L0"`, to the tuple of mesh slots its dies occupy, numbered row by row (slot = y × width + x). A legal placement:

- gives every operator exactly as many slots as it has dies (`W.inventory()`);
- uses each slot at most once;
- leaves the digital units' slots (`W.hub_nodes()`) free.

To try your own, edit the slots and check legality before evaluating:

```python
seat = dict(rep.seat)
a, b = seat["ffn1@L0"], seat["ffn2@L0"]
seat["ffn1@L0"], seat["ffn2@L0"] = (b[0],) + a[1:], (a[0],) + b[1:]   # exchange one die of ffn1 and ffn2
mine = ss.Pi(n_blocks=rep.n_blocks, cuts=rep.cuts, seat=seat)
print(ss.legal(mine, W.fab, W.inventory()))                           # (True, 'ok'), or the reason it is not legal
print(C.evaluate(W, mine, phase, 0.4)[0].t_opt_s)
```

To move a die to an empty slot instead, take a slot from `W.usable_slots()` that no operator uses; a mesh that is completely full, like this one, has none. `C.candidate_layout(W, name)` returns the default fill (`sequential`), any built-in heuristic (`snake`, `least_manhattan`, `clustered`, `nmap_greedy`, `heaviest_first`), or a random placement (`random_s<k>`).

## The paper's experiments

`--experiment NAME` runs one of the paper's configuration sets instead of `--custom`. Records go to `results/records/NAME/`, or `capacity_sweep_m<N>/`.

| name | what it runs | protocol |
|---|---|---|
| `reference` | four models and the 2.7B-class reference, 8 macros per die, one unit, prefill and decode at 512 tokens | confirmation |
| `capacity16` | the four models with 16 macros per die | confirmation |
| `distributed` | the four models with four head-group units | confirmation |
| `qkv_split` | OPT-13B with row- and column-split QKV on a 49 × 49 mesh | confirmation |
| `capacity_sweep --macros N` | the four models at N = 4, 8, 16 or 32 macros per die | exploration |
| `organisation` | Gemma-7B with one unit, four layer-group units, four head-group units | exploration |
| `context_length` | Gemma-7B prefill and decode at 128–4096 tokens | exploration |

`--list` shows the configurations, and `--only <id>` runs one of them. A few configurations of the paper use the annealer's second random-stream setting (`search_sa.Schedule(tie_draw=False)`); the experiment definitions mark them, so the records regenerate exactly. [08 Reproducing the paper](08_reproduce_paper.md) gives the full order.

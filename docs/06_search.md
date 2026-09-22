# 06 Run the placement search

The search chooses the die seats of every operator set to minimize the
evaluator's latency at one setting (bandwidth, port ratio, phase). This
page shows the search as a snippet on your configuration, then the
frozen protocol scripts and how their statistics are read.

## What the search is

A simulated annealer over seats (`scripts/search_sa.py`). Moves: swap two
dies between sets, or migrate one die to a free slot. Every candidate is
scored incrementally (only the two hand-offs a move touches are
re-priced). The block cuts are found separately by an exact dynamic
program (`scripts/search_dp.py`) and matter only for the pipeline
caliber; under the serial caliber cutting is free and the frozen results
keep one layer per segment. Inside a die, the macro assignment is
enumerated exhaustively (`scripts/search_withindie.py`).

The frozen setting: 24 by 24 mesh, kappa 2, 0.4 GB/s, prefill, serial
caliber; three start rules (clustered, random, snake) times three seeds
per start; 1200 steps, cooling 0.996, initial temperature 20 ms.

## Run it on your configuration

```bash
python3 scripts/cimsim_cli.py search --bandwidth 0.4 --starts clustered,random,snake --seeds 0,1,2 \
    --steps 1200 --alpha 0.996 --out-dir analysis/search_k2_b04
```

This is the frozen protocol on the main configuration (kappa from the
fabric, prefill, serial caliber, the temperature 20 ms that the frozen
legs used at 0.4 GB/s). Output:

```
fabric mlx300-multidie576 | account gpt-2.7B-class | kappa 2 | B 0.4 GB/s | phases prefill | caliber single | 3 starts x 3 seeds | 1200 steps, alpha 0.996, t0 20 ms
  sa_clustered_s0        2550.35 ->   1922.26 ms  accepted 665/1200  2.4 s
  sa_clustered_s1        2550.35 ->   1918.00 ms  accepted 738/1200  2.4 s
  ...
  sa_snake_s2            4106.67 ->   1930.45 ms  accepted 697/1200  2.4 s
best endpoint sa_random_s2: 1904.24 ms | headline sa_random_s1: 1908.82 ms | spread 1.99%
strongest baseline random_s3: 2118.71 ms | headline gain 9.91% | best-of-all 10.12% | vs sequential fill 54.47%
-> analysis/search_k2_b04/search.json, best_pi.json, headline_pi.json, sa_<start>_s<seed>.json
```

Products in `--out-dir`: `search.json` (the setting, the schedule, every
run with its start and end latency, acceptance counts, move counts and
endpoint deployment, the headline statistics and the baseline
comparison), `best_pi.json` and `headline_pi.json` (deployments ready
for `evaluate`), and one deployment file per run.

The seed formula `1000003 * s + i`, with `i` over the sorted start
names, reproduces the frozen runs bit for bit. The strongest baseline is
the best of the seven rules at seed 0 and the random fills at seeds 1 to
4, as in the frozen protocol; `--no-baselines` skips that scoring.

### The options

| option | meaning | default |
|---|---|---|
| `--starts` | start rules, comma-separated | `clustered,random,snake` |
| `--seeds` | annealer seeds | `0,1,2` |
| `--steps`, `--alpha` | budget and cooling | 1200, 0.996 |
| `--t0` | initial temperature, seconds of latency | 20 ms at 0.4 GB/s, 2 ms at 12.5, else 20 ms times 0.4 / B |
| `--objective` | `t` latency or `e` energy | `t` |
| `--phases`, `--caliber`, `--device-scale` | as for `evaluate`; a phase mix searches the weighted sum | prefill, single, 1.0 |
| `--bandwidth`, `--kappa`, `--fabric`, `--workload` | the setting | 0.4, the fabric's, the main configuration |

### Choosing the schedule

`--t0` is the initial temperature in seconds of latency. The frozen legs
use 20 ms at 0.4 GB/s and 2 ms at 12.5 GB/s; the objective's spread
scales with 1 over bandwidth, and the default follows that rule at other
bandwidths. A temperature set by the rule span divided by 20 turned most
of the budget into a random walk on this instance and was recorded as
superseded. When you change the workload, compare the named rules'
spread at your setting (`evaluate` on each) and scale `--t0` with it, or
run the same budget with `--t0 0` (greedy) as a control.

### In Python

The annealer is `search_sa.anneal(J, pi0, n_slots, Schedule(t0, alpha,
steps), seed)` on an incremental objective; `cimsim_cli.Objective(W,
pi0, mu, caliber, bw, device_scale)` is the one the command line uses.
`SAResult` carries the best deployment, its cost, the start cost, and
the accepted, proposed and infeasible counts per move family. The
annealer takes `feasible=<callable>` to restrict the slots; every start
must satisfy it.

## The frozen protocol scripts

| command | what it does | output |
|---|---|---|
| `python3 scripts/kappa_geometry_sweep.py` | the search in six cells: 24x24 and 12x48 at kappa 1, 2, 4; every run, endpoint, binding resource and the gains at 0.4 and 12.5 GB/s | `analysis/kappa_geometry_sweep.json`, `.png` |
| `python3 scripts/main_config_export.py` | re-scores the 24x24 kappa 2 cell on prefill and decode and writes the ledger of every published percentage | `analysis/main_config_results.md`, `.json` |
| `SEAT_KAPPA=2 python3 scripts/rerun_seating_seeds.py` | the budget curves per start and seed, at 0.4 and 12.5 GB/s | `analysis/seating_seeds_k2.json` |
| `ABL_KAPPAS=2 python3 scripts/objective_ablation.py` | the same budget under four objectives (ours, wire-only, word-hops, max-hops), each endpoint re-scored under ours | `analysis/objective_ablation_k2.json` |
| `python3 scripts/search_dp.py` | the block-cut dynamic program on the standing instance, pipeline caliber, k = 1, 2, 4, 8, 16, 32 segments | printed table |
| `python3 scripts/search_withindie.py` | the intra-die instance: exhaustive macro assignment and the annealer against it | `analysis/search_withindie.json` |
| `python3 scripts/intra_die_integration.py` | the intra-die cost folded into a whole-layer objective at each bandwidth anchor | `analysis/intra_die_integration.json` |

The sweep runs 54 anneals plus the baseline scoring and takes a few
minutes; the others are faster. All of them overwrite their outputs in
`analysis/`, which the tests read, so run them on a copy of the tree if
the frozen numbers must stay.

## Reading the statistics

The frozen documents report the search three ways, and the denominator
is always named:

- **Headline gain against the strongest baseline**: for each of the
  three annealer seeds take the best endpoint over the three starts;
  the headline is the median of those three, against the strongest
  baseline. On the main configuration 9.91% (1908.82 ms over random seed
  3 at 2118.71 ms). The range over the three seeds is 9.66 to 10.12%,
  and the best of the nine runs (10.12%) is labelled apart from the
  headline.
- **Gain against the default fill** (sequential, 4192.54 ms): 54.5%.
  Large because the default is poor, so never the headline.
- **Endpoint spread**: max over min of the nine endpoints minus one; a
  check that the search has converged rather than a result.

The mechanism reading (why the endpoint is faster) is in
`analysis/mechanism_table.md`: the binding resource per hand-off and the
hotspots the search removes. When the binding column reads `port` for
most hand-offs, the port floor is reached and no further seating can
help; raise kappa or the bandwidth instead.

## When not to search

Read the phase diagram first (page 07). Above the upper boundary at your
device rate the communication is masked and the search returns the
baseline's latency within a fraction of a percent (0.70% at 12.5 GB/s on
the main configuration). Below the lower boundary every placement is
communication-bound and the search still pays, but the absolute latency
is set by the bandwidth.

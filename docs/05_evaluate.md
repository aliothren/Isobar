# 05 Evaluate one deployment

You have a hardware description, the workload account, and a deployment
(yours, a named rule's, or the search's endpoint). This page prices it.

## The deployment file

A deployment is a JSON file with the fields of page 02:

```json
{
 "n_blocks": 32,
 "cuts": [1, 2, 3, ..., 32],
 "seat": {"qkv_proj@L0": [546, 305, 510, 254], "attention@L0": [77], "out_proj@L0": [...], ...},
 "hub": null, "attach": null, "beta": null
}
```

Slot indices are row-major on the die grid (index = y times 24 plus x on
the main configuration). Every set must have exactly the number of dies
the account gives it, and no slot may be used twice. Generate one from a
named rule to see the format:

```bash
python3 scripts/cimsim_cli.py baseline --rule clustered --seed 0 --out analysis/clustered.json
```

The rules: random, sequential, snake, least_manhattan, clustered,
nmap_greedy, heaviest_first. `--seed` matters for random only.

## Price it

```bash
python3 scripts/cimsim_cli.py evaluate --deployment analysis/clustered.json --bandwidth 0.4 --phases prefill,decode --loads 5 --out analysis/clustered_eval.json
```

Output on the main configuration:

```
fabric mlx300-multidie576 | account gpt-2.7B-class S=512 | kappa 2 | B 0.4 GB/s | caliber single | device x1
[prefill] latency 2550.352 ms  energy 2.3379 J
    layers 921.113 ms | hand-offs 1629.225 ms | propagation 0.014 ms | pipeline interval 80.067 ms
    hand-off words 1.421e+09 total, 6.517e+08 on the busiest resources | hand-off energy 0.0410 J
    159 hand-offs; binding resource: link 127, port=link 32
    busiest 5 hand-offs (words on the busiest resource / link rate):
      ffn2@L0              10485760 words    26.214 ms  link      mesh:seg(0, 3)-(0, 4) +  25 flows, 5 hops max
      ffn2@L1              10485760 words    26.214 ms  link      mesh:seg(3, 3)-(3, 4) +  25 flows, 5 hops max
      ...
[decode] latency 27.306 ms  energy 0.0046 J
    ...
-> analysis/clustered_eval.json
```

The binding line counts hand-offs by what sets their time: a link, a
port, or both at once (`port=link`, a hand-off whose busiest link
carries exactly one port's load). The ffn1 to ffn2 hand-offs of the
clustered rule are the busiest: 25 flows of the same volume, five
producers to five consumers, on adjacent links.

An inadmissible deployment stops with `illegal deployment: <reason>`
instead of a price. The JSON holds the same numbers in full: the score
per phase with its decomposition, and one row per hand-off (its total
words, its busiest resource and load, whether a link or a port floor
binds, the longest path in hops).

The decomposition keys, in the JSON under `per_phase.<phase>.decomp`:

| key | meaning |
|---|---|
| `layers_s` | layers times (compute / device_scale + write + digital) |
| `d2d_serial_s` | sum over hand-offs of busiest resource words / link rate |
| `propagation_s` | sum over hand-offs of the longest path's hops times the per-hop delay |
| `stage_s` | per pipeline segment: its layers plus its hand-offs |
| `t_single_s`, `t_pipe_interval_s` | the serial sum, and the slowest segment |
| `d2d_words`, `d2d_busiest_words` | total hand-off words, and the words on the busiest resources |
| `d2d_flat_J`, `d2d_surplus_J` | hand-off energy at the flat price, and the distance surplus |

## The knobs

| option | meaning | default |
|---|---|---|
| `--bandwidth` | link bandwidth per direction, GB/s; divides every hand-off's busiest words | 0.4 |
| `--kappa` | port ratio; ports carry their load at kappa times the link rate | the fabric's `ports.ratio`, else 1 |
| `--device-scale` | divides matrix compute only; the fixed terms stay, so the gain saturates | 1.0 |
| `--phases` | `prefill`, `decode`, or both; decode has the same seats and 1-row hand-offs | `prefill,decode` |
| `--caliber` | `single`: the serial sum; `pipe`: the pipeline interval, then `cuts` matters | `single` |
| `--d2d-pj-per-word`, `--d2d-ns-per-hop` | the package link's energy per word and delay per hop | 10, 20 |
| `--fabric`, `--workload` | the hardware and the account | the main configuration |
| `--loads N` | print the N busiest hand-offs | 8 |

## Compare several deployments

```bash
for r in sequential clustered snake random; do
  python3 scripts/cimsim_cli.py baseline --rule $r --out analysis/$r.json > /dev/null
  for b in 0.4 12.5; do
    printf "%-15s %5s GB/s  " $r $b
    python3 scripts/cimsim_cli.py evaluate --deployment analysis/$r.json --bandwidth $b --phases prefill --loads 0 | grep latency
  done
done
```

```
sequential        0.4 GB/s  [prefill] latency 4192.536 ms  energy 2.3937 J
sequential       12.5 GB/s  [prefill] latency 1025.827 ms  energy 2.3937 J
clustered         0.4 GB/s  [prefill] latency 2550.352 ms  energy 2.3379 J
clustered        12.5 GB/s  [prefill] latency 973.262 ms  energy 2.3379 J
snake             0.4 GB/s  [prefill] latency 4106.672 ms  energy 2.3537 J
snake            12.5 GB/s  [prefill] latency 1023.068 ms  energy 2.3537 J
random            0.4 GB/s  [prefill] latency 2153.112 ms  energy 2.5251 J
random           12.5 GB/s  [prefill] latency 960.620 ms  energy 2.5251 J
```

The frozen comparison of every named rule, five random fills and the
nine search endpoints, on prefill and decode at both bandwidths, is one
command and is the source of the headline table:

```bash
python3 scripts/main_config_export.py      # -> analysis/main_config_results.md / .json
```

## In Python

The command line wraps `search_eval.score(pi, W, mu, caliber, d2d_gbps,
device_scale)` on a `cimsim_cli.Workload`; per-hand-off loads come from
`search_eval.resource_loads(flows, W.die_ic, ports=True, kappa=kappa)`,
a dict keyed by `("mesh:seg(x1, y1)-(x2, y2)", "+"|"-")` for a link
direction and `("port", die, "inj"|"ej")` for a port, with port loads
already divided by kappa. `cimsim_cli.handoff_flows(W, pi, phase)` gives
the flow list of every hand-off in chain order. A full score of a
544-die deployment takes about 40 ms; the evaluator in the search
re-scores only the two hand-offs a move touches, about 1.3 ms.

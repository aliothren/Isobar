# 02 Concepts

Five objects appear in every run. Knowing what each one holds tells you
where a change goes. The cost model itself is written out in
[`formulation.md`](../formulation.md); this page is about the interfaces.

## 1. The fabric

The physical machine: a list of levels from the package down to the
crossbar, each with a count per parent, a grid the instances occupy, and
a link with its topology, routing, propagation and energy per word; plus
the analog device's row time, the digital vector unit and the external
attention unit. It is one YAML file under `models/fabric/`, loaded and
validated by `scripts/fabric.py`. The main configuration is
`mlx300_multidie576.yaml`: 576 die slots on a 24 by 24 mesh with XY
routing, eight macros per die on a 2 by 4 grid, and so on down.

The fabric is the source of truth for structure. The link bandwidth the
evaluator prices is given per call (`--bandwidth`), not in the file; the
port ratio may be declared in the file (`ports: {ratio: 2}` on the die
level) and overridden per call (see object 4).

## 2. The workload account

The model is a GPT-style block chain. CiMLoop's mapper is run once per
operator (qkv projection, attention, output projection, ffn1, ffn2) for
prefill and for decode, and the result is frozen into one JSON file:
compute time, weight-write time, energy, the number of dies the operator
spans, and the volumes of its die-level flows. The main file is
`analysis/scale_2p7b_per_op.json` (2.7B class, S = 512). The evaluator
reads this file; it never calls the mapper. Page 04 says how the file is
made.

The die-set granularity follows from the account: at the main
configuration each layer is 17 dies (qkv 4, attention 1, out 2, ffn1 5,
ffn2 5), so 32 layers occupy 544 of the 576 slots. These sizes are the
tiler's answer and cannot be edited by hand; a deployment that seats a
set on a different number of dies is illegal.

## 3. The deployment

The decision variable, written (gamma, alpha, beta) in the documents and
`Pi` in code (`scripts/search_space.py`):

| field | meaning | main configuration |
|---|---|---|
| `cuts` (gamma) | ascending end indices of the pipeline segments over the layer chain | `[1, 2, ..., 32]`: one layer per segment; only the pipeline caliber reads it |
| `seat` (alpha) | for every operator set `op@L<i>`, the tuple of die slot indices it occupies | 160 sets, 544 distinct slots |
| `hub`, `attach` | the die-level hub and the offload-unit attach slot | `null`: the fabric's own |
| `beta` | the macro assignment inside a die | `null`: the standing contiguous assignment; the intra-die instance is searched separately |

Slot indices are row-major on the die grid (index = y times X plus x).
`Pi.to_json()` and `Pi.from_json()` move it to and from a file;
`search_space.legal(pi, fabric, inventory)` says whether it is admissible
and why not.

Seven named rules generate baseline deployments from the account alone
(`scripts/search_baselines.py`): random, sequential, snake,
least_manhattan, clustered, nmap_greedy, heaviest_first. The search starts
from three of them.

## 4. The hand-off term

Between consecutive operator sets every producer die ships its piece of
the output to every consumer die (R-split multicast). Each flow is routed
on the declared mesh under XY routing and its words are accumulated on
every link direction it crosses and on the source and destination die
ports. The hand-off costs the busiest resource's load divided by the link
rate, plus propagation over the longest path. Ports count at the declared
ratio kappa: a port at twice the link rate carries its load in half the
time. The evaluator therefore takes two numbers per call:

- `d2d_gbps`: the link bandwidth per direction in GB/s (0.4 in the main
  configuration; 12.5 as the contrast).
- kappa, the port ratio: `--kappa` on the command line, defaulting to
  the fabric's `ports: {ratio}` on the die level; in Python an attribute
  on the workload object (`W.port_ratio = 2.0`), 1.0 if unset.

Two consequences worth knowing before the first run. The term is a lower
bound on what any schedule can achieve on the busiest resource, so a
packet simulator lands at or above it (page 08). And the largest port
load of a hand-off divided by kappa is a floor no placement can beat,
because seats move flows between links but every flow still leaves its
producer's port and enters its consumer's; whether a layout is bound by
a link or by that floor is reported.

## 5. The score

`search_eval.score(pi, W, mu, caliber, d2d_gbps, device_scale)` returns
a `Score` with the latency that ranks (`t_opt_s`), the packet-toll
pessimistic end (`t_pess_s`, equal to `t_opt_s` on the shipped fabrics),
the dynamic energy (`e_J`), and per phase a decomposition: layer compute
plus write plus digital time, the serialized hand-off time, propagation,
total and busiest words, flat and distance-surplus energy.

| argument | meaning | default |
|---|---|---|
| `mu` | phase weights, for example `{"prefill": 1.0}` or `{"prefill": 1.0, "decode": 1.0}` | prefill only |
| `caliber` | `"single"`: the serial sum over layers and hand-offs; `"pipe"`: the pipeline interval, the slowest segment | `"single"` |
| `d2d_gbps` | link bandwidth per direction | 12.5 |
| `device_scale` | divides the matrix compute time; 2.0 means a device twice as fast, write and digital terms unchanged | 1.0 |

The search minimizes `t_opt_s` at a fixed setting; energy is reported
alongside and used only as a tie-break. Incremental re-scoring after a
seat move (`ScoreSession.update`) is what makes the search affordable;
it is pinned identical to a full re-score.

## What is fixed in this version

The XY routing rule, the R-split convention, the serial prefill at batch
1, and the one-layer-per-segment default. The D2D link's energy per word
and propagation per hop as used by the evaluator (10 pJ per word, 20 ns
per hop) are constants in `scripts/search_eval.py`; the command line
overrides them with `--d2d-pj-per-word` and `--d2d-ns-per-hop`. Page 10
lists what the model does not price at all.

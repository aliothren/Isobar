# 08 External checks: BookSim

The hand-off term is a rate-level bound. BookSim 2 is a cycle-level
router simulator with per-flit routers, queueing and flow control. The
bridge in `scripts/booksim_bridge.py` runs one hand-off's flow set
through both, so that BookSim's batch completion time can be placed
against the term, and so that a set of candidate placements can be
ranked by both judges.

## Build BookSim once

The sources are vendored under `tools/booksim2/` and are not committed;
`tools/booksim2/BUILD_NOTES.md` has the recipe. In short: generate the
parser on the host (`flex`, `bison`), apply the repository's patch, build
in the container:

```bash
# host
cd workspace/tools/booksim2/src && flex config.l && bison -y -d config.y && cd ..
patch -p0 -d src < ../../scripts/booksim_patches/0001-file-traffic-batch.patch
# container
cd /home/workspace/tools/booksim2/src && make -j4
```

The patch adds file-driven batch traffic (`src dst count` lines) and a
per-hop channel latency; nothing else. Check:

```bash
python3 tests/run_tests.py --slow      # the group 38 gates run instead of being skipped
```

## Judge one hand-off of a deployment

```bash
python3 scripts/cimsim_cli.py booksim --deployment analysis/clustered.json --handoff ffn2@L3 --scale 0.01
```

The hand-off is named by its consuming set. Its flows are taken from the
deployment on the fabric's die mesh (which must be square), the volume
is scaled by `--scale` so the packet count stays tractable (the bridge's
batch accounting fails near 600,000 packets), and the batch runs through
BookSim under the bridge's conversion table: packets of 17 flits of 8
bytes (16 payload flits, 128 bytes), a 14-cycle hop, buffers sized to
the bandwidth-delay product, one injection channel per node. That table
is fixed by the pre-registration in the record and pinned by tests.

```
hand-off into ffn2@L3: 25 flows, 2.621e+07 words; the evaluator's busiest resource 1.049e+07 words (link, mesh:seg(9, 3)-(9, 4) +) at kappa 2
BookSim batch: 25 node pairs, 2050 packets at scale 0.01 on a 24x24 mesh, kappa 1 (one injection channel per node)
  bound 13940 flit cycles (channel 13940, injection 6970) | BookSim 17023 cycles | ratio 1.2212 | 2.6 s
  packet_latency_avg 8464.75
  network_latency_avg 1764.58
  hops_avg 3.68
```

The bound is the bridge's own flit-caliber reading of the evaluator's
term, the maximum of the mesh-channel bound and the injection bound;
BookSim lands at or above it. A ratio near one says the term is tight
on this hand-off; a ratio well above one means queueing that the term
does not price. Here it is 1.22: the clustered rule's ffn hand-off
pushes 25 flows from five adjacent producers through two shared links,
and the packets queue behind each other beyond the occupancy bound. The
frozen ranking checks (below) are about whether such deviations reorder
candidates, which they do not at the recorded correlation. `--out`
writes the readings as JSON.

In Python: flows are `(source node, destination node, packets)` on a k
by k mesh with node = y times k plus x, `booksim_bridge.run_batch(flows,
k)` returns cycles and the latency averages, `flit_bounds(flows, k)` the
two bounds, `run_per_packet_serial(flows, k)` the pessimistic rail, and
`lam(t_book, t_opt, t_pess)` places a measurement in the bracket.

## Rank candidate placements under both judges

The frozen ranking check is `scripts/b_fanout_24x24_rerank.py`: nine
stages of 17 dies on the 24 by 24 mesh, 13 candidates (named rules,
random draws and annealer endpoints), the same batch under our term and
under BookSim, Spearman correlation over the 13. With average ranks the
frozen value is 0.953. The volume per pair is scaled down so that one
candidate is about 154,000 packets; larger batches trip BookSim's batch
accounting. `scripts/b7_handoff_probe.py` is the smaller 6 by 6 version
with the term-versus-bound half.

To rank your own candidates, build one flow list per candidate with the
same node convention and call `run_batch` per candidate; compare the
ordering with the evaluator's `t_opt_s` (page 05) with the Spearman
helper in `scripts/main_config_export.py`.

## What the check can and cannot say

- BookSim gives every node one injection channel at the link width, so
  it judges kappa = 1 only. The kappa = 2 main results are the system
  model's own; the ranking check at kappa 1 is the evidence that the
  term orders placements as a packet network does.
- The bridge runs one hand-off batch at a time. The full 2.7B hand-off
  (25 flows of a million words each) is beyond a tractable packet count;
  the checks use scaled volumes and keep the flow structure.
- The hop latency, buffer depth and packet format are aligned to the
  Simba silicon figures, not to the ReRAM package; the check is about
  the term's behaviour under a router network, not a calibration of the
  package.

`BOOKSIM_DEBUG=1` prints BookSim's output tail when a run fails to
parse.

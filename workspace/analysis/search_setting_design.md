# Search-experiment settings chosen from the phase diagram

Revised 2026-09-16 to the writer's synchronisation notes (Isobar_search_experiment_notes.md). Pre-registered in
FIXLIST as S7. Numbers quoted are from artifacts already on record
(ladder_v0, seating_seeds, bw_slice_pair, fanout_floor_probe,
b3_shrunk_rerank); the predictions are arithmetic on them, not results.

## 1. The rule

**Fix a real deployment instance first; choose bandwidths from that
instance's own boundaries second.** Fixed per instance: workload,
mapping, device rate, topology, routing, execution mode, and the
port / link capacity ratio (one injection + one ejection port per die
at the link rate). The placement set P and the cost model give
B₋ = min_P A(p)/R and B₊ = max_P A(p)/R; three sampling points with a
declared, reproducible rule:

| point | rule | what it shows |
|---|---|---|
| above the band | B = 2 B₊ | other costs lead: placement's whole-model effect is diluted |
| inside the band | B = √(B₋ B₊) | different placements change which cost leads |
| below the band | B = B₋ / 2 | communication leads: how much placement can cut |

The legacy 0.4 and 12.5 GB/s points are kept and labelled. No bandwidth
is claimed to "represent real systems"; the multipliers are a sampling
rule, stated with the instance.

**Search once, re-score everywhere.** Under T(p) = R + A(p)/B with R
seat-invariant (pinned to 2e-6 by the bandwidth slice) the ordering of
placements is the same at every B, so the candidate batch is searched
at ONE bandwidth and re-scored at the three points; there is no
"champion per bandwidth". The whole-model gain at each point is
G = η · r(B) with η the communication improvement of the fixed pair and
r the communication share at the reference — an identity, checked to
1e-16 on record.

**Two things are read at every point, separately:** how much of the
whole cost communication is (r), and how much of that communication
placement can still move (η, and its ceiling 1 − floor/A).

## 2. Why two instances: the bottleneck's source, not the bandwidth

The 544-die result showed that moving into the band does not create
headroom: the search endpoint sits exactly on the **port floor**
(every consumer die must receive the full V_b, so A ≥ Σ V_b for any
seating). Lowering the bandwidth scales the floor with everything
else; speeding up compute raises r; neither opens room below the floor.
So the dimension that changes what placement can do is the
**communication structure** — whether the busiest resource is a port
(unmovable) or a shared link (movable). Two representative instances,
one of each:

### Instance A — the port-floor instance (whole-model, "where gains stop")

The 2.7B stack as deployed: per-op mapping (qkv 4, attention 1, out 2,
ffn1 5, ffn2 5 dies per layer), 32 layers, 544 of 576 dies, 24×24 mesh,
XY, serial prefill, R-split multicast. P = the seven named seating
rules. R = 921.2 ms (NeuRRAM rate).

| | value |
|---|---|
| A_min / A_max (busiest words, links ∪ ports) | 555.6M (random) / 1314.8M (sequential) |
| port floor Σ V_b | 523.0M |
| search endpoints (9 runs, item 4) | 523.0M — all on the floor (ratio 1.0000) |
| strongest random draw (5 seeds) | 539.9M (1.032× floor) |
| B₋ / B₊ at the NeuRRAM rate | 0.603 / 1.427 GB/s |

Sampling points and the **predicted** whole-model gain of the search
endpoint (identity G = η·r; η = 5.874% vs random seed 0, 3.13% vs the
strongest draw; the ceiling is the floor against A_max):

| point | B (GB/s) | r | G vs seed 0 | G vs strongest | ceiling (floor vs worst rule) |
|---|---|---|---|---|---|
| above, 2B₊ | 2.855 | 17.4% | 1.02% | 0.55% | 20.1% |
| in-band, √(B₋B₊) | 0.928 | 39.4% | 2.31% | 1.23% | 36.5% |
| below, B₋/2 | 0.302 | 66.7% | 3.92% | 2.09% | 49.7% |
| legacy 0.4 | 0.400 | 60.1% | 3.53% | 1.88% | 47.0% |
| legacy 12.5 | 12.5 | 4.6% | 0.27% | 0.14% | 6.2% |

What this instance answers: **where improvement stops** (the floor, at
every bandwidth), and **when a simple rule is already close** — the
best random draw is 3.2% above the floor in the communication term, the
seed-0 draw 6.2%, least_manhattan 15.5%, the stacked rules 2.4–2.5×.
Outside judge: done (item 3 on the shrunk complete instance; the tie
set on the floor is where the judge and the term part company).

### Instance B — the shared-link instance (a synthetic concurrent communication task)

The cross-traffic load on the same 544-die seating: 32 logical stages,
stage i sends a data object of V words to i+2, i+4, i+8 (out-of-range
edges dropped: 30 + 28 + 24 = 82 stage pairs); R-split — the producer
stage's 17 dies each hold V/17 and every one of the consumer stage's 17
dies receives every piece, so each pair delivers 17V and the whole task
delivers 82 × 17 × V = 1394M words at V = 1e6. **All 82 pairs form one
initially-ready batch**; A(p) is the busiest resource of that merged
batch. V = 1e6 is a synthetic parameter with no tensor provenance and is
kept this round: uniformly scaling V scales every A(p) and leaves
rankings and relative gains unchanged, which is why 1e6 was admissible
for the ranking experiments it served. Its boundaries (B₋/B₊ = 0.020 /
0.033 GB/s against the 2.7B stack's R) are a consequence of the declared
R, V and concurrency and are NOT a hardware anchor for the real 2.7B;
this round does not splice B's one-shot communication onto the 921 ms
compute of the whole model.

| | value |
|---|---|
| A_min / A_max over the seven rules | 18.29M (random) / 30.00M (clustered), links ∪ ports |
| port floor (max per-die inflow) | 3.00M — every rule 6.1–10.0× above it; ports never bind (link-only = with ports) |

What this instance answers: **whether the search removes removable
contention** in a specified concurrent communication task, and whether
packet-level re-evaluation supports the same selection. Whether this
communication structure arises in a real deployment, and what whole-
model gain it would carry, needs a workload and an execution process it
does not have; those are named as out of scope, not assumed.

## 3. Code-caliber check (read from the code, 2026-09-16)

| item | what the code does |
|---|---|
| V allocation and units | `check_c_crosstraffic` / `search_ordering.CrossTrafficJ`: per pair, the producer stage's dies each send V/17 (width 1.0 = one 8-bit activation word = 1 byte) to every consumer die (`_one_boundary_flows`, R-split). CrossTrafficJ counts FLOWS per wire; with equal pieces that is words × 17/V — a monotone identity. Neither includes ports; on this instance ports never bind. BookSim: 128 B payload per packet (16 payload flits of 8 B + 1 head flit), `packets_for(bytes)`. |
| B's stage organisation | all 82 pairs' flows are accumulated into ONE load map and J = max over wires: a single merged batch, A_merged(p) = max_r Σ_k Q_{k,r}(p). Confirmed. |
| A's stage organisation | 159 boundaries (32 layers × 5 die-sets, the wrap excluded), each its own batch; the hand-off term is Σ_k max_r Q_{k,r}(p) / rate — the serial form. R = layers_s (per-layer compute, which scales with device rate, + K/V write + elementwise, which do not) + propagation (Σ_k max hops × 20 ns), the latter seat-dependent but ≤ 2e-6 of T. |
| BookSim timing | `sim_type = batch`, one batch, each source node's packet count patched in; `injection_process = bernoulli, rate 1.0` — every packet is ready at t = 0 and each node offers one packet per cycle on its single injection channel; completion = "Overall min batch duration" = from t = 0 to the last packet's delivery (inject + drain). Routing `dor` (XY), 14-cycle hop (channel 10 + router 4), vc_buf 34, num_vcs 16 (default), credit_delay 2 (default). Available statistics besides the duration: packet-latency average, network-latency average, flit-latency average, hops average — no per-node or per-port counters without patching BookSim. |
| B's BookSim input | the same merged batch: all pairs' flows in one flow file, same readiness (t = 0), same XY routing; the analytic judge and the packet judge see one task. |

The serial/merged distinction matters for reading A against B:
A_merged ≤ A_serial for the same flows, but A and B are different
communication graphs, so their numerical gap is not attributable to the
organisation alone.

## 4. What is run, and what is read

**A — bandwidth slices (re-scoring only).** Candidates: the seven named
rules (seed 0), random seeds 1–4, the nine item-4 endpoints. P for the
boundaries = the seven rules; endpoints found outside P are overlaid,
never used to move the points. Points: 2B₊, √(B₋B₊), B₋/2, plus 0.4 and
12.5. Per point and per named reference ref ∈ {random seed 0, the
strongest random draw, the best named rule}: r_ref(B), η_achieved =
1 − A_search/A_ref, η_ceiling = 1 − A_floor/A_ref, G = 1 − T_search/T_ref,
and the identity G = r_ref · η_achieved checked directly. η_ceiling is
an optimistic bound against a known lower bound; reaching the analytic
floor is not the same as a packet-optimal completion time (item 3).

**B — the search (full instance).** Objective: the fan-out busiest-wire
load (S6's E2b), 2000 steps, α 0.996, t₀ = span/20 over the seven rungs,
THREE INDEPENDENT SA SEEDS from the random start (the strongest rule);
one run from the clustered start is carried for contrast, labelled, and
does not substitute for a seed. Recorded per run: start, seed, t₀,
best-so-far per 100 evaluations, wall time. Read for every baseline and
endpoint: A(p), η vs random seed 0 and vs the strongest random draw,
A/A_floor, and whether the busiest resource is a link or a port before
and after. No preset threshold: a small, zero or reversed gain is kept
and explained; an endpoint that reaches the port floor is a valid
result, not a failure.

**B — the shrunk complete instance under BookSim.** Same logical shape
(+2/+4/+8 fan-out, R-split, merged batch) on the 6×6 mesh: 9 stages × 4
dies = 36 dies, 13 pairs, V scaled to a tractable packet count and
recorded. Candidates: named rules on this grid, random draws, SA
endpoints (3 seeds). Both judges on the same batch: A_merged and the
BookSim batch duration; report the best baseline under each judge, the
selected endpoint's gain or loss under each, the rank correlation, and
the within-tie packet differences. Percentages do not extrapolate to 544
dies. For A's floor tie set, the two most different endpoints are
compared on the statistics BookSim exposes (packet vs network latency,
hops); per-port arrival counters are not available.

## 5. What is not claimed

No bandwidth represents a product. The port floor is a property of
the mapping (R-split multicast to every consumer), not of placement;
lowering it is a mapping question and out of this design's scope. The
544-die gains remain model predictions; the outside judge speaks on
the shrunk instances only.

## 6. Results and conclusion (2026-09-16; artifacts and hashes in FIXLIST, S7 RESULTS)

**A — slices.** The identity G = r_ref · η_achieved holds directly at
every point. η_achieved equals η_ceiling for every reference: the
endpoint is on the port floor, so at every bandwidth the search has
taken all the headroom the analytic term can see. G vs random seed 0 /
vs the strongest draw: 1.02 / 0.53% at 2B₊, 2.31 / 1.21% in-band,
3.92 / 2.07% at B₋/2, 3.53 / 1.86% at 0.4, 0.27 / 0.14% at 12.5.

**B — full instance.** Three independent seeds end at 16.24–16.35M
words (0.72% spread); every baseline and endpoint is link-bound;
endpoints 5.4× above the port floor; the busiest link's load falls
11.3% from random seed 0 and 8.6% from the strongest random draw.

**B — shrunk instance, two judges.** Spearman 0.807, bound holds
(1.35–2.20×). Caveat: on 9 stages × 4 dies the search reaches the port
floor, unlike the full instance. Under BookSim the four floor-tied
endpoints read −5.6 / −5.1 / +2.6 / +6.6% against BookSim's best random
draw; our judge has them all at +25%.

**Diagnosis of a floor tie (A, shrunk).** Two endpoints on the same
analytic floor differ by 16% in BookSim time; the entire difference is
on the 5→5 die boundaries, with network latency +34% and hops unchanged
— dynamic contention on links loaded up to V, the load the term treats
as free.

**Conclusion.** A's further gains are bounded by the R-split mapping's
port floor, not by the search or the bandwidth; the whole-model gain
is the baseline's distance from the floor (3–6% of the communication
term) times the communication share. B's search removes shared-link
contention (−8.6 to −11.3% on the busiest link at full size, all of it
on the shrunk grid). The analytic cost and packet completion time
agree on the selection only down to the floor: inside a floor-tied set
the packet judge orders the endpoints over ±6–11% and can rank the
selected one below the best random draw. A tie-breaker inside the
floor set (total link occupancy, or the count of links at the floor
value) is the natural next refinement of the term; it is proposed, not
run.

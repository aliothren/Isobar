# Published-quantity registry

> Frozen 2026-09-22. The main-result rows are the paper's numbers; rows marked κ = 1 or named after an earlier instance are sensitivity cells or earlier-stage exhibits and are kept with their own denominators.

Every ratio this project publishes, with its DENOMINATOR, its
instance semantics, and its envelope quantifier. Two numbers may not
be compared, added, or printed side by side unless their rows agree on
the denominator. (A4 + A2 of the r3/r4 improvement list.)

**Envelope quantifier.** `certified` = exhaustive over the declared
space, so the number is the space's property. `observed` = multi-start
search over a space too large to enumerate, so the number is a bound
with an evaluation set. Every `observed` row names its evaluation set.
Ruling on exhibits: the main proof exhibit is the S6 cross-scoring
matrix (`observed`); the exhaustive within-die instance is the
`certified` ENVELOPE exhibit standing beside it.

## Placement levers (the diagram's band)

| quantity | denominator | semantics | quantifier |
|---|---|---|---|
| placement-dependent bandwidth band, package level (B− 0.535 / B+ 1.421 GB/s, 2.66×) | the placement extrema of the bottleneck load over the seven named rules, at the NeuRRAM rate, κ = 2 | the band in which the placement decides which cost leads; κ = 1: 0.603 / 1.427, 2.37× | observed (7 rules) |
| placement-dependent band, intra-die level (B− 0.606 / B+ 1.616 GB/s, 2.67×) | the per-operator masking thresholds over all 70 macro seatings of the ffn die | the same band one level down, under the overlap model | **certified** (exhaustive) |
| ordering latency spread (6.55× / 12.26× / 3.57×) | that weave's BEST ordering latency | 48-die pipelined orderings on one weave; adversarial configurations marked in place | observed (enumerated orderings per weave) |
| weave energy spread (ring / torus / mesh) | the mesh ladder's energy per rung | the SAME seven seatings re-priced under another weave — an ENERGY column quantity, named apart from the ordering spread above | observed (7 named seatings) |
| MAIN RESULT: seating-search gain, main configuration (prefill 9.91%; decode 1.57%) | the strongest baseline's whole-model latency at the same configuration (κ = 2, 0.4 GB/s, 24×24, NeuRRAM rate; random_s3) | median over three SA seeds of best-over-three-starts; range 9.66–10.12%, best-of-nine 10.12% labelled apart | observed (9 runs) |
| gain vs the default fill, main configuration (54.5%) | the A4 default (stacked) fill's latency | the cost of the deployment choice, not the search's margin | observed |
| κ sensitivity of the search gain (κ 1: 1.86%, κ 2: 9.91%, κ 4: 9.92%) | that cell's strongest baseline | at κ = 2 and 4 every baseline reads the same (ports never bind) and the search gains agree within the seed range; κ raises the hardware itself by 6.7% apart | observed |
| objective ablation, main configuration (loss avoided 11.4% / 11.2%) | the resource-aware endpoint's latency | how much worse the distance / hop proxies' selections are under the true cost | observed (3 seeds) |
| A3 intra-die β gain incl. package hand-offs (9.02% at 0.4 GB/s) | the shipped seating's layer time incl. the chain's two hand-offs | layer-level, 355M-class instance; 9.52% without the package term | certified (exhaustive) |
| dynamic energy change of the headline layout (+0.26%) | the strongest latency baseline's system dynamic energy (random_s3, 2.5229 J) | E = per-op CiMLoop energy + elementwise + payload words × max(hops,1) × 10 pJ; static not modelled; B- and κ-independent | observed (same layouts as the headline G) |
| communication share of dynamic energy (9.0% random_s3, 1.8% distance rules) | system dynamic energy of that layout | how much of E the seating can move at all | observed |
| energy edge of the compact rules (+7.33% clustered vs random_s3) | random_s3's dynamic energy | the compact-vs-dispersed trade-off; latency cost 20.4% | observed |
| fan-out busiest-link reduction (11.3% vs random seed 0 / 8.6% vs strongest draw) | the reference's busiest-link words on instance B (V = 1e6, 82 pairs, merged batch) | the communication-term gain of the fan-out search; NOT a whole-model gain (B carries no R) | observed (3 SA seeds from the random start) |
| seating gain vs strongest baseline at κ = 1 (weak 1.86% / GRS 0.13%; a sensitivity cell, not the main result) | min over the seven named rules (seed 0) and five random fills (seeds 0–4), scored under the evaluator | the 544-die seating search's endpoint against the best baseline the evaluator can name; the earlier 3.53% / 0.24% are the same endpoints against random seed 0 alone (kept, labelled) | observed (3 start families × 3 SA seeds) |
| within-die band ratio (1.51× attn / 2.00× ffn) | the exhaustive best joint per-die cost | A3 co-residency space, 280 / 70 seatings, 0.4 GB/s cell | **certified** (exhaustive) |
| within-die shipped headroom (+17.8% / +20.0%) | the exhaustive optimum | the shipped contiguous mapping's distance from it, same cell | **certified** |

## Search quantities (S-series)

| quantity | denominator | semantics | quantifier |
|---|---|---|---|
| regret ratio | the instance's DECLARED reference (named-baseline rung, or the exhaustive optimum where one exists — which, is stated per row) | search endpoint ÷ reference; 1.000 = reached it | observed, except the within-die row (certified reference) |
| E0 regret (%) | the true objective's own optimum | how much an arm's argmin costs under the truth | observed (7 named seeds, fixed budget) |
| band_ratio | the exhaustive optimum | worst ÷ best over an enumerable space | **certified** |
| noise band (1.8%) | the multi-start best | convergence scatter of independent starts — the significance floor, not a result | observed |

## Hand-off accounting (never mixed: different denominators)

| quantity | denominator | semantics |
|---|---|---|
| D2D total hand-off share (10.2% at GRS) | whole-model serial latency | ALL 159 hand-offs, intra-layer and inter-layer |
| inter-layer hand-off share (1.15% at GRS) | whole-model serial latency | the 31 layer-boundary hand-offs only — paid at every boundary, cut or not |
| cut-dependent fee (0) | — | what a stage boundary costs beyond the hand-off already paid: zero in the frozen model (one mesh, unpriced package seam) |
| busiest / total words | that hand-off's total words | how much of a hand-off's concurrent flows stack on one link — the seat-sensitive geometry |

**Caliber label on every hand-off number: LINKS AND PORTS.** The
term is the busiest resource over the mesh links AND the die's own
injection / ejection ports (one of each per die at the link rate — a
declared model). The port was added after B7's external adjudication
(finding F-B7): against a packet-level router network on a 36-die
package the wire-only term was a valid lower bound everywhere (BookSim
1.20× on wire-stacked geometries) but loose where flows stack on a
PORT rather than a wire (2.38×, dispersed) — a looseness biased toward
the dispersed family, which our own ladder calls best. Pricing the port
lifted the ladder's best end more than its worst and so SHRANK every
spread (GRS 6.8% → 6.3%, weak 1.95× → 1.82×) and cut the search's
reported seating gains about threefold (weak 11.4% → 3.5%). What
survives externally: the ranking (Spearman 0.886, top-1 agreement,
selected-solution regret 1.0000, disagreements only inside the term's
own ties) and the S6 verdict order (Spearman 1.000, E0 best and E1
worst under BookSim). Data: `analysis/b7_handoff_probe.json`,
`analysis/b7_s6_rerank.json`.

## Latency–energy trade (the band sweep)

| quantity | denominator | semantics |
|---|---|---|
| latency paid (%) | the cell's latency optimum | how far into the band a seating sits |
| energy bought (points) | the energy-optimal seating's energy | percentage points of the T-optimum's energy premium recovered at that band width |

## Region classification (A1)

`certified compute-dominant` / `certified communication-bound` /
`uncertain` per (device tier × link) cell: the verdict compares
compute against the communication BRACKET's two rails. On production
packet-free weaves the rails coincide (Δ ≡ 1.00 by construction), so
the uncertain band has width zero; a middle band exists only on
packet-declared fabrics. Data: `analysis/certified_regions.json`.

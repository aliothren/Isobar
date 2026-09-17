# Writing-materials library

Measured instances registered for the paper's argument, each with its
generator script and figure. Entries are CONDITION-BOUND exhibits — the
claim each carries is stated with the condition attached, never as a
bare constant. (Opened at C64-c per the ladder-v0 review; the report
red-lines apply: entries carry results and mechanisms, no test history
or internal numbering in any outward use.)

## The condition-bound flip: one seating, best-to-worst under a traffic change

The SAME clustered seating (literal rectangle tiling, 32 stages × 17
dies on the 24×24 grid) is the BEST of the seven named baselines on the
busiest die wire under pure-chain traffic (6.2M words; wide rectangle
borders disperse the single hand-off) and the WORST under many-to-many
fan-out traffic, every stage an equal volume to stages +2/+4/+8 (30.0M
words vs snake 28.0M, sequential 22.2M, random 18.3M; the mid-grid seam
between rectangle columns saturates uniformly, five wires at 30.0M
each). The ordering across seatings INVERTS with the pattern: compact
wins the chain, dispersed wins the cross-traffic.

Use: (a) S6 evidence material — distance/compactness proxy objectives
(E1 family) rank correctly under one traffic pattern and invert under
another; an objective's validity domain is condition-bound
(SEARCH_SPEC §7 [AMENDED 11]). (b) The literature tie-in: the same
sentence of the clustered baseline's source paper both defines the
strategy and predicts this failure mode, and the measurement reproduces
both halves on cue (excerpt in `baseline_traces.md`).

Generator: `scripts/check_c_crosstraffic.py`. Figure:
`analysis/check_c_crosstraffic.png`.

## The MASKED form of the same mechanism: within-die co-residency wants interleaving

CONDITIONS THIS ENTRY IS PERMANENTLY BOUND TO: the 0.4 GB/s active
cell x the A3 co-residency configuration (offload, d = 1024,
production 2×4 mesh with glb centre). On that cell the exhaustive
optimum INTERLEAVES the co-resident ops' macros (ffn1 {0,1,3,5} /
ffn2 {2,4,6,7}; qkv {0,1,6} + out {4}) while the shipped CONTIGUOUS
mapping sits mid-band — +17.8% (attn) / +20.0% (ffn) above the
per-die joint optimum, exhaustive bands 1.51× / 2.00×. The other
half of the same sentence: in the g = 2.0 safe cell the whole band
COLLAPSES TO ZERO (all seatings tie, proven by exhaustion) —
whether within-die placement matters at all is itself a CELL
question; the phase-diagram semantics recur at this third level.
SA (S3 day 8) reaches the exhaustive optimum exactly, regret 1.000.

SCOPE — masked form, NOT a flip: this data contains no rank
inversion (no seating wins under one condition and loses under
another); what changes with the condition is the MAGNITUDE
(18–20% → 0). Rank inversion remains exclusive to the flip entry
above — the sharpest piece of the evidence set; do not dilute it by
calling every condition-dependence a flip.

Use: (a) the search chapter's within-die exhibit — ground truth by
enumeration, search validated against it, and a realizable ~18–20%
per-die reading on the shipped mapping, always quoted with both
conditions attached; (b) alongside the flip entry: two levels, one
mechanism — inversion at the die level, masking at the macro level.

Generator: `scripts/search_withindie.py`. Data:
`analysis/search_withindie.json` (hash pinned in FIXLIST).

## Index: the three condition axes vs section 5's three formal evidence pieces

Each axis names the evidence piece it belongs to -- do not conflate
when section 5 is written (per the day-11 review):

- LOAD axis (the condition-bound flip, entry 1 + figure panel 1) =
  **condition-bound**: the same seating's goodness flips with the
  traffic pattern, no crossing along the bandwidth axis.
- CELL axis (the masked form, entry 2 + figure panel 2) = exactly the
  clause **"no crossing along the bandwidth axis"** made visible: the
  gap collapses to zero at the safe cell; never an inversion.
- WEAVE axis (F-L3/F-L4 + `weave_inversion.png` + figure panel 3) =
  **paradigm-dependence**: what wins on ring is `sequential` -- on a
  1D closed chain that IS the most compact ordering, while the
  2D-distance-compact seatings (clustered / least_manhattan / nmap)
  scatter when moved onto the ring. The axis does not say "dispersed
  beats compact"; it says **what counts as compact depends on the
  weave** -- a seating optimized under one weave is wrong under
  another (this is the S6 E3 arm's mechanism).
- **Rank inversion proper** (distance proxy vs true congestion giving
  opposite rankings) lives in NONE of the figure panels: it is the S6
  E1-vs-E0 exhibit, now MEASURED AT ARGMIN LEVEL (day 12): the
  distance arm's own search lands at a clustered-class seat it
  self-scores best (10.18G word-hops) and the truth scores 18.088M =
  +58.9% over the E0 optimum -- the "self-scores well, truth scores
  badly" matrix cell, robust to the mix weights (1.71x at 0.3/0.7).
  Companion finding F-S6a: the weave arm is wrong EVEN UNDER THE
  BENIGN LOAD (the chain control leg -- not a "safe cell": that term
  stays reserved for masked, all-tie cells) -- ring's chain optimum
  is ring-adjacency, 1.38x on the mesh chain. Data: `analysis/search_s6.json` (hash in FIXLIST), figure
  `search_s6.png`.

## Standalone exhibit: the bus paradigm cannot even write the objective

Under the shared-medium bus weave the busiest RESOURCE is the single
medium, whose occupancy is the total volume -- SEAT-INVARIANT: the
ordering objective degenerates to a constant and regret is undefined.
Registered as an exhibit in its own right (not merely the reason E3
declined bus): it is the measured form of the sentence "without the
right paradigm the objective function cannot even be written down."

## Natural fooled-proxy pair: centroid caliber vs per-flow caliber

Two faithful-LOOKING distance proxies disagree with each other: the
stage-CENTROID caliber scores `random` BEST (a spread set's centroid
sits mid-grid, so all pair distances collapse: 194.9M-wd, below every
structured seating), while the per-flow word-hops caliber (the spec's
literal Sigma_e v_e dist(e)) scores `random` WORST (15.28G) and
clustered best (10.18G). The centroid form arose as an implementation
deviation from the pre-written definition and was corrected toward
the spec BEFORE any search ran (gate R4; FIXLIST); it is kept here
because a proxy being completely fooled by dispersion -- and two
proxies contradicting each other -- is itself evidence material for
section 5, better filed than hidden.

## External adjudication: the hand-off term against a packet-level network

The die-level hand-off term — busiest resource over the mesh links and
the dies' own ports — was checked against BookSim on a 36-die package,
the first outside verdict it has had. Our accounting equals the
simulator's own channel bound exactly (integer equality, three
geometries), and the simulator lands above our bound everywhere:
**1.20× where a hand-off's flows stack on a wire, 2.38× where they
stack on a die's port**. That second number named a real omission (the
port, since priced) and is the reason dispersed seatings were being
flattered. What survives externally: the RANKING our term induces
(Spearman 0.886, top-1 agreement, selected-solution regret 1.0000,
disagreements only inside the term's own ties) and, on a shrunk
instance, the **S6 verdict order itself — E0 best, E1 worst, Spearman
1.000**, with magnitudes compressed (E1 1.26× under the packet judge
vs 1.85× under ours).

Use: the search chapter's "is the evaluator trustworthy" paragraph.
The honest shape is a bound that is tight where it matters for
ranking and loose in a direction we named and then fixed — better
material than a bound that was simply right.

Generators: `scripts/b7_handoff_probe.py`, `scripts/b7_s6_rerank.py`.
Data: `analysis/b7_handoff_probe.json`, `analysis/b7_s6_rerank.json`.

## The deployment split costs exactly nothing — and the reason is the
## same homogeneity that makes balanced cutting optimal

On an enumerable instance (4 blocks × 2 dies on a 3×3 mesh, 181,440
joint states — the joint optimum is *certified*), the shipped
DP-then-SA split reaches the joint optimum EXACTLY: gap 1.000 at both
cells over five seeds, DP top-3 refinement and two alternation rounds
each gaining zero. The mechanism, checked rather than assumed: the
DP's cut decision is INVARIANT to the seating, because the seating
moves each block's time by hand-off amounts far below the compute term
that dominates the partition. Verified in the regime where the
partition genuinely groups blocks (a swept per-cut seam price drives
the optimal depth to 2–3 stages) — the gap is still zero there.

Use: the methods section's justification for solving γ and (α, β)
separately, stated WITH its scope — the invariance is exactly what
capacity heterogeneity or replication would break, so this licenses
the split for the homogeneous stacks reported here and not in general.

Generator: `scripts/b5_joint_exact.py`. Data:
`analysis/b5_joint_exact.json`.

## The port floor: where the seating search's gain comes from, and where it stops

Under R-split multicast every consumer die's ejection port carries the
boundary's full volume V_b, so the hand-off term is ≥ Σ_b V_b for EVERY
seating — a floor no placement can go below — with equality iff no link
is loaded above V_b. The 544-die weak-cell winner sits exactly on it
(ratio 1.0000); random fills sit 3–6% above it; stacked rules 2.4–2.5×.
So the whole seating gain is the baseline's distance from the floor
times the communication share: 1.9% against the strongest random draw
at 0.4 GB/s, 0.13% at 12.5, and 0.5–3.9% across the band sampled from
the diagram. Below the floor the analytic term has no resolution, and a
packet-level judge on a shrunk complete instance orders the floor-tied
endpoints over 11%, by dynamic contention on links loaded up to exactly
V — the load the term treats as free.

Use: the search chapter's central mechanism paragraph — it explains
the gain, bounds it, and names what an improved term would need (a
tie-breaker inside the floor set). Pair with the shared-link instance
(fan-out), where the search cuts the busiest link 8.6–11.3% and stays
far above the floor: two bottleneck sources, two behaviours.

Generators: `scripts/a_bandwidth_slices.py`, `scripts/b3_shrunk_rerank.py`,
`scripts/b_fanout_search.py`, `scripts/b_shrunk_fanout_rerank.py`;
test pin: `test_port_floor_under_r_split`. Design and conclusion:
`analysis/search_setting_design.md`.

## Link stacking: the mechanism behind the ranking (main configuration)

Under R-split multicast a 5-die → 5-die hand-off is 25 flows. The
distance-driven rules minimize path length and win at it (4.1 G word-hops,
2.9 hops, vs 22.7 G and 16 hops for a random fill) but stack 10–25 of the
flows on the link between two compact groups; the random fill stacks 8–10
and so has the lower busiest-resource sum (479 M vs 494–652 M words). The
search keeps the dispersion and de-stacks the rest (5 flows on its busiest
links, 55 of 159 boundaries at the port floor): 395 M words, −9.9% of the
model at 0.4 GB/s. Use: the one paragraph in §4.3 that explains, with
loads, why the adapted rules place below a random fill on this instance
and what the search adds. Data: `analysis/mechanism_table.md`;
provenance of every rule: `analysis/baseline_provenance.md`.

## Dynamic energy: no penalty within the search's family, a real trade-off between families

Energy as coded: per-op CiMLoop energy + elementwise + payload words ×
max(hops, 1) × 10 pJ; static not modelled; independent of bandwidth and
κ. The headline layout changes system dynamic energy by +0.26% against its
baseline (nine endpoints +0.10…+0.56%), because communication is 9% of
dynamic energy for dispersed layouts; the compact rules save 81% of
communication energy = 7.3% of the system at 1.8–20% more latency. Use:
the energy sentence of the main result and the compact-vs-dispersed
trade-off; intra-die energy is not modelled and is said so. Data:
`analysis/energy_export.md`.

## The packet judge agrees where links bind

On a 24×24 fan-out task that keeps 17 dies per stage (link-bound like the
full instance), BookSim and the analytic cost pick the same best random
draw, rank 14 candidates at ρ = 0.96, and place every search endpoint
12–31% ahead of that draw; on the port floor (the 6×6 shrinks) the packet
judge spreads the analytically tied endpoints by ±6–11%. Use: §3.3, the
scope sentence for the term's discriminating power. Data:
`analysis/b_fanout_24x24_rerank.json`, `analysis/b3_shrunk_rerank.json`.

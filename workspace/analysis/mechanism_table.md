# Mechanism table (S10 task A2): resource loads behind the main-configuration ranking

24×24, κ = 2, 0.4 GB/s, prefill; 159 serial boundaries per layout; loads in words (ports in link-time units = port words / κ); A = Σ over boundaries of the per-boundary maximum.

| layout | T (ms) | H (ms) | A (M words) | total word-hops (G) | mean hops | Σ max link (M) | Σ max port/κ (M) | boundaries link- / port-bound / tie | A by type: qkv / attn / out / ffn1 / ffn2 (M) |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| default_A4 | 4192.5 | 3271.4 | 1308.6 | 9.67 | 6.81 | 1308.6 | 261.5 | 157 / 0 / 2 | 148 / 121 / 83 / 197 / 760 |
| sequential | 4192.5 | 3271.4 | 1308.6 | 9.67 | 6.81 | 1308.6 | 261.5 | 157 / 0 / 2 | 148 / 121 / 83 / 197 / 760 |
| clustered | 2550.4 | 1629.2 | 651.7 | 4.10 | 2.88 | 651.7 | 261.5 | 127 / 0 / 32 | 96 / 94 / 42 / 84 / 336 |
| nmap_greedy | 2202.7 | 1281.6 | 512.6 | 4.24 | 2.98 | 512.6 | 261.5 | 114 / 0 / 45 | 52 / 81 / 48 / 85 / 246 |
| least_manhattan | 2156.6 | 1235.5 | 494.2 | 4.12 | 2.90 | 493.9 | 261.5 | 112 / 1 / 46 | 49 / 81 / 48 / 81 / 235 |
| heaviest_first | 2409.8 | 1488.7 | 595.5 | 14.24 | 10.03 | 595.5 | 261.5 | 147 / 0 / 12 | 43 / 110 / 75 / 147 / 220 |
| random | 2153.1 | 1231.9 | 492.8 | 22.82 | 16.06 | 492.8 | 261.5 | 144 / 0 / 15 | 40 / 95 / 72 / 92 / 194 |
| random_s3 | 2118.7 | 1197.5 | 479.0 | 22.59 | 15.90 | 479.0 | 261.5 | 137 / 0 / 22 | 39 / 93 / 69 / 96 / 181 |
| sa_random_s1 | 1908.8 | 987.6 | 395.1 | 21.93 | 15.43 | 395.1 | 261.5 | 104 / 0 / 55 | 39 / 69 / 47 / 82 / 158 |

## Hotspots (top-3 boundaries by A_b per layout)

| layout | boundary | A_b (M) | binding | max link (M) @ key | max port/κ (M) | mean hops |
|---|---|---:|---|---|---:|---:|
| default_A4 | ffn2@L0 | 26.21 | link | 26.21 @ ('mesh:seg(11, 0)-(12, 0)', '+') | 2.62 | 5.00 |
| default_A4 | ffn2@L1 | 26.21 | link | 26.21 @ ('mesh:seg(4, 1)-(5, 1)', '+') | 2.62 | 5.00 |
| default_A4 | ffn2@L3 | 26.21 | link | 26.21 @ ('mesh:seg(14, 2)-(15, 2)', '+') | 2.62 | 5.00 |
| sequential | ffn2@L0 | 26.21 | link | 26.21 @ ('mesh:seg(11, 0)-(12, 0)', '+') | 2.62 | 5.00 |
| sequential | ffn2@L1 | 26.21 | link | 26.21 @ ('mesh:seg(4, 1)-(5, 1)', '+') | 2.62 | 5.00 |
| sequential | ffn2@L3 | 26.21 | link | 26.21 @ ('mesh:seg(14, 2)-(15, 2)', '+') | 2.62 | 5.00 |
| clustered | ffn2@L0 | 10.49 | link | 10.49 @ ('mesh:seg(0, 3)-(0, 4)', '+') | 2.62 | 2.68 |
| clustered | ffn2@L1 | 10.49 | link | 10.49 @ ('mesh:seg(3, 3)-(3, 4)', '+') | 2.62 | 2.68 |
| clustered | ffn2@L2 | 10.49 | link | 10.49 @ ('mesh:seg(6, 3)-(6, 4)', '+') | 2.62 | 2.68 |
| nmap_greedy | ffn2@L20 | 12.58 | link | 12.58 @ ('mesh:seg(13, 7)-(14, 7)', '+') | 2.62 | 7.32 |
| nmap_greedy | ffn2@L5 | 10.49 | link | 10.49 @ ('mesh:seg(4, 8)-(4, 9)', '+') | 2.62 | 3.00 |
| nmap_greedy | ffn2@L8 | 10.49 | link | 10.49 @ ('mesh:seg(6, 10)-(7, 10)', '+') | 2.62 | 4.60 |
| least_manhattan | ffn2@L29 | 15.73 | link | 15.73 @ ('mesh:seg(23, 9)-(23, 10)', '+') | 2.62 | 7.24 |
| least_manhattan | ffn2@L25 | 12.58 | link | 12.58 @ ('mesh:seg(1, 23)-(2, 23)', '-') | 2.62 | 3.00 |
| least_manhattan | ffn2@L15 | 10.49 | link | 10.49 @ ('mesh:seg(6, 9)-(7, 9)', '+') | 2.62 | 3.72 |
| heaviest_first | ffn2@L2 | 10.49 | link | 10.49 @ ('mesh:seg(11, 13)-(11, 14)', '+') | 2.62 | 3.80 |
| heaviest_first | ffn2@L10 | 10.49 | link | 10.49 @ ('mesh:seg(8, 14)-(8, 15)', '+') | 2.62 | 5.88 |
| heaviest_first | ffn2@L14 | 10.49 | link | 10.49 @ ('mesh:seg(16, 14)-(16, 15)', '+') | 2.62 | 6.08 |
| random | ffn2@L5 | 10.49 | link | 10.49 @ ('mesh:seg(16, 15)-(17, 15)', '-') | 2.62 | 14.72 |
| random | ffn2@L24 | 10.49 | link | 10.49 @ ('mesh:seg(13, 1)-(13, 2)', '-') | 2.62 | 13.72 |
| random | ffn2@L2 | 8.39 | link | 8.39 @ ('mesh:seg(8, 10)-(8, 11)', '+') | 2.62 | 21.04 |
| random_s3 | ffn2@L18 | 10.49 | link | 10.49 @ ('mesh:seg(6, 14)-(6, 15)', '-') | 2.62 | 20.80 |
| random_s3 | ffn2@L2 | 8.39 | link | 8.39 @ ('mesh:seg(11, 3)-(11, 4)', '-') | 2.62 | 14.72 |
| random_s3 | ffn2@L9 | 8.39 | link | 8.39 @ ('mesh:seg(9, 18)-(10, 18)', '-') | 2.62 | 16.48 |
| sa_random_s1 | ffn2@L1 | 5.24 | link | 5.24 @ ('mesh:seg(1, 8)-(2, 8)', '+') | 2.62 | 18.04 |
| sa_random_s1 | ffn2@L2 | 5.24 | link | 5.24 @ ('mesh:seg(11, 4)-(11, 5)', '-') | 2.62 | 16.60 |
| sa_random_s1 | ffn2@L4 | 5.24 | link | 5.24 @ ('mesh:seg(0, 20)-(0, 21)', '+') | 2.62 | 18.00 |

## Reading (data-supported)

**The hand-off is R-split multicast**: every producer die of a set ships its
piece to every consumer die, so a 5→5 boundary (ffn1 → ffn2) is 25 flows of
1.05 M words each, 26.2 M words delivered, and a 4→1 boundary (qkv → attention)
is 4 flows into one die. The per-boundary cost is the busiest resource, and the
port floor at κ = 2 is V/κ = 2.62 M words for every ffn2 boundary.

**Why the adapted rules lose to the random fills.** The three distance-driven
rules minimize path length and succeed at it — 4.10–4.24 G word-hops and 2.9
mean hops against 22.6–22.8 G and 16 hops for the random fills. But packing a
stage's 17 dies into a compact group and seating the next stage beside it
funnels the 25 ffn2 flows through the few links between the two groups: the
busiest ffn2 link carries 10 flows under clustered (10.49 M), 10–12 under
nmap_greedy, 10–15 under least_manhattan, and all 25 under the sequential /
default fill (26.21 M — one link carries the whole boundary). A random fill
spreads producers and consumers over the package so the 25 flows take mostly
disjoint routes: its busiest ffn2 link carries 8–10 flows, and its aggregate
A is 479–493 M against 494–652 M for the rules — five times the
path length, a lower maximum. On this instance the cost is decided by link
stacking, not by distance; the rules optimize the wrong quantity and the
random fills pay for their length only in energy, which the latency objective
does not price.

**Why the resource-aware search beats the random fills.** The endpoint keeps
random's dispersion (15.4 hops, 21.9 G word-hops) and removes the remaining
stacking: its busiest ffn2 links carry 5 flows (5.24 M, twice the port floor),
55 of 159 boundaries are brought to the point where the busiest link equals
the port floor, and A falls from 479 M (the strongest random draw) to 395 M —
17.5% of the communication term, 9.9% of the whole model at 0.4 GB/s. By type the
reduction sits where the stacking was: ffn2 181 → 158 M, attention 93 → 69 M,
out_proj 69 → 47 M; qkv is already at its floor for every layout (39 M).

**On nmap_greedy specifically**: the implemented rule minimizes words × centroid
distance along the chain with NMAP's construction and one-sweep refinement; it
carries no per-link capacity term (see baseline_provenance.md for what of the
original is and is not implemented). Its short paths (2.98 hops) and its 10–12
stacked flows per hot link are both visible above; the statement the data
supports is that a distance-weighted traffic objective does not see link
stacking on this instance, not a statement about the original NMAP's
bandwidth-constrained formulation.

# Baseline provenance (S10 task C): original work → implemented rule → optimized quantity → adaptation

Read from `scripts/search_baselines.py` and `analysis/baseline_traces.md`
(the check-D excerpts and replays). Every row states what the CODE does;
the "original" column is the cited method's scope as recorded, and a
rule's result never speaks for the whole original method or platform.
None of the rules prices per-link capacity or die ports; that is the
evaluator's contribution, and it is what the objective ablation measures.

| implemented rule (label) | original work | what the implemented rule optimizes | resource information it uses | adaptation to this legal space (declared) | what of the original is NOT implemented |
|---|---|---|---|---|---|
| `sequential` (= the A4 default fill) | none — the stacked row-major fill; the deployment default | nothing; stages placed in chain order, row-major | none | dies of a stage are consecutive slots | — |
| `snake` | none — boustrophedon fill (consecutive stages adjacent) | adjacency of consecutive stages | none | row-major with alternating row direction | — |
| `clustered` | Gemini (Cai et al., HPCA 2024, arXiv:2312.16436) — the "clustered core allocation" strategy Gemini DESCRIBES and critiques, Sec. VII | compactness: each stage a consecutive, rectangular core group; stages walk the rectangle grid in snake order | none (geometry only) | 24×24 tiled into 3×6 rectangles (18 slots, 17 used), 8 × 4 rectangles for 32 stages; the definition taken at its word (check A3 replaced a blob-growth heuristic with the literal tiling) | Gemini's own mapper / architecture exploration and its evaluation pipeline; only the baseline strategy it names is implemented |
| `least_manhattan` | SIAM (Krishnan et al., 2021, arXiv:2108.08903) — the chiplet-IMC benchmarking framework's placement rule | Manhattan distance of each die-set to the PREVIOUS set's centroid (chain order, greedy) | distance only | multi-die sets seated on the nearest free slots to the previous centroid; SIAM has no worked placement example, so the rule is replayed, not recomputed | SIAM's cross-layer evaluation (NoC/NoP simulation, thermal, area, its cost models); only its placement rule |
| `nmap_greedy` | NMAP (Murali & De Micheli, DATE 2004, "Bandwidth-constrained mapping of cores onto NoC architectures"), Sec. 5 heuristic | Σ over chain boundaries of words × Manhattan distance between the two sets' centroids (the shortest-path communication cost adapted to a centroid-distance caliber) | traffic volume × distance; no per-link capacity term in the implemented cost | initialize(): max-communication set at the mesh centre, then repeatedly the unmapped set communicating most with the mapped ones, seated minimizing comm × distance to the mapped sets; then ONE O(U²) pair-swap sweep with per-row commit (the original's structure, verbatim; the earlier run-to-convergence variant was reverted). A "core" is a die-set. On 2.7B the sweep commits swaps moving 4 sets (773.7M → 769.3M word-hops) | the original's bandwidth-constraint check on the links (its title's constraint) and its split-traffic / minimum-path routing phase are not implemented — the implemented rule is NMAP's construction and refinement structure on a distance-weighted traffic cost. Whether the original's bandwidth constraint would bind on this instance is not tested here; the writer should verify the original's exact constraint handling before characterizing it |
| `heaviest_first` | Graham / LPT lineage (longest-processing-time-first scheduling) | boundaries taken in descending traffic volume; each not-yet-placed endpoint set seated on the free slots that stretch THAT boundary least (anchor: mesh centre for the first, the placed neighbour's centroid after) | traffic volume ordering + distance | the objective carrier differs from scheduling (distance stretch instead of machine load); replay only. On the 355M unit chain all boundary volumes are equal, so the order degenerates to chain order (noted) | LPT's makespan guarantee has no counterpart here; the rule is a lineage, not a reproduction |
| `random`, `random_s1..s4` | none | nothing; uniform random assignment of the 544 dies to the 576 slots | none | seeds 0–4 declared; the S9 sample is these five and no others | — |

Two facts the mechanism table adds (main configuration, κ = 2, 0.4 GB/s, prefill): the three
distance-driven rules reach the shortest total paths on the instance (4.1–4.2 G word-hops, 2.9
mean hops) and still lose to the random fills (22.6–22.8 G word-hops, 16 hops) on the
busiest-resource sum (494–652 M vs 479–493 M words) — under R-split multicast every producer die
of a 5-die set ships to every consumer die, and a compact pair of sets funnels those 25 flows
through the few links between the two groups; dispersion spreads them over disjoint paths. The
resource-aware search keeps the dispersion (15.4 hops) and removes the remaining stacking
(395 M words, 55 of 159 boundaries brought to the point where the busiest link equals the port
floor). See `analysis/mechanism_table.md`.

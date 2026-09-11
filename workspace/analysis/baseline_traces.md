# Baseline execution traces for the manual source comparison (check D)

Prepared for the HUMAN replay of each cited rule against the code
(S2 day 5 item 0). Host: the 355M 48-unit chain on the 6x8 die grid
(1 die per unit -- every step is hand-checkable); the 2.7B rectangle
tiling is fully recomputable from its parameters (below).

Source recomputability notes: SIAM -- no worked placement example in
the paper: RULE REPLAY ONLY (A2 pin). NMAP -- its examples are task
graphs, not our chain: NO DIRECTLY RECOMPUTABLE EXAMPLE; the rule
replay + convergence pin (A1) cover it. Graham/LPT -- the classic
scheduling examples are recomputable in spirit only (different
objective carrier); rule replay (A4) covers it. Gemini -- definition
only, no example; the rectangle tiling is checked against the
definition (A3 + the tiling parameters below).

## least_manhattan (SIAM rule) -- first 8 steps

| step | prev centroid | top-3 candidates (slot: dist) | pick |
|---|---|---|---|
| 0 unit0 | (0.00,0.00) | 0: 0.0, 1: 1.0, 6: 1.0 | [0] |
| 1 unit1 | (0.00,0.00) | 1: 1.0, 6: 1.0, 2: 2.0 | [1] |
| 2 unit2 | (1.00,0.00) | 2: 1.0, 7: 1.0, 3: 2.0 | [2] |
| 3 unit3 | (2.00,0.00) | 3: 1.0, 8: 1.0, 4: 2.0 | [3] |
| 4 unit4 | (3.00,0.00) | 4: 1.0, 9: 1.0, 5: 2.0 | [4] |
| 5 unit5 | (4.00,0.00) | 5: 1.0, 10: 1.0, 9: 2.0 | [5] |
| 6 unit6 | (5.00,0.00) | 11: 1.0, 10: 2.0, 17: 2.0 | [11] |
| 7 unit7 | (5.00,1.00) | 10: 1.0, 17: 1.0, 9: 2.0 | [10] |

## heaviest_first (LPT lineage) -- first 8 placements
(all boundary weights equal on the unit chain: 1,310,720 words --
the descending order degenerates to chain order, noted)

| boundary | anchor | pick |
|---|---|---|
| unit0->unit1 | centre (2.5, 3.5) | unit0:[20] |
| (same) | prev centroid | unit1:[14] |
| unit1->unit2 | (2.00,2.00) | unit2:[8] |
| unit2->unit3 | (2.00,1.00) | unit3:[2] |
| unit3->unit4 | (2.00,0.00) | unit4:[1] |
| unit4->unit5 | (1.00,0.00) | unit5:[0] |
| unit5->unit6 | (0.00,0.00) | unit6:[6] |
| unit6->unit7 | (0.00,1.00) | unit7:[7] |

## nmap_greedy -- construction order + swap summary
[SUPERSEDED by the check-D excerpt verdict below, then RECOMPUTED
under the reverted-to-original semantics:]
355M dynamic selection head: ['unit1', 'unit0', 'unit2', 'unit3',
'unit4', 'unit5'] -- unit1 first (max comm 2w, tie broken to the
first middle), then unit0 (tie w vs w against unit2, names-order
break), then chain-forward; matches the hand reasoning. Refinement
= ONE fixed O(U^2) sweep, per-row best-commit (A1 pins a full
independent replay of that structure). Sweep effect: 355M commits
zero swaps (construct already optimal under the caliber); 2.7B
commits swaps moving 4 sets, cost 773.7M -> 769.3M word-hops.

## clustered -- the rectangle tiling parameters (fully recomputable)

2.7B: 24x24 grid / 32 stages x 17 dies -> rectangle 3 WIDE x 6 TALL
= 18 slots (waste 1/stage; corrected by the hand recomputation --
this file first said 6x3), 8 columns x 4 rows = 32 rectangles,
stages in SNAKE order over rectangle rows; within a rectangle:
row-major, first 17 slots (stage 0 = {0,1,2, 24,25,26, ... 120,121},
drop 122 -- hand-derived and equal to code). 355M: 48 stages x 1 die -> 1x1 rectangles = the
snake walk itself (degeneration, noted).


## Check D anchor excerpts (verbatim from the sources)

### clustered -- Gemini (Cai et al., HPCA 2024; arXiv:2312.16436), Sec. VII insight

> "the widely used clustered core allocation strategy [7], [15], [46],
> [55], [57], [66], where a layer is assigned to consecutive and
> rectangle-like core group, may not always be a good choice. This is
> because the dependencies between certain layers may have particularly
> high data transfer requirements, and clustering cores for each layer
> together cannot disperse this transfer demand, leading to network
> congestion."

CORRESPONDENCE: our implementation assigns each stage a consecutive,
literally rectangular core-group (the 3x6 rectangle tiling) -- the
first half of the sentence is the definition we implement; the second
half is the congestion pathology check C must reproduce under a
heavy-cross-dependency load (the excerpt supplies both the premise --
"dependencies ... particularly high data transfer requirements" --
and the predicted failure mode).

### nmap_greedy -- NMAP (Murali & De Micheli, DATE 2004), Sec. 5

> "we use a heuristic approach that has three phases: an
> initialization phase that computes an initial mapping, followed by
> the second phase, where minimum path computations are performed. In
> the last phase, the initial solution is iteratively improved by
> invoking the second phase for each pair-wise swapping of vertices."

> "In the initialize() routine, the core that has maximum
> communication demand is placed onto one of the mesh nodes with
> maximum number of neighbors. Then for each core yet to be mapped,
> the core that communicates most with the already mapped cores is
> selected. The core is placed onto the mesh node that minimizes the
> communication cost with mapped cores."

> "The routine mappingwithsinglepath() finds the best mapping obtained
> by pair-wise swapping of vertices, invoking shortestpath() routine
> O(U^2) times."  [pseudocode, verbatim structure:]
>   for i = 1 to |U|: for j = i+1 to |U|:
>       Ptemp = Placed with vertices wi, wj swapped;
>       commcost = shortestpath(Ptemp);
>       if commcost < bestcommcost: Bestmapping, bestcommcost = Ptemp, commcost
>   assign Bestmapping to Placed   [committed PER OUTER ROW]

VERDICT (check D bit again): the original refinement is a FIXED SINGLE
systematic O(U^2) pass with per-row commit -- NOT run-to-convergence
(which our A1 repair had installed); and initialize() selects the next
core DYNAMICALLY (max communication with the already-mapped set) and
seats it minimizing the communication cost to ALL mapped cores -- not
a static descending order. Both corrected in the implementation; the
A1 pin becomes a full independent replay of the original procedure.
Cost caliber: their shortest-path comm cost is adapted to our
chain/centroid-distance caliber (declared; the REFINEMENT STRUCTURE is
verbatim).

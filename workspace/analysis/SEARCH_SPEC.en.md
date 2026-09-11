# SEARCH_SPEC v1 — the search milestone's founding specification

> Repo-resident revision of `SYNC_search_v1` (2026-09-10), the semantic
> authority for worklist step 7 (S1–S6). Dual identity: the implementation
> spec AND the paper's search-chapter method draft. All rulings are final;
> the two spots marked "v1 default, swappable" are the only open knobs.
> The accepted implementation-layer amendments (review, 2026-09-10) are
> integrated in place and marked **[AMENDED]**; the run disciplines are
> pre-registered in FIXLIST (SEARCH V1 PRE-REGISTRATION, C64-a).
> Reading order: §1–§2 background once; §3–§8 are the normative body
> (implementation reference); §9–§10 the path and discipline.

---

## 1. Positioning (why this chapter exists; what it claims and does not)

The three-step argument (final):
1. Under LLM scaling and device acceleration, placement becomes a
   non-ignorable design factor in analog CIM — the simulation chapters
   established this (the phase diagram gives the "when it matters"
   criterion and the three-region structure).
2. Prior work does not model the placement dimension: mapper-class spaces
   have no position (two different placements are the same point in their
   cost models); chiplet-side methods act on streaming digital substrates
   (weights stream from DRAM each stage, energy is a real lever), and
   neither their space nor their objective transfers to a weight-resident
   analog substrate.
3. We therefore define a new, placement-aware search problem — space,
   objective, constraints — and give a feasible search method and results.

Three claims (experiment owners in §10):
- **Capability**: the first system able to run placement-aware search for
  analog CIM; prior absence is not algorithmic weakness — the correct
  objective cannot be written on an evaluator with no contention pricing
  and no position dimension.
- **Value**: in the phase diagram's active cells, search beats the
  strongest named heuristic; in the safe cell everything ties.
- **Necessity**: the same algorithm under a wrong referee confidently
  searches wrong (S6's four arms); the evaluation platform is not
  optional.

Explicit non-claims: no superiority claim for SA or any search method; no
entry into the search-methodology contest; no chasing multiplier records.

## 2. Literature coordinates (which component each source feeds)

- **Alpa (Zheng et al., OSDI 2022) → variable level 1 (§8 DP).** The
  complete solve form for "chain partition + resource assignment"; oracle
  interface (outer DP consumes inner cost t(segment, resource) budget
  tables = §8's F(k,j,d) lookup); objective form T = Σ_k t_k +
  (B−1)·max_k t_k with B=1 / B→∞ our single / pipe calibers (§5 step 4);
  the enumerate-t_max DP trick is needed only if §12's batch-B switch
  opens — pure calibers degenerate to plain interval DP.
- **Gemini (Cai et al., HPCA 2024) → variable levels 2–3 (§8 SA).** The
  nearest SA practice on the same assignment space; its OP2/OP3/OP4
  translate to our permutation / migration / swap families; the
  ergodicity-argument-ships-with-code practice (§8's one-pager). Its
  graph-partition level uses Tangram's DP (Gao et al., ASPLOS 2019) —
  level 1's original source and second endorsement.
- **RapidChiplet (Iff et al., CF 2025) + BookSim2 (Jiang et al., ISPASS
  2013) → evaluation layer (§5).** Its throughput proxy = min over links
  of (bandwidth / load) is the same functional as our busiest-wire
  occupancy — independent convergence + third-party defense of the
  contention semantics; its "closed-form proxy search + BookSim
  anchoring" two-tier architecture is the published isomorph of our §5
  bracket + V2 calibration. Caution: its latency proxy is a zero-load
  path-weight sum — our PROPAGATION term, not our serialization term; do
  not conflate.
- **SIAM (Krishnan et al., 2021) → one S2 baseline (§9).** Same level,
  same Simba anchor; its placement rule is collectable verbatim:
  least-Manhattan sequential placement → registered as
  `least_manhattan`. Nothing else enters the implementation.
- **NoC mapping lineage → S2 baselines (§9) and S6's E1 referee (§7).**
  Hu & Marculescu (ASP-DAC 2003; TCAD 2005): E1's canonical source —
  minimize traffic × distance communication energy under bandwidth
  reservation; E1 implements this faithfully, citation in code comments.
  NMAP (Murali & De Micheli, DATE 2004): `nmap_greedy(+swap)`'s rule
  source. BMAP (Shen et al., NOCS 2007), clustering SA (Lu et al., 2008):
  lineage footnotes, cited not implemented.
- **EcoNAS (Zhou et al., CVPR 2020) + Zero-Cost Proxies (Abdelfattah et
  al., ICLR 2021) → S6 protocol (§7).** The "each arm searches, the truth
  re-scores" protocol is established methodology in NAS; these are its
  sources (systematic proxy rank-fidelity study; the recorded degradation
  of proxy discrimination among head candidates — precedent for the
  "self-scores high, truth scores low" cell).
- **Background kit.** Graham/LPT (1969): `heaviest_first` (§9); max-
  objective combinatorial prototype. sequence-pair (Murata et al., TCAD
  1996): §4's "representation guarantees legality" ruling. Bottleneck QAP
  (Burkard et al., textbook): the within-die problem's classical seat
  (capacity-constrained bottleneck assignment).
- **Internal citations (implementation looks these up directly).** C58
  price∝length theorem and the bus counterexample (E1's validity domain);
  A1 degeneracy theorem and A3 co-residency reopening (the within-die
  space's existence condition); the soft-lever table (active cells' space
  width prior); b1_orderings and A4's 544-seat seating + 16-package seam
  example (S4's standard payload); the O19 ten-scheme registry (the
  condition-enumeration weave pool).

## 3. Condition layer (frozen givens; no search arm may touch)

- Hardware F: package grid P, the within-die slot tree
  (macro/core/crossbar, leaf capacity cap(s)), per-level interconnect
  schemes σ_ℓ and BW_ℓ, propagation parameters (the ns_per_mm chain),
  DR-9 offload-unit declared parameters. **The weave is a condition, not
  a variable** (the FIXLIST principle sentence): the search at most
  re-runs under different weave conditions — semantically S6-style
  condition enumeration.
- Workload W: a chain of L homogeneous blocks, decomposed by the frozen
  tiling T (mapper output, column-split regime) into the weight-block set
  B_W and per-op traffic generation rules. **[AMENDED, S1 day 2]** the
  DIE-SET GRANULARITY is part of T and is DECLARED BY THE WORKLOAD
  (legal() consumes the declared inventory, never re-derives it): the
  2.7B class seats per-op sets (block_chain), the 355M class seats
  per-UNIT under the C13 two-dies-per-layer co-residency rule.
  **[AMENDED, S1 day 3]** the weave is likewise a condition and enters
  through the workload constructor's `die_weave=(topology, params)`
  parameter (default: the fabric config's own) -- score() itself is
  weave-free; this is S6's E3 entry point and the condition-enumeration
  knob, added BEFORE the interface freeze so E3 never touches frozen
  code. Row split is an explicit
  regime switch (A2); any use must be stated at both levels; not a v1
  variable.
- Phase set Φ = {prefill(S), decode}; service caliber c ∈ {single,
  pipe}; phase weights μ are declared inputs.
- The mapper and the CiMLoop calibration layer stay frozen and shared;
  mapping-placement joint search is named future work (outside v1).

## 4. The search space Ω

Decision variable Π = (γ, α, β):
- Level 1, γ (chain partition): a vector of contiguous-segment cut points
  over [1..L]; segment k's weight set W_k derives from T.
- Level 2, α (seating): an injection α: ⋃_k D_k → P. **[AMENDED 1 — the
  O10 lesson; O17c's 4.3× flip-point miss its precedent]** |D_k|'s lower
  bound AND its fill-exact value come from `plan_spatial` (the tiler),
  never ceil(vol/cap) — capacity arithmetic is not legality (2.7B ffn1:
  capacity 4, tiler 5; qkv@6144: capacity 14, tiler 24). Replication is
  an extension switch, v1 OFF. α also carries the small dimensions:
  hub / boundary-port position (effective only on grids of width ≥ 3,
  per C28) and the offload-unit attach point h ∈ P.
- Level 3, β (within-die seating): per die d an injection β_d: W(d) →
  slots(d).

Legality legal(Π) = the formalization of Placement.verify(): contiguous
segments, pairwise-disjoint die groups, per-level capacity, no overlap,
residency completeness, **plus the tiler fold-in [AMENDED 1]**. Ω = {Π :
legal(Π)}.

Legality encoding ruling: representation-guarantees-legality as the
principle (cut vectors are contiguous by construction; assignments use
permutation encoding); at capacity-saturated spots the two-step operator
(move-out then move-in) is the declared exception — written into the
operator table and the ergodicity argument.

## 5. The evaluation pipeline (Π → numbers, fully closed-form)

Four steps, all reusing standing machinery; S1 is interface closure only:
1. Traffic extraction flows(Π, φ): hyperedges {(S_e, D_e, v_e)} —
   multicast once, reduction-hub merging, value-word metering,
   placement-endogenous — the dividing line against all prior work.
2. Occupancy: load_r(Π,φ) = Σ_{e: r∈route_σ(e)} v_e.
3. Per-op time. Optimistic end t^opt = max(t_comp, max_r load_r/BW_r) +
   t_prop; the pessimistic end adds, on packet-declared weaves, the full
   per-hop toll Σ_e n_pkt(e)·hops(e)·t_hop (n_pkt = ⌈v_e/payload⌉; the
   packet guard list per O19's standing state).
4. Composition: T_single = Σ_op t_op + FT(φ) (fixed floor: on-chip K/V
   write + digital unit; offloaded = unit + link, attach point h enters
   via routing); the pipe caliber takes segments as stations, T_B = Σ_k
   t_k + (B−1)·max_k t_k (B=1 / B→∞ = the two standing calibers).
   Energy E(Π,φ) = E_fixed + Σ_e v_e·price(e) (price ∝ wire length, C58).
   **[AMENDED — FT bookkeeping]** segment-borne member terms ride their
   segment; global terms enter once (the A4 serial semantics extended).

**Bracket policy (ruling)**: ranking always by the optimistic end T^opt
(exact on compile-time weaves; the measured reachable floor on packet
weaves — V2 endorsed). The pessimistic end never ranks; it is the
robustness gate. **[AMENDED — execution face]** every results table from
S3 on carries the Δ column, Δ(Π) = T^pess/T^opt; where candidates' Δ
differ significantly the conclusion states whether the ranking survives
the protocol-tier worst assumptions. Not deferred to writing time.
**[AMENDED, S1 day 2-3]** Δ is produced from S1 day 2 onward (every
Score carries t_pess and Δ); on packet-free weaves — every production
fabric — the toll is zero and **Δ = 1.0 is a DEFAULT ASSUMPTION BY
CONSTRUCTION, not a verified conclusion**: the pessimistic end only
separates from the optimistic one on packet-declared weaves.
**[AMENDED, S1 closeout — schedule_slack's seat]** `schedule_slack`
(O26) is a PLATFORM INPUT of the condition layer and was never a
score() argument: it rides the FABRIC the workload holds (the same
entry route as the weave) and is consumed exactly where its O26
semantics apply — the occupancy-bound paths (`link_occupancy` reads
it from W's fabric; the 355M backend inherits it). The 2.7B serial
hand-off term is a direct transfer time, NOT an occupancy bound, so
slack rightly does not multiply it. No arm of S6 tunes slack (arms
share the condition layer). Not dropped; seated.

## 6. Objective and phase modes

Main objective: min_{Π∈Ω} J(Π) = Σ_{φ∈Φ} μ_φ · T^{(c)}(Π,φ).

- Energy is the lexicographic tie-break (equal J → smaller E; B1's
  measured 1.74× is the deciding channel). Energy does not enter the main
  objective — the two-tier measured flat axis grants the license. **Every
  results table reports both columns** (a latency column with an energy
  column beside it). **[AMENDED 9 — instance→objective mapping + the
  tie-break clause's scope; from ladder v0's measured column split
  (C64-c findings F-L1/F-L2)]** The tie-break clause above HOLDS ONLY
  for instances whose main objective is T. Measured basis: on the 2.7B
  caliber the per-boundary words are placement-invariant by
  construction, so SEATING moves T only through the µs propagation term
  (73 µs across the seven baselines; T_pipe bit-identical) while the
  energy column spreads 8.0%. Mapping, per instance:
    * 2.7B seating instance — **main objective = E** (T reported
      alongside as the flat column);
    * 355M ordering instance — **main objective = wire time** (the
      link-occupancy caliber; 4.0× measured spread);
    * the cuts/segment level and condition enumeration — main objective
      stays T, energy stays the lexicographic tie-break.
  Scope of the two standing sentences, filed after the E-column
  reconciliation (both T-column leaders within 0.1% of the E-best
  seat): "8.0%" quantifies the FULL seven-seat spread, dispersed end
  included; "latency-optimal seating costs the system below
  one-thousandth in energy" quantifies the T-best→E-best gap
  (nmap_greedy +0.060%, least_manhattan +0.011% of system energy vs
  clustered). The old blanket "within-percent boredom of the energy
  column demonstrates latency optimization is free" is RETIRED in favor
  of these two scoped statements.
- Three phase modes, μ declared: one-hot (single phase) / weighted mix /
  constrained (min T_decode s.t. T_prefill ≤ budget). **v1 default:
  constrained** (serving reality; v1 default, swappable). The phase is a
  first-class dimension of the space definition.
- **[AMENDED 3 — constraint handling]** Constrained mode uses REJECTION
  (J semantics stay pure; no penalty coefficient exists), with the
  anti-stranding guardrail: every multi-start seed set contains at least
  one FEASIBLE named-baseline solution (ladder table v0 is the pool);
  if all baselines are infeasible in a cell, "the constraint is
  unsatisfiable there" is a filed RESULT — never rescued by a penalty.

## 7. The S6 referee family (four arms; same Ω, algorithm, budget, seeds)

- E0 = §6's full J.
- E1 = Σ_e v_e·dist(e) (the distance proxy; the faithful implementation
  of Hu-Marculescu's canonical objective, citation in code comments; the
  C58 theorem gives its validity domain — price ∝ length AND no
  contention axis; the paper phrases it as "a validity domain that did
  not migrate with the substrate", not a strawman).
- E2 = J under a one-hot μ (single phase).
- E3 = J with route_σ swapped to the wrong paradigm tier (weave pool =
  the O19 registry).
- Protocol: each arm argmin-searches → all re-scored by E0 under the full
  phase set; regret R_i = J(Π_i*)/J(Π_0*); the cross-scoring matrix
  (E_i's self-score of Π_i* vs E0's verdict — the "self-scores high,
  truth scores low" cell is the core exhibit).
- Cell discipline: active cells only (fast device tier, shared medium,
  offloaded decode, weak D2D × spanning) + one safe-cell control
  (expected: all four arms tie ≈1.00). Per-cell expectations pre-written.
- Arm isolation: the four evaluators share no tunable constants; every
  E1–E3 number has a citation or a declaration.
- **[AMENDED 11 — evidence material registered (C64-c)]** The
  condition-bound flip instance, measured: the SAME clustered seating
  swings from best of all seven (6.2M busiest-wire words, pure-chain
  traffic) to worst (30.0M, +2/+4/+8 fan-out) as the traffic pattern
  changes (`scripts/check_c_crosstraffic.py`,
  `analysis/check_c_crosstraffic.png`) — the measured exhibit that an
  objective's validity domain is CONDITION-BOUND, i.e. E1-style
  distance/compactness proxies rank correctly under one traffic pattern
  and invert under another. Registered here as S6 evidence material and
  in the writing-materials library (`analysis/MATERIALS.md`), not only
  in the check record.

## 8. Solver split and the operator table

- Level 1: exact interval DP. State F(k, j, d) = first j blocks in k
  segments using d dies; segment costs from a pre-budgeted oracle table
  t(segment range, group size) (closed form makes full enumeration
  cheap); cut-point edge weights include hand-off fees. **[AMENDED 1]**
  the oracle table's group-size axis is the TILER-FEASIBLE SIZE SET
  (possibly sparse), not "integers ≥ bound"; DP states unchanged.
  **[AMENDED 2 — direction statement]** edge weights price hand-offs at
  ADJACENT-SEATING REFERENCE HOPS (α refines under fixed γ): this makes
  the DP systematically OPTIMISTIC on hand-off fees, but hand-offs are
  the measured cheapest edge class (the 0.10 GB/s-threshold family), so
  the bias's effect on cut choice is expected negligible — its actual
  magnitude falls out of day 8's joint-vs-decomposed small instance for
  free and is filed back here. Homogeneous block stacks are expected
  near-degenerate — uniform cutting is the declared baseline (A4's flat
  spread is that point), expectation pre-written; the DP earns its keep
  under capacity heterogeneity or with replication on.
- Levels 2–3: SA. Three operator families — permutation (within-group /
  within-slot exchange), migration (cross-group / cross-die moves;
  capacity-saturated spots use the two-step operator), swap (pairwise,
  NMAP-refinement style). Support: (a) incremental evaluation — an
  ordered line-load structure, one step recomputes affected lines then
  re-takes the max, with an incremental ≡ full identity pin; (b)
  multi-start + parameterized schedules; (c) a one-page ERGODICITY
  argument ships with the code (a constructive path between any two
  legal Π, the two-step operator handled, degenerate configurations
  declared — where A1 zeroes the space, say so).
- Decomposition coupling declaration: hub / boundary-port position acts
  across levels — recorded as single-variable; the decomposition cost is
  measured ONCE on a small instance (joint vs decomposed J gap) and
  filed.

## 9. S2 named-baseline registry (uniform generator signature, all pass verify(), seeded)

| name | rule | source |
|---|---|---|
| random | uniform random legal seating | — |
| sequential | index-order fill | the mapper's default-seat by-product |
| snake | serpentine fill | standing |
| least_manhattan | consecutive-level least-Manhattan sequential placement | SIAM |
| clustered | **[AMENDED 8 — C64-c checks A3+D]** literal rectangle tiling, the Gemini definition ("a layer is assigned to consecutive and rectangle-like core group") taken at its word: the grid is tiled into equal divisor-pair rectangles (smallest waste, one per stage), stages walk the rectangle grid in snake order, within a rectangle row-major first-`need` slots — connectivity, perfect tiling and determinism BY CONSTRUCTION. The earlier BFS blob growth (from [AMENDED 6]: self-implemented, the collaborator withdrew) FRAGMENTED under check A3 (4/32 stages disconnected) and is replaced. Degeneration, pinned: on the 355M 1-die-per-unit class the 1×1 rectangles reduce clustered to the snake walk. Excerpt + parameters: `analysis/baseline_traces.md` | Gemini (definition) |
| nmap_greedy(+swap) | **[AMENDED 7 — C64-c check D]** original three-phase structure verbatim: max-comm set seated first (mesh centre), then the set communicating most with the MAPPED ones (dynamic selection) to the least comm×distance seat; refinement = ONE fixed O(U²) pairwise-swap sweep with per-row best-commit (`mappingwithsinglepath()`), **not** run-to-convergence — the original's termination is the sweep itself. Declared adaptations: cost caliber = chain comm × centroid Manhattan distance; only equal-size die-sets swap. Excerpts: `analysis/baseline_traces.md` | NMAP, DATE 2004 |
| heaviest_first | heaviest flow to the currently idlest line | Graham/LPT lineage |

Ladder semantics: random proves the space non-trivial; named heuristics =
"the best you can do without searching"; nmap_greedy doubles as the
greedy tier; search must beat the strongest named tier with margin to
count. The registry closes here — no additions.

## 10. Implementation path (dependency order; each step ships + gates + expectations)

**S1 evaluator interface** (the only true dependency).
- Ships: score(Π, μ, c) → (T_opt, T_pess, E, per-level decomposition);
  the Π triple fully expresses the standing inputs; incremental hooks;
  A4's 544-seat + 16-package payload wired as the standard test case.
- Gates: a hand-checked small case locks score outputs ≡ the standing
  analysis scripts, item by item; incremental ≡ full pin.
- **[AMENDED 6]** no interface hand-off (the collaborator has withdrawn).
**S2 baseline registry** (needs S1).
- Ships: §9's generators + "ladder table v0" — every baseline's score
  readings on the S4 payload × active cells (both columns). The first
  three ladder rungs stand before any search runs; the table doubles as
  S3's control column and the §6 guardrail's feasible-seed pool.
- Expectations pre-written: monotone ladder (random worst → named →
  greedy); the energy column within percent.
**S3 single-level search** (needs S1, S2).
- Ships: the SA body (§8 in full) + the ergodicity page; two single-level
  instances — the within-die level (A3 co-residency condition; the space
  is proven non-degenerate there) and the die-level ordering level —
  each with regret readings against the ladder table (Δ column rides).
- **[AMENDED 10 — the 355M uniform chain is a SOLVED DEGENERATE CORNER;
  the ordering instance's condition declared before S3 opens]** Ladder
  v0 proved it: on the uniform pipeline chain six of the seven named
  baselines tie at 1.00 avg hops, and 1.00 IS the lower bound for
  chain-adjacent hand-offs — that workload's ordering problem is closed
  by heuristics, and the 4.0× wire-time spread is entirely the gap to
  random. The die-level ordering instance therefore runs under the
  DECLARED CROSS-TRAFFIC CLASS LOAD (the check-C reinforcement fan-out
  family: every stage an equal volume to stages +2/+4/+8; wire-time
  objective per [AMENDED 9]; the space is measured open there —
  busiest-wire 18.3M–30.0M across the seven seatings), chosen over the
  A3 co-residency alternative because A3 already hosts the within-die
  instance and the two instances' conditions stay disjoint. The
  uniform-chain version is FILED as the solved-degenerate-corner
  record and is never a search demonstration target.
- Expectations pre-written: search never below any named baseline;
  substantive margin in active cells (magnitude prior: the soft-lever
  table); the safe cell all-ties. Flips are findings.
**S4 full deployment search** (needs S3).
- Ships: DP (oracle table fully enumerated) + two-level DP+SA linkage;
  runs the A4 payload; exhibits = the result class previously
  unobtainable — two-phase constrained trade-off solutions, best seating
  under weave condition enumeration, seam-bound variant recomputation.
**S6 four-arm experiment** (needs S3; order vs S4 may follow the paper's
needs — **ruling: keep the original order, S4 then S6**).
- Ships: E1–E3 (§7 isolation discipline) + per-cell regret tables + the
  cross-scoring matrix + the safe-cell control.
- Per-cell expectations written before running.
**~~S5 solver reconciliation~~ — RETIRED (C64-a, 2026-09-10).** The
collaborator has withdrawn. O6 retires with it; the 47% figure is
permanently unpublishable (the 11% flat figure stays usable under the
standing citation rule).

## 11. Cross-cutting discipline

The full standing set: post-v6 separate files; frozen_v6 and both tex
untouched; expectations pre-written; flips booked as findings; touching
frozen numbers goes through the changelog; SUMMARY zh/en synced at each
closeout. Plus:
- Randomness management: seed sets pre-registered; every reading reports
  the multi-start distribution (median + range), never a single best —
  no lucky-solution reporting.
- Work starts only from the decided table + the changelog's live state
  (the O19 phantom-task legislation case).

## 12. Extension switches (named, all OFF in v1)

Weight replication (|D_k| above the tiler minimum); tiling × placement
joint search (evaluation returns to the inner loop; cost returns to the
Gemini scale — the real reason it never opened); batch-B intermediate
values (mixed objective opens the enumerate-t_max DP); a third package
level (N-level schema extension; trigger conditions in FIXLIST O16).

---
Execution note: start at S1. Implementation-layer objections to the S1
signature (fields, serialization, incremental hook shape) are raised
before code; §5–§8 semantics are not in objection scope. Each step's
closeout stops for review. **[AMENDED, S1 day 3 — the freeze
discipline]** the S1 interface signature is FROZEN at the S1 closeout;
from then on, ANY interface or semantic change goes through a formal
amendment of THIS document (marked in place) plus the FIXLIST record —
never a casual code-side edit. The day-2 inventory amendment is the
precedent: code and spec must move together.

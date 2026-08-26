# Golden re-baselines

Every entry: which goldens moved, why the move is legitimate, what stayed pinned.


## v0 -> v1 (workstream B: TrafficExtraction), 2026-08-05

**What changed:** per-crossbar and per-link traffic switched from the uniform
placeholder (`total / n_crossbars`, subtree-summed trunks) to the mapping's real
multicast/reduction structure (`scripts/traffic.py`). A multicast slice now
crosses an upper edge once instead of once per leaf; idle instances carry zero.

**Goldens moved:**
- `slow_golden_v0.json` (tiny2x2 max/min 3.579, uniform) retired ->
  `slow_golden_v1.json` (active-crossbar spread under structured volumes).
- per-level volume equality (an artifact of the uniform division) replaced by
  leaf-level == stats-counters conservation.
- downstream: comm dumps, the heatmap spread (ffn1 3.58x is superseded), and the
  per-level volume x distance distribution ("~65% at glb<->macro" rested on a
  ~32x multicast overcount of the trunk).

**Stayed pinned (must NOT move):** the 12 system-scenario totals
(`system_golden_v0.json`, checked via tests/compare_baseline.py) -- B touches the
communication ANALYSIS layer only; energy/latency totals do not flow through
build_flows.

## W3 (D2D)

`xfail_single_die_d2d_degenerate_invariant` removed from group 4/5: the gap it
documented is closed. Its acceptance clause ("single-die fabric => zero
inter-die cost AND the pre-D2D total; replace the flat charge, never add")
lives on as group 15 (`test_d2d.py`), tests 1-2. Note the assertion changed
form deliberately: pricing lives on the multi-die variant + surplus model
(`reference_hops` semantics), NOT on the default config's `pj_per_word`, so
the old literal check (`pj_per_word is not None` on the default) would have
been the wrong thing to promote.

## Anchored findings (upgrade protocol)

The contention results were promoted from placeholder sensitivities to
findings stated at PUBLISHED link bandwidths (analysis/ANCHORS.md: Simba
on-die 8.75 GB/s silicon-measured, ESP 32 GB/s, FlooNoC 80.6 GB/s). Per the
upgrade rule, the promotion is pinned as group 17
(test_anchored_findings.py) against the frozen fixture
stack_per_op_v1.json: low-anchor spread 1.42-8.60x, the 1.65x hub-position
lever, high-anchor collapse, the mid-anchor condition divergence, the
three anchors landing consistently with the PREVIOUSLY published thresholds
(blind-test coherence), and the h-tree==bus decode tie being trunk physics
rather than a transcription merge.

## O12: the co-residency basis (v2)

The 48-die seating packs two ops per die, but every per-op run had the
whole die -- and the mapper exploited the idle arrays for WEIGHT
REPLICATION over P (e.g. out_proj: 8 copies), accelerating compute. Under
the seating shares (SHARE_355M_48DIE pins; P/Q spatial banned) replication
is impossible and every prefill op lands at X7 x P512 = 3584 cycles =
5.192 ms; decode is untouched. Consequences, re-scored and re-pinned
(stack_per_op_v2.json, group 17 additions): prefill stall-free 314.65 ->
813.06 ms; anchored spread at Simba 1.42-8.60x -> 1.00-3.11x; hub lever
1.65x -> 1.50x; the v1 "mid-anchor condition divergence" finding does NOT
survive and is retired. The v1 fixture stays as the exclusive-die
reference basis (the blind-test coherence ran on it, historically). Energy
moves <2% per op. The 12 scenario goldens (system_golden_v0) remain the
exclusive-die reference and are unchanged.

Register direction confirmed by test: co-residency shrinks every
contention multiplier (test_share_vs_fulldie_direction).

## O18: the 48-die chain pinned; offload script's 24-vs-48 leftover fixed, 2026-08-21

**What changed:** new group 18 (`test_feasible48.py`, 10 tests) pins the
feasible 48-die configuration's D2D chain on the v2 fixture: half-layer
stages (A 23.49312 ms / B 10.38336 ms), busiest-wire integers 1/2/8/47,
surplus energies 0/183.5/1368.4 uJ, pipelined knees 32/64/256/1024 w/c
(halves 16/32/128/512; scenario B one octave higher), single-pass
invisibility at 256 w/c, and the 64 w/c beat tables.

Writing the pins exposed that `analyze_offload_contention.py`'s D2D table
and placement figures still used the retired 24-die configuration (busiest
6/23, whole-layer stages). Unified to the 48-die half-layer convention
(`half_stages`, single-sourced; the placement figures now import the same
`assignments` as `analyze_d2d.py`). **Published numbers that moved:** the
offload pipelined dividend is +126% (stage 23.49 -> 10.38 ms) -- v1
published +53%, and the +13% briefly quoted during the O12 cascade mixed a
half-layer A stage with a whole-layer B stage; scenario B D2D at 64 w/c is
now snake 1.14x / sequential 2.29x / far-pairs 9.15x / bus 53.7x; decode
D2D under B ~2.3x (sequential). `offload_contention.json` and the three
offload/placement figures regenerated; SUMMARY (zh/en), PROGRESS, FIXLIST,
report cascaded.

**What stayed pinned:** all on-die numbers (groups 14/17), scenario
goldens, the scenario-A D2D chain (its stage/knees were already on the
48-die convention), and the v1/v2 fixtures. Suite: 142 passed / 1 xfail.

## O7: the compute/communication overlap bracket, 2026-08-21

**What changed:** every critical-path composition now publishes both ends
of the overlap bracket -- max(compute, network) (perfect overlap; the
headline end, identical to all previously published numbers) and
compute + network (zero overlap). Code: `run_op` gains
`total_latency_sum_s`, `die_pipeline_interval` gains `interval_sum_s`;
all five analysis scripts emit `*_sum` JSON fields, band/whisker figures,
and both-end thresholds (bandwidth sweeps extended to cover the
zero-overlap knees). Tests: 5 new (group 17: the bracket identity
upper - lower == sum(min(compute, serial)), anchored upper-end pins,
both-end ordering invariance; group 18: pipelined-beat bracket, no-network
collapse). Suite: 147 passed / 1 xfail.

**What stayed pinned:** every previously published number is unchanged --
it is the bracket's lower end (groups 14/17/18 all green untouched).
Headline additions: Simba prefill spread 1.00-3.11x gains the zero-overlap
end 1.38-4.02x; the doubling thresholds move at most 2x between ends while
the 1% thresholds move ~64x; both ends rank schemes identically. Docs
(SUMMARY zh/en, PROGRESS, report, FIXLIST C16 + register re-audit)
cascaded.

## O22/O23: physical wire accounting -- v2 -> v3, 2026-08-21

**What changed:** `link_occupancy` now routes each flow's DOWN (inputs)
and UP (partial sums) components separately; full-duplex schemes keep the
two directions on different wires (`Interconnect.DUPLEX`, bus = shared
medium; `path_directed()` with direction tags, the up route retracing the
down route), and the up component is weighted by `fabric.psum_word_bytes`
(default 2.0 = 16-bit partial sums, platform input DR-7).
`duplex=False, psum_bytes=1.0` reproduces the previous accounting exactly
(verified: 1.00/1.13/1.58/1.34/2.42x at the reference input).

**Goldens moved:** `stack_per_op_v3.json` frozen (compute/write
bit-identical to v2; `serial_s` re-accounted). Published multipliers grew:
Simba prefill 1.00-3.11x -> 1.03-5.31x (hub lever 1.50 -> 1.56x), decode
cap 1.15 -> 1.34x, thresholds ~2x higher, single-op ffn1 table 1.75-13.96x
-> 3.43-27.68x (ratios intact). Die-level chain integers 1/2/8/47 ->
1/1/4/47 (sequential rows = snake on full-duplex wires; adversarial
halves), knees 32/32/128/1024 w/c. Group 15 mechanism tests re-pinned with
the old accounting kept as an explicit `duplex=False` check; group 18
integers re-pinned; group 14 (synthetic direction-less flows) unchanged
and a v3 single-op pin added; group 17 gains the v3 anchored readout, the
"understated before" direction pin and the ordering pin. The full rerun
chain (contention_system, contention_impact, placement_tradeoff,
multidie_placement, run_2p7b_block, anchored, d2d, offload, scale_tiers)
regenerated every JSON and figure.

**What stayed pinned:** energies (all groups), the v1/v2 fixtures as
references, the scheme ordering at every anchor, the O7 bracket identity.

## O24: the non-matmul operators on the digital unit -- v3 -> v4, 2026-08-21

**What changed:** softmax, GELU, LayerNorm x2 and the residual adds x2 are
modeled as closed-form records on a digital vector unit next to the glb
(`fabric.digital`, platform input DR-8; shipped generic: 64 lanes @ 1 GHz,
Horowitz ISSCC 2014 per-op energies; glb passes at the calibrated
15.47 pJ/word). They enter the stall-free stack (serial with the matmuls),
the half-layer stages (single source `llm_workload.half_layer_stages`, now
used by analyze_d2d / analyze_offload_contention / tests), the scenario
totals (A: all four; B: softmax leaves with the attention), the 2.7B tier,
and the per-operator ledger (plus the embedding read and the LM head as a
real 8-die matmul, vocab padded to 65,536).

**Goldens moved:** `stack_per_op_v4.json` frozen (matmul rows bit-identical
to v3; four elementwise rows per scheme). 355M prefill stall-free 813.06 ->
826.42 ms (+13.37 ms digital, 1.6%); decode 14.77 -> 14.80 ms; stages
23.49 / 10.38 -> 23.80 / 10.63 ms, offload dividend +126% -> +124%;
reference-input multipliers 1.00 / 1.53 / 2.29 / 1.90 / 4.13 -> 1.00 / 1.52
/ 2.27 / 1.88 / 4.08; Simba prefill 1.03-5.31x -> 1.03-5.24x (hub lever
1.56 -> 1.55x); scenario-B stack 498.40 -> 505.48 ms; D2D pipelined knees
read 16 / 16 / 64 / 1,024 w/c (v3: 32 / 32 / 128 / 1,024 -- a grid reading:
the 32 w/c point sits 0.3% under the 1.3% longer beat); 2.7B tier-L @ESP
clustered / row-fill / spread 1.23 / 2.19 / 2.01x -> 1.22 / 2.14 / 1.97x.
Group 20 (`test_elementwise.py`) pins element counts, digital-unit
scaling, the offload predicate, the stage single-source, the generic
magnitudes and the v4 readouts. Suite: 162 passed / 1 xfail.

**What stayed pinned:** energies of the matmuls, every ranking, the v1-v3
fixtures as references, groups 14/15/17/18 untouched (they pin the
matmul-only stages and readouts explicitly).

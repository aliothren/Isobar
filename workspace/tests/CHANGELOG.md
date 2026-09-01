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

## O9: the offload receiving side as a black-box interface -- v4, 2026-08-26

**What changed:** the external attention unit is modeled as an interface
(`fabric.AttentionUnit`, platform input DR-9): compute rate and average
cost per MAC, per-call overhead, K/V memory bandwidth / energy / capacity,
die<->unit link bandwidth / energy / reference hops, unit count. Shipped
generic public figures: 2 T MAC/s at 1 pJ/MAC, K/V memory 25.6 GB/s at
50 pJ/word (2 G words), link 12.5 GB/s (18,112 w/c) at 10 pJ/word, one
unit. The unit sits at the die scheme's hub; per layer Q, K/V and the
attention output cross the die wires as node-to-node flows
(`llm_workload.offload_streams` / `offload_flows`) and the unit's chain is
link out + compute (incl. softmax ops) + K/V append and full read + link
back (`attention_unit_cost`), serial inside the unit. Entered in
analyze_offload_contention (end-to-end stacks and multipliers, unit stage,
beat with the streams), analyze_anchored_sweep (end-to-end decode rows),
analyze_system_gpt2 (scenario-B totals gain `unit_E_B` / `unit_L_B`), the
ledger (an "attention on the external unit" entry with link / compute /
K/V rows; the three offloaded ops point to it; offloaded type tables now
titled end to end) and a new sweep `analyze_offload_unit_sensitivity.py`.
No fixture changed: the die-side stacks, stages and energies are
untouched, and every die-side number stays published as its own column.

**New readouts (generic unit, S=512):** prefill unit chain 0.527 ms and
0.73 mJ per layer (link priced at the placement's mean 3.5 hops; the
scenario totals use the reference 1 hop: 16.3 mJ) -> scenario B 194.7 ->
211.0 mJ and 209.6 -> 222.2 ms, still under A (296.4 mJ / 328.0 ms);
offload stall-free stack 505.5 -> 518.1 ms; unit stage 8.61 ms under the
die stage 10.63 ms, dividend +124% kept (needs >~1.2 T MAC/s per unit,
-57% at 0.25 T); decode 0.99 -> 1.99 ms per token (K/V read 25 MB at
25.6 GB/s), energy 0.47 -> 1.76 mJ, scenario B 0.38 -> 1.67 mJ and 1.00
-> 2.01 ms (A: 0.58 mJ / 14.80 ms); streams converge on the attach point:
busiest die wire 1 / 1 / 4 / 47 -> 36 / 25 / 38 / 143 hand-off
equivalents (snake / rows / far pairs / bus), beat 10.05x the die stage
at 256 w/c and 1.00x at the 12.5 GB/s anchor; anchored decode end to end
at Simba 1.01-3.28x (die side 1.03-5.61x). Ledger: prefill offloaded
whole model 195.91 -> 212.22 mJ and 736.92 -> 749.56 ms (unit 7.7% /
1.7%); decode 465 -> 1,753 uJ and 1.48 -> 2.48 ms (unit 73.5% / 40.5%).
Group 21 (`test_offload_unit.py`, 6 tests): stream volumes equal the
die's foregone writes and projections, an infinite unit reduces to the
die side, decode scales with context, generic magnitudes, the end-to-end
dividend never exceeds the die side, streams route to the hub. Suite:
171 passed / 1 xfail.

**What stayed pinned:** all v1-v4 fixtures, groups 14-20, every die-side
readout and ranking, the O7 bracket, the D2D chain integers.

## O9 follow-up: the unit link priced at the die placement everywhere -- v4, 2026-08-27

**What changed:** `llm_workload.unit_link_hops(fabric=None, assignment="snake")`
is the one source of the hop count that prices the offload streams' link
energy: the mean over the 24 attention dies of the routed-grid distance to
the attach point under the canonical 48-die snake seating (84 / 24 = 3.5).
Every script passes it (analyze_offload_contention, analyze_system_gpt2,
op_breakdown, analyze_anchored_sweep, analyze_offload_unit_sensitivity);
the interface's `link_reference_hops` (1) is only the fallback of a direct
call without a placement. Rule recorded (FIXLIST C22): die-side quantities
carry the die placement by default, the unit's internals stay average
costs. The cost record gains `link_hops`; the ledger's link row states the
hop count; the scenario totals JSON gains `unit_link_hops`.

**Goldens moved:** none (no fixture holds the unit). Readouts: unit energy
16.3 -> 17.6 mJ per prefill model (link 0.50 -> 1.76 mJ), scenario B
prefill 211.0 -> 212.3 mJ (A 296.4), decode B 1.671 -> 1.674 mJ per token
(2.87x A); ledger prefill offloaded 212.22 -> 213.48 mJ (unit row 7.7% ->
8.2%), decode 1,753 -> 1,755 uJ; every latency, stage, dividend and ranking
unchanged. Group 21 gains `test_unit_link_hops_come_from_the_die_placement`
(3.5 from every entry; hops move the link energy only). Suite: 172 passed /
1 xfail.

**What stayed pinned:** all fixtures, groups 14-20, the die-side readouts.

## O13: the 2.7B block as a chain of die-sets -- v4, 2026-08-27

**What changed:** the spanning-operator die flows (tier M / tier L) were
hub-routed and sized by the structured traffic model's leaf counters --
row-driver reads (14x the input tensor) and ADC reads (48x the output
piece, at partial-sum width). Those re-reads happen out of the die's own
buffer; the die-to-die wire carries the tensor once, the layer hand-off
convention. `llm_workload.block_chain` (data-flow order, dies and split
dim from plan_spatial, the attention die = qk^t + softmax + av, the
external unit when offloaded), `seat_block` (disjoint seats: clustered /
row-fill / spread), `block_die_flows` (node-to-node flows producer ->
consumer; column split = every owner's piece to every consumer at
activation width, row split = all partial sums at partial-sum width) and
`die_flow_surplus_energy`; `link_occupancy` honours a flow `width`;
`analyze_scale_tiers.py` publishes the routed chain as the headline and
keeps `tierM_v1` / `tierL_v1` / `tierL_hub_once` as the comparison; the
combined figure shows both bracket ends. `analyze_multidie_placement.py`
untouched (its JSON is the v1 comparison; P=64 recorded by
analyze_scale_tiers).

**Readouts moved (anchors: on-die ESP 32 GB/s, D2D GRS 12.5 GB/s):**
tier M 3.10 / 6.20 / 6.20x -> 1.00x at every seating (zero-overlap
1.03 / 1.06 / 1.06x), surplus 0 / 1.15 / 1.30 mJ -> 0 / 31 / 35 uJ; tier L
prefill 1.22 / 2.14 / 1.97x -> 1.02x (zero-overlap 1.26 / 1.28 / 1.26x),
surplus 0 / 792 / 829 mJ -> 30.5 / 27.1 / 30.1 mJ (+1.2-1.3% of 2297 mJ);
offloaded decode 1.27 / 2.50 / 2.27x -> 1.00 / 1.01 / 1.01x; combined
figure latency leverage 1.55 / 4.0 / 1.75x -> 1.55 / 1.00 (1.03) / 1.00
(1.01)x, energy 0.46 / 58 / 36% -> 0.46 / 1.58 / 1.33%. Every 355M
number, fixture and group untouched. Group 22 (`test_die_chain.py`,
8 tests) pins the mechanism and the readouts. Suite: 180 passed / 1 xfail.

**What stayed pinned:** all fixtures, groups 14-21, the 355M readouts, the
v1 tier numbers as the comparison rows in scale_tiers.json.

## C25: wire volumes in values -- v4 -> v5, 2026-08-27

**What changed:** `traffic.extract` now returns leaf volumes in VALUES.
Timeloop counts the Inputs dataspace in input bit slices (X, 7 per signed
8-bit word), the Outputs dataspace in output bits (Z, 8 per word), once
per physical cell column of a weight (Y at the column level, 2), and its
"Total scalar accesses" add fills and updates to reads; v1-v4 took those
totals as 8-bit words -- 14x the input tensor and 48x the output piece on
every on-die wire. Now: row-driver READS / X and ADC READS / Z / Y_col,
with a guard that the leaves' distinct slices reassemble P*C*N and P*M*N
exactly once (the check that would have caught this at v1). The uniform
(v0 comparison) path follows. Energies, K/V writes, layer hand-offs and
the O13 die flows never used the counters and are unchanged.

**Goldens moved:** `stack_per_op_v5.json` frozen (compute / write /
digital-unit rows bit-identical to v4; all 60 serialization rows moved);
`slow_golden_v2.json` (tiny2x2 spread 1.25, same value, provenance
updated). Readouts: single op 3.43-27.68x -> 1.00x (zero-overlap
1.07-1.59x; scheme ratios kept: bus/star occupancy 8.27x, corner/centre
1.67x); whole stack at 16,384 w/c 1.00/1.52/1.88/2.27/4.08x -> 1.00x for
every scheme (zero-overlap 1.01/1.03/1.05/1.04/1.11x); Simba anchor
1.03-5.24x -> 1.00x (zero-overlap 1.01-1.15x), ESP <= 1.04x, FlooNoC
<= 1.02x; buffer lever 1.49-1.55x -> 1.00x; offloaded decode
1.03-5.61x -> 1.00x; 1% thresholds 5.7-45 GB/s -> never / 0.35 / 0.71 /
0.71 / 1.41 GB/s, doubling only the bus at 0.35 GB/s; per-crossbar maps
3.62x / 1.50x -> 3.69x / 1.70x; region 17.8% unchanged; ledger
perfect-overlap latencies = compute + write (prefill 826.4 ms, offloaded
end to end 518.1 ms, decode 14.81 / 2.02 ms); 2.7B tiers 1.00x at every
NoC anchor (were 1.33x at Simba). Group 11 rewritten (values, unit
decomposition, reassembly guard), group 14 single-op table re-pinned,
group 17 gains the v5 block (readout, direction v5 <= v3, thresholds,
ordering), group 22 re-pinned. Suite: 185 passed / 1 xfail.

**What stayed pinned:** every energy, every compute / write / stage
number, the D2D chain integers and knees, the O9 unit numbers, the O13
tensor-once flows and surplus energies, groups 12-13 and 15-16 and 18-21.

## O25 / O17 / O26 registered: the anchor-identity re-read -- doc-only, 2026-08-27

**What changed:** nothing in code, fixtures or goldens. The
results-affecting register gained two rows that are reading positions,
not numbers: the four bandwidth anchors (Simba / ESP / FlooNoC on die,
GRS die to die) are digital-ecosystem links, and every "hidden at every
published bandwidth" sentence is the reading of one cell (NeuRRAM-class
device x digital-class link) of a phase diagram (model scale x device
speed x transfer paradigm x link tier); the thresholds carry no anchor
and are unchanged. Documents re-labelled accordingly: SUMMARY zh/en 2.5
(new), PROGRESS 5.5 (new) / 5.2 / 6.4 / 8.2 / 9, ANCHORS identity +
real-system survey and registry mapping, DIRECTION update, FIXLIST
re-cut (O25 anchor grid, O17 device axis, O26 busiest-wire bound, O27
static energy, S1-S6). Estimates for the analog-reality tier and the
device scales are marked [est] / [derived] and enter no external
document until O25 / O17 run (P0 gate).

**What stayed pinned:** everything -- 185 passed / 1 xfail on the v5
fixtures.

## C26: the anchor registry, the analog-reality tier and the per-axis sweeps -- v5, 2026-08-28

**What changed:** `scripts/anchors.py` is the single source of every
bandwidth anchor (with `status`), of the estimated analog-reality band, of
the chip points and of ONE device-cycle constant (10.14 us / 7 = 1.4486 us);
`analyze_anchored_sweep.py`, `analyze_scale_tiers.py`,
`analyze_corner_flip.py` (v1 -> v5 fixture), `analyze_d2d.py`,
`analyze_offload_contention.py`, `test_anchored_findings.py` and
`test_contention_anchors.py` import from it. `anchored_sweep.json` keys are
registry keys and carry five columns (three digital anchors + the band
ends); `offload_contention.json` gains the analog columns under a separate
key. New: `scripts/sweep_axes.py` -> `analysis/phase_sweep.json` +
`sweep_axis_{ondie,d2d_355m,d2d_2p7b,d2d_probe,unit_link}.png`; group 23
(`tests/test_anchor_registry.py`, 15 tests).

**Goldens:** none moved. The cycle rounding in `analyze_d2d.py` /
`analyze_offload_contention.py` (1.449 -> 1.4486 us) shifts their JSON
readouts by 0.03% (words/cycle knees unchanged: 16 / 16 / 64 / 1,024 w/c);
every pinned assertion holds. Suite: 200 passed / 1 xfail.

**What stayed pinned:** every energy, compute, write and multiplier of v5;
the group-17 anchored table is reproduced from the sweep's digital columns.

## C27: the fill-exact 2x4 / 4x2 die grids become the default -- v5 -> v6, 2026-08-28

**What changed:** `mlx300.yaml`, `mlx300_multidie.yaml`,
`mlx300_multidie48.yaml`, `mlx300_mesh.yaml`: macro mesh [3,3] -> [2,4]
(pitch 800 um), crossbar mesh [3,3] -> [4,2], core pitch 400 um; the
earlier grids are `mlx300_3x3.yaml` (comparison only); `mlx300_2x4.yaml`
removed. `fabric.provenance()` recorded in every result JSON. Every result
regenerated on the new default (`analysis/regen_v6.sh`). Geometry only:
star and bus serializations, compute, write, every energy except the
router distance term, D2D and the unit are bit-identical to v5.

**Goldens moved:** `stack_per_op_v6.json` frozen (mesh centre / corner
rows moved, 24 of them; tree, star, bus rows identical; the stall-free
stack +6 us of propagation). Readouts: single op zero-overlap star 1.071 /
routed 1.286 x3 / bus 1.589 (was 1.071 / 1.214 / 1.286 / 1.357 / 1.589);
corner / centre 1.67x -> 1.00x; Simba zero-overlap 1.01 / 1.05 / 1.05 /
1.05 / 1.15; 1% crossings 0.195 / 0.782 x3 / 1.89 GB/s; 2^k knees 256 /
1,024 x3 / 2,048 w/c; analog low end routed 1.31x (was 1.16 / 1.58 /
1.31); prefill energy 298.77 mJ (+0.13%, distance term at mean 1.5 hops);
line-vs-grid router lever 1.33x / 0.25% of a block. Groups 14 and 17
gained v6 blocks; the 3x3 mechanism anchors (groups 13 / 14 / 4 geometry)
load `mlx300_3x3.yaml` explicitly and keep their numbers; group 23
re-pinned; `test_fabric` checks both grids.

**What stayed pinned:** every v1-v5 assertion (frozen fixtures), the D2D
integers and knees, the O9 unit numbers, the O13 flows and surplus
energies, the 2.7B tier readouts, the O25 D2D / unit-link / probe
readouts.

## C28: the hub-lever gate and the identical-series figure rule -- doc + figures, 2026-08-28

**What changed:** `scripts/analyze_grid_gating.py` (new; closed-form on
the frozen ffn1 flows): 3x3 / 2x4 / 4x4 / 2x8 x hub centre / corner,
two fillings for the 16-slot grids, plus the heaviest-talker sweep;
`analysis/grid_gating.{png,json}`; group 24 (`tests/test_grid_gating.py`,
6 tests). `scripts/figstyle.py` (new) merges identical series and brackets
tied bars; six plotting scripts use it, their figures regenerated with no
numeric change. No golden moved.

**Finding:** corner busiest = N - macros in the hub's column (xy routing),
so the hub-position lever is gated by the grid's width along the routing's
first axis: 2-wide grids 1.00x in any filling, 3x3 1.67x, 4x4 1.50x in
both fillings; the soft-placement lever is 1.75x on the 2x4.

## C29: the busiest-wire occupancy stated as the bound it is; `schedule_slack` -- 2026-08-28

**What changed:** `Fabric.schedule_slack` (>= 1, default 1.0) in every
YAML, validated, in `provenance()`; `link_occupancy` multiplies every
occupancy by it and returns it; the hand-rolled beat formulas
(`analyze_offload_contention.py`, `die_serial`) carry it; the ledger and
the sweep header state it. Group 25 (`tests/test_schedule_slack.py`, 5
tests). No golden moved: slack = 1 everywhere, the numbers are the bound.

**Statement:** for a given routing the busiest wire's occupancy is the
least serialisation any schedule can reach -- exact for star and bus, a
lower bound for routed grids; the max end is the exact ideal of a
compile-time scheduled fabric and the optimistic bound of a NoC. Suite:
216 passed / 1 xfail.

## C30: the device as a fabric input -- 2026-08-28

**What changed:** `fabric.Device` (`cycle_seconds`, `input_slices_per_mvm`
-> `t_mvm_s`) declared as the `device` block of every config, validated, in
`provenance()`; bandwidths declared in GB/s (`*_gbps`) and converted at load
with the fabric's device (unit link 12.5 GB/s = 18,107 words/cycle, was
18,112); the registry's constants are the default fabric's device;
`Fabric.verify_cycle` in `run_op` checks the CiMLoop macro's cycle against
the declaration; the four literal sites read the fabric. Group 26
(`tests/test_device_input.py`, 7 tests); `test_d2d` identities read the
device. Goldens: none moved beyond -0.03% on the unit-link times (the
rounding unification). Suite: 223 passed / 1 xfail.

## C31: the (t_MVM x bandwidth) plane -- the device becomes an axis (O17b), 2026-08-31

**What changed:** `scripts/sweep_axes.py`: the serialization scoring is
rewritten in GB/s form (`ser_at`: ser_ref x 11.310 GB/s / g -- numerically
identical at the NeuRRAM tier, and device-free when crossed with t_MVM,
which is exactly the group 26 identity); new `axis_device_plane` (device
grid 0.05-100 us, 8 points per decade, plus the three silicon marks from
`anchors.device_marks()` -- the registry is the only source a plane mark
may come from; crossed with axes A, B1, B3 and C; B2 is read at the marks
only, having already been crossed with axis A) and three figures
(`device_plane.png`, `device_plane_collapse.png`, `device_fixed_terms.png`);
the sweep header states what does NOT scale with t_MVM (K/V write DR-5,
digital unit DR-8, attention unit DR-9, every link's GB/s).
`phase_sweep.json` gains a `plane` block (device grid, r surfaces,
closed-form coefficients, mark readouts, the collapse and the fixed-term
decomposition). Group 27 (`tests/test_device_plane.py`, 5 tests); group
23's schema check requires `plane`. No golden moved (the GB/s rewrite is an
identity; every v1-v6 pin reproduced).

**Finding:** the plane's metric is the busiest operator's network / compute
ratio r(g, t) -- the whole-stack multiplier is not device-scalable because
the K/V write and the digital unit do not scale with t_MVM. r = 1 is the
closed form g = 11.310 x (ser_ref / mm_ref) x (10.14 us / t): a slope -1
line in log-log, and the bisection-swept thresholds land on it to 1e-9.
Boundaries (prefill, attention offloaded; knee ffn2 on every scheme): star
0.202 / routed 0.808 x3 / bus 2.02 GB/s at NeuRRAM -> 15.4 / 61.6 / 154
GB/s at HERMES (76.3x): Simba 8.75 and ESP 32 fall BELOW the routed line
(network exposed), FlooNoC 80.6 alone stays above it; the 2.7B chain's
boundary moves 1.01 -> 77 GB/s, 6.2x past GRS -- both stories flip inside
the analog family, now as measured plane readings. The die<->unit link's
boundary is 0.101 GB/s x (10.14 us / t) in BOTH phases (S cancels in
net / compute there). Fixed terms: the same 76.3x device speeds prefill
9.33x (826.4 -> 88.6 ms) and decode only 1.11x (14.78 -> 13.34 ms --
corrects the "1.3x" once written in FIXLIST): the matrix part collapses
exactly in g x t_MVM, the whole stack does not -- the finding, not a bug.
Suite: 228 passed / 1 xfail.

## C32: the mapper-measured V(d, S) -- the d law settled (O17c), 2026-08-31

**What changed:** `scripts/run_scaling_probes.py` (new): 48 mapper runs,
single core, resumable -- d in {1024, 2560, 4096, 5120, 6144, 8192} at
S = 512 (5120 / 6144 added to pin the predicted crossing) and S in
{128..2048} at d = 1024 (3 ops); residency tiler, column split only
(`plan_spatial` gains `max_dies` and `dims` -- d = 8192's ffn needs 32
dies on the 48-die fabric; the O15 row split stays unexercised), full die
per piece, dh = 64, prefill. Records per (d, S, op): busiest macro edge
volume + direction, serialization at 16,384 w/c, compute, die split ->
`analysis/scaling_probes.json`. `scripts/analyze_scaling_law.py` (new) ->
`scaling_law_vds.png` + `scaling_law_summary.json`. Group 28
(`tests/test_scaling_law.py`, 5 tests). No golden moved.

**Findings:** (1) above the flip the busiest on-die wire is the INPUT
TRUNK: down = S x d words per macro edge exactly, ratio = d / 114,688
(16,384 w/c x 7 slices) -- "knee ~ d" with slope exactly 1, the closed
form the O29 boundary family draws; (2) the flip d* = 1,220-1,350
measured (qkv 1,224 / out_proj 1,288 / ffn1 1,349; ffn2 down everywhere)
-- the ideal-capacity prediction 5,793 is FALSIFIED, 4.3x off (macro
fanout + exact die fill); below d* the mapper replicates weights in
underfull dies (compute halves at d = 1024); (3) ffn2 steps with the
tiler's macro C split (0.0714 at 4096 -> 0.0446 at 5120): mapper-dependent
exactly where the tiler steps; (4) every probed ratio is S-independent,
attention included (qk^t: volume ~ S^2, compute ~ S^2, ratio 1/14); the
d = 2560 probes reproduce the 2.7B block's ratios on a different package.
Suite: 233 passed / 1 xfail.

## C33: the d family on the plane; scheme multipliers verified -- 2026-08-31

**What changed:** `sweep_axes.py`: the plane gains the O29 boundary FAMILY
(`d_family` in the JSON; both panels of `device_plane.png`): on die
(routed) one line per width tier -- d = 1024 the production base
(co-residency C14; its knee ffn2 sits x2 above the trunk line, the same
C-split mechanism as ffn2's step), 2560 / 4096 / 8192 the trunk law x4;
ffn2's tiler step is an annotation, not a kinked line. Die level: the
tiler closed form (tensor once; ffn2's S x 4d entry from `block_chain`,
which gains `max_dies` / `dims`; d = 1024 = the C13 half-layer hand-off) --
the d = 2560 line passes exactly through the measured B2 mark, asserted at
build time. `analyze_scaling_law.py`: the probes' stored macro edges
re-scored under mesh / bus (closed form, zero mapper): routed x4.00 EXACTLY
at every d and op (the family is measured, not extrapolated); the bus
multiplier drifts x13.3 -> x8.25 with the up share (the O17b "x10" is
basis-specific); star re-scoring reproduces the stored serialization to
1e-9. Figure hygiene: out_proj = ffn1 merged under the C28 rule in
`scaling_law_vds.png`. Family at t_ref: 0.808 / 1.010 / 1.616 / 3.232 GB/s
on die, 0.101 / 1.010 / 1.616 / 3.232 GB/s at the die level (the levels
coincide for d >= 2560: mesh's x4 multicast = ffn2's 4d-wide tensor).
Groups 27 / 28 gain one test each. Suite: 235 passed / 1 xfail.

## C34: O28 closed -- the T1 (die-buffer) axis audited: counter units again, 2026-08-31

**What changed:** the audit confirmed the suspicion exactly: Timeloop
throttles the glb per dataspace in its COUNTER units (input fills x7 bit
slices; output fills AND updates x8 bit groups; the write port binds --
ffn1: 7*S*C + 2*8*S*M = 37,224,448 units), and every cached Timeloop point
equals units / bandwidth to machine precision -- the "160x at 64 w/c"
anomaly reproduced in closed form; against ~8.9M value-unit hub words that
is a ~4.2x unit inflation (C25's sibling on the T1 axis). No shipped
config declares a hub bandwidth, so nothing published moved. The readable
T1 axis is now ANALYTIC in value units (`sweep_axes.py` axis `t1_hub` +
`sweep_axis_t1_hub.png`): the hub is one shared port (the MX100-class
DMA + shared-SRAM medium) and per matmul op hub words = the T2 bus words
+ the input tensor arriving once (P x C x N) -- the T1 = T2-bus
equivalence holds as an identity, shifted by the in-fill (ffn1 +6.25%).
Readout: knee ffn2 everywhere; 1% at 2.27 / 2.33 GB/s (prefill on chip /
offloaded; the bus's 1.89 shifted); busiest-op net = compute at 2.42 GB/s;
MX100-class 3.9-5.0x at the estimated band's 0.4 GB/s, 1.00x at 8 GB/s;
decode-offloaded == prefill-offloaded exactly (S cancels).
`analyze_bandwidth_sweep.py` becomes the executable audit (asserts the
closed form; labels its Timeloop curve in counter units); unit warnings at
the `mlx_system` push site and the `fabric` field. Group 29
(`tests/test_t1_hub.py`, 4 tests); the sweep schema gains `t1_hub`.
Suite: 239 passed / 1 xfail.

## C35: O29 closed -- the phase diagram drawn, 2026-09-01

**What changed:** `scripts/analyze_phase_diagram.py` (new, zero mapper) ->
`analysis/phase_diagram.png` + grayscale check copy +
`phase_diagram_table.md`; a `phase` stage in make_figures; group 30
(`tests/test_phase_diagram.py`, 4 tests). Two panels on the same
(t_MVM x bandwidth) plane: slope -1 boundaries, the d family with model
names (d = 1024 the production base), three shaded layers, digital anchors
as horizontal lines with statuses, estimated bands / chip bandwidths
marked as estimates, HERMES / ISAAC error-bar points and NeuRRAM's
t-coordinate-only mark, two trend arrows, the collapse inset, and
validation points coloured AND shaped by measured / closed-form
(grayscale-safe): the 17c probes (left; ffn2's tiler step gets its own
"known step -- expected" marker class) and the measured B2 block-chain
marks (right; on the d = 2560 line at all three silicon speeds).

**Semantics corrected in review (not layout):** the d >= 2560 die-level
lines are O13 BLOCK CHAINS INCLUDING their spanning operators (column
split: each receiving die takes the full input) -- which is why they sit
ABOVE the single 4-die operator probe. Relabelled: pure hand-off (black,
d = 1024; = the die<->unit link under offload) / block chain incl.
spanning operators (blues) / single 4-die operator (purple); the three
layers restated accordingly; the plane JSON's `d2d_form` carries the same
phrasing. Suite: 243 passed / 1 xfail.

## C36: the anchor leftovers settled -- Mythic derived, HERMES published, ESP primary; MX100 blocked, 2026-09-01

**What changed:** the O25 P2 leftovers closed by a literature pass.
Mythic M1076 t_MVM derived: 25 TOPS / 76 tiles / (2 x 1024 x 1024) =
6.38 us (tile array from 80M weights / 76 tiles); `device_marks()` now
serves FOUR silicon marks -- plane, phase diagram, collapse and
fixed-terms figures regenerated with the fourth mark, the diagram's table
gains a Mythic column (groups 27 / 30 re-pinned). The HERMES link rate
was published all along: the arXiv methods' spec table gives a maximum
link data-rate of 3.2 Gbit/s = 0.4 GB/s per link (418 links, Parallel
Prism) -- the first published analog-CIM link rate in the registry,
landing exactly on the analog-reality band's LOW end; the identity
statement is amended everywhere, the band stays the class estimate, and
HERMES becomes a PUBLISHED bandwidth point on the phase diagram (0.4 GB/s
against its own star knee of 15.4 GB/s: deep in the everything-contends
layer). The ESP anchor is primary-sourced (ESSCIRC 2022 read: 5 data
planes x 64 bit + 1 control x 32 bit at a measured 800 MHz; 281 Gb/s
tile-to-tile headline; the anchor's 32 GB/s = the 5 data planes, one
plane = 6.4 GB/s -- multi-plane aggregation stated): status secondary ->
measured, the ANCHORS.md citation caveat resolved (group 23 re-pinned).
MX100 stays pending, BLOCKED on its source (arXiv:2410.14882 publishes
no TOPS or MVM rate, checked 2026-09-01) -- recorded as worklist item 12.
Suite: 243 passed / 1 xfail.

## C37: V0 -- silicon-point normalization; the HERMES self-consistency audit; a C36 mis-reading corrected, 2026-09-01

**The correction (the validation track's V0, caught in review):** C36
plotted HERMES's 0.4 GB/s per PHYSICAL link against our per-macro-link
star knee (15.4 GB/s at 133 ns) and read "deep in the everything-contends
layer" -- a granularity mismatch (418 links / 64 cores vs one link
feeding 32 arrays); a fabric 38x under its knee could not sustain the
measured 63.1 TOPS. **The rules, now explicit in the registry
(`ChipPoint` docstring):** (1) t_mvm_s is PER TOKEN -- TOPS-derived row
times are tile-shape invariant, so no array-height folding (Mythic 6.38
us / ISAAC 1.6 us stand); (2) a bandwidth coordinate is the chip fabric's
aggregate supply to the array group one of OUR links serves (32 arrays);
published per-physical-link rates aggregate (HERMES: (418/64) x 0.4 x 32
~= 83.6 GB/s; the per-link 0.4 kept as `ondie_gbps_per_link`, still the
analog band's low end); estimated bands are authored at our granularity.
**The audit (`anchors.hermes_self_consistency()`):** need 256 INT8 / 133
ns ~= 1.93 GB/s per core vs supply (418/64) x 0.4 ~= 2.61 GB/s --
headroom ~1.36x: a fabricated analog chip provisioned its fabric just
above its own knee, the first external silicon point validating the knee
formula. The diagram redrawn (HERMES at ~84 GB/s: "the organisation
decides", fitting a compile-time scheduled fabric); group 23 re-pinned +
1 audit test. Suite: 244 passed / 1 xfail.

## C38: O21 closed (the 2,048-token ceiling) + hygiene 25 / 27, 2026-09-01

**O21:** `llm_workload.attention_die_context_ceiling` -- the feasible
two-dies-per-layer seating's K/V ceiling in closed form:
(DIE_WEIGHT_CELLS - 8 d^2 resident cells) / (4 d cells per token) =
**2,048 tokens** at d = 1024 (the "~2.5k" estimate corrected; a
cell-capacity upper bound). `check_context_ceiling` raises past it (the
message points at O14, the long-context mechanism), and
`die_to_die_activation` guards the two-dies-per-layer path (die slots >=
2 x layers) -- S = 512 everywhere unaffected. Validity statements updated
in SUMMARY (zh + en), PROGRESS, settings (assumption 5 carries the
computed value). **Hygiene 25:** `slot_pitch_um` gains its first consumer
-- a link may declare `ns_per_mm` instead of `ns_per_hop` (resolved at
load as pitch x ns/mm; both at once rejected; shipped configs keep their
explicit DR-4 per-hop values, so nothing published moves). **Hygiene
27:** the `reduction_hyperedges` membership convention is CONFIRMED
against Timeloop's spatial index order at the loop-nest level (Timeloop
flattens a nested spatial block with the innermost loop fastest --
exactly our first-listed-slowest convention); the parser's nest-order
preservation and a no-repeated-dim guard are pinned on the frozen ffn1
fixture, and the traffic.py docstring drops its "to be confirmed" caveat.
Tests: +3 (capacity/O21), +1 (fabric/ns_per_mm), +1 (interconnect/
membership). Suite: 249 passed / 1 xfail.

## C39: the offloaded twin of the fixed-terms figure; the write-bound mechanism, 2026-09-01

**What changed:** `sweep_axes.py`: the plane's fixed-terms block gains an
offloaded twin (`fixed_terms_offloaded` + `offload_relay`;
`device_fixed_terms.png` becomes four panels, prefill/decode x
on-chip/offloaded). Offloaded, the die keeps the projections + FFN
(scaling with t_MVM); the new fixed floor is the attention unit + link +
die digital remainder at the DR-9 generic values (decode 1.02 ms = unit
1.00 + link 0.01 + digital 0.01; prefill 19.71 ms = 8.61 + 4.03 + 7.08);
the NeuRRAM totals tie the C21 ledger exactly (518.12 / 1.99 ms). The
WRITE-BOUND mechanism is stated in writing (settings, assumption 22,
SUMMARY zh+en, ANCHORS DR-9, the caption): on chip each decode token must
be SET into its K/V row before qk^t/av can read it -- a fast device with
attention on chip is self-contradictory; the exits are DR-5 or DR-9.
**Findings (two expectations corrected):** no crossing threshold exists
-- the offloaded floor beats the write wall in both phases, so offload
wins single-pass latency at every device tier (the expected 1-3 us
threshold is falsified; the condition is stated parametrically); and the
offloaded decode is not a pure scaling wedge -- the unit floor caps it
(76.3x device buys 1.93x offloaded vs 1.11x on chip; prefill 19.7x vs
9.33x). The punchline is the fixed-terms RELAY: DR-5 sets the on-chip
ceiling, DR-9 the offloaded one. Group 27 + 1 test. Suite: 250 passed /
1 xfail.

## C40: the hygiene slate cleared -- exact energies, seeded sampling, the UCIe anchor, regen semantics, 2026-09-01

**What changed:** (22) `tl_output_parsing.exact_total_energy_J` sums the
per-component 'Energy (total)' lines and `run_mlx_layer` ships it in place
of pytimeloop's rounded per-compute-table total (ffn1 fixture: 2699.48 ->
2697.92 uJ, +0.058%, pinned in test_perceive; rounded value kept on
`energy_summary_J`; published JSON energies move <= 0.5% at the next
regeneration and the ledger's residual row closes then). (23)
`crossbar_value_real.py` seeds its CNN activation draw -- the
1.199-vs-1.204 rerun drift gone going forward, the published 1.204x
stands until the value stage regenerates. (24) make_figures audited:
every declared stage output exists; guarded by
`test_make_figures_outputs.py`. (26) the UCIe-S 64 D2D anchor (x16
standard-package module at 32 GT/s per lane = 64 GB/s per direction; UCIe
Consortium spec; status `spec` -- a standard's ceiling, one epistemic
step past post-layout, honestly separated from measured silicon): in the
D2D readout columns, all D2D tables/figures + the phase diagram
regenerated, group 23 re-pinned. (28) `run_scaling_probes.py --fresh`.
Suite: 252 passed / 1 xfail.

C40 addendum -- found while closing, PRE-EXISTING (verified identical at
the pushed HEAD via stash): two SLOW-suite goldens fail --
test_per_level_volume_conservation_v1 (12,288 vs 311,296; an old v1
identity apparently left in counter units by the C25 value reform) and
test_position_spread_golden_v2 (1.091 vs the pinned 1.25; the tiny2x2
spread never re-pinned after the C27 grid change). Fast suite unaffected.
Recorded as worklist item 13: re-derive with attribution, never band-aid
the pins.

C40-r (review amendments, 2026-09-01): (22) the exact-energy sum now
INCLUDES the temporal-reduction and address-generation adders (separate
line items in Timeloop's account; zero under this architecture's ERTs,
asserted on the fixture -- so nothing changes numerically today, and a
future ERT pricing them cannot be silently dropped), and the fixture pin
is joined by an IDENTITY that re-validates at every regeneration: the sum
agrees with the stats file's own Summary 'Energy:' line within its print
precision. (23) confirmed the seeded randn is the only stochastic source
on the value-sampling path (numpy does deterministic transforms; the
GPT-2 branch uses a fixed text). (26) the UCIe anchor states its four
conventions explicitly -- standard package chosen deliberately (organic
substrate, GRS's packaging class; the advanced x64 module's 256 GB/s
noted, not adopted), raw signaling ceiling with no protocol overhead
deducted, one module = one model die-link as a stated mapping convention,
and the press-only "first silicon" claim removed from the registry
(revisit when a per-link silicon measurement publishes). (28)
regen_v6.sh's probe line now passes --fresh (regeneration re-measures;
resume stays for interrupted runs). Process rules from the slow-suite
finding: the v6 freeze precondition now includes both suites fully green,
and the slow suite runs weekly + mandatorily before every freeze;
attribution clue recorded for item 13 (12,288 = 3 x 4096, 311,296 = 76 x
4096). Suite: 252 passed / 1 xfail.

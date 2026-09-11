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
Recorded in the worklist (now plan step 3): re-derive with attribution, never band-aid
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


C41 (2026-09-03): the Simba reproduction preset (worklist step 1, day 2).
models/fabric/simba.yaml expresses the 36-chiplet MCM prototype in the
fabric schema at the papers' EXPERIMENT operating point (MICRO'19 §4.1:
0.72 V, 1.03 GHz PE clock, GRS 11 Gb/s mode = 5.5 GB/s per link direction
-- NOT the 12.5 GB/s max; X-Y routing): die level = chiplet (6x6 NoP mesh,
20 ns/hop, 10 pJ/word GRS midpoint), macro level = PE (16 on the 4x5 NoC
with 4 spare slots = Global PE's 3 router stops + RISC-V; 8.75 GB/s and
10 ns per hop, pj_per_word 0 stated as uncharged), psum_word_bytes 3.0
(24-bit partial sums). Device: `device_class` field added to the fabric
schema (explicit whitelist reram_macro | digital_throughput); the Simba
device is digital_throughput (1/1.03 GHz cycle, slices=1) and
verify_cycle becomes a declared no-op for that class ONLY -- the bypass
never infers from missing ReRAM parameters, the default fabric keeps the
hard reconciliation, and a typo'd class refuses to load (validate).
anchors.py gains operating-point CONSTANTS (SIMBA_EXPERIMENT_GRS_GBPS 5.5,
NOC 8.75, PE_HZ 1.03e9, MACS_PER_CHIPLET_CYCLE 1024) deliberately outside
the Anchor rows so readout columns do not widen; the grs anchor's
derivation names the split. The device-input guard now exempts EXACTLY
["simba.yaml"] via the explicit class. Config frozen per SIMBA_PREREG.md:
from this entry on, no simba.yaml parameter moves to fit a result. New
group 31 (test_simba_fabric): geometry pins (36/6x6, 16/4x5, 576 PEs,
24x30 leaf grid), link pins (bandwidth words/cycle to 1e-9, hop
latencies, energy convention), device pins (2.11 TOPS/chiplet closed form
consistent with the published 4 TOPS at 2 GHz), the bypass contract both
ways, provenance carries device_class, and the D2D readout columns stay
[12.5, 64, 0.1, 2.0]. Suite: 259 passed / 1 xfail.


C42 (2026-09-02): Simba workload integration (step 1, day 3).
scripts/simba_workload.py: ResNet-50 target layers as closed-form ConvOps
(shapes from He et al. Table 1, stated as the model source -- the Simba
papers name layers without dimensions); conv_structure() builds
traffic.TrafficStructure directly from an explicit {K,C,P,Q} split (K
renamed to M so the existing dim-classification tables apply unchanged;
traffic.py untouched). Volume semantics = touched extents, the
anti-im2col rule: min((P-1)s+R, P*R) - 2*pad per axis; exact for 1x1
layers and for 3x3-pad-1 without spatial split; halo-carrying P/Q splits
on R>1 layers REFUSE (NotImplementedError) until a convention is
hand-locked, and (review) so does stride>1 with pad>0 (off-by-one against
the real map; no target layer uses either). compute_seconds at
utilization 1.0 (declared optimistic; our 100,352 one-chip cycles vs JSSC
Fig 18's measured 114,688 = exactly 7/8, direction consistent with the
pre-declared underestimate). GUARD SUBSTITUTION, stated for the
validation chapter: the mlx path's "reconcile derived volumes against
Timeloop's own counters" guard does NOT exist on the Simba path -- there
is no macro and no counter to reconcile (the closed form IS the volume
source). Its replacement is the day-4 hand-check gate (C43): both edge
directions, conservation, multicast/reduction membership and anti-im2col
locked against hand-derived integers. Any wording like "traffic reconciled
against simulator counters" must scope itself to the ReRAM path. Group 32
(9 tests). Suite: 268 passed / 1 xfail at this point.

C43 (2026-09-02): the conv-traffic hand-check HARD GATE passed (step 1,
day 4). Group 33 (test_simba_pilot_gate): pilot 3x3 conv (K=C=4, 4x4,
pad 1) under die K:2xC:2 and PE K:2xC:2 -- multicast groups {0,2}/{1,3}
and reduction hyperedges {0,1}/{2,3} (transposed partitions of the
instance grid, membership by the C38 index convention), per-edge volumes
32/32 die and 16/16 macro, leaf shares {die 16, macro 32}, conservation
(IA reassembles once, psums count C-copies), the anti-im2col assertion
(die edge 32, never 9x = 288), and the 1x1-conv == matmul bridge
(res4a_branch1 die edge = P*Q x C/2, the same shape as the width-law
trunk). Every expected value is a hand-derived integer in the test file's
comments. Suite: 272 passed / 1 xfail.


C44 (2026-09-02): T1, the Fig 9 seating-spread experiment (step 1, day
5). Amendment A1 written BEFORE the run (tiling enumeration rule,
sourced on §4.1's power-of-two convention and the paper's own
best-tiling baseline; IA home = anchor chiplet, per §5.2's
single-source broadcast description; OA local; multicast DEDUP on
shared route segments; on-die constant excluded with direction noted;
T1b band re-anchored [1.265, 5.06] on the measured 2.53).
scripts/simba_targets.py: closed-form evaluator (seatings -> node
indices on the row-major die table, dedup'd multicast + psum unicast
loads on the XY mesh, [max,sum] bracket + one-shot propagation).
OUTCOME, pinned honestly (group 34): serialization is seating-FLAT
(busiest segment 100,352 words at every seating; 18.246 us vs compute
24.357 us), slope only from propagation (+40 ns/bar): ratios 1.0000 ..
1.0066 vs measured 1.000 .. 2.530. T1a mechanically true but graded
NOT CLAIMED (degenerate, 4 orders below the effect); T1b FAIL ->
tier-2 class gap in the pre-declared UNDER direction, the entire
2.5x distance effect attributed to per-packet latency accumulation
(>= 738 packets at the 17-flit cap) + sync barriers, left for the
BookSim step to stamp (SIMBA_PREREG §8). Enumeration: four
multicast-structured candidates tie and the readout is tie-robust;
{C:4} loses 9x (psum width). No parameter touched. Suite: 275 passed
/ 1 xfail.


C45 (2026-09-03): T2, the Fig 15 data-placement experiment (step 1, day
6). Amendment A2 written BEFORE the run: active-32 declaration,
per-layer tiling frozen by baseline-scored enumeration (the paper's own
best-tiling convention), data blocks from the structure (IA per
distinct-input coord, OA per reduction hyperedge), Fig 14(b) sequential
baseline sourced verbatim, greedy procedure OURS-declared against the
paper's stated objective (dedup'd multicast-tree size for IA, unicast
distance sum for OA, iterative, exclusivity while unused dies remain),
res4a corner-vs-center sub-case under the §5.2-sourced K:32 with the
position-flatness risk PRE-STATED. scripts/simba_targets.py: T2
machinery (t2_candidate_splits / t2_baseline_homes / t2_greedy_homes /
t2_evaluate / t2_run). OUTCOME (group 35 pins, prereg §9): the lever
reproduces -- greedy never loses, and the best-gaining layer COINCIDES
with the figure's (res3a_branch1, ours 1.983 vs their 1.160); T2a pass
with two recorded caveats (res2c tie = self-aligned-baseline convention
artifact, 32/32 blocks local, their gain tiling-contingent --
zero-communication P:4xQ:8 is legal per JSSC §III-B; center-vs-corner
direction holds but degenerately); T2b FAILS its band on BOTH sides
(1.983 over, sub-case 1.0044 under) with ONE tier-2 mechanism read two
ways: placement-insensitive per-packet + sync terms (JSSC Fig 18)
missing from our denominator inflate ser-dominated ratios and carry the
whole position effect where dedup flattens ours. Absolute latencies stay
UNDER (6.96 us vs Table II 8.92 us reference). BookSim stamp pointer
unchanged. Suite: 281 passed / 1 xfail.


C46 (2026-09-03): the packet-level bracket (SIMBA_PREREG A3; the
reviewer's closed-form step 1, adopted with three corrections argued
first). Schema: Link gains packet_payload_bytes (None = off; every
production config) and packet_wire_overhead (>= 1); simba.yaml declares
128 B / 1.0625 on both links (17-flit packets = 1 header + 16 x 64-bit
payload flits, JSSC §II-C/III-D). Semantics: N x hops x t_hop is NOT a
schedule lower bound on a cut-through NoC (packets pipeline), so it
enters as the PESSIMISTIC end of a published bracket [pipelined bound,
round-serialized end] -- per source the terms sum, across sources max,
composes by SUM and absorbs propagation; the busiest-wire r=1 semantics
stays with the optimistic end untouched. The 17/16 header-share
multiplier IS an unconditional tightening and applies to both ends.
Expectations were pre-registered in A3 and the run reproduced them
(T1 pess bar-1 67.263 us vs 67.26 predicted; bar-5 ratio 2.3987 vs
~2.400); one recorded slip: the sub-case's "~1.78" used corner distance
10 where the active-32 maximum is 9 -- model output 1.6220 matches the
declared formulas. Results: T1 bracket [1.0066, 2.3987] with the
pessimistic end INSIDE T1b's band, tracking the measured ladder from
below with a distance-linear residual 0.7-5.2% (ack/sync fingerprint,
BookSim's assignment upgraded from "explain 2.5x" to "measure a <= 5.2%
residual"); T2 sub-case bracket [1.0041, 1.6220] contains the measured
1.05; T2 layer speedups compress toward 1 at the pessimistic end but
res3a stays 1.86 vs 1.16 -- the missing dilutant is a
placement-INSENSITIVE constant, sharpening the T2b record. Re-pins:
group 34 ser 18.2456 -> 19.386 us, {C:4} enumeration 219 -> 232.7 us,
new packet-bracket pins; group 35 opt speedups 1.9838 / 1.7922 / corner
1.0041 + pessimistic pins. Production fabrics numerically unchanged
(fields absent). Suite: 282 passed / 1 xfail.

C46-a (2026-09-03, closure audit on review): the pessimistic-end
arithmetic CLOSES to 1e-17; the reviewer's reconstruction mixed two
calibers (whole-map 784-packet framing vs the frozen {K:2,P:2} tiling's
two 392-packet slices at h = k and 2k -> the 3k coefficient; and the
pre-A3 ser 18.246 vs the x17/16 19.386). Our bookkeeping share of the
confusion fixed: SIMBA_PREREG §10a publishes the per-bar decomposition
table and marks §8's serialization numbers as pre-A3/superseded; a
closure identity joined group 34 (pess == comp + ser + pkt with the
slice decomposition, to 1e-12). §10b scopes the BookSim residual
candidates: psum packet density is ALREADY modeled (res4[b-f]_branch2a
C:4 exercises it); res3a's frozen tiling has NO reduction edge, so its
1.86-vs-1.16 residual stays with placement-insensitive constants.
Suite: 283 passed / 1 xfail.


C47 (2026-09-03): T3 + the Simba plane point (step 1, day 7). Amendment
A4 first (seatings, per-point best tiling under A2-greedy homes, graded
rail = pessimistic with the reason stated, class definitions with the
10% plateau tolerance, expected classes). T3 machinery
(t3_seating/t3_point/t3_classify/t3_run) + group 36 pins. OUTCOME: the
graded rail scores 1/3 -- A4-3 is the FIRST pre-registered choice
falsified by outcome, logged here formally (the round-serialized rail
over-penalizes small-n communication; elbows need a point inside the
bracket); the class bracket [opt rail, pess rail] contains the measured
class 3/3 (post-hoc reading, labeled, not a criterion swap); the bound
rail never exceeds measured anywhere; res3a's n=4/8 points expose the
tiling-freedom divergence again (zero-communication P/Q tilings, legal
per JSSC §III-B, beat silicon's realized mapping -- same root as T2's
res2c). T3 completes as the droppable target without dropping. PLANE
POINT: ChipPoint gains `paradigm` (analog default); Simba joins CHIPS as
the first digital chip point (t 497 ns derived via the C37 per-token
rule on the C41 device; on-die 560 GB/s per 32-array group; D2D 12.5/
5.5) and is excluded from device_marks() by paradigm -- the r=1
machinery keeps its four analog marks (pinned). analyze_phase_diagram
draws the diamond on both panels; ANCHORS.md gains the chip row and the
digital-exception note. Reading: on-die placement-free, D2D on the GRS
line below the spanning-chain boundaries -- the diagram predicts exactly
the exposure Fig 9 measured. Suite: 288 passed / 1 xfail.


C48 (2026-09-03): step-1 closeout (day 8). The per-target
measured-vs-bracket figure: scripts/analyze_simba_validation.py ->
analysis/simba_validation.png (reads t1/t2/t3_run live, so it can never
drift from the pinned record; house rules -- measured = gray bars,
optimistic rail = filled circles, pessimistic rail = open diamonds,
identity by marker/linestyle not color alone); make_figures gains the
"simba" stage (the stage-output guard covers it). Docs: SUMMARY §2.6
(EN+ZH) -- the validation-chapter section with both structural findings
and the honest verdicts; script-index rows; the groups-31-36 test note;
PROGRESS 3b marks the reproduction done; README's key-scripts line
extended. SIMBA_PREREG §12 = the closing verdict (claim-strength order:
ordering-class evidence, factor evidence, named gaps with owners,
direction discipline unbroken) and hands §10b to BookSim, the bracket
row to the robustness table, and §2.6 to the paper. The record is
closed; further Simba work reopens via changelog. Suite: 288 passed / 1
xfail.


C49 (2026-09-04): the soft-placement lever at the anchors (worklist step
2; half-day closed form, zero mapper). Pre-registered in FIXLIST step 2
BEFORE the run (review-amended: triple cells, two A-rows with distinct
semantics, per-cell direction expectations, coverage declared, gating
self-checks). scripts/analyze_soft_lever.py: uniform (D,U) per-op flow
model FIT against all five schemes' stored serializations
(contention_system.json) -- exact to 0 for all 6 matmuls both phases,
which PROVES node-uniformity, so A1 (real joint seat permutations, 8
bundles on the 2x4) = 1.000 exhaustively by symmetry; A2 (C28's x4
stressor, seat orbit exhaustive, marked non-realizable): mechanism
1.750x constant, whole-stack folds prefill 1.609x @ 0.4 GB/s -> 1.000
@ >= 2, decode 1.084x -> 1.000, fixed shares 76%/97% at 0.4; band > 1%
only below 1.37/1.08 GB/s, > 10% below 1.06/0.33. Shipped-stack
refold reproduces the stored row to 0. Expectations: all pre-written
directions held; the inherited 1.31x@0.4 SUPERSEDED by 1.609x (v6
ledger -- a finding per the pre-registration), the inherited 1.5-1.7x
band-low-end confirmed. Die-level rows collected (not recomputed) with
sources; the reading -- the on-die soft channel is CLOSED on the
production grid, placement leverage lives at the DIE level (Simba's
silicon says the same, SUMMARY §2.6) -- lands as SUMMARY §2.7 (EN+ZH)
+ analysis/soft_lever_table.md. Feeds step 5's attribution-split row.
Group 37 (5 tests). Suite: 293 passed / 1 xfail.


C49-a (2026-09-04, adjudication on review): what A1's 1.000 IS. The
either/or was put to the data: any two seatings carry IDENTICAL per-wire
loads (14 wires, wire by wire, all 6 lever ops both phases -- pinned in
group 37), so the row is STRUCTURAL DEGENERACY -- zero freedom -- not
differences canceling at the max. Second evidence layer: the traffic
extraction's conservation guards certify per-leaf even division on
Timeloop's own counters (ffn1 fixture: in_leaf 65,536 / out_leaf 32,768
single values). All prose re-calibrated to the conditioned claim: the
on-die soft-placement freedom is frozen to zero BY THE MAPPING under
three stated conditions (fill-exact grid, uniform mapping, fixed
bundling), each of which reopens the space when it breaks (C28
stressor demonstrates; MoE expert routing / variable-length attention
are natural producers); the unconditioned phrase "placement leverage
lives at the die level" is banned from the table (asserted). The
attribution framework gains its third hand, kept for the paper: the
MAPPING decides whether placement has any play at all. Suite: 294
passed / 1 xfail.


C49-b (2026-09-04): A3, natural non-uniformity via multi-operator
co-residency -- the REALIZABLE reopened-space probe the C49-a degeneracy
theorem called for (review addition; pre-registered in FIXLIST step 2
before the run, one-day cap unused). Block-exclusive reading: under
offload the die keeps the projection set, tiling integrally at d=1024
(qkv 3 / out_proj 1 / ffn1 4 / ffn2 4 macros; the attention-half die has
4 FREE slots); traffic density x8/k on each op's own macros (exact for
distinct-partition dims, stated); joint seatings exhaustive (280 attn /
70 ffn); compute/write from the stored ledger -- wire geometry only,
the compute-parallelism fork a stated boundary that cancels in the
ratio. RESULTS: mechanism 3.00x (attn) / 2.67x (ffn) -- EXCEEDING A2's
synthetic 1.75 (its "ceiling" is now scoped to the uniform-mapping
world); whole-stack 1.434x prefill / 1.057x decode at 0.4 GB/s, 1.000
above the knee. Expectation reconciliation: every pre-written direction
held (realizable lever > 1, monotone in g, prefill > decode, attn
variance > ffn, stack in [1.05, 1.609]); the magnitude pre-estimate
(mech 1.1-1.8) was UNDERSHOT by the data -- recorded as a finding. The
connector lands in the table and SUMMARY §2.7 (EN+ZH): after offload
what remains on the die IS this co-resident set; the space reopens, the
evaluator needed no new code. Group 37 +2 tests. Suite: 296 passed / 1
xfail.


C50 (2026-09-04): the document round (worklist step 3). (1) The two
stale SLOW goldens re-derived with attribution, never band-aided:
test_per_level_volume_conservation_v1 was a CALIBER MIX -- the left
side moved to value units at C25 while the right side stayed RAW
'Total scalar accesses' (counter units including fills: 311,296 =
76 x 4096); the correct right side is reads-only divided by the unit
factors, 57,344/7 + 65,536/16 = 12,288 = the flows total EXACTLY (the
test now pins the identity to 1e-9 and the 12,288 itself);
slow_golden_v2's 1.25 (= 5/4) was measured on the 3x3-with-hole grid
and never re-derived after the C27 fill-exact 2x4 switch -- on the 2x4
the 32 active crossbars fall into exactly two share classes, 4,608 vs
4,224 value units -> 12/11 = 1.0909, re-pinned with the attribution in
the fixture's provenance field. (2) DR-table refresh (EN+ZH): DR-2 now
priced directly by the anchored soft-lever table (band > 1% only below
~1.4 / ~1.1 GB/s; realizable lever 1.43x/1.06x at 0.4); DR-5 carries
the device-axis framing (the one device-side input that moves decode:
76.3x device -> 1.11x on-chip vs 1.93x offloaded). (3) SUMMARY gains
§2.8, the five-layer validation frame (inherited calibration /
counting / semantics / external behaviour / robustness), EN+ZH.
(4) README's key-scripts line adds the soft-lever generator. (5) The
LOCAL report tex (phase_diagram_report.tex -- the only tex in scope,
per the user's 2026-09-04 re-scope; settings_and_assumptions.tex and
company_report.tex explicitly untouched) absorbed the findings:
contributions extended (the mapping third hand; the pre-registered
reproduction), a new section "Pricing the software band at the
anchors" (degeneracy theorem conditioned on its three premises, the
realizable reopening, where the wide bands live), the validation
section rebuilt on the five-layer frame with the Simba reproduction
subsection + the measured-vs-bracket figure, and the conclusion's band
sentence -- content rules held (no test counts, no internal codenames,
no correction history). Suites: fast 296 / slow 302 expected all green.


C51 (2026-09-04): BookSim bridge, day 1 of step 4. Environment: BookSim2
vendored (tools/, un-tracked; tarball via the harness web channel),
parser generated on the host (container lacks flex/bison; nothing
installed anywhere), g++-only container build; the cimsim patch (TRACKED
at scripts/booksim_patches/0001-file-traffic-batch.patch, 171 lines)
adds traffic=file exact per-pair batches (per-source quotas override
batch_size) and the mesh_channel_latency knob. Conversion table (the
pre-registration's authority, amended with day-1 findings): flit payload
8 B, channel cycle 1.4545 ns, hop = channel 10 + default router
pipeline 4 = 14 cycles (alloc-delay overrides trip an IQ assertion;
split amended from the ruled 12+2, total and -1.8% remainder
unchanged), packet 17 flits, vc_buf_size 34 ALIGNED by BDP/line-rate
reasoning (default 8 throttles ~2x; insensitive vs 64), injection
caliber declared (max of channel/injection bounds on both rails).
GATES GREEN: B exact (85,456 == 85,456; interface base 37 cycles), A
1.0018. Lambda guard and unicast-decomposition label implemented per
the ruling; the review's bar1-narrow-bracket prediction could not be
reproduced arithmetically (recorded; the guard is armed regardless).
FLAGGED for review before day 2: expectation correction -- BookSim
measures the network-intrinsic share only; day 2 becomes a
two-component gap decomposition. New slow group 38
(test_slow_booksim, binary-missing = clean skip). Fast suite unchanged:
296 / 1 xfail.

C51-a (2026-09-04): interface-base correction -- the day-1 log's base 37
was measured under the DEFAULT 8-flit buffer (credit-stalled even a lone
packet); the BDP-aligned config's constant is 7 cycles (38 = 17 + 14 +
7), pinned in group 38; gate B stays exact. Slow suite: 306 / 0 / 1
xfail.


C52 (2026-09-05): BookSim day 2 -- the two-component decomposition,
measured (analyze_booksim_slack.py -> analysis/booksim_slack.json; all
quantities in the declared bridge caliber). Network-internal share
(bound -> BookSim): bar1 +0.18% (35 cycles), bar5 +0.74% (147 cycles)
-- bar5 > bar1, the distance-linearity signature confirmed INSIDE the
network layer, magnitudes single-digit percent as the amended
pre-registration wrote; both brackets classified WIDE by the guard
(bar1 included -- the review's narrow-bar1 prediction did not
materialize in this caliber, recorded), lambda ~0.0012 at both points:
the cycle-accurate reference lands ON the busiest-wire bound, certifying
its reachability by a real router (the schedule_slack lower end is
real). Protocol share (BookSim -> silicon): the BookSim distance ratio
is 1.0056, so silicon's 2.530x decomposes as 1.0056 (network-internal,
measured) x 2.516 (protocol: consumer buffering / per-block handshake
rounds -- now attributed WITH a measured anchor instead of "residual").
Triangulation note: the A3 round-serialized closed rail (2.40) sits
between BookSim's network-internal ratio and silicon -- the three-way
ordering bound < BookSim < closed-pess-rail < silicon is exactly the
stacked-layers picture. Group 38 +1 test. Slow suite: 307 / 0 / 1
xfail expected.


C53 (2026-09-05): BookSim day 3 -- records propagation per the signed
frame; step 4 CLOSED (the 3-day box took 2). ANCHORS gains the
NoC-paradigm slack passage (evidence status "cycle-accurate reference",
kept distinct from silicon; certification +0.18-0.74% network-internal
with the distance ordering; protocol share DECLARED and measured 2.516x
against Simba's seating experiment; the four-way ordering bound <
BookSim < round-serialized rail < silicon). SUMMARY §2.8's fourth layer
updated EN+ZH. phase_diagram_report.tex's validation subsection carries
the executed cross-check (two components, each with a number) and drops
it from "next steps". analyze_phase_diagram: the D2D panel carries the
certification annotation; NO corrected boundary line is drawn for this
fabric -- that requires a platform packet declaration (payload/packet
cap), a DR-tier input we refuse to invent. Step 5's robustness input
renamed "network-internal coefficient + declared protocol share".
Figures regenerated. Suites: fast 296 / slow 307, both green.


C54 (2026-09-05): the robustness pass (worklist step 5; half-day closed
form, zero new simulation). Criteria pre-registered
(ROBUSTNESS_CRITERIA.md) with the caliber vocabulary (REGION / STRADDLE
/ ORDERING / THRESHOLD-GATE / MEASURED-EXACT; FAIL vs UNINFORMATIVE
enforced) and review-amended three ways before the run: R11 recast as
the accounting audit's DISCRIMINATION RADIUS (1.36x -- blind beyond; a
high-information row, not a free pass), R15 renamed the
WORST-PROTOCOL-ASSUMPTION overlay (Simba endpoint tier, 2.516x,
extrapolation declared, with the mandatory counter-note that protocol
share is an endpoint-design parameter), R12's 1.68x location caveat
(the tiling-divergence site -- pure model-error headroom larger; triage
pre-written). Run: 15 rows -> analysis/robustness_table.md + .json;
digital-anchor region calls survive 5x and the overlay (min residual
margin 4.3x); the workspace straddle fails 5x only in the
placement-strengthening direction; R13's bracket containment dies at 5x
as a bracket should. Group 39 (4 tests) pins the verdicts INCLUDING the
reds. SUMMARY S2.8 layer 5 (EN+ZH) and the report's validation chapter
absorb the verdicts. Fast suite: 300 / 1 xfail.


C55 (2026-09-05): FREEZE = tag v6. Final read-through passed (wording
layer deferred to the writing month by decision); both suites fully
green on the final pre-tag run (fast 300 / slow 311, each + 1 xfail);
the citation snapshot analysis/frozen_v6.md exported so the writing
month cites frozen numbers. Covers C41-C54: the Simba reproduction
(preset, workload, gate, three targets, packet bracket, plane point,
closeout), the anchored soft-placement band (degeneracy adjudication +
the realizable A3 reopening), the document round with the two slow
goldens re-derived, the BookSim cross-check (bridge, identity gates,
two-component decomposition, records propagation), and the robustness
table with its pre-registered criteria and honest reds.


C56 (2026-09-08): the die-level D2D ENERGY column (O27 pre-flight,
post-v6; pre-registered in FIXLIST step 8 with the convention correction
to the review's naive bytes-x-price formula). Zero mapper: B1 from the
stored 48-die ordering sweep (gate: stored surplus_uJ reproduced exactly
from words x (hops-1) x pJ; total scales with avg hops per the C23
replace-never-add convention), B3 from the stored 4-die probe (charged
words inferred and cross-checked across placements; latency read at the
stored 256-w/c column), B2 closed-form on the 2.7B chain's three seating
styles (block_die_flows leaves distance=0.0 -- per-flow hops charged
from the seating via the interconnect; the first uncorrected run's fake
1.000s caught and fixed). RESULTS: lever real (B1 6.553x = avg-hops
ratio; B3 5.33x; B2 1.08-1.15x), share SUB-percent everywhere
(0.03-0.76% -- our filed arithmetic hand; the review's single-digit-%
hand missed), and the draft's no-anti-ordering expectation OVERRULED:
B1 surfaces a latency TIE broken by 1.745x energy (sequential-rows vs
snake), B3 a genuine off-optimum INVERSION, B2 diverging style orders
-- while the latency-best choice stays energy-best or within 8.3% of a
sub-percent account in every scenario (system cost < 0.1%). Paper
wording lands two-tier per the pre-registration. Figure
d2d_energy_column.png; group 40 (4 tests) pins the gates, the numbers
and both overruled expectations. Fast suite: 304 / 1 xfail. O27's MAIN
BODY not started (stopped at the gate per instruction).


C56-a (2026-09-08, figure rework on review): the D2D energy-column
figure recolored (user: not grayscale -- latency blue / energy orange,
CVD-safe, color follows the MEASURE) and amended three ways: the middle
panel carries the numbers on the figure (near-optimum zoom inset with
(lat, E) pairs -- clustered E 1.08, row-fill E 1.00 -- so the capping
sentence self-certifies; the inversion pair annotated), the title drops
"energy-free" for "SUB-PERCENT BOUNDED" (no words beyond the figure's
own conclusions), and the left panel marks "far pairs" as a CONSTRUCTED
stress position with the real-space spread (1.74x) stated -- preventing
the "6.5x in real ordering space" misreading.

C57 (2026-09-08): O27 main body -- static energy + peak concurrency,
closed form, layered caliber per the filed discipline. Schema:
Level.idle_power_w (per-instance watts, PLATFORM INPUT, default None =
not modeled; shipped configs unchanged -- asserted). Structural layer
(parameter-free): E_static = P x makespan inherits the latency ordering;
the pairwise CROSSOVER powers are real results needing no input --
prefill: all non-positive (energy and latency verdicts already agree;
static power only widens offload's lead); decode: the write wall's
latency penalty becomes an ENERGY penalty at P* = 0.085 W chip static
power (A-vs-B flips to offloaded) -- the headline. Share layer published
as a FUNCTION over a labeled input grid (values await the DR /
literature anchors being retrieved under the provenance discipline).
Peak concurrency: schedule-level counts (1-die 256 crossbars; 48-die
pipelined 48 dies / 12,288 crossbars; per-die avg dynamic 0.905 W ->
pipelined estimate 43.4 W) with the boundary sentence shipped verbatim
in every output. static_energy.json/.md; group 41 (4 tests). Fast
suite: 308 / 1 xfail. Anchor integration pending the retrieval.


C57-a (2026-09-08): O27 closed -- the anchor retrieval returned the
honest answer: NEITHER NeuRRAM nor HERMES publishes a numeric standby
power (NeuRRAM: qualitative power gating with non-volatile retention;
HERMES: static measured on all supplies and folded into totals, never
disclosed separately) -- verbatim record in
analysis/papers/power_extracts.md. Integration under the provenance
discipline: two DERIVED active-power anchors (NeuRRAM ~20-25 mW /
active 256x256 core at 130 nm, from GOPS / TOPS-per-W; HERMES ~101
mW/core at 14 nm, 63.1/9.76 corroborated by 0.86 uJ / 133 ns) bound the
production die's ACTIVE-CLASS scale at 5.0-25.9 W, against which the
parameter-free decode flip threshold (0.085 W) reads 0.33-1.7%:
unless a real chip's static power sits below roughly one percent of
its active-class scale, the decode energy verdict follows the latency
verdict -- with NeuRRAM's gating the one published mechanism that could
dip under. The share layer stays a FUNCTION and the static point value
stays a DR item, exactly as the layered discipline required. Group 41
+1 test. Fast suite: 309 / 1 xfail. Worklist step 8 CLOSED.

## C57-b (2026-09-08) -- O27 review round: provenance + denominator labels; the peak wing written up

Three review findings on the C57-a closeout, all landed. (1) The
5.0-25.9 W active-class interval mixes a 130 nm RRAM end with a 14 nm
PCM end -- it is a CROSS-TECHNOLOGY EXTRAPOLATION, the third provenance
class that must be declared: kept as an interval, labeled
order-of-magnitude-scaling-only, never for point conclusions; and since
the production die is the Wan device (a geometric scale-up of NeuRRAM),
prose cites the NeuRRAM end (~5.0 W) as PRIMARY and HERMES as the
cross-technology reference. (2) The 0.33-1.7% figure's numerator and
denominator were different calibers: the denominator is the FULL-STREAM
peak active power while decode -- the regime the flip is about -- is the
lowest-utilization regime; the figure now ships with its denominator
label plus the note that against decode's own active power the ratio is
an order of magnitude higher (exact value = the DR static point item);
the denominator-free anchor is the absolute 0.085 W flip and the
NeuRRAM power-gating half-sentence, which survive unchanged. (3) The
peak-concurrency wing (O27's second deliverable) was BUILT and PINNED
at C57 but omitted from the closeout report -- verdict "done, not
written up": FIXLIST step 8 now records it explicitly and
static_energy.md section 3 states its three uses (power-delivery
worst-instant input; a function of placement/schedule and hence a
candidate search constraint dimension; the reviewer's power-density
column). No numbers moved; group 41 +1 label-pinning test
(test_bracket_provenance_and_denominator_labels). Fast suite: 310 / 1
xfail.

## C58-a (2026-09-08) -- A5 days 1-2: the overlay route ruling + the derived lower-link prices

Day 1 (route ruling, user, filed before any number ran): the OVERLAY
route. The CiMLoop account keeps its inherited silicon calibration
untouched; core/crossbar traffic will be priced as a DECLARED
supplement outside it (the D2D-surplus convention, words x pJ/word x
hops). Reasons filed in FIXLIST O1: semantic honesty (declare a
supplement vs claim account coverage through a stand-in edit that moves
every pinned total ~2%), evidence grades kept unmixed (calibrated
account vs derived-tier supplement), and DR-1's arrival becoming a
constant swap instead of a model-change round. The one price paid: the
xfail's acceptance clause (energy inside the perceived CiMLoop stats)
is REWRITTEN -- it now passes on positive derived prices in the fabric
config plus a positive overlay energy column for both levels
(analysis/lower_link_energy.json, day 3); the old clause and the ruling
are recorded in the test docstring. The xfail still fails today, as it
must until day 3.

Day 2 (provenance ruling, user: route (b), not (a)): the prices are
DERIVED down a chain with every step sourced -- router energy on the
frozen ffn1 fixture (the macro link IS silicon-calibrated) 26.68 uJ,
divided by the C25 value-word volume through glb<->macro (8,912,896,
crossbar_comm.build_flows) = 2.993 pJ/value-word at reference_hops 1,
scaled by the C38 declared slot-pitch ratios (macro 800 / core 400 /
crossbar 100 um; energy ~ wire capacitance ~ length) -> core 1.497,
crossbar 0.374 pJ/word. The 1 pJ/word value is retired to what it
always was: a sentinel, now the pre-registered route-(a) FALLBACK that
fires only on a broken geometry chain and carries its own EXAMPLE
DEFAULT label. Acceptance gate (the pre-registered number): charging
ffn1's value volumes at the derived prices, 2 hops = 50.3 uJ = 1.86% of
the 2.70 mJ operator -- the C25 ~2% ceiling reproduced by an
independent arithmetic, PASS. The price values themselves were NOT
pre-registered (readouts, not predictions). New:
scripts/derive_lower_link_prices.py -> analysis/lower_link_prices.{json,md};
tests/test_lower_link_prices.py (group 42, 4 tests). Days 3-6 pending.
Fast suite: 314 / 1 xfail.

## C58-b (2026-09-08) -- A5 days 3-4: the overlay column lands; the last xfail is promoted

Day 3 (mechanism): the two lower links carry their derived prices in
the fabric config (mlx300.yaml core 1.4967 / crossbar 0.3742 pJ/word
per LEVEL-hop, calibration label "derived-C58a route (b); overlay-only;
DR-1 replaces outright" -- the validator's price-monotone-up-the-tree
check holds), and scripts/analyze_lower_link_energy.py charges the C25
touched-extent value volumes at those prices outside the CiMLoop
account (words x pJ/word x hops; edge distances from build_flows are in
leaf units, hops = distance / pitch ratio; because price ~ pitch, the
level framing is asserted IDENTICAL to per-leaf-unit charging -- the
caliber choice cannot move the total). No existing number moved: the
lower-link pj_per_word had no consumer until this script.

Day 4 (gates, with both riders from the release instruction): G0 price
tie fabric == derivation; G1 conservation on the C25 touched-extent
volumes -- leaf 25,165,824 words EXACTLY equals row reads / 7 + adc
reads / 16, upper levels at or below it (multicast strictness); G2 the
pre-registered ceiling gate WITH the itemized breakdown table: core
10,485,760 words x 1.0000 mean hops x 1.4967 pJ = 15.69 uJ; crossbar
25,165,824 x 1.5000 x 0.3742 pJ = 14.12 uJ; total 29.82 uJ = 1.11% of
the 2.70 mJ operator -- inside the C25 ~2% ceiling and below the day-2
flat-2-hop arithmetic (real mean hops < 2, the pre-filed direction).
All PASS.

xfail_lower_level_links_are_priced PASSES under its rewritten
acceptance and is PROMOTED to test_* in this same round per the
runner's own rule (day 6 keeps the closeout bookkeeping). The suite
carries ZERO expected-fails for the first time since the xfail
convention was introduced. New artifacts:
analysis/lower_link_energy.{json,md}; group 42 +4 tests. Fast suite:
319 / 0 xfail; slow: 330 / 0 xfail. Day 5 (rankings -> joules) NOT
started -- stopped at its gate per the release instruction.

## C58-c (2026-09-08) -- A5 days 5-6: rankings become joules; A5 closed

Day 5. The conversion turned out to be a structural theorem, not a
computation: route (b) prices every level proportionally to its slot
pitch, so all three on-die levels share ONE per-leaf-slot price --
2.9934 pJ/8 leaf = 1.4967/4 = 0.3742/1 = 0.374177 pJ/word/leaf
(asserted from the fabric to 1e-9). Every volume x distance ranking
therefore converts to joules by a single constant, and the
pre-registered ORDER pin passes in its strongest form: orders AND
ratios preserved exactly by construction. The maps now have units --
2x4 default: busiest crossbar 0.343 uJ, lightest 0.202 uJ, 1.70x;
3x3 variant: 0.276 / 0.075 uJ, 3.69x. Region half: the committed 17.8%
index metric untouched and reproduced; the pre-registered
physical-length re-score (the index metric is anisotropic in disguise:
a macro step is 800 um, a core step 400) reads 21.4% with the order
PRESERVED -- dataflow order 6.75 uJ/layer vs size order 8.58, gap 1.83
uJ/layer (x12 layers: 81 vs 103 uJ per model pass); labeled an
attribution readout (inter-operator activation transport sits in
neither the CiMLoop account nor the overlay column). The search-side
sentence is pinned verbatim: distance rankings ARE energy rankings
exactly as long as price ~ length holds; a DR-1 breaking the
proportionality can genuinely reorder -- recorded as a finding, never
re-parameterized. New: scripts/analyze_ranking_joules.py (two-stage:
region on host with io_study, main in container) ->
analysis/ranking_joules.{json,md}; tests/test_ranking_joules.py
(group 43, 4 tests).

Day 6, closeout. The company deliverable: SUMMARY zh/en 2.1's energy
decomposition table gains the supplement row (+ core/crossbar wires
+29.8 uJ = +1.11%, outside the baseline's untouched 100%, itemized
15.7 + 14.1 uJ, DR-1-replaceable), and the "transport < 2% is a lower
bound" caveat is upgraded honestly to "~2.8% all-in; every remaining
unpriced term is still a network term". FIXLIST factor map re-audited
(per-op placement + calibration rows); O1 CLOSED at the derived-price
tier. A5 done end to end: route ruling -> derived prices -> overlay
column -> gates with the itemized table -> joules with exact order
preservation -> company row. Fast suite: 323 / 0 xfail.

## C59 (2026-09-08) -- A6: per-scheme ENERGY wire models; O8 closed

The gap (O8, filed at W2): Bus.hops() charged Manhattan-to-driver, so
the energy re-pricing saw a bus as a point-to-point wire and tied
star <-> bus-centre exactly (mean hops 1.3125 both) -- "identical
energy, 8x latency" was partly a model artifact; h_tree's flat
level_length default (1 per level) was the same gap smaller.

Day 1 (inventory + pre-registration, closed before code): rulings --
bus = the SERPENTINE line, (N-1) slot pitches charged whole to every
transfer (deliberately the model harsher on bus; replaceable example);
h_tree same round, its physical lengths registered as LITERALS
(anchors.HTREE_MACRO_LEVEL_LENGTH_SLOTS, the S5 collaborator's solver
reads the same table). Energy-vs-latency consumer split inventoried;
moving-pin list closed at EMPTY (all shipped configs star/mesh).

Days 2-4: energy_hops() beside hops() -- identity for point-to-point
schemes (the day-2 gate: fast suite green untouched, zero pins moved),
Bus and HTree overrides; the six energy call sites switched (pa
re-pricing, build_flows distances, die surplus, scale tiers, d2d
column, multidie placement); latency/contention paths untouched.
Re-run against the pre-registration, two-handed: the artifact tie is
DEAD (bus 2.8580 mJ vs star 2.7113, 1.054x; component tier 7/1.3125 =
5.33x on the 3x3 tie host exactly as pre-filed, 7/1.5 = 4.67x on the
2x4 default -- the pre-reg had conflated the grids, recorded); the
pre-written NEW physically-correct tie is ALIVE (bus-centre ==
bus-corner to 1e-12 -- the whole line swings either way, the driver
position keeps only latency meaning); h-tree 2.7513 mJ (root-weighted
direction confirmed); variant energy span 1.007x -> 1.057x while the
latency side did not move. Sentence triage as pre-written: "a latency
finding, not an energy finding" SURVIVES, now resting on wire models
(1.057x vs 8.25x); "energy is contention-blind" SHARPENED -- the
account now sees the MEDIUM, still not the schedule. Star row 2.7113
vs the C27-era doc quote 2.7128 predates this round (star is
C59-invariant by construction); docs refreshed with the note in
place. The A5-linkage pin (user's supplement): a bus variant at the
CROSSBAR level charges the full 7-pitch local line through the same
build_flows distances the C58 overlay column reads -- the lower
levels are covered by construction. Docs: SUMMARY zh/en 2.3.1b(b)
rewritten, artifact caveats 2/3 closed, the stale "1 xfail" paragraph
(an A5 leftover caught by the day-1 inventory) rewritten in both
languages. New: interconnect.energy_hops/mean_energy_hops +
physical_level_length; tests/test_wire_models.py (group 44, 6 tests) +
group 14 tie test extended. Fast suite: 329 / 0 xfail.

## C60 (2026-09-08) -- A7: torus + ring join the registry (folded models); O19's first queue items landed

Day 1 (pre-registration, four rulings + two review clauses, all filed
before code): torus AND ring in one round; sweep minimal set =
occupancy + hub-gating machinery plus ONE die-level product row (the
48-die ordering spread); SUMMARY gains the row this round; and the
undeclared physical assumption ruled before start -- wrap links are
NOT free: FOLDED models by default (every hop on a folded axis = 2
slot pitches), with clause 1 splitting the accessors (router_hops =
crossing count for per-router packet constants, hops = physical
length for the ns_per_mm and price-per-length chains; a validation
guard refuses packet params on folded schemes) and clause 2 sharpening
the expectation to the three-sentence portrait (mean flat-to-worse,
tail truncated in count, net benefit = busiest-wire redistribution).

Days 2-3: the classes (Torus folds axes of width >= 3, width <= 2
degenerates to mesh -- the pre-filed note held; Ring = the uniformly
folded 1D cycle), hand-derived identity pins on both grids, the C59
energy identity kept verbatim (point-to-point, on physical length),
zero committed pins moved. Readouts, two-handed against the
pre-registration: the 3x3 corner/centre peak lever (pinned 5/3) reads
EXACTLY 1.00 under torus -- the hub-position lever can be zeroed by
topology, landing the compression prediction in its strongest form;
the antidote is for eccentric hubs only (central hubs gain no count
and pay the fold, mean physical 1.67-2.0x worse on these small grids
-- clause 2's 'slight' exceeded, booked); and THE FLIP: the 48-die
ordering spread WIDENS under ring (6.55x -> 12.26x; a 1D cycle's far
end beats a 2D mesh's) while torus narrows it (3.57x), with the
ordering roles swapping (ring's native sequential rows = exactly
1.000). Day 4: the caliber confirmation (count and phys spread
columns coincide structurally -- both 6x8 axes fold, the uniform
scalar cancels; asserted elementwise) and the three doc placements:
SUMMARY zh/en new section 2.9 (the three honest seating sentences +
the weave knob's 3.4x lever on the ordering-penalty axis as a third
hand + the paradigm-dependence instance: the ordering BASELINE swaps
with the weave), footnote hooks at the 12-19x pipeline paragraphs,
registry rows updated, FIXLIST factor map re-audited. Every frozen
claim untouched. New: interconnect.Torus/Ring + router_hops split +
the fabric packet guard; scripts/analyze_torus_ring.py;
tests/test_torus_ring.py (group 45, 9 tests). Fast suite: 338 / 0
xfail.

## C61 (2026-09-09) -- A2: the row split measured end to end; O15 resolved

The scaling law's one declared exception (row split: cut C, add
partial sums across dies) becomes measured rows. Day 0, the identity
rerun: 18 mapper runs (d 1024/2560/4096 x six matmuls, O17c settings
verbatim) reproduce the frozen probes 18/18 BITWISE -- worst relative
drift 0.000e+00, the noise tier never used; every later difference
attributes to the split switch alone. Day 1, the hand gate: 13/13 on
the first try (P=128, C=16,384, M=1024 -- exactly 2 dies, C:2 pieces
exactly one die each): the mapper carries the die-level C split, the
extraction reads it, the edge volumes land on the hand integers
exactly (down = the disjoint slice, twice = the full input once -- a
row split multicasts nothing; up = full-M unmerged psums), the
reduction hyperedge is [[0,1]]; caliber note filed (psum pricing is
DR-7 16-bit x2; "3 bytes" was Simba's 24-bit wire). Day 2:
pre-registration concretized -- per-LEVEL swap inequalities (die:
2Mn > C; macro: the formula with the mapping's factors), the S weld
tied to its projections/FFN scope, the frozen-number fence (regime
tags in SUMMARY zh/en; new rows only; tex deferred by standing rule).

Days 3-4, the scan (25 points, resumable; probe knobs min_dies /
dims added default-neutral): feasibility frontier EMPTY. P1 die line
100% with ffn2's minimal-split EXACT tie (2Mn = C = 4096); the
per-level split is real (die psum / macro trunk in the small-n rows);
P2 weld holds (ffn2 S-free at 0.0179). P3 REFUTED IN THE MAIN: the
voluntary underfull row split is exactly 2x worse on-die for M-heavy
ops (compute halves, full-M psum stays) and better only for C-heavy
ffn2 -- the company sentence flips to "replication stays the better
underfull exit, except C-heavy shapes". Two findings booked: the
LOAD-RELOCATION VALVE (row split relaxes the on-die busiest wire up
to 4x -- ffn2 0.0714 -> 0.0179 -- while the die edge goes
psum-dominated everywhere; the HARD RULE: both levels, always, and
this is the first constraint a future split-regime search variable
must encode; die counts move both ways, so load relocates, not area)
and the ffn1 IDENTITY SENTINEL (row ratio == column ratio at every
width, direction flipped dn -> up; pinned across the two independent
files as a free regression tripwire). Day 5: SUMMARY zh/en row-split
subsection, R10's note upgraded (the named other regime is MEASURED;
the column-split structure unmoved in its own regime), O15 RESOLVED,
no phase-figure psum family (the row-split busiest wire never exceeds
the column line at any measured width -- reason recorded). New:
scripts/a2_identity_rerun.py, a2_hand_gate.py, run_a2_row_split.py;
analysis/a2_*.json + a2_row_split.md; tests/test_row_split.py
(group 46, 9 tests). Fast suite: 347 / 0 xfail.

## C62-a (2026-09-09) -- A3: O14 closed at the declaration tier

The narrowed ruling executed (half a day, no execution machinery: the
company's roadmap is nowhere near long context and the item is weakly
tied to the paper). check_context_ceiling gained an OPT-IN
over_ceiling="window" mode -- the default "reject" is byte-identical
and its pins unchanged -- which truncates to the 2,048-token ceiling
and ships WINDOW_MODE_DECLARATION verbatim: the computation becomes
equivalent sliding-window attention (a semantics change), and the
accuracy impact of that change is OUTSIDE this platform's evaluation
scope. The validity domain is re-stated in the guard, SUMMARY zh/en
and FIXLIST: S <= 2048 under full-attention semantics / any S under
window mode with the semantic change declared on file. Eviction and
tiered residency are archived as un-built design space awaiting
product intent -- no machinery, no pricing, in no scan. Also filed
(before A4 starts): the review's three A4 pre-registration amendments
-- the two-axis deviation expectation (latency: handoff propagation +
occupancy, closed-form number pre-estimated; energy: the B2
sub-percent frame, which is where that frame actually applies), the
16x20 grid declared example geometry with the aspect-sensitivity
half-sentence (an S4 question, out of scope), and the pure-serial
composition semantics declaration (batch-1 single-request; never
tabled against b1_orderings' pipeline readouts). Group O21 block +1
test. Fast suite: 348 / 0 xfail.

## C62-b (2026-09-09) -- A4: the whole-model static spread measured; O16 under its only realistic hypothesis

Days 1-3 under the narrowed ruling (static spread only; hybrid
residency = decision-layer future work; rewrite bounded out in one
closed-form line). Day 1: seating rule declared (block_chain 17
dies/layer x 32 = 544 -- the review's ~320 was a capacity-packing
estimate, revision recorded), 24x24 = 576 grid DECLARED (near-square,
no product basis; aspect sensitivity out of scope, an S4 question),
and the two-axis closed-form pre-estimates produced before the script
existed. Day 2 (closed form, zero mapper; symmetric columns, the
mid-run asymmetry bug fixed before numbers): whole machine 1034.8 ms
at GRS vs block x 32 extrapolation 1021.8 = +1.27% (+12.0% at
0.1 GB/s); energy 2.394 vs 2.351 J = +1.83%. Latency direction held
everywhere; magnitudes explained -- the pre-estimate missed the
standing multicast-to-every-consumer-die convention (inter-layer words
exactly 4x) and used a matmul-only baseline. Energy EXCEEDED the
pre-registered B2 sub-percent frame: booked as a finding and, per the
day-3 review, DECOMPOSED BY NATURE -- 43.03 mJ = 1.63 accounting
caliber (the x4 multicast flat, geometry-free) + 9.99 inter-layer hop
surplus + 31.41 layer-offset variation (the data's sharpening of the
review's two-way split: the largest term is that layer 0, the
extrapolation base, is the one row-tight cluster) -- verdict
GEOMETRY-DOMINATED at 96.2%, so the corollary "whole-machine D2D
energy ~4.0% of the account" ships QUALIFIED: it carries the declared
geometry and is never a bare constant. Semantics fence pinned: batch-1
pure serial, never tabled against b1_orderings' pipeline readouts.
S4 payload shipped (seating map + the 16-package x 2-layer seam
example split field). New: models/fabric/mlx300_multidie576.yaml,
scripts/analyze_full_model_seating.py -> a4_full_model.{json,md};
tests/test_full_model_seating.py (group 47, 6 tests). O16 MEASURED
under the hypothesis; O20's captioned debt quantified. Fast suite:
354 / 0 xfail.

## C63-a (2026-09-09) -- O19 batch opened; item 1 (duplex) closed-as-already-done

The batch's two qualitative rulings filed (the weave never enters the
search's variable set -- condition enumeration, not a dimension; new
weaves are instrument-side completion, not paper evidence). Item 1
executed as its own mandated inventory demanded (the moving-pins list
delivered BEFORE code): the list came back EMPTY -- the direction-
split full-duplex account has been live since O22/O23 (2026-08-21),
every published multiplier was re-pinned on it that round, the
resolved-items table has said "O22 RESOLVED (C17)" all along, and
duplex=False survives only as the explicit pre-O22 comparison knob in
tests. The batch plan's item rested on a stale sentence in the O19
archive that was never synced. Residue fixed: that sentence retired
in place, the stale Mesh docstring ("segments are undirected")
corrected, and one confirmation pin added (group 44: the DUPLEX
contract per scheme, the split keying live occupancy resources, the
merge knob demonstrably piling both directions on one wire). Zero
account movement; the premise correction is the item's result. Items
2 (switch) and 3 (CMesh) queued; express links optional; FlooNoC-
class + routing params queued-conditional with the 9/16 deadline.
Fast suite: 355 / 0 xfail.

## C63-b (2026-09-09) -- O19 batch item 2: the switch weave

The registry gains `Switch` (repo naming rule: never "crossbar" --
that is the ReRAM array): non-blocking up to port bandwidth, the
weave that is placement-irrelevant BY CONSTRUCTION. Port bandwidth is
the only first-order parameter; hops is a declared end-to-end
constant (param, default 1.0) inherited by energy_hops/router_hops
(C59/C60 identities trivial); a flow occupies its endpoints' TX/RX
ports under the duplex split; THE N^2 WIRING PRICE IS DECLARED IN THE
IDENTITY AND ENTERS NO ACCOUNT. Both pre-registered expectations
landed exactly: ordering spread 1.00 in both calibers (control arms
6.55x/12.26x/3.57x beside it) and identical busiest-port crossings
under every ordering -- placement-irrelevance measured. One
pre-registration refinement, caught at test-writing time before any
published sentence: the star-degeneration identity holds for
NODE-TO-NODE flows (pinned equal multisets + bottleneck); hub-rooted
flows FUNNEL through the switch's single hub port (800 vs star's
private 100 -- star is the N-port idealization); both faces pinned.
The company sentence: the "switch vs mesh" decision is computable --
N^2 wiring buys off placement sensitivity outright. New:
interconnect.Switch; scripts/analyze_switch_weave.py ->
switch_weave.{json,md} + switch_ordering.png; tests/test_o19_batch.py
(group 48, 5 tests). Fast suite: 360 / 0 xfail.

## C63-c (2026-09-09) -- O19 batch item 3: CMesh

The registry gains `CMesh(Mesh)` -- the concentrated mesh, k nodes
per router (param concentration [cx, cy]; routers at tile centers;
router-grid steps cost the tile pitch; [1,1] degenerates to mesh
EXACTLY, pinned on every pair including the HUB with zero extra
resources). One pre-registration amendment, filed at implementation
time before any readout: the concentration cost's physical carrier is
the ROUTER LOCAL PORT (k tile nodes share one router's injection/
ejection bandwidth), not a wire -- a wire-only account would have let
the funnel vanish at high k; the amended contract adds the shared
per-tile port resource (k > 1 only; the HUB is router-resident and
port-free). All amended expectations landed: port load = k exactly
(monotone by construction), and the overall bottleneck reads
4.0/4.0/4.0/8.0 over k = 1/2/4/8 on the uniform hub-rooted flows --
concentration on the 2x4 grid is FREE up to the computed crossover
k* = 4 and binding beyond (at k = 8 the port is the bottleneck
resource). The design sentence: "how many nodes per router is free"
is a computed crossover, not a rule of thumb. New: interconnect.CMesh;
scripts/analyze_cmesh.py -> cmesh_weave.{json,md} +
cmesh_concentration.png; group 48 +3 tests. Fast suite: 363 / 0 xfail.

## C63-d (2026-09-09) -- O19 optional item: express links; the batch's main body complete

The registry gains `Express(Mesh)` under the LOCKED family (uniform,
station-free: every line position carries a link to c + s; no station-
alignment degree of freedom; skip >= extent degenerates to mesh
exactly, pinned). Calibers: physical hops == Manhattan == mesh
pair-by-pair (asserted -- express never saves wire, it saves router
crossings and local-segment contention); router_hops counts one per
express traversal -- the count/length split's third appearance, and
the fabric packet guard now lists express beside torus/ring. The
price-curve readout (corner/centre hub lever vs declared wire price,
two hosts) replaced the planned spectrum sentence with better ones,
both hands booked: on the 3x3 the pre-written risk landed as an EXACT
TIE (express s=2 == torus: lever 1.000 at 2.0x wire); on the 6x8 the
UNREGISTERED FINDING -- express s=2 makes the lever WORSE (2.000 vs
mesh 1.667) while improving both absolutes (24->16, 40->32), the
lever is non-monotone in s (2.0/1.5/1.0), and torus dominates every
express variant. The pre-registered "compresses toward 1 but not to
1" was wrong in both directions -- booked. The honest sentence:
express is an ABSOLUTE-decompression valve (the only weave whose
centre-hub busiest drops below mesh), not a sensitivity antidote; the
fold is the dominant antidote at 2x; the switch pays N^2 for the same
lever plus node-to-node flatness. New: interconnect.Express;
scripts/analyze_express.py -> express_weave.{json,md} +
express_price_curve.png; group 48 +3 tests. Fast suite: 366 / 0
xfail. The O19 batch's main body (items 1-3 + the optional) is
complete well inside the 9/16 deadline; the two queued-conditional
items' trigger is now met -- awaiting the user's call.

## C63-e (2026-09-09) -- O19 conditional item A: hier_wide (FlooNoC-class)

The registry gains `HierWide(CMesh)`: the cmesh local tier (access
wire + shared gateway port) under a WIDE MULTI-CHANNEL BACKBONE --
FlooNoC's identity is multiple physical channels, so each backbone
segment carries W parallel channels and a flow rides lane = source
node % W (HUB lane 0; deterministic, declared). Degeneration chain
pinned: W=1 == cmesh exactly (modulo the name prefix), +[1,1] ==
mesh. ADDENDUM caught at contract time: item 3 had left CMesh's
router_hops un-overridden (its backbone step is one router over a
tile pitch of wire) -- fixed, and the packet guard now lists cmesh
and hier_wide (five count/length-split schemes). THE FIDELITY
READOUT delivered a third outcome neither pre-written hand named:
at the FlooNoC anchor (80.6 GB/s per channel, declared caliber) every
hier_wide variant TIES the poured-mesh 4.000x numerically, but the
binding resource MIGRATES to the local gateway port at every W --
the backbone's width cannot be consumed on this host (W = 1/2/4
identical; the tie is the host's funnel coincidence, grid 4 ==
gateway 4). The deliverable sentence: the poured-mesh reading was
right numerically and wrong structurally -- the digital control tier
now names where its constraint sits. New: interconnect.HierWide +
CMesh.router_hops; scripts/analyze_hier_wide.py ->
hier_wide.{json,md} + hier_wide_fidelity.png; group 48 +3 tests.
Fast suite: 369 / 0 xfail.

## C63-f (2026-09-09) -- O19 conditional item B: routing knobs; THE BATCH AND O19 CLOSED

Mesh gains two default-byte-neutral params (the full-suite gate ran
green before any readout; a Torus._route signature mismatch the gate
surfaced was fixed in the same edit): `reply: retrace (default) | yx`
and `routing: ... | o1turn` (the declared PARITY stand-in -- the
fractional 50/50 oracle does not fit the one-path-per-flow
interface). The readout closed the occupancy-completeness debt more
decisively than planned, three findings stacked: (1) the PATH
IDENTITY, caught by a pin's first draft -- for hub flows
retrace-of-XY IS the YX path (single-bend dimension order walked
backwards), so the reply knob is path-identical on its whole
hub-flow domain, pinned as equality; (2) the SINK-FUNNEL INVARIANT
-- sink-convergent patterns' busiest wires are conservation-fixed;
every reply variant ties on every pattern and weight, so the
on-record XY/YX asymmetry cannot move any busiest-wire number in
this account (routing algorithms' habitat is the queueing tier,
outside the O26 bound); the pre-written "YX relieves where the up
side binds" hand is REFUTED and pinned; (3) o1turn-parity NEVER
beats plain XY on any tested pattern (all-pairs 12 vs 8, 9 vs 6;
mirror 4 vs 2, 2 vs 1) -- shipped as a condition-enumeration arm
with that warning. New: Mesh reply/o1turn + order plumbing
(Torus._route included); scripts/analyze_routing_params.py ->
routing_params.{json,md} + routing_params.png; group 48 +2 tests.
Fast suite: 371 / 0 xfail. THE O19 BATCH IS CLOSED inside the 9/16
deadline -- items 1-3, the optional, both conditionals; O19 itself
CLOSED: ten schemes in the registry, nothing queued.

## C64-a (2026-09-10) -- the search milestone opens: spec landed, pre-registration, S1 day 1

The founding spec is now repo-resident: analysis/SEARCH_SPEC.en.md --
the revised SYNC_search_v1 with every accepted implementation-layer
amendment integrated in place and marked [AMENDED]: (1) tiler
feasibility everywhere (the O10 lesson; oracle group-size axis = the
tiler-feasible set, possibly sparse); (2) the DP edge-weight direction
statement (adjacent-reference pricing is systematically optimistic on
hand-offs, expected negligible -- day 8 measures the magnitude for
free); (3) constrained mode = rejection with the anti-stranding
guardrail (every multi-start contains a feasible named baseline; an
all-infeasible cell is a RESULT, never a penalty rescue) + the FT
bookkeeping seat; (4) the Delta = T_pess/T_opt column on every results
table from S3 on; (5) seed sets pre-registered, distributions not
single-bests; (6) the collaborator's withdrawal: no interface
hand-off, clustered self-implemented from the literature, S5 RETIRED,
O6 retired with it, the 47% figure PERMANENTLY unpublishable (11%
flat stays). FIXLIST rows and dependency lines updated; .gitignore
whitelists the spec.

S1 day 1: scripts/search_space.py -- Pi = (gamma cuts + segment/stage
views, alpha seat map + hub/attach, beta structural), legal() = the
Placement.verify formalisation with the tiler fold-in (the rejection
message cites O10), feasible_die_counts() (amendment 1's entity),
JSON round-trip, and pi_from_a4_payload() wiring the 544-seat +
16x2-seam payload as the legal standard case. Gates green
(tests/test_search_space.py, group 49, 6 pins): the O10-type
counterexample refused (ffn1 at capacity's 4 vs the tiler's 5), all
pathology cases refused, the feasible set measured sparse. Fast
suite: 377 / 0 xfail. S1 days 2-3 -> C64-b.

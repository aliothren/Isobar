# System-Level CIM Simulator — Features & Results

> On top of **CiMLoop** (Timeloop + Accelergy + CiM extensions), we model the
> company's ReRAM CIM chip as a **system** (package → die → macro → core →
> crossbar, weights resident) rather than a single macro. **The central object is
> placement** (physical position/layout — the level existing on-chip CIM work,
> CiMLoop included, stops short of); the other models (attention K/V write etc.)
> serve to **validate that the composed simulation behaves as expected and to put
> numbers on known intuition**. All changes are **decoupled overlays** — the
> Timeloop core is untouched; uncalibrated parameters are placeholders.
>
> **Reading order**: §0 approach → §1 hardware → §2 denominators (where energy/time
> go; which levels carry a price) → §3 models & results per level → §4 whole-model
> GPT-2 three scenarios → §5 per-pair communication dumps → §6 assumptions &
> limitations → §7 DR data-request map → §8 placeholder params → §9 script index
> → §10 tests.

---

## 0. Approach

**Two distinctions** run through all of it:

1. **Mapping vs placement.** Mapping (how a weight matrix is partitioned,
   bit-sliced, duplicated) is logical, handled by CiMLoop's mapper — we take it as
   given. Placement (which physical crossbar/core/die each mapped block occupies)
   is the level **nobody models**. Resident weights make placement a one-time,
   irreversible decision that fixes every subsequent inference's communication
   distance.
2. **"A level exists" vs "a level is charged."** A hierarchy level can be present
   in the simulator and still be free: traffic counted, energy zero, latency zero.
   Much of this work is locating those places and pricing them.

**Everything falls into four categories** (same vocabulary as the report's
accounted-by columns):

| Category | Content |
|---|---|
| **kept** | the silicon-calibrated macro model: glb, readout/conversion chain, array drivers — untouched |
| **re-priced** | the router distance term (+0.2% of block energy at the current layout, sign pending DR-4); per-crossbar value refinement (≤1.002× on this device, hence not needed) |
| **added** | the K/V write model (energy + serial SET latency) |
| **awaiting data** | DR-1…6 (map in §7) |

**Three main conclusions** (details in §2–§4):

1. **Placement machinery is built at every level and its effects are measured**:
   crossbar position differs 3.62× (v1 real traffic), region placement differs 17.8% (both are
   rankings); the macro level is priced (line vs mesh = 1.52× NoC energy =
   **0.34%** of a block). The unpriced levels (core/crossbar links, D2D) are
   exactly where the leverage should be larger → each gap is one DR.
2. **Where the leverage is, and is not**: ~59% of energy is analog compute +
   conversion, ~39% buffering (glb alone 33%); the macro NoC is 0.99% and the flat
   off-die port 0.69% → **within-die placement is not an energy lever** (and these
   transport shares are **lower bounds** — every unpriced term is a network term);
   the payoff route is **contention (bandwidth) and D2D**.
3. **Validation by composition**: that ReRAM writes are expensive is common
   knowledge (it is why these chips are weight-stationary), not a finding.
   Charging the one write inference cannot avoid (K/V) makes decode come out
   write-latency-bound and offload come out as a throughput win, as expected — with
   numbers: **decode latency 10.12×, write = 90% of the step, offload −93% latency
   / −34% energy**. The qualitative picture needs no calibration; the magnitudes
   move with DR-5.

**CiMLoop default vs our fix** (history):

| Dimension | CiMLoop default | Fix |
|---|---|---|
| Weight residency | streams weights from DRAM | wrong for ReRAM → `ws_chip2chip_link` resident (used to inflate energy ~36%/prefill, ~150×/decode) |
| Physical position | topological, no coordinates | distance overlay (§3.1); measured: moves neither total at today's params, see §2 |
| Attention write | QK^T/AV as plain matmuls | write cost/latency overlay (§3.2); the only material difference source (decode latency 10.12×) |
| Latency | cycles, interconnect infinitely fast | propagation + write latency (§2/§3); bandwidths still unset (DR-2) |
| Value-dependent energy | one distribution per layer | inject per model (§3.3); a synthetic workload once reused resnet's distribution |

---

## 1. Hardware model: package → die → macro → core → crossbar (weights resident)

```
package (ws_chip2chip_link: weights resident, no weight-DRAM streaming)
 └ die × N            N≈18 (4-bit) / 36 (8-bit); GPT-2 resident, 256-die package ample
    └ macro × 8
       └ core × 4
          └ crossbar × 8          = 256 crossbars / die
crossbar = the reused 256×256 4-bit ReRAM macro `wan_nature_2022`
```

- [`models/arch/3_chip/mlx_die.yaml`](../models/arch/3_chip/mlx_die.yaml) — DIE: 8 MB SRAM (`glb`) + 8 macros + inter-macro `router` + 4 cores/macro
- [`models/arch/2_tile/mlx_core.yaml`](../models/arch/2_tile/mlx_core.yaml) — CORE: local I/O buffers + 8 crossbars
- [`scripts/mlx_system.py`](../scripts/mlx_system.py) — hardware config + `LAYOUT`/`HOP_LATENCY_NS` + runners + `n_dies_for_weights()`

**Key: ReRAM weights are resident, not streamed.** Programmed once (SET 8520 ns +
endurance), top level `ws_chip2chip_link` (no weight DRAM; only activations move),
not `fetch_weights_lpddr4`. **The only per-inference write is attention K/V.**

**The instantiated system is a single die**: the top-level `chip2chip_link` has
**instances=1** — a **flat off-die port** charging each op's activation I/O a fixed
64.3 pJ/word (0.69% of op energy), with **no inter-die topology/routing/distance
behind it**. Multi-die workloads = each op costed on its own die and summed;
inter-layer hand-offs unrepresented (→ DR-3).

**Capacity (why multi-die is mandatory)**: GPT-2 medium has **302M** weights; one
die = 8.4 MB = **16.8M** 4-bit weights → **18 (4-bit) / 36 (8-bit) dies** resident;
a single layer (12.6M) fits one die.

---

## 2. Denominators: where energy and time go, and which levels carry a price

Any added cost matters in proportion to the term it lands on, so the denominators
come first.

### 2.1 Energy decomposition (ffn1, prefill, S=512; baseline's current calibration)

| Component | Group | Energy (µJ) | Share |
|---|---|---|---|
| `glb` | buffer (on-die SRAM) | 892 | **33.0%** |
| `integrator` | analog compute | 646 | 23.9% |
| `adc` | conversion | 483 | 17.9% |
| `wordline_cap` | analog compute | 223 | 8.3% |
| `output_buffer` | buffer | 157 | 5.8% |
| `sample` | conversion | 141 | 5.2% |
| `row_drivers` / `cim_unit` | analog compute | 39.1 / 38.7 | 1.4% / 1.4% |
| others (<1% each)† | — | 78.1 | 2.9% |
| **total** | | **2,700** | 100% |

† `router` 0.99% (**on-die macro NoC**; block mean 0.65%, range 0.39–0.99%),
`shift_add` 0.74%, `chip2chip_link` 0.69% (**flat off-die port**), `input_buffer`
0.47%. The two transport components are **distinct things, stated separately** —
never merged as "the on-die network".

> **Under the current calibration, transport is <2% — and a lower bound** (every
> unpriced term is a network term); the expensive part is **staging: glb alone is
> 33%**. Reading protocol: shares are against the currently priced cost → network
> rows read as **lower bounds**, all other rows as **upper bounds**. The table
> excludes the two terms we add: the K/V write (~0.9% of block energy, both
> phases) and the distance re-pricing (+0.2% at the current layout).

### 2.2 Latency composition (share of a block's critical path, scenario A, stall-free)

| Term | Mechanism | prefill | decode | Accounted by |
|---|---|---|---|---|
| Compute | Timeloop cycles × cycle time | 79% | 10% | baseline (kept) |
| Bandwidth stalls | demand > link bandwidth | — | — | **mechanism present but inert**: no limits set, `Bandwidth throttling = 1.00` (DR-2)ᵇ |
| K/V write | serial SET before compute | 21%ᵃ | **90%ᵃ** | added (§3.2) |
| Propagation | hops × ns/hop, round trip | 0.006% | 0.13% | added (§3.1) |
| Inter-die hand-offs | D2D links between layers | — | — | not modeled (DR-3) |

ᵃ Shares of a stall-free critical path; they rest on §3.2's write granularity (a K
append = 64 row-serial SET pulses at the ~8.5 µs placeholder width, no
parallel/incremental programming). A device that programs a column in parallel
collapses these numbers (DR-5).
ᵇ With real limits set, compute can only grow → the write share, the 10.12×, and
the 93% **can only fall**.

**Bandwidth sensitivity (W1; source
[`scripts/analyze_bandwidth_sweep.py`](../scripts/analyze_bandwidth_sweep.py)).**
Contention is modeled in two tiers. They lower-bound the same serialization at
different places, so they enter the critical path by **max, never by sum** (no
double-charging):

| Tier | Mechanism | Owns | Why |
|---|---|---|---|
| **T1** | Timeloop's native throttling (demand > supply → cycles stretch) | **storage hubs** (the glb read/write port) | it models aggregate rates well |
| **T2** | analytic per-link occupancy `volume/bandwidth`, worst link wins | **network links** (router; D2D later) | only we have per-link loads (the structured flows of §5) |

T2's implementation `crossbar_comm.link_occupancy()` is **level-agnostic**: when
D2D lands, die-to-die links feed the same function. With the shipped config no
bandwidth is set anywhere, so the term is identically zero and the system totals
cannot move.

![bandwidth sensitivity](bandwidth_sweep.png)

> **Where the knee is: ffn1's router trunk flips from compute-bound to
> link-bound at ~2.9e4 words/cycle.** That position is **not a placeholder** — it
> follows from the op's real link volume (51.2 M words, v1 structured traffic,
> reconciled against Timeloop's counters), the device cycle time (1.449 µs, from
> CiMLoop's calibrated macro model), and the compute latency. In absolute units
> that is **≈ 20 GB/s** for 8-bit words — **squarely inside the range real on-die
> NoCs occupy**. So DR-2 (per-level link bandwidths) is not a formality: **the
> answer can land on either side of this knee**, and on the left side on-die
> communication becomes prefill's dominant latency term.
>
> **That still would not make DISTANCE matter** (measured, see §2.3): today's T2
> reads per-link volumes only, never distance; permuting macro slots leaves the
> serialization time bit-identical. Bandwidth makes *communication* dominant;
> making *position* dominant additionally needs routed contention (O5).
>
> **Per-phase robustness** (same script): in prefill the first op to flip is
> `av` at ~3.6e4 w/c ≈ **25 GB/s** — inside the range real NoCs occupy, so
> prefill is **at risk**; decode is dominated by the **write** (13.3 ms) and
> communication only catches up at ~166 w/c ≈ **0.11 GB/s**, implausibly slow →
> **decode's 10.12× / 90% / offload 93% hold across the whole plausible band**.
>
> ⚠️ **Regime note**: stalls-on and stalls-off are **different accounting
> regimes**; the multipliers on this curve are placeholder-bandwidth
> sensitivities and **must not be cited as findings** before calibration. Every
> other latency number in this writeup is the stall-free regime. (The earlier
> "75×–1200×" claim had no traceable source and was retracted; this figure is
> its sourced replacement.)

### 2.3 Whether contention follows position is a property of the SCHEME (W2)

Contention is not inherently placement-blind or placement-sensitive; that is a
property of the interconnect scheme, and the scheme is now an input
([`scripts/interconnect.py`](../scripts/interconnect.py) plus `topology:` in the
fabric config):

| Scheme | Shared resource | Contention follows placement? |
|---|---|---|
| **`star`** (private links; the pre-W2 model) | none | ❌ **No — and that is a correct property, not a defect**: a private wire has no segment to contend for. Measured: permuting macro slots 0↔7 leaves the serialization bit-identical |
| **`mesh`** (XY routing) | each grid segment | ✅ yes |
| **`h_tree`** (k-ary tree) | each tree edge; the **root edge is shared by all** | ✅ yes, but through GROUPING rather than distance |

**The mechanism, stated precisely (and pinned by tests)**: under a routed scheme
with *equal* flow volumes, congestion depends only on WHICH SLOTS are occupied —
permuting the logical nodes is provably a no-op. **Placement bites once the
flows differ in volume**: putting the heavy talker on the hub costs nothing,
putting it in a far corner loads the hottest segment. Measured (3×3, mesh, one
node at 4× volume): **3V on the hub vs 6V in the corner**. Real workloads are
heterogeneous, so this is a live mechanism, not a construction.

**A ranking reversal** (hand-derived and reproduced in code — the clearest
evidence the model really distinguishes layouts):

| Layout | heatmap spread (distance) | mesh peak segment (congestion) | total segment load |
|---|---|---|---|
| 3×3 | 3.62× (**worse**) | **3V (better)** | 10V |
| 2×4 | **1.50× (better)** | 4V (**worse**) | 12V |

**The same two layouts rank in opposite orders under the two metrics**: 2×4
spreads distance more evenly but, being elongated, funnels more flows onto one
segment. Uniform is not the same as uncongested — a single metric would give the
opposite recommendation.

### 2.4 The pricing boundary, and which way numbers can move

**The distance overlay can only act on a component with an energy model AND
fanout>1; in the die model only `router` (fanout=8, the macro level) qualifies.**
The core/crossbar-level `inter_*_spatial` carry zero energy in Accelergy, and the
off-die port is distance-blind by construction. Of the four levels data traverses,
**one is priced — and it is the smallest lever**.

**Directionality**: pricing any waiting term enlarges the denominator — the network
share of energy can only **rise**, glb/readout shares only **fall**; on the latency
side real bandwidths only grow compute → the write's 90% of decode, the 10.12×, and
offload's 93% are **ceilings**. The one open sign is the +0.2% distance re-pricing
(DR-4). **Three numbers move under none of this**: the closed-form validation
<0.1% (a volume identity), 3.62× (traffic structure × geometry, no calibrated price involved), and each token's K/V
being programmed exactly once in its lifetime (a structural invariant).

---

## 3. Models & results, level by level

### 3.1 Distance and placement (macro level and below) — the central work

CiMLoop communication = `volume × fixed per-word energy`, position-blind. We overlay
distance:

- [`scripts/placement_aware.py`](../scripts/placement_aware.py) — `perceive →
  placement prior → distance model → re-aggregate`; energy (`position_aware_cost`,
  base = the component's own reported `Energy (total)`) + latency
  (`position_aware_latency`). Priors (`place_grid`/`place_linear`) and patterns
  (`to_center`/`tree`/`all_to_all`/`neighbor`) pluggable; explicit assumption
  `reference_hops` (→ DR-4) cancels in ratios — **relative comparisons are robust**.
- [`scripts/crossbar_comm.py`](../scripts/crossbar_comm.py) — aggregate traffic
  decomposed into **per-pair** (node↔node) flows: a nested floorplan gives each
  crossbar coordinates; multicast/reduction trees yield `(src→dst, volume,
  distance)` + heatmap + geometric `level_max_hops`.

**Macro level (priced; reaches the system totals)**: with 8 macros the geometry is
exact, no simulation needed — to-hub mean hops 1.3125 (near-square mesh) vs 2.0
(line) → **line = 1.52× the macro NoC energy**; full setting sweep 3.00×
(neighbor 1.0 → linear all-to-all 3.0). Times the level's denominator (router =
0.65% of block energy) → **moves the whole block by 0.34%**: placement demonstrably
changes a calibrated cost — and at this level the lever is small.

**Crossbar level (relative map, v1 = 3.62×)**: under the v1 real traffic structure
(`traffic.py`: a multicast slice crosses an upper edge once, idle instances carry
zero, shared volume attributed by share), ffn1 uses the full array and a corner
crossbar costs **3.62×** a central one (the uniform-era 3.58× is retired per the
CHANGELOG). **The structural difference shows on partially-utilized ops**: a small
2×2 matmul really uses only **32/256** crossbars with the idle region at zero —
the uniform model smeared that into a full-array spread. The level still carries
zero energy → a **ranking**, awaiting DR-1; rankings are what a search consumes.

![per-crossbar communication cost heatmap](crossbar_comm_heatmap.png)

**Region level (relative map, 17.8%)**: hardware and mapping fixed, only which
cores each of 6 matmuls occupies changes — dataflow order beats size order by
**17.8%** (volume-weighted all-pair Manhattan; source
[`scripts/analyze_region_locality.py`](../scripts/analyze_region_locality.py),
reusing io_study's deterministic floorplan). **The metric matters**: NN-min reads
31.2% but flatters adjacency (`ffn1→ffn2` scores 1 under both orders while its
volume-weighted mean distance is 3.47 — the equal pair of bars in the figure).

![region locality, volume-weighted](region_locality_vw.png)

**Independent corroboration from the search side**
([`scripts/die_solver.py`](../scripts/die_solver.py), collaborator): the same
claim reached from the **reduction structure** rather than from distance —
keeping each M-block's C-tiles inside one macro drives cross-macro reduction
merges from 4 to **zero**, at a cost of one extra core (27 -> 28 of 32). On-die
reduction energy 0.89 -> 0.79 uJ (flat router) / 1.48 -> 0.79 uJ
(distance-weighted; the latter rests on a component that does not yet exist —
FIXLIST O6).

**With the denominator supplied**
([`scripts/analyze_placement_impact.py`](../scripts/analyze_placement_impact.py)
runs his four matmuls through our full pipeline):

| quantity | value | share of system |
|---|---|---|
| system energy of the 4 matmuls | 1,229.0 uJ | 100% |
| his reduction term (baseline) | 1.482 uJ | 0.121% |
| his saving (distance-weighted = **47% of the term**) | 0.692 uJ | **0.056%** |
| his saving (flat = 11% of the term) | 0.099 uJ | 0.008% |
| CiMLoop's own router energy, same 4 ops | 9.23 uJ | 0.75% |

> **Two conclusions.** (1) **The magnitudes reconcile**: his lambda-1 reduction
> term is **0.161x** CiMLoop's own router charge — he models the *inter-core
> partial-sum subset* of what CiMLoop charges in aggregate, not a competing
> total. (2) **Two independent routes land in the same place**: the on-die
> energy lever is **under 1% in both accountings** (ours 0.34% at the macro
> level, his 0.056% from reduction clustering). This *strengthens* conclusion 2
> of §0 rather than weakening it — **the energy payoff is not within a die; it
> is in contention (DR-2) and D2D (DR-3)**.
>
> (Caveat: the measurement uses our default gpt2_medium histograms on BERT
> shapes, so the value-dependent part carries a few percent of error — not
> enough to move the order-of-magnitude judgement.)

**Propagation latency (all three levels, placement-dependent since A-3)**:
worst-case hops computed from the ACTUAL layout × placeholder ns/hop. Default
layout: 12×5 + 3×2 + 2×1 = **136 ns/op** (the 2×4 variant reads 10/3/2 → 116 ns);
0.006% (prefill) / 0.13% (decode) of block latency. What makes it **matter** is
bandwidth (DR-2): without link limits there is no contention for distance to act
through.

### 3.2 The attention K/V write (crossbar level) — validation + quantification

Expensive ReRAM writes are not news (the µs-scale SET is why these chips are
weight-stationary), but K/V is the write inference **cannot avoid**, and the
baseline maps QK^T/AV as plain weight-stationary matmuls — charging **nothing**.
Modeling it is both a necessity for a system simulator and a **validation target
for the whole composition**: if the system model is right, decode should come out
write-latency-bound and offload should pay in throughput — §4 bears both out.

Model: `write_cells × E_WRITE_PER_CELL_J` (energy) + `write_rows × T_SET_NS`
(latency), both derived from the one **append-only** geometry in `block_ops`
(prefill programs all S tokens; decode appends the new one; rewriting the cache
each step would violate residency and burn endurance in seconds). **Axis
asymmetry**:

| op | weight shape | decode adds a token | write cells | SET pulses |
|---|---|---|---|---|
| `qk^t` | K^T: `dh(rows) × S(cols)` | a new **column** | dh | **dh = 64** (64 wordlines) |
| `av` | V: `S(rows) × dh(cols)` | a new **row** | dh | **1** (one wordline) |

→ decode vs prefill: **write energy ↓512×, write latency only ↓5×** — the direct
reason decode is write-latency-dominated.

**Measured**: whole-model write energy prefill 2.52e-3 J / decode 4.9e-6 J (~0.9%);
write latency prefill **65.4 ms** / decode **13.3 ms** (90% of decode latency).
Energy vs latency view (one block):

![energy view vs latency view](energy_vs_latency.png)

| phase | attention share (energy) | attention share (latency) | write share of block latency |
|---|---|---|---|
| prefill S=512 | 33.7% | 35.6% | 21% |
| decode S=512 | 33.7% | **93.3%** | **90%** |

> **The decode split is the telling one**: attention is 33.7% of energy but 93.3%
> of latency. Energy and latency give opposite verdicts — an energy-only model
> concludes attention is minor in exactly the regime where it owns the critical
> path.

### 3.3 Value-dependent energy (crossbar level)

**Magnitude**: the value-dependent part is ≈ **a quarter of an op's energy**
(measured: realistic vs all-zeros distribution = 24.9%) → getting the distribution
right matters. A synthetic workload once reused resnet's distribution; now
[`scripts/value_stats.py`](../scripts/value_stats.py) injects per simulated model +
op type.

**Per-crossbar spread**
([`scripts/crossbar_value_real.py`](../scripts/crossbar_value_real.py): real
weights + real activations, per-tile re-simulation; two stages to avoid the
torch/timeloop segfault):

![per-crossbar value energy: device x workload](crossbar_value_device_compare.png)

| per-crossbar energy spread | GPT-2 ffn1 (LayerNorm) | resnet18 conv (ReLU-sparse) |
|---|---|---|
| **wan** (bit-serial) | 1.000× | 1.002× |
| **raella** (value-sensitive) | 1.010× | **1.204×** |

1. **Device class is the first-order factor**: bit-serial energy is set by
   precision/ADC steps → per-crossbar ≈ 0; raella-class devices exploit
   value/bit sparsity → real spread.
2. **Input heterogeneity is the workload factor**: sensitive device × CNN
   (ReLU-sparse, 80–91% zeros per block) = 1.204×; LayerNorm-flattened GPT-2 only
   1.010×. Spread varies along contraction row-blocks; **weight distribution barely
   matters (~1%)**.
3. **Whether to model it is a device-class question (DR-6)**; this device
   (bit-serial) does not need it. (Light approximate mode:
   [`crossbar_value.py`](../scripts/crossbar_value.py)
   `value_mode="uniform"|"per_crossbar"`.)

### 3.4 Sequence scaling & KV-cache ([`scripts/llm_workload.py`](../scripts/llm_workload.py))

Six ops scale with **S** and **phase**; each op is a normal die-hierarchy run,
composable with crossbar_stats/comm/placement_aware. Measured (prefill, incl. K/V
write; source [`scripts/analyze_seqlen_kv.py`](../scripts/analyze_seqlen_kv.py)):

| S | 64 | 128 | 256 | 512 | 1024 |
|---|---|---|---|---|---|
| attention energy share | 10.7% | 14.8% | 22.0% | **33.7%** | **49.1%** |
| attention latency share (stall-free) | 52.6% | 46.0% | 43.2% | 35.6% | 38.4% |

Energy share rises monotonically with S²; the latency share is highest at *small* S
(write latency ∝ S until the 256-row cap, while compute keeps growing), the curves
crossing near S≈512.
![attention share vs sequence length](attention_share_vs_seqlen.png)

**KV-cache (a traffic term only when offloaded)**: with attention resident, K/V
live in the arrays and there is **no** "re-read the cache each step" stream; it
appears once attention is offloaded — read ∝ G² (dominant), write ∝ G:
![KV-cache cost vs generation length](kv_cache_vs_genlen.png)
![energy with vs without KV-cache](energy_with_without_kv.png)

---

## 4. GPT-2 system-level three scenarios (whole model, S=512, ×24 layers)

- **(C) baseline** — unmodified CiMLoop, no overlays;
- **(A) full + overlays** — + distance energy/latency + K/V write energy/latency;
- **(B) offload** — only static ops on-chip. C/A execute identically and differ
  only in what is charged; A/B differ in what runs on-chip.

### 4.1 prefill
![system comparison prefill](gpt2_system_comparison_prefill.png)

| Scenario | Energy | Latency |
|---|---|---|
| (C) baseline | 0.284 J | 0.249 s |
| (A) full + overlays | 0.288 J (**1.01×**) | 0.315 s (**1.26×**) |
| (B) offload attention | 0.191 J | 0.203 s |

A−C latency = 0.0655 s, **exactly the 65.4 ms write latency**; offload (A→B) saves
34% energy, 36% latency.

### 4.2 decode (one generation step)
![system comparison decode](gpt2_system_comparison_decode.png)

| Scenario | Energy | Latency |
|---|---|---|
| (C) baseline | 5.60e-4 J | 1.46 ms |
| (A) full + overlays | 5.66e-4 J (**1.01×**) | **14.8 ms (10.12×)** |
| (B) offload attention | 3.75e-4 J | 0.987 ms |

A−C = 13.3 ms, exactly the write latency; **offload saves 93% latency / 34%
energy** — a throughput argument.

### 4.3 Attribution per level (read every result with its level and denominator)

| Level | Metric | Measured ratio | That level's share | Status |
|---|---|---|---|---|
| **crossbar — K/V write** | SET pulses×T_SET; cells×E_write | **decode latency 10.12×** | write = **90%** of decode latency (0.9% of energy) | measured, **in the totals** |
| **macro (×8) — comm energy** | router energy × hops/ref | mesh→line **1.52×**; setting sweep 3.00× | router = **0.65%** of block → **0.34%** block effect | measured, **in the totals** (A/B/C use grid+to_center) |
| macro/core/crossbar — propagation | actual-layout max_hops × ns/hop | default 136 ns/op, **placement-dependent** (A-3) | 0.006% / 0.13% of block latency | wired |
| crossbar (256/die) — relative map | v1 real traffic × Manhattan | **3.62×** (idle-zeroing on partially-used ops) | that level's energy is 0; nothing to scale | measured, **not in the totals** |
| region (6 matmuls) — relative map | volume-weighted all-pair Manhattan | **17.8%** (BERT) | same | measured, **not in the totals** |
| core/crossbar link energy | — | — | **0%** (`inter_*_spatial` zero-energy) | **not modeled → DR-1** |
| bandwidth / contention | — | — | `throttling = 1.00`: no stall representable | **not modeled → DR-2** |
| inter-die (D2D) | — | — | instances=1 flat port (0.69%); no topology | **not modeled → DR-3** |

> - The qualitative picture (decode write-bound, offload = throughput win) needs no
>   calibration; **the magnitudes (10.12×/90%/93%) are set by the write-granularity
>   assumptions and move with DR-5** (and are ceilings — §2.3 directionality).
> - Judge offload by **A vs B** (B vs C is apples-to-oranges); B counts only what
>   stays on-chip, not the receiving unit.

### 4.4 Where to see the searched mappings
Every op goes through the Timeloop mapper (`models/include/mapper.yaml`: EDP,
`random_pruned`, 10k-mapping cap, stop after 100 without improvement,
single-threaded/reproducible). Best mappings in
`gpt2_system_mappings_{prefill,decode}.txt`.

---

## 5. Per-pair communication dumps (auto-saved on every run)

Every `run_op` saves `analysis/comm/<op>_<phase>_comm.{csv,json}`: aggregate bus
volumes decomposed into every `crossbar↔core↔macro↔glb` link's volume + physical
distance. Three-level tree `glb → 8 macros → 32 cores → 256 crossbars` → **296
edges** per op.

**CSV** (one link per row; example `qk^t` prefill):
```
level,           src,   dst,     volume_words, distance_hops, volume_x_distance
glb<->macro,     glb,   macro2,  28835840,     12.0,          346030080   <- far-corner macro
glb<->macro,     glb,   macro4,  28835840,     1.5,           43253760    <- near-center
macro<->core,    macro0,core0.0, 7208960,      3.0,           21626880
core<->crossbar, core0.0,xb4,    901120,       0.25,          225280
```
**JSON**: hierarchy shape + all flows + per-crossbar cost + spread summary
(`max_over_min: 3.58`; cheapest `id=132@(7,7)` near-center, priciest `id=66@(14,0)`
far corner).

**Three takeaways (v1 structured)**: ① ffn1 position spread 3.62× (plus the
idle-zeroing effect on partially-utilized ops); ② `volume×distance` still
concentrates at the top, now on real volumes: `glb↔macro` **60%**, `macro↔core`
24%, `core↔crossbar` 16% (the v0 65/25/10 rested on a 32× multicast overcount of
the input trunk; ffn1 is output-dominated and outputs don't multicast, so the
top-level conclusion survives the correction); ③ prefill is on-die-traffic-heavy,
decode communication is tiny overall; inter-die activations are far below on-die
volumes — not a bottleneck:

| Interconnect (model total, words) | prefill | decode |
|---|---|---|
| router (macro NoC) | 13.1 G | 25.7 M |
| glb (on-die SRAM) | 8.25 G | 16.1 M |
| chip2chip (off-die port) | 5.03 G | 9.83 M |
| inter-die activations (logical) | 12.1 M | 23.5 K |

---

## 6. Assumptions & limitations

1. **Per-op search, no cross-layer/cross-die co-optimization**: each op is
   EDP-searched independently then aggregated; layer→die placement is assumed, not
   searched; no inter-layer fusion/global schedule.
2. **One layer/die, no packing**: each op uses one die's 256 crossbars
   (`chip_in_system.meshX=1`); ffn1 uses ~26% of a die, the rest idles → 24 dies is
   conservative; capacity packing would need ~6–8.
3. **Oversized layers unhandled**: a layer > 1 die needs `meshX>1` (arch supports
   it; never run). GPT-2 medium never triggers it.
4. **Energy position-awareness stops at the macro level** (DR-1); propagation
   latency is placement-dependent since A-3.
5. **Write model**: one SET pulse per row, no write-verify — both scale decode
   latency directly (DR-5).
6. **Placeholder magnitudes**: distance absolute scale, per-hop latencies, write
   energy, off-die port cost — all uncalibrated. Ratios robust; absolutes not.
7. **Value-distribution granularity**: one distribution per layer; per-crossbar
   spread verified to be a device-class question (§3.3, DR-6).
8. **Offload accounting**: B counts only what stays on-chip (§4).

**Relaxation route**: ① capacity packing → ② oversized layers across dies
(`meshX>1`).

---

## 7. DR data-request map (each → which numbers move, and which way)

| DR | Data requested | Numbers it moves | Direction |
|---|---|---|---|
| **DR-1** | per-hop/per-word energy of core- and crossbar-level links | network energy share; the 3.58× map and the 17.8% | network share ↑; rankings become joules |
| **DR-2** | link bandwidths at each level | compute latency; write share, 10.12×, 93% | compute ↑, the rest ↓; latency becomes placement-sensitive. **The knee is now located at ~20 GB/s per macro link (§2.2) and real NoCs can sit on either side — this request is decisive, not a formality** |
| **DR-3** | D2D topology/routing/latency/bandwidth/energy | network energy share; whole-package placement spread | network share ↑; unlocks the go/no-go experiment |
| **DR-4** | what the router's calibrated per-word energy represents: one hop or an average multi-hop transfer | the router term; the **sign** of the +0.2% re-pricing | resolves the one open sign |
| **DR-5** | SET pulse width, cells programmable in parallel, incremental programming, write-verify, endurance | the write term: 21%, 90%, 10.12×, 93% | **these stand or fall with it** |
| **DR-6** | device class (precision- vs value/sparsity-driven) + ADC calibration point | whether per-crossbar value modeling is needed | gates the refinement (§3.3) |

**Why DR-4**: the router's calibrated vector-access energy is 48.3 pJ vs the glb's
3.3e4 pJ ≈ **1:680** — it likely represents a single short hop rather than an
average multi-hop transfer. Until settled, the network share is uncertain in one
direction only: **toward underestimation**.

---

## 8. Placeholder parameters (awaiting company data)

| Parameter | Placeholder | Source | Affects | DR |
|---|---|---|---|---|
| `E_WRITE_PER_CELL_J` | 1.0e-10 J | wan SET ~100 pJ | write energy | DR-5 |
| `T_SET_NS` | 8520 ns | wan SET pulse | write latency (the bottleneck) | DR-5 |
| `E_DRAM_PER_WORD_J` | 5.0e-11 J | typical DRAM | KV-cache energy | — |
| `HOP_LATENCY_NS` | 1–5 ns/hop | placeholder | on-die propagation | rel. DR-2 |
| `DIE_HOP_LATENCY_NS` | 20 ns/hop | placeholder | inter-die latency | DR-3 |
| per-level `bandwidth` (T2 links / T1 hubs) | unset (= unlimited) | — | stalls; knee at ~2.9e4 w/c ≈ 20 GB/s (§2.2) | DR-2 |
| `reference_hops` | 1.0 | placeholder | distance-energy scale/sign | DR-4 |
| histogram source | `gpt2_medium` | real workload | value energy | DR-6 |
| weight bits / layer→die | 4-bit / 1 layer per die | placeholder | die count, inter-die volume | — |

---

## 9. Script index

| Script | Purpose |
|---|---|
| `fabric.py` + `models/fabric/*.yaml` | physical fabric config (single source of truth; `CIMSIM_FABRIC` picks variants) |
| `placement.py` | explicit Placement (per-level slot tables + verify + JSON; `sequential_fill` reproduces the legacy floorplan bit for bit) |
| `interconnect.py` | interconnect scheme registry: `star`/`mesh`/`h_tree`, selected per level by `topology:` in the fabric config (§2.3) |
| `traffic.py` | real traffic structure (multicast trunks once, idle zeroed, divisibility guard against Timeloop counters) |
| `make_figures.py` | one driver for every figure (7 stages; `--tag` for config variants without clobbering canonical) |
| `mlx_system.py` | hardware config (resident die hierarchy) + LAYOUT + runners + `n_dies_for_weights` |
| `placement_aware.py` | distance overlay: energy (`position_aware_cost`) + latency (`position_aware_latency`) |
| `crossbar_stats.py` | per-crossbar stats + communication structure + `hierarchy()` |
| `crossbar_comm.py` | per-pair flows + heatmap + geometric hops + `save_flows()` (auto-dump) |
| `llm_workload.py` | sequence scaling + write cost/latency + KV-cache + die-to-die + histogram injection |
| `value_stats.py` | general value-histogram loader (per model / layer type) |
| `crossbar_value.py` | fast per-crossbar value approximation (uniform / per_crossbar) |
| `crossbar_value_real.py` | real per-crossbar value pipeline (real weights+activations, per-tile re-sim; two stages) |
| `analyze_system_gpt2.py` | whole GPT-2 three-scenario comparison, `[S] [phase]` (§4) |
| `analyze_energy_vs_latency.py` | energy-vs-latency view (§3.2) |
| `analyze_seqlen_kv.py` | sequence-scaling + KV-cache figures (§3.4) |
| `analyze_region_locality.py` | region-placement comparison + 17.8% (compute on host / plot in container, §3.1) |
| `analyze_position_aware.py` | placement × pattern sweep (resnet18) |
| `analyze_crossbar_value_compare.py` | device×workload 2×2 per-crossbar energy figure (§3.3) |
| `analyze_bandwidth_sweep.py` | two-tier contention bandwidth sensitivity sweep (§2.2) |
| **search side** (collaborator) | |
| `die_solver.py` | reduction-clustered placement solver: lambda-1 hierarchical metric + two placers (see §3.1 note) |
| `placement_sim_compare.py` | encodes a placement as average hops for the simulator ⚠️ **cannot run today**, see FIXLIST O6 |
| `analyze_placement_impact.py` | supplies the system-level denominator for the solver's saving |

```python
from scripts import llm_workload as lw
res = lw.run_block(lw.GptConfig(), S=512, phase="prefill")   # or "decode"
lw.report_block(res, title="prefill S=512")                  # energy + latency tables
```
```bash
python3 scripts/analyze_system_gpt2.py 512 prefill    # whole-model system level (or: 512 decode)
```

---

## 10. Tests (`workspace/tests/`)

```bash
python3 tests/run_tests.py           # fast suite, a few seconds (in the container)
python3 tests/run_tests.py --slow    # plus one real end-to-end mapper run, ~2 min
```

These tests do **not** check whether the model matches reality (that waits for
calibration data). They check three more basic things:

1. **We read the simulator's output correctly**: every component energy that
   `perceive` extracts from a frozen stats file matches an independent
   line-by-line extraction of the same file, and the components sum to the op
   total. This pins the July unit-mismatch bug (a dedicated tripwire: the value
   the buggy formula would produce must stay far above the true one; if they
   ever get close, the reconstruction crept back in).
2. **The code computes what the docs say**: the write geometry (prefill programs
   all S tokens, decode appends exactly 1; K touches 64 wordlines, V touches 1),
   the distance geometry (1.3125 / 2.0), and "ratios don't depend on
   reference_hops" are all checked against **hand-derived formulas** — no
   simulation involved.
3. **Nothing changed silently**: today's outputs (e.g. the 2x2 example's 3.579x
   position spread) are frozen as golden files; any code change that moves them
   trips the test. Goldens are versioned (`_v0` = uniform-traffic model); when
   the traffic structure upgrade lands, re-baselining to `_v1` with a changelog
   entry is the normal procedure, not a failure.

The six system-level totals (a ~45-min run) are not in the automatic suite;
they go through `tests/compare_baseline.py`, which diffs a fresh
`gpt2_system_totals_*.json` against the frozen `system_golden_v0.json` (the
acceptance gate for re-plumbing work; model upgrades re-freeze with
`--freeze v1` plus a changelog entry).

There are also 3 **xfail** (expected-fail) tests — the known-gap list: lower
levels carry no energy model (DR-1), propagation latency does not vary with
placement, and D2D does not exist. Each turns green when its gap is closed;
promote it to a must-pass test at that moment.

Note: all-green does **not** mean physically correct. It only guarantees "the
code equals the documented model"; whether the model is right waits for the
calibration chain (public silicon data + company parameters). The one place in
the repo where two independent derivations confirm each other is the <0.1%
closed-form validation of the I/O model.

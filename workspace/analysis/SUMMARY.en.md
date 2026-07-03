# System-Level CIM Simulator — Feature Overview

> On top of **CiMLoop** (Timeloop + Accelergy + CiM extensions), we add the
> system-level factors it abstracts away, for the company's ReRAM CIM chip:
> **resident multi-die hierarchy, placement/topology-aware cost, crossbar-level
> analysis, LLM workload (sequence scaling + attention K/V write + KV-cache),
> latency modeling, and value-dependent energy correction**. Most additions are
> **decoupled overlays** that do not touch the Timeloop core; uncalibrated numbers
> are placeholders.
>
> **Reading order:** §0 motivation → §1–5 feature modules → §6–7 whole-GPT-2
> results + communication stats → §8 modeling assumptions & limitations →
> §9–10 reference (parameter table / script index).

---

## 0. The gaps we close

| Dimension | CiMLoop default | Consequence / our fix |
|---|---|---|
| **Physical position** | Topological, no coordinates/distance | Near/far layouts cost the same → distance overlay (§2) |
| **Latency / time** | Only cycles, interconnect assumed infinitely fast | System latency under-counted → latency modeling (§5) |
| **Attention write** | QK^T/AV as plain matmuls | Ignores writing K/V every inference → write cost/latency (§4.2/§5) |
| **Weight residency** | Streams weights from DRAM by default | Wrong for ReRAM (non-volatile, resident) → resident multi-die (§1) |
| **Value-dependent energy** | Uses that layer's `histograms` | Synthetic workload once reused another layer's dist. → inject per model (§4.5) |

---

## 1. Hardware model: package → die → macro → core → crossbar (weights resident)

```
package (ws_chip2chip_link: die-to-die link, weights resident, no weight-DRAM streaming)
 └ die × N            N≈18 (4-bit) / 36 (8-bit); GPT-2 resident, 256-die package has ample room
    └ macro × 8
       └ core × 4
          └ crossbar × 8          = 256 crossbars / die
crossbar = the reused 256×256 4-bit ReRAM macro `wan_nature_2022`
```

- [`models/arch/3_chip/mlx_die.yaml`](../models/arch/3_chip/mlx_die.yaml) — die: 8 MB SRAM (`glb`) + 8 macros + inter-macro `router` + 4 cores/macro
- [`models/arch/2_tile/mlx_core.yaml`](../models/arch/2_tile/mlx_core.yaml) — core: local I/O buffer + 8 crossbars
- [`scripts/mlx_system.py`](../scripts/mlx_system.py) — hardware config + `LAYOUT`/`HOP_LATENCY_NS` + runners + `n_dies_for_weights()`

**Key: ReRAM weights are RESIDENT, not streamed.** ReRAM is non-volatile /
weight-stationary: weights are **programmed once and stay**, and are not rewritten
during inference (SET = 8520 ns + endurance limits). The top level is
`ws_chip2chip_link` (**no weight DRAM, only activations flow die-to-die**), not
`fetch_weights_lpddr4` (which re-streams weights every inference — an SRAM-CiM
assumption, wrong for ReRAM; it inflated energy ~36%/prefill, ~150×/decode). The
**only per-inference writes are attention K/V**.

**Capacity (why multiple dies are required):** GPT-2 medium has **302M** weights;
one die = 8.4 MB = **16.8M 4-bit weights** → needs **18 (4-bit) / 36 (8-bit) dies
resident**; a single layer (12.6M) fits on one die.

---

## 2. Placement / topology-aware cost (energy)

CiMLoop communication = `volume × fixed per-word energy`, **position-invariant**.
We overlay distance:

- [`scripts/placement_aware.py`](../scripts/placement_aware.py) — `perceive →
  placement prior → distance model → re-aggregate`. Priors (`place_grid`/
  `place_linear`) and patterns (`to_center`/`tree`/`all_to_all`/`neighbor`) are
  pluggable. Key explicit assumption is `reference_hops`; **relative** comparisons
  are robust, absolute values depend on it. Distance acts only on interconnect,
  never compute/storage.
- [`scripts/crossbar_comm.py`](../scripts/crossbar_comm.py) — decomposes aggregate
  traffic into **per-pair** (node↔node) flows: a nested floorplan gives each
  crossbar coordinates, and walking the multicast/reduction tree yields
  `(src→dst, volume, distance)`, giving **per-crossbar cost that varies by
  position** + a heatmap.

**Result** — same volume, cost varies ~**3.58×** by position:

![per-crossbar communication cost heatmap](crossbar_comm_heatmap.png)

---

## 3. Crossbar-level statistics

- [`scripts/crossbar_stats.py`](../scripts/crossbar_stats.py) — per-crossbar
  compute/weight/input/output (average), per-level bus traffic, and the
  communication STRUCTURE parsed from the mapping (multicast/reduction/bit-slice).
  Per-pair flows use it as input.

---

## 4. LLM workload modeling

[`scripts/llm_workload.py`](../scripts/llm_workload.py) generates the 6 ops of a
GPT transformer block, with shapes scaled by **S** and **phase**; each op is still
a normal die-hierarchy run, so it composes with crossbar_stats/crossbar_comm/
placement_aware.

### 4.1 Sequence-length scaling
attention (QK^T/AV) ∝ S², FFN/projections ∝ S → attention is no longer artificially small.
![attention share vs sequence length](attention_share_vs_seqlen.png)

### 4.2 Attention write cost (energy)
QK^T/AV are activation×activation → K/V must be **programmed into ReRAM** every
inference, not amortized. Overlay `write_cells × E_WRITE_PER_CELL_J`.

### 4.3 KV-cache (decode)
Each step reads the whole KV-cache: read ∝ G² (dominant), write ∝ G.
![KV-cache cost vs generation length](kv_cache_vs_genlen.png)
![energy with vs without KV-cache](energy_with_without_kv.png)

### 4.4 Static vs dynamic (offload)
ReRAM is weight-stationary — good for static weights (FFN/projections); dynamic
attention is the offload candidate.
![GPT-2 static vs dynamic offload](gpt2_static_vs_dynamic.png)

### 4.5 Value-dependent energy correction + per-crossbar mode
CiMLoop energy is **data-value-dependent**: each layer's `histograms` set the ReRAM
analog current / ADC / cell conduction → energy. The synthetic workload once reused
ResNet's distribution; now [`scripts/value_stats.py`](../scripts/value_stats.py)
**injects per simulated model + op type** (change model → change `hist_source`).

**Per-crossbar mode** ([`scripts/crossbar_value.py`](../scripts/crossbar_value.py),
`run_op(value_mode=...)`):
- `"uniform"` (default) = one distribution for the whole op, every crossbar
  identical (current behavior, exact);
- `"per_crossbar"` = **each crossbar uses its own tile's distribution** → its own
  value-dependent energy.

Measured split: energy = **floor (fixed, 75%) + value part (distribution-dependent,
25%)** (the floor is calibrated by running an all-zero distribution). Per crossbar we
scale only the value part, **total conserved**:
```
E_i = E_floor/N + (E_value/N) × (activity_i / mean_activity)
```
The per-crossbar distribution source is pluggable: `uniform` / `synthetic`
(placeholder, tile-to-tile magnitude spread) / `weights` (interface ready, pending
real weight-tensor tiling). Demo (ffn1, synthetic spread=0.5): total conserved but
**per-crossbar energy spreads 1.28×**:

![per-crossbar value-dependent energy heatmap](crossbar_value_heatmap.png)

---

## 5. Latency modeling

Latency structure ≠ energy: energy **sums**, latency is a **critical path** (max over
parallel, sum over serial). Three parts:

| Part | Source | Mechanism |
|---|---|---|
| compute + bandwidth stall + IO | Timeloop native cycles | insufficient bandwidth → stall → cycles↑ (`bandwidth_limiter` is this knob) |
| distance propagation latency | overlay `position_aware_latency` | `hops × hop_latency_ns`, serial across phases, max over parallel |
| ReRAM write latency | overlay `write_latency_s` | SET 8520 ns row-serial, before compute; prefill programs the whole C, decode 1 row/step |

**Bandwidth experiment:** give the router a finite bandwidth → latency balloons
linearly with `1/bandwidth` (75×–1200× at placeholder values) → **latency is
dominated by the bottleneck bandwidth; the default "infinitely fast" interconnect =
systematic under-count**.

**Energy vs latency view** (single block):
![energy view vs latency view](energy_vs_latency.png)

| phase | attention share (energy) | attention share (latency) | write latency of block |
|---|---|---|---|
| prefill S=512 | 33.7% | **35.6%** | 21% |
| decode S=512 | **87.8%** | 47.8% | 22% |

> In prefill, FFN/projections are still the single largest component (energy 66%) —
> at S=512 the transformer is FFN-heavy, which is normal; the chart is about the
> attention share + the red write block. **Decode is the opposite: with weights
> resident, compute collapses and attention K/V write is 82% of energy**, FFN only
> 12% (consistent with §6.2).

---

## 6. GPT-2 system-level search (whole-model three-way comparison, resident multi-die)

The whole GPT-2 (gpt2-medium, 24 layers) runs on the resident multi-die hierarchy,
three scenarios:

- **(C) baseline** — raw CiMLoop, no overlays;
- **(A) full + overlays** — + position-aware comm + distance latency + ReRAM write energy & latency;
- **(B) offload** — only static ops on chip, dynamic attention offloaded.

### 6.1 prefill (S=512, ×24 layers)
![system comparison prefill](gpt2_system_comparison_prefill.png)

| Scenario | Energy | Latency |
|---|---|---|
| (C) baseline CiMLoop | 0.284 J | 0.249 s |
| (A) full + overlays | **0.485 J** (1.71×) | **0.315 s** (1.26×) |
| (B) offload attention | 0.324 J | 0.203 s |

Overlays reveal (A vs C): energy +71%, latency +26%; offload benefit (A vs B):
saves **33% energy, 36% latency**.

### 6.2 decode (S=512, ×24 layers, single generation step)
![system comparison decode](gpt2_system_comparison_decode.png)

| Scenario | Energy | Latency |
|---|---|---|
| (C) baseline CiMLoop | 5.60e-4 J | 1.46 ms |
| (A) full + overlays | **3.46e-3 J** (6.19×) | **1.89 ms** (1.29×) |
| (B) offload attention | 6.35e-4 J | 0.987 ms |

With weights resident, decode compute energy is tiny, so **ReRAM write (K/V) becomes
the absolute dominant term** (A/C energy 6.19×, the red block); **offload saves 82%
energy, 48% latency**.

### 6.3 Conclusions
> - **The residency fix rewrites the decode picture**: the old "decode is DRAM-bound"
>   was a **streaming artifact**; with residency, decode compute collapses to ~0.56 mJ
>   and **attention K/V write dominates**.
> - **Energy under-counts attention; latency (especially decode) is write-dominated.**
>   Judge offload by **A vs B** (B vs C is apples-to-oranges).
> - **For generation-heavy decode, offloading attention saves a lot (energy −82%,
>   latency −48%).**

### 6.4 Where to see the mapping-search result
Every op goes through the Timeloop **mapper search** (config `models/include/mapper.yaml`:
objective **EDP**, `random_pruned`, up to **10,000** valid mappings per op, stop after
100 with no improvement, single-thread reproducible). **The chosen best mapping is in
`gpt2_system_mappings_{prefill,decode}.txt`** — each op's loop nest (how P/C/M are
tiled and spread over package→die→macro→core→crossbar→columns/rows, `Spatial-X/Y` =
spatial parallelism) is the search's output.

---

## 7. Per-pair communication stats files (auto-saved every run) + analysis

Every `run_op` auto-saves `analysis/comm/<op>_<phase>_comm.{csv,json}`, decomposing
aggregate bus traffic into **every `crossbar↔core↔macro↔glb` link**'s volume +
physical distance.

### 7.1 File contents and example
Down/up is a **three-level tree**: `glb → 8 macros → 32 cores → 256 crossbars`, so
each op has **296 edges** = 8+32+256.

**CSV** (one line per link, example `qk^t` prefill):
```
level,           src,   dst,     volume_words, distance_hops, volume_x_distance
glb<->macro,     glb,   macro2,  28835840,     12.0,          346030080   ← far-corner macro
glb<->macro,     glb,   macro4,  28835840,     1.5,           43253760    ← near-center macro
macro<->core,    macro0,core0.0, 7208960,      3.0,           21626880
core<->crossbar, core0.0,xb4,    901120,       0.25,          225280
```
**JSON**: hierarchy shape + all flows + **per-crossbar cost** (id/coord/cost) +
position-spread summary (`per_crossbar_cost: {min: 4.28e6, max: 1.53e7,
max_over_min: 3.58}`; cheapest `id=132@(7,7)` near center, most expensive
`id=66@(14,0)` far corner).

### 7.2 Three key findings
1. **Position spread 3.58×**: same volume, corner crossbars cost 3.58× the center
   (the crossbar-aware core effect).
2. **Distance-weighted cost concentrates at the top level**: volume is conserved per
   level (ffn1: 637M words each), but `volume×distance` is **~65%** at `glb↔macro`,
   ~25% at `macro↔core`, ~10% at `core↔crossbar` → **distance-reduction gains are
   mainly at the top `glb↔macro` interconnect**.
3. **prefill is on-die-NoC-dominated; decode communication is tiny overall** (no
   weight traffic once resident); die-to-die activation is far below on-die traffic
   and is **not the bottleneck**:

| Interconnect (model total) | prefill (all ops) | decode (all ops) |
|---|---|---|
| router (on-die NoC) | 13.1 G | 25.7 M |
| glb (on-die SRAM) | 8.25 G | 16.1 M |
| chip2chip (die-to-die, native) | 5.03 G | 9.83 M |
| die-to-die activation (logical, inter-layer hidden state) | 12.1 M | 23.5 K |

---

## 8. Modeling assumptions & limitations (know these before calibration)

The current simulation is **per-op search + 1 layer/die without packing + one weight
distribution per op type** — three clear placeholder simplifications:

1. **Per-op search, not cross-layer/cross-die joint.** Each op is EDP-searched to
   optimum independently, then aggregated; **the layer→die placement is our
   assumption, not searched.** Timeloop does no layer fusion / global schedule.

2. **1 layer/die, leftover capacity unused.** Each op uses only one die's 256
   crossbars (`chip_in_system.meshX=1`); ffn1 weights fill ~26% of a die, and the
   **rest is idle — we do not pack the next layer in.** → die count = `n_layers=24`,
   **conservative (over-provisioned)**; real capacity packing (~4 layers/die) needs
   only ~6–8 dies.

3. **Oversized layers not handled.** If a layer > 1 die (larger model / higher
   bit-width) the current setup is insufficient; set `chip_in_system.meshX > 1` to
   spread one op spatially across dies (arch supports it, not yet exercised). Every
   GPT-2 medium layer fits, so this is untriggered.

4. **Value-dependent distribution granularity:**
   - **across layers**: one averaged distribution each for static/dynamic (all 24
     layers' static ops share one);
   - **across crossbars within a layer**: `value_mode="uniform"` (default) is
     uniform → per-crossbar energy is symmetric; `value_mode="per_crossbar"` (§4.5,
     **implemented**) scales each crossbar's value part by its own distribution → a
     per-crossbar spread, **but the distribution is currently a synthetic placeholder**;
   - to add: tile a real weight tensor per the mapping → a histogram per 256×256 tile
     (`source="weights"`, interface ready), which makes the per-crossbar spread real.

5. **Topology / bit-width / hop costs are all placeholders** (see §9), pending company
   parameters.

**Relaxation roadmap (by value):** ① per-crossbar distribution — **mode already
implemented (§4.5)**, only needs `source` wired to a real weight tensor → ② capacity
packing (realistic die count) → ③ oversized layers across dies (`meshX>1`).

---

## 9. Placeholder parameters (pending company calibration)

| Parameter | Placeholder | Origin | Affects |
|---|---|---|---|
| `E_WRITE_PER_CELL_J` | 1.0e-10 J | wan SET ~100pJ | attention write energy |
| `T_SET_NS` | 8520 ns | wan SET pulse | attention write latency (bottleneck) |
| `E_DRAM_PER_WORD_J` | 5.0e-11 J | typical DRAM | KV-cache energy |
| `HOP_LATENCY_NS` | 1–5 ns/hop | placeholder | on-die distance latency |
| `DIE_HOP_LATENCY_NS` | 20 ns/hop | placeholder | die-to-die latency |
| per-level `bandwidth` | placeholder | — | compute/IO latency (very sensitive) |
| `reference_hops` | 1.0 | placeholder | distance-energy absolute value |
| histogram source | `gpt2_medium` | real workload | value-dependent energy |
| weight bit-width / layer→die | 4-bit / 1 layer per die | placeholder | die count, die-to-die volume |

---

## 10. Script index

| Script | Purpose |
|---|---|
| `mlx_system.py` | hardware config (resident multi-die) + LAYOUT + runners + `n_dies_for_weights` |
| `placement_aware.py` | distance overlay: energy (`position_aware_cost`) + latency (`position_aware_latency`) |
| `crossbar_stats.py` | per-crossbar stats + communication structure + `hierarchy()` |
| `crossbar_comm.py` | per-pair flows + heatmap + geometry hops + `save_flows()` (auto-dump) |
| `llm_workload.py` | sequence scaling + write cost/latency + KV-cache + die-to-die + histogram injection |
| `value_stats.py` | general value-histogram loader (by model / layer type) |
| `crossbar_value.py` | per-crossbar value-dependent energy mode (uniform / per_crossbar) |
| `analyze_gpt2_offload.py` | GPT-2 static/dynamic offload analysis |
| `analyze_energy_vs_latency.py` | energy vs latency view chart |
| `analyze_system_gpt2.py` | whole GPT-2 system-level three-way comparison, args `[S] [phase]` |
| `analyze_crossbar_value.py` | per-crossbar energy demo (uniform vs per_crossbar) + heatmap |

```python
from scripts import llm_workload as lw
res = lw.run_block(lw.GptConfig(), S=512, phase="prefill")   # or "decode"
lw.report_block(res, title="prefill S=512")                  # energy + latency tables
```
```bash
python3 scripts/analyze_system_gpt2.py 512 prefill    # whole-model system-level (or 512 decode)
```

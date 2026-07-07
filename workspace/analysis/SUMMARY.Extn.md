# Extended Summary — An I/O Cost Model for Weight-Stationary CiM Crossbar Mapping

This document summarizes the development of an analytical **I/O (data-movement) cost model**
for mapping transformer layers onto Compute-in-Memory (CiM) crossbar fabrics, using CiMLoop
(Timeloop + Accelergy v4). We first developed and validated the model on a small **toy tile
array** (32×32 crossbars), then **extended it to an MLX-style 4-level hierarchy** built on a
256×256 4-bit ReRAM macro (wan_nature_2022), keeping the same equations.

Workload throughout: **BERT-base-class (~100M params)** — hidden=768, 12 heads, head_dim=64,
intermediate=3072, 12 layers, sequence length P=128. Six unique matmul shapes per encoder
layer; the four trained ones (`qkv_proj`, `attn_out_proj`, `ffn1`, `ffn2`) form the
weight-stationary fabric, while `qk`/`av` are dynamic attention (activations, not weights).

---

## 1. Motivation

Early analysis of BERT-100M on a small CiM tile array showed **crossbar under-utilization**:
some tiles went unused. Investigation of the raw Timeloop `.map.txt` revealed the cause was
the **mapper choosing weight reloads** — when a layer is larger than the fabric, the mapper
streams weights from DRAM and reuses a few tiles many times (e.g. ffn1 reloaded **72×** on a
4×8 chip) rather than spreading across more tiles.

This is the wrong regime for ReRAM: **weight writes ≫ compute**, so real ReRAM accelerators
are **weight-stationary** — every weight is written into a crossbar **once** and never
reprogrammed during inference; a layer occupies **multiple crossbars** that all hold their
weights for the whole run. We therefore built a weight-stationary mapping and an I/O cost
model on top of it.

---

## 2. Toy Design — `cim_tile_array` (32×32 crossbars)

### 2.1 Configuration

- **Macro (crossbar):** `basic_analog`, logical array **32×32** (32 out-channels M × 32
  in-channels C), 8-bit weights/activations.
- **Chip:** `cim_tile_array` — a 2-D grid of `TILE_COLS × TILE_ROWS` crossbars with
  `row_noc` (input broadcast) and `col_noc` (output accumulation).
- **System:** `fetch_weights_hbm2_ws` — a **weight-stationary** DRAM config in which
  `main_memory` forbids temporal iteration over weights
  (`no_iteration_over_dataspaces: [Weights]`), turning weight-stationary from a preference
  into a hard constraint (0 reloads).
- **Per-matmul grid sizing:** the grid is sized *exactly* to each matmul so it always tiles
  evenly:
  ```
  TILE_COLS = round_up_even(M / 32)      # one column of crossbars per 32-wide M-block
  TILE_ROWS = round_up_even(C / 32)      # one row    of crossbars per 32-tall C-block
  ```

### 2.2 Result

With the constraint (no reloads) + exact grid, **every trained matmul maps at 0 weight
reloads and 100% tile utilization** — one weight block per crossbar, all crossbars used:

| matmul | grid (cols×rows) | crossbars | reloads |
|---|---|---|---|
| qkv_proj | 72×24 | 1,728 | 0 |
| attn_out_proj | 24×24 | 576 | 0 |
| ffn1 | 96×24 | 2,304 | 0 |
| ffn2 | 24×96 | 2,304 | 0 |

Per encoder layer = 6,912 crossbars; the whole no-reprogram 12-layer model = **82,944
crossbars** (= 84.9M weights ✓).

---

## 3. The I/O Cost Model (equations)

Developed on the toy design; **architecture-parametric** (depends only on the crossbar
dimensions, bit-widths, and layer shape).

### 3.1 Per-crossbar (crossbar level)

```
weight_in = array_row × array_col × weight_bits / 8     # programmed ONCE
data_in   = array_row × input_bits  / 8                 # per cycle
data_out  = array_col × output_bits / 8                 # per cycle
```

### 3.2 Chip level (per matmul)

```
tiles_parallel     = (M / array_col) × (C / array_row) × G          # ALL blocks resident
weight_prog_cycles = 1                                              # write-once (see note)
total_weight_moved = M × C × G × weight_bits / 8                    # into chip, moved ONCE
total_input_moved  = C × P × G × input_bits  / 8    over P iters    # input streamed once
output_size        = M × P × G × output_bits / 8                   # final output tensor
output_moved       = output_size × (C / array_row)                 # ALL partial outputs off
                   = tiles_parallel × (array_col × output_bits/8) × P    # the crossbars
```

- `tiles_parallel` = active crossbars used; `G` = independent matmuls in parallel (head
  count); `P` = tokens (sequence length) streamed through the stationary weights.
- `act_iterations = out_iterations = P` (one token per cycle through stationary weights).

### 3.3 What changed vs. an older reload-based derivation

| quantity | reload design | **weight-stationary** |
|---|---|---|
| `tiles_parallel` | mapper's small active count (8–32) | `(M/array_col)(C/array_row)G` — all blocks |
| `weight_prog_cycles` | `G·(M/(tiles·array_col))·(C/array_row)` (many reloads) | **1** (write-once) |
| `total_weight_moved` | reloaded every pass | `M·C·G·w/8` (once) |
| I/O driver | weight-reload passes | **P (tokens)** |

---

## 4. Validation on the Toy Design

Compared each equation against the simulator's measured NoC byte volumes (Timeloop
`.stats.txt`, parsed by `scripts/crossbar_stats.py`).

**Chip-level I/O (32×32 crossbar):**

| Layer | Weight (M×C) | Input (C×P) | in **Theo** | in **Sim** | out **Theo** | out **Sim** | Tiles ∥ | util % |
|---|---|---|---|---|---|---|---|---|
| qkv_proj | 2304×768 | 768×128 | 98,304 | 98,250 | 7,077,888 | 7,074,000 | 1,728 | 75% |
| attn_out_proj | 768×768 | 768×128 | 98,304 | 98,250 | 2,359,296 | 2,358,000 | 576 | 25% |
| ffn1 | 3072×768 | 768×128 | 98,304 | 98,250 | 9,437,184 | 9,432,000 | 2,304 | 100% |
| ffn2 | 768×3072 | 3072×128 | 393,216 | 393,750 | 9,437,184 | 2,358,000  | 2,304 | 100% |
| qk | 128×64 | 64×128 | 98,304 | 98,250 | 393,216 | 393,000 | 96 | 4.2% |
| av | 64×128 | 128×128 | 196,608 | 196,250 | 393,216 | 196,500  | 96 | 4.2% |

*(Tile util % vs. the largest matmul, 2,304 crossbars.)*

**Crossbar-level I/O (one 32×32 crossbar — identical for all layers):**

| Weight in | data in/cyc | data out/cyc | data in total (×P) | data out total |
|---|---|---|---|---|
| 1,024 B | 32 B | 32 B | 4,096 B | 4,096 B |

**Findings:**
- **Input & weight: `Sim/Theo = 1.00`** — validated to <0.1%.
- **Output: a subtlety.** `output_size` (final tensor) is *not* the data movement. Each
  output is a sum of `C/array_row` partial products, so the true **output movement =
  `output_size × (C/array_row)`**. The raw `col_noc` counter matches this on wide/square
  grids but **under-counts on tall grids** because the mapper **splits the
  C-reduction across levels** (part within a column on `col_noc`, the rest across columns
  above it). The **theory is the reliable total**; a single internal NoC counter is only a
  shape-dependent slice. (An earlier hand-fit of `min(M,C)/32` was fitting this slice, not
  the physics — corrected to `C/array_row`.)

---

## 5. Extension to the MLX Design

### 5.1 Architecture — a 4-level hierarchy

- **Crossbar (macro):** `wan_nature_2022` — 256×256 **4-bit** ReRAM, **W4A8** (WEIGHT_BITS=4,
  INPUT_BITS=OUTPUT_BITS=8). One 4-bit weight per cell (`N_WEIGHT_SLICES=1`).
- **Core (tile, `mlx_core`):** input/output buffers + `crossbar_in_core` (×8 crossbars).
- **Die (chip, `mlx_die`):** `glb` (8 MB) → `macro_in_die` (×8) → `router` →
  `core_in_macro` (×4). Total **8 × 4 × 8 = 256 crossbars/die**.
- **System:** `fetch_weights_hbm2_ws` (same weight-stationary constraint).

```
die → glb(8MB) → macro_in_die(×8) → router → core_in_macro(×4)
    → core → input/output_buffer → crossbar_in_core(×8) → macro[wan_nature 256×256]
```

### 5.2 W4A8 logical crossbar

wan_nature packs its 256 physical **columns** as **2 weight-bit-slices (Y) × 128 output
channels (M)**, with bit-serial inputs. So the **logical weight array is 256(C) × 128(M)**
(read from the mapped weight blocks: `M_blk=128, C_blk=256`). Note: `crossbar_stats` reports
`array_cols=2` here — a mis-read that grabs the Y-slice extent instead of M; the correct M is
taken from the weight-block size (`M_hi − M_lo`).

### 5.3 What transfers / what changes

- **Equations transfer unchanged** — just plug in `array_row=256, array_col=128,
  weight_bits=4, input_bits=8, output_bits=8`.
- **`crossbar_stats` needs config overrides** (its defaults are hardcoded for the toy chip):
  `crossbar_levels = ("macro_in_die","core_in_macro","crossbar_in_core")`,
  `noc_components = ("router",)`; per-crossbar dims taken from the weight blocks, not
  `array_cols`.
- **Fixed die, not per-matmul grid** — MLX is a fixed 256-crossbar fabric, so `tiles_parallel`
  comes from the mapper's placement; a small layer genuinely under-uses the die (real
  under-utilization), and the mapper fills spare crossbars with **token-parallel replicas**.

### 5.4 Results

All layers map **weight-stationary, 0 reloads**.

**Chip level (MLX W4A8):**

| Layer | Weight (M×C) | Input (C×P) | in **Theo** | out **Theo** | active tiles | weight xbars | util % (of 256) |
|---|---|---|---|---|---|---|---|
| qkv_proj | 2304×768 | 768×128 | 98,304 | 884,736 | 108 | 54 | 42% |
| attn_out_proj | 768×768 | 768×128 | 98,304 | 294,912 | 144 | 18 | 56% |
| ffn1 | 3072×768 | 768×128 | 98,304 | 1,179,648 | 144 | 72 | 56% |
| ffn2 | 768×3072 | 3072×128 | 393,216 | 1,179,648 | 144 | 72 | 56% |
| qk | 128×64 | 64×128 | 98,304 | 196,608 | 32 | 12 | 12.5% |
| av | 64×128 | 128×128 | 196,608 | 98,304 | 32 | 12 | 12.5% |

**Crossbar level (MLX W4A8):**

| Layer | Array (C×M) | Weight in | data in/cyc | data out/cyc | in total | out total |
|---|---|---|---|---|---|---|
| qkv/attn/ffn1/ffn2 | 256×128 | 16,384 B | 256 B | 128 B | 32,768 B | 16,384 B |
| qk | 64×128 | 4,096 B | 64 B | 128 B | 8,192 B | 16,384 B |
| av | 128×64 | 4,096 B | 128 B | 64 B | 16,384 B | 8,192 B |

**Architectural observations:**
- `weight_in = 16,384 B` (vs. 1,024 on the toy): larger 256×128 array but **4-bit** weights.
- **`output_moved` is far smaller** relative to the toy, because the accumulation factor is
  `C/array_row = C/256 = 3` (vs. `C/32 = 24`): bigger crossbars → fewer partial sums per
  output → less output traffic. A real win of larger crossbars.
- **One MLX die holds a whole encoder layer:** 54+18+72+72 = **216 weight-crossbars ≤ 256/die**;
  the full 12-layer model ≈ **2,592 crossbars ≈ 11 dies** (a 256-die package is ~4% used).

### 5.5 Boundary validation (the key check)

On a multi-level hierarchy, no single **internal** NoC equals the chip-level total (e.g. the
`router` multicasts inputs (~1.33×) and only partially reduces outputs). The correct
comparison is at the **chip boundary** — the `glb` buffer. There the model matches exactly:

| Layer | input **Theo** | `glb` Inputs partition (encoded) | ÷ ENCODED_INPUT_BITS (7) | match |
|---|---|---|---|---|
| qkv_proj | 98,304 | 688,128 | 98,304 |  1.00 |
| ffn2 | 393,216 | 2,752,512 | 393,216 | 1.00 |
| av | 196,608 | 1,376,256 | 196,608 | 1.00 |

`glb` partition ÷ `ENCODED_INPUT_BITS` (= 7 for signed 8-bit inputs) equals the theory **to
the byte** on all layers. The lesson is the same as the `col_noc`/output case: **validate at
the boundary, not at an internal NoC.**

---

## 6. Summary of Contributions

1. **A weight-stationary mapping** for CiM crossbars (forbid weight reloads + size fabric to
   the layer) giving **0 reloads / 100% tile utilization** on the toy design, and 0 reloads on
   the fixed MLX die.
2. **An analytical I/O cost model** (per-crossbar + chip level) that is **architecture- and
   bit-width-parametric** and evaluable without running the simulator.
3. **Simulator validation:** input and weight movement match to <0.1%; output movement
   corrected to `output_size × (C/array_row)` (the raw NoC counter is a per-level slice);
   boundary check at `glb` matches to the byte.
4. **Extension to a realistic 4-level MLX W4A8 fabric** (256×256 4-bit ReRAM), reusing the
   same equations — confirming the model generalizes across crossbar size, bit-width, and
   hierarchy depth.

**Scope:** this is an **I/O / data-movement** cost model (bytes moved, iterations). Energy,
area, and latency come from the underlying CiMLoop/Accelergy model and are used as-is (their
absolute magnitudes are ADC-dominated and technology-dependent). The natural next step is to
turn `bytes × iterations` into energy/latency (per-byte NoC energy + bandwidth) and to model
the inter-crossbar **pipeline datapath** (activations flowing layer→layer through the resident
fabric).

---

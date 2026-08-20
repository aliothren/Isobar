# Bandwidth Anchors — published NoC / D2D link specs with provenance

Purpose: the simulator's link bandwidths are platform inputs. Until the real
chip's values arrive, results are stated against PUBLISHED link specs from
fabricated (or post-layout) accelerators, so that "where real chips land on
our threshold curves" is a sourced statement, not a guess. Consumed by
`scripts/analyze_anchored_sweep.py`.

## On-die NoC, per link, one direction

| tier | value | system | provenance | notes |
|---|---|---|---|---|
| **LOW — 8.75 GB/s** (70 Gb/s) | Simba chiplet-internal NoC | Zimmer et al., *A 0.32–128 TOPS Scalable MCM-Based DNN Inference Accelerator with Ground-Referenced Signaling in 16 nm*, IEEE JSSC 2020 | "At 0.72 V, each link of the NoC achieves 70-Gb/s bandwidth." Silicon-measured; a 16 nm inference chiplet — the closest published cousin to our die NoC. |
| **MID — 32 GB/s** (256 Gb/s) | ESP open-source SoC NoC, tile-to-tile | as reported in the FlooNoC comparison table (arXiv:2409.17606, Table; ESP: 12 nm FinFET, 16×16 mesh) | secondary source (FlooNoC's own comparison), noted honestly. |
| **HIGH — 80.6 GB/s** (645 Gb/s) | FlooNoC wide-link NoC | Fischer et al., *FlooNoC: A 645 Gbps/link 0.15 pJ/B/hop Open-Source NoC*, arXiv:2409.17606 | "achieve a bandwidth of 645 Gbps per link"; 0.15 pJ/B/hop; 12 nm post-layout (Occamy silicon sibling measured 584 Gbps). |

Also in the same comparison table: Celerity 96 Gb/s (16 nm silicon, 5×5
mesh), Ou et al. 45 Gb/s — bracketing LOW and MID.

## Die-to-die (package), per link, one direction

| value | system | provenance | notes |
|---|---|---|---|
| **12.5 GB/s** (100 Gb/s) | Simba package GRS mesh | same JSSC 2020: "36 dice ... mesh network with 100 Gb/s interconnect in each link direction"; lanes run 11–25 Gb/s at **0.82–1.75 pJ/bit** | silicon-measured D2D on an organic substrate; the pJ/bit range brackets our 5 pJ/word (=0.63 pJ/bit) example as OPTIMISTIC by ~1.3–2.8× |

## Conversion into the simulator's unit

The simulator meters bandwidth in words/cycle: 1 word = 8 bit, device cycle
= 1.4486 µs (calibrated array model) → **1 GB/s = 1,449 words/cycle**.

| tier | GB/s | words/cycle |
|---|---|---|
| LOW (Simba on-die) | 8.75 | 12,675 |
| MID (ESP) | 32.0 | 46,354 |
| HIGH (FlooNoC) | 80.6 | 116,793 |
| D2D (Simba GRS) | 12.5 | 18,107 |

**What is and is not substituted.** An anchor substitutes exactly ONE
number — the per-link bandwidth. The workload (GPT-2 medium, our mapper
runs), the chip architecture (8 macros x 4 cores x 8 crossbars of 256x256
ReRAM arrays), the device cycle (1.4486 us), and all traffic volumes remain
OUR chip's. Nothing else from Simba/ESP/FlooNoC (frequency, word width,
router design, die size) is imported. This is a one-variable sensitivity
substitution answering "if our die NoC's links delivered what fabricated
NoCs deliver, what happens" — not a simulation of those chips.

Caveats: per-link, one direction, headline rates (no protocol overhead
deducted); our model treats a link as undirected (up+down share it), which
is conservative by up to 2× against duplex hardware. Process nodes differ
(12–16 nm vs our 130 nm device model) — the anchors bound what NoCs of
shipping accelerators deliver, they do not calibrate our wires.

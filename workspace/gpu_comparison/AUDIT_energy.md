# Energy ledger audit (GPU comparison)

Date: 2026-10-22. This second version corrects the attribution of the GRS link model and unifies the comparison on a 16-bit K/V cache.

The reported quantity is energy. Latencies stay in `cim_requests.csv` / `comparison_summary.csv` for internal accounting. All CIM results are **modeled dynamic energy**.

| deliverable | content |
| --- | --- |
| `energy_ledger.csv` | per-component ledger: counting basis, formula, unit energy and source, coverage, double-counting check |
| `energy_breakdown.csv` | components per configuration, before/after the audit, scenario columns |
| `comparison_summary.csv` | the comparison summary |
| `sweep/sweep_all.csv` | the 432-point sweep |

## 1. Does each model's output include static power?

| model | conclusion | basis |
| --- | --- | --- |
| CiMLoop / Accelergy (CIM arrays, ADC, integrator, sample, drivers, shift-add, buffers, GLB, router, intra-operator die links) | dynamic only | every component in the mapper statistics shows `Leakage energy (total): 0.00e+00 pJ`, and the ERTs have no leakage entries; energy = computes × each component's fJ/compute |
| interconnect (10 pJ/word/hop = 1.25 pJ/bit) | dynamic only, priced by traffic | as Gemini (HPCA 2024) §V-B2 treats clock-forwarding links (GRS, UCIe): the links can enter low-power states, so energy = traffic × unit energy; Gemini's Simba/GRS baseline uses this model. The fabric levels have `idle_power_w = None` |
| K/V and embedding memory (50 pJ/B) | dynamic only | access energy, without standby or refresh |
| digital unit (1 pJ per MAC-equivalent) | full-load average | an accelerator-level 2 TOPS/W coefficient, which at full load includes the unit's own static share; idle power between forwards is not modelled |
| digital element-wise (Horowitz class + GLB) | dynamic only | energy per operation / per access |

No static term can be counted from the models' own definitions.

**The withdrawn GRS static term.** The previous version took a repository note ("GRS link power is independent of traffic, no sleep") as the basis for a static term. That contradicts Gemini's classification of GRS, so it was withdrawn; the note is treated as unverified until checked against the JSSC original.

- 1.75 pJ/bit × 100 Gb/s = 0.175 W is the link's operating power at that rate, not an extra leakage power.
- It cannot be added on top of transfer energy that the same PHY already prices per bit.
- "All links always on" is kept only as a scenario estimate (section 6) and enters no result.
- 10 pJ/word itself is the midpoint of the GRS 0.82–1.75 pJ/bit range in the registry; it is not derived from gating.

Not covered:

- ReRAM periphery / ADC bias and idle power;
- digital-unit idle power;
- LPDDR standby and refresh;
- the residual power of the links' low-power states;
- clock, control and host interface.

## 2. Double-counting check

- The `chip2chip_link` / `data_staging` terms in a CIM account are the mapper's internal traffic for one operator split across dies (0.0112 fJ/compute in the LM-head statistics, about 0.3%). Hand-offs between operators are counted once, in the interconnect term.
- The digital unit's 1 pJ per MAC-equivalent includes its internal buffers and control; K/V memory and the hub link are counted separately.
- The element-wise operators' GLB accesses are their own reads and writes; the operand movement of the matrix operators is inside the CIM account.
- The LM head's hand-offs in and out are counted in the interconnect term at the port bound, and its array energy in the model-end term. The embedding read is counted once.
- Per-bit link energy and the always-on scenario are two alternative views of the same PHY and are never added.

## 3. Bit widths and the main comparison

| item | CIM simulation | A100 / FasterTransformer | Thor / llama.cpp Q8_0 |
| --- | --- | --- | --- |
| weights | 8 bit (2 ReRAM cells per weight) | FP16 | Q8_0 (8-bit block quantization) |
| activations | 8 bit (7 input bit slices) | FP16 | Q8_1 / Q8_K, 8 bit |
| accumulation / partial sums | 16-bit digital intermediates, 2-byte partial sums | FP32 | FP32 |
| K/V cache | main comparison 2 B / element (as the GPUs); 1 B as a quantized supplement | FP16 | f16 (default) |

Both GPU baselines keep a 16-bit K/V cache, so the main comparison uses the CIM configurations with 2 B per element (`*_kv16`). Each configuration also has a 1 B row as a quantized-setting supplement.

## 4. Capacity and grid with the LM head

| configuration | LM-head dies | slots needed | extended grid | vocabulary / padded | energy scale |
| --- | --- | --- | --- | --- | --- |
| A0_ref | 64 | 2200+1+64=2265 | 48x48 | 50272 / 65536 | ×0.767 |
| A1_m16 | 32 | 1160+1+32=1193 | 35x35 | 50272 / 65536 | ×0.767 |
| A4_col | 64 | 2400+1+64=2465 | 50x50 | 50272 / 65536 | ×0.767 |
| B0_ref | 128 | 1232+1+128=1361 | 37x37 | 256000 / 262144 | ×0.977 |
| B1_m16 | 64 | 616+1+64=681 | 27x27 | 256000 / 262144 | ×0.977 |

The extended grid adds rows and columns outside the backbone; the backbone coordinates and hand-off paths are unchanged. The 16-macro configurations scale the LM-head die count by capacity and take the energy from the 8-macro measurement.

**The two LM-head changes.**

1. In the previous formal ledger (delivered 10-21, `sweep/comparison_summary_before_audit.csv`), the LM-head energy was the mapper's price of the padded (power-of-two) vocabulary: 1.015 mJ per token for Gemma, 0.513 J per request.
2. This audit removes the padded columns by scaling with vocabulary / padded width (OPT 0.767, Gemma 0.977).

The first implementation of that correction took the workload configuration's default vocabulary of 50257, which made Gemma's scale 0.19 (0.103 J). The before/after comparison caught this intermediate result, and the scale was changed to the model's own vocabulary before any table was delivered. The only change against the previous formal ledger is therefore the padding correction: Gemma −0.011 J (−0.11%), OPT-13B −0.12 J (−0.26%).

## 5. Results after the audit (modeled dynamic energy)

Main comparison (K/V 2 B per element, matching the GPUs' 16-bit cache):

| main configuration | E / request (J) | mJ / output token | GPU measured / CIM dynamic | CIM arrays and periphery | K/V access | interconnect | digital unit | element-wise | model end |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A0_ref_kv16 | 58.61 | 57.24 | **93×** | 40.0% | 41.3% | 17.5% | 0.4% | 0.1% | 0.7% |
| A1_m16_kv16 | 48.53 | 47.39 | **113×** | 40.6% | 49.8% | 8.1% | 0.5% | 0.1% | 0.8% |
| A4_col_kv16 | 56.99 | 55.65 | **96×** | 41.0% | 42.4% | 15.3% | 0.4% | 0.1% | 0.7% |
| B0_ref_kv16 | 11.45 | 22.90 | **166×** | 52.6% | 29.8% | 12.6% | 0.3% | 0.2% | 4.4% |
| B1_m16_kv16 | 9.85 | 19.70 | **193×** | 54.5% | 34.7% | 5.1% | 0.4% | 0.3% | 5.1% |

All configurations, including the 1 B K/V rows. The mesh bandwidth does not change the energy, so each GRS-tier row equals its 0.4 GB/s row:

| configuration | K/V B/element | E / request (J) | mJ / token | GPU/CIM | CIM | K/V | interconnect | model end | E before audit | change |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A0_ref | 1.0 | 46.52 | 45.43 | 118× | 50.4% | 26.0% | 22.1% | 0.9% | 46.64 | -0.26% |
| A0_ref_kv16 | 2.0 | 58.61 | 57.24 | 93× | 40.0% | 41.3% | 17.5% | 0.7% |  | new |
| A1_m16 | 1.0 | 36.44 | 35.59 | 150× | 54.1% | 33.2% | 10.7% | 1.1% | 36.56 | -0.33% |
| A1_m16_kv16 | 2.0 | 48.53 | 47.39 | 113× | 40.6% | 49.8% | 8.1% | 0.8% |  | new |
| A2_grs | 1.0 | 46.52 | 45.43 | 118× | 50.4% | 26.0% | 22.1% | 0.9% | 46.64 | -0.26% |
| A2_grs_kv16 | 2.0 | 58.61 | 57.24 | 93× | 40.0% | 41.3% | 17.5% | 0.7% |  | new |
| A3_m16_grs_kv | 1.0 | 36.44 | 35.59 | 150× | 54.1% | 33.2% | 10.7% | 1.1% | 36.56 | -0.33% |
| A3_m16_grs_kv_kv16 | 2.0 | 48.53 | 47.39 | 113× | 40.6% | 49.8% | 8.1% | 0.8% |  | new |
| A4_col | 1.0 | 44.89 | 43.84 | 122× | 52.0% | 26.9% | 19.4% | 0.9% | 45.02 | -0.27% |
| A4_col_kv16 | 2.0 | 56.99 | 55.65 | 96× | 41.0% | 42.4% | 15.3% | 0.7% |  | new |
| A5_col_grs | 1.0 | 44.89 | 43.84 | 122× | 52.0% | 26.9% | 19.4% | 0.9% | 45.02 | -0.27% |
| A5_col_grs_kv16 | 2.0 | 56.99 | 55.65 | 96× | 41.0% | 42.4% | 15.3% | 0.7% |  | new |
| B0_ref | 1.0 | 9.74 | 19.48 | 195× | 61.9% | 17.5% | 14.8% | 5.1% | 9.75 | -0.12% |
| B0_ref_kv16 | 2.0 | 11.45 | 22.90 | 166× | 52.6% | 29.8% | 12.6% | 4.4% |  | new |
| B1_m16 | 1.0 | 8.14 | 16.29 | 233× | 65.9% | 21.0% | 6.2% | 6.2% | 8.16 | -0.15% |
| B1_m16_kv16 | 2.0 | 9.85 | 19.70 | 193× | 54.5% | 34.7% | 5.1% | 5.1% |  | new |
| B2_grs | 1.0 | 9.74 | 19.48 | 195× | 61.9% | 17.5% | 14.8% | 5.1% | 9.75 | -0.12% |
| B2_grs_kv16 | 2.0 | 11.45 | 22.90 | 166× | 52.6% | 29.8% | 12.6% | 4.4% |  | new |
| B3_m16_grs_kv | 1.0 | 8.14 | 16.29 | 233× | 65.9% | 21.0% | 6.2% | 6.2% | 8.16 | -0.15% |
| B3_m16_grs_kv_kv16 | 2.0 | 9.85 | 19.70 | 193× | 54.5% | 34.7% | 5.1% | 5.1% |  | new |

GPU baselines:

- A100: 5473.7 J (GPU device power 253 W × 21.635 s, 5.345 J/token).
- Thor: 1898.7 J (whole-board VIN; per-request power × time, averaged over the 541 requests; 3.797 J/token).

The GPU measurements include their static power; the CIM side is dynamic energy.

## 6. Scenario: all links always on (12.5 GB/s tier only, not part of any result)

The scenario counts the link directions of a full bidirectional 2-D mesh on the extended grid, 4n(n−1), plus the digital unit's 2 hub ports. Each direction is charged for the whole request at the operating power of GRS at 25 Gb/s × 4 lanes: 1.75 pJ/bit × 100 Gb/s = 0.175 W. This is a hypothetical "no low-power state at all" scenario and is mutually exclusive with the adopted traffic-based model.

| configuration | extended grid | link directions | always-on power | request time | scenario energy | remaining power budget (E_GPU − E_CIM)/T_CIM |
| --- | --- | --- | --- | --- | --- | --- |
| A2_grs_kv16 | 48x48 | 9026 | 1580 W | 22.36 s | 35319 J | 242 W |
| A3_m16_grs_kv_kv16 | 35x35 | 4762 | 833 W | 12.29 s | 10243 J | 441 W |
| A5_col_grs_kv16 | 50x50 | 9802 | 1715 W | 21.40 s | 36715 J | 253 W |
| B2_grs_kv16 | 37x37 | 5330 | 933 W | 3.52 s | 3280 J | 537 W |
| B3_m16_grs_kv_kv16 | 27x27 | 2810 | 492 W | 2.15 s | 1058 J | 878 W |

The remaining power budget is the mean power that, with every uncovered power taken as zero, keeps the energy break-even over that configuration's execution time. It changes with the execution time and is not a verified acceptable link idle power.

## 7. Changes against the previous version

- LM-head padding correction: OPT-13B −0.26%, Gemma −0.11% (section 4 describes the two steps).
- The main comparison now uses the 16-bit K/V rows: OPT-13B 58.61 J, 93×; Gemma 11.45 J, 166×; the 16-macro rows 48.53 J, 113× and 9.85 J, 193×. The 1 B K/V rows (118×, 195×, ...) remain as a quantized-setting supplement.
- The "GRS link no-sleep static bound" classification is withdrawn and replaced by the scenario estimate. Its link counts are updated on the extended grid (9024 + 2 for 48×48, 5328 + 2 for 37×37), and `P_remaining` is renamed the remaining power budget.
- The sweep table's energy column follows the LM-head correction (< 0.3%).

## 8. Items not covered

- ReRAM array periphery / ADC bias and idle power.
- Digital-unit idle power between forwards.
- LPDDR standby and refresh (tens of mW for a 2 GB package).
- The residual power of the links' low-power states (negligible under the traffic-based model).
- Clock distribution, control, host interface and cooling.

The one-time weight preload and ReRAM programming are excluded by convention.

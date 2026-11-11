# GPU literature-baseline comparison: report

> After the energy-ledger audit (2026-10-22), the reported quantity is **modeled dynamic energy**. That covers energy per request, energy per output token, the GPU/CIM energy ratio and the component breakdown; see `AUDIT_energy.md` and `energy_breakdown.csv`. Latencies in this report are for internal accounting only.
>
> The audit made three changes:
>
> - The LM-head energy is scaled by vocabulary / padded width (OPT-13B −0.26%, Gemma −0.11%).
> - Every configuration has a 16-bit K/V row, which is the main comparison: OPT-13B 58.61 J, 93×; Gemma 11.45 J, 166×.
> - Interconnect energy uses the traffic-based model, as Gemini (HPCA 2024) does for clock-forwarding GRS / UCIe links. "All links always on" is kept only as a scenario estimate.
>
> The table in section 3 is the 1-byte K/V set before the audit.

Date: 2026-10-21. Directory `workspace/gpu_comparison/`:

| path | content |
| --- | --- |
| `sources/` | source records, the Hydra raw CSV and the length frequencies |
| `configs/` | 8 configurations and the resource table |
| `scripts/` | `gpu_baselines.py` (baseline extraction), `cim_request.py` (request-cost engine), `run_all.sh`, `summarize.py` (summary) |
| `gpu_baselines.csv` | the GPU baselines |
| `cim_requests.csv` | one row per configuration and input length, with phase times and energy components |
| `comparison_summary.csv` | the comparison summary |

Reproduce: `python3 gpu_comparison/scripts/gpu_baselines.py && bash gpu_comparison/scripts/run_all.sh && python3 gpu_comparison/scripts/summarize.py`.

## 1. GPU baselines

| group | device / backend | workload | request time | request energy | J / output token | energy boundary |
| --- | --- | --- | --- | --- | --- | --- |
| A | A100 40 GB, FasterTransformer | OPT-13B, 64:1024, single request | 21.635 s (1024 / 47.33) | 5473.74 J (253 W × T) | 5.345 | GPU device power |
| B | Jetson AGX Thor, llama.cpp Q8_0 | Gemma-7B, 541 IFEval requests, 13–345 input tokens (84 lengths), 500 output tokens each | 24.82638 s (execution window 24.82547 s) | 1898.68 J (per-request vin_cur × time, then averaged) | 3.797 | whole-board input; the GPU rail (794.70 J) only as a component |

The group A values were checked against the paper PDF:

- §VII (p. 978): DGX A100 40 GB / 1.55 TB/s, FasterTransformer, single device, 64 input / up to 1024 output tokens.
- §VIII-A (p. 979): "253 Watts vs. 77.1 Watts".
- Fig. 10 (p. 980): the GPU at [64:1024] runs 47.33 tokens/s at 0.19 token/J.

The group B values were recomputed from the CSV's raw fields. They match the expected values digit for digit, and the CSV hash matches.

## 2. The CIM request model

A request is one prefill of L tokens plus O − 1 single-token forwards. Forward j has an effective context of L + j; the first token reuses the prefill logits, matching Hydra's `llama_n_eval` = 499.

Static CIM operators, digital element-wise work and hand-off traffic are exactly proportional to the number of query rows. The measured accounts at S = 128 / 256 / 512 / 1024 confirm this: compute, energy and die flows scale by ×2 per doubling, and the decode terms stay constant. Every length is therefore priced from the S = 512 confirmation record; the attention and K/V terms are closed form per context.

The fixed mapping is each record's prefill-512 confirmation representative, shared by both phases. Under that layout, the decode communication time is within 1% of a layout searched for decode (OPT-13B 20.37 vs. 20.42 ms/token, Gemma 4.04 vs. 4.07 ms/token), so no new search was run.

The model is completed with:

- the embedding read (unit memory, 50 pJ/word) and OPT's position-embedding add;
- the final norm;
- the LM head, resident on CIM with the vocabulary padded to a power of two (OPT-13B 64 dies, Gemma-7B 128 dies). One row is computed per generated token, including an estimate of the unit interface in and out;
- the argmax;
- Gemma's RoPE.

The K/V capacity suffices at the largest context: OPT-13B 1087 tokens, 0.445 GB; Gemma 845 tokens, 0.19 GB. Decode uses the materialized algorithm throughout and reads the K/V once per layer.

The energy is dynamic energy: CIM arrays and periphery (accounts), digital element-wise work, unit attention compute, K/V memory, interconnect (10 pJ/word flat plus surplus hops) and the model end. **The platform has no static or background power model** (the fabric's `idle_power_w` is unset). The report therefore gives the counted energy and the remaining average power that keeps the efficiency advantage, P_remaining,max = (E_GPU − E_CIM,accounted) / T_CIM.

## 3. Results

| configuration | setting | T_CIM (s) | of which prefill | E_CIM (J) | J / token | E_GPU/E_CIM | energy saving | T_GPU/T_CIM | P_remaining,max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A0_ref | 8 macros, 0.4 GB/s | 33.558 | 1.402 | 46.64 | 0.0455 | 117.4× | 99.15% | 0.64× | 161.7 W |
| A1_m16 | 16 macros, 0.4 GB/s | 24.758 | 0.886 | 36.56 | 0.0357 | 149.7× | 99.33% | 0.87× | 219.6 W |
| A2_grs | 8 macros, 12.5 GB/s | 12.914 | 0.186 | 46.64 | 0.0455 | 117.4× | 99.15% | 1.68× | 420.3 W |
| A3_m16_grs_kv | 16 macros, 12.5 GB/s, K/V 51.2 GB/s | 7.568 | 0.151 | 36.56 | 0.0357 | 149.7× | 99.33% | 2.86× | 718.4 W |
| A4_col | column-split QKV (2400 dies, 49×49), 0.4 GB/s | 18.405 | 0.507 | 45.02 | 0.0440 | 121.6× | 99.18% | 1.18× | 295.0 W |
| A5_col_grs | column-split QKV, 12.5 GB/s | 11.958 | 0.127 | 45.02 | 0.0440 | 121.6× | 99.18% | 1.81× | 454.0 W |
| B0_ref | 8 macros, 0.4 GB/s | 4.247 | 0.245 | 9.75 | 0.0195 | 194.7× | 99.49% | 5.85× | 444.8 W |
| B1_m16 | 16 macros, 0.4 GB/s | 4.118 | 0.236 | 8.16 | 0.0163 | 232.8× | 99.57% | 6.03× | 459.1 W |
| B2_grs | 8 macros, 12.5 GB/s | 2.181 | 0.066 | 9.75 | 0.0195 | 194.7× | 99.49% | 11.38× | 866.0 W |
| B3_m16_grs_kv | 16 macros, 12.5 GB/s, K/V 51.2 GB/s | 1.484 | 0.065 | 8.16 | 0.0163 | 232.8× | 99.57% | 16.73× | 1273.8 W |

Group B values are means over the 541 requests weighted by length frequency, and the ratios are ratios of means; group A is a single request.

**Time components (shares of the request).**

- **A0:** interconnect 65.9%, K/V memory 28.1%, CIM compute 5.3%. A decode token takes about 31.5 ms:
  - hand-offs 20.4 ms;
  - K/V re-reads 9.2 ms (mean context about 600 tokens, 246 MB / 25.6 GB/s);
  - CIM 1.6 ms.
- **A0 hand-offs by type** (20.4 ms in total):
  - qkv → digital unit 15.1 ms over 40 layers. The 10 row-split qkv dies each send one row of 15360 columns of 2-byte partial sums, 307 KB per layer; the busiest link carries 153,600 words at 0.4 GB/s.
  - ffn1 → ffn2 2.2 ms; out_proj → ffn1 1.6 ms; unit → out_proj 1.4 ms; across layers 0.08 ms.
- **A4, column-split QKV:** qkv → unit sends only 15 KB per layer, and the decode hand-offs fall to about 7.6 ms/token. The request takes 18.4 s, faster than the A100 (1.18×), at essentially unchanged energy. Prefill is only 4%.
- **B0:** interconnect 51.8%, K/V 31.4%, CIM 14.6%.
- **Faster links and memory:** at the GRS mesh tier, the hand-offs shrink to 6–12% and the K/V re-reads become the main term (A2 73%, B2 61%). With 51.2 GB/s K/V bandwidth on top, the CIM compute share rises to 23–42%.

**Energy components.** Across all configurations:

| component | share |
| --- | --- |
| CIM arrays and periphery | 50–66% |
| K/V memory | 18–33% |
| interconnect | 6–22% |
| model end | 1–6% |

The interconnect energy is the same at 0.4 and 12.5 GB/s because it is priced per byte. In the model end, Gemma's 128-die LM head costs 1.0 mJ per token. With 16 macros the die count halves, the interconnect energy falls by more than half, and the total energy falls by 16–22%.

**Reading.** The two-orders-of-magnitude energy gap compares dynamic energy with measured GPU power. The GPU side includes the card's or board's static power; the CIM side does not. By P_remaining,max, the efficiency advantage holds as long as the whole CIM system's mean background power during the request stays below 162 W (A0) or 445 W (B0). For a package of 2200 + 64 ReRAM dies and one digital unit, that budget is generous, but a total-energy estimate needs static power parameters.

In time, OPT-13B on the reference 0.4 GB/s mesh is slower than the A100 (0.64×). A decode token's 199 hand-offs take 20 ms on 0.4 GB/s links, the same bottleneck as in the communication-sensitivity experiments. GRS-tier links and wider dies bring it to 2.9× the A100's speed, and column-split QKV already matches it at 0.4 GB/s (1.18×). Gemma against Thor is 5.9× faster in the reference configuration, because Thor itself takes about 50 ms per token.

## 4. Boundaries and assumptions

- **Precision.** CIM: 8-bit weights and activations, 2-byte partial sums, 16-bit digital intermediates, K/V 1 byte. The A100 point's dtype is not reported (the PNM side is FP16). Hydra Q8_0: 8-bit block-quantized weights, 8-bit quantized activations, FP32 accumulation.
- **GRS-tier configurations** reuse the layout searched at 0.4 GB/s and re-price it without a new search. Communication is only 6–12% in these configurations, so a new search would have a limited effect.
- **Model end.** The LM head's extra dies count against capacity as resident. Its hand-offs are estimated at the port bound, placement-free. The embedding table sits in the unit memory.
- **Not modelled:** static / background power, PHY always-on power, phase-switch data movement (zero under a fixed mapping), and host overhead on the GPU side beyond tokenizer and sampling.
- **Unit K/V** is a single-channel serial read/write model (reads and writes do not overlap), as in the existing setting.

## 5. Deliverables

| file | content |
| --- | --- |
| `gpu_baselines.csv` | 12 rows |
| `sources/hydra_requests.csv` | 541 rows |
| `sources/hydra_input_lengths.csv` | 84 rows |
| `cim_requests.csv` | 10 configurations: one row per group A configuration, 84 per group B configuration |
| `cim_requests_<id>_meta.json` | per configuration: layout id, T reproduction check, resources |
| `comparison_summary.csv` | 10 rows, with component shares and P_remaining |
| `configs/resources.csv` | the resource table |

## 6. Configuration sweep (added 2026-10-21)

`scripts/sweep.py` re-prices fixed layouts along four axes, without a new search:

| axis | values |
| --- | --- |
| macros per die | 4 / 8 / 16 / 32, each with its measured accounts and its confirmed / exploration layouts |
| device row rate | NeuRRAM 10.14 µs (reference), ISAAC 1.6 µs (design point), HERMES 4-phase 0.52 µs, HERMES 1-phase 0.133 µs (derived from the published peaks; energy per operation unchanged) |
| mesh bandwidth per direction | 0.4 (HERMES class), 1.6, 4.0 (ISAAC-class on-chip link), 12.5 GB/s (Simba GRS) |
| K/V memory bandwidth | 25.6 (two LPDDR4 channels), 51.2 (two LPDDR5 channels), 136 GB/s (one LPDDR5X ×128 package, CXL-PNM paper Table I) |

OPT-13B also has the 8-macro column-split QKV. In total there are 432 points; the data are in `sweep/sweep_all.csv` and the pivot tables in `sweep/sweep_tables.md`.

Findings:

- **Energy** changes only with capacity and partitioning; rate and bandwidth do not change the energy per operation or per byte.
  - OPT-13B: 73.5 / 46.6 / 36.6 / 33.3 J at 4 / 8 / 16 / 32 macros.
  - Gemma: 13.6 / 9.8 / 8.2 / 7.6 J.
  - GPU/CIM ratio: 75–164× (OPT-13B), 140–252× (Gemma).
- **Time**: the axes matter in this order.
  - Mesh bandwidth: 0.4 → 1.6 GB/s takes the OPT-13B reference point from 33.6 s to 17.1 s.
  - K/V bandwidth: decode re-reads the K/V every token; 25.6 → 136 GB/s takes the 12.5 GB/s-mesh point from 12.9 s to 5.3 s.
  - Capacity: 32 macros at 0.4 GB/s gives 16.5 s.
  - Device rate matters least: CIM compute is only 5–15% of prefill and decode, and the four rates differ by only 5% on the reference mesh.
- **OPT-13B against the A100:** 211 of 240 points are faster. All the slower points are row-split configurations on the 0.4 GB/s mesh, plus one 4-macro point at 1.6 GB/s. Column-split QKV reaches 1.18× already at 0.4 GB/s. The fastest combination (32 macros, HERMES 1-phase, 12.5 GB/s, 136 GB/s K/V) takes 2.32 s, 9.3×.
- **Gemma against Thor:** all 192 points are faster; the reference is 5.85×, the fastest 58.7× (0.42 s).

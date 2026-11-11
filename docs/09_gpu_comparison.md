# 09 Energy per request against GPUs

This page shows how to estimate the energy of a complete generation request on a CIM deployment and compare it with a measured GPU baseline. This is Table III of the paper. The scripts are in `workspace/gpu_comparison/`.

## In short

```bash
# host, from workspace/ (or the container)
bash gpu_comparison/scripts/run_all.sh       # the four configurations of Table III; PYTHON=... selects the interpreter
```

This needs the `reference` and `capacity16` records ([05 Deployments](05_deployments.md)) and `results/accounts/model_end_costs.json` ([04 Models](04_models.md)). It writes `results/gpu_comparison/comparison_summary.csv`, with one row per configuration.

## What is computed

`gpu_comparison/scripts/cim_request.py` computes the latency and energy of one request of L input tokens and O output tokens as one prefill of L tokens followed by O − 1 decode steps of one token each. The steps reuse the deployment record of the configuration: its account and the placement its search found.

- **Placement.** The search representative of the record (prefill, 512 tokens) is used for every step, prefill and decode. On this placement, the decode communication time is within 1% of a placement searched for decode.
- **Prefill of L tokens.** The record is for 512 tokens. CIM compute and writes, the digital element-wise work and every hand-off's data volume are proportional to the number of tokens processed. They are therefore taken from the 512-token record and scaled by L / 512; the hop delay is not scaled. The digital unit's attention and K/V time are computed for L tokens directly (`offload.unit_layer_cost`).
- **Decode step j.** It processes one token against a context of L + j tokens. CIM compute, writes and the decode hand-offs come from the decode entries of the same account and placement; they are the same for every step. The unit's attention compute and its K/V reads grow with the context and are recomputed for every step. With 16-bit K/V values (`kv_bytes_per_element: 2`), K/V time and energy double.
- **Model end.** Each step adds:
  - the embedding read of the tokens it processes, from the unit's memory;
  - the final norm and the argmax, on the dies' digital vector units;
  - the LM head for one token.

  The LM head is resident on its own CIM dies: 64 for OPT-13B and 128 for Gemma-7B at 8 macros, from `model_end_costs.json`. Its energy counts only the real vocabulary, not its padding to a power of two. These dies are added outside the backbone mesh, so the backbone placement and its hand-offs are unchanged. The LM head's own transfers are estimated from its port and unit-interface bandwidths, independent of placement.
- **Totals.** The request time is the sum of all steps. The energy is the sum of their dynamic energies. For Gemma-7B, the result is averaged over the input lengths of the GPU workload, weighted by how often each occurs.

The CIM energy is **modeled dynamic energy**. It covers the CIM arrays and periphery, the digital work, attention on the unit, K/V memory accesses, mesh traffic and the model end; static and idle power are not modelled. The GPU numbers are measured device or board energy and include static power. The summary therefore also reports how much average background power the CIM system could draw before its energy reached the GPU's: (E_GPU − E_CIM) / T_CIM.

## A configuration file

Each file in `gpu_comparison/configs/` describes one comparison:

```json
{
 "id": "gemma7b_ref",
 "group": "gemma7b_thor",
 "model": "gemma7b",
 "record_experiment": "reference",
 "config_id": "gemma7b_prefill512_colrow_sq_mesh_xy_k2_b0.4_offcenterK1",
 "bw_gbps": 0.4,
 "die_macros": 8,
 "unit_overrides": {},
 "rope": true,
 "learned_positions": false,
 "lengths": [[13, 2], [17, 1], [18, 3]],
 "output_tokens": 500,
 "kv_bytes_per_element": 2,
 "lm_head_padding_correction": true
}
```

| field | meaning |
|---|---|
| `id` | name of the configuration (output file names) |
| `group` | which GPU baseline to compare with (`opt13b_a100` or `gemma7b_thor`, defined in `scripts/summarize.py`) |
| `model` | model key |
| `record_experiment`, `config_id` | the deployment record whose searched placement is used |
| `bw_gbps` | mesh bandwidth for the request; may differ from the record's, to re-evaluate the same placement at another bandwidth |
| `die_macros` | macros per die of that deployment |
| `unit_overrides` | digital-unit parameters to change, e.g. `{"kv_words_per_second": 51.2e9}` |
| `rope`, `learned_positions` | position encoding: rotary (computed on the unit) or a learned table (read with the embedding) |
| `lengths` | input lengths and how many requests have each length; the result is the request-weighted mean |
| `output_tokens` | generated tokens per request |
| `kv_bytes_per_element` | 2 for a 16-bit K/V cache (as in the GPU runs), 1 for 8-bit |
| `lm_head_padding_correction` | count the LM head's energy for the real vocabulary only, not its padding to a power of two |
| `layout` (optional) | name of another placement of the record to use, e.g. a baseline such as `random_s209`; default: the search representative |
| `device_rate_factor` (optional) | CIM device speed relative to the reference (2 = rows twice as fast); energy per operation unchanged |

Name the file `<id>.json`: the summary looks configurations up by their id.

## Your own comparison

1. Run the deployment you want to evaluate, e.g. `run_experiments.py --custom --model opt13b --macros 16`.
2. Measure the model end once, in the container: `python3 scripts/measure_model_end.py opt13b`.
3. Copy a configuration file and set `record_experiment` to `custom`, `config_id`, `die_macros` and the request shape.
4. If you compare with another GPU, add its request time and energy to `GPU` in `gpu_comparison/scripts/summarize.py` and use its key as `group`.
5. Run one configuration:

```bash
# host, from workspace/ (or the container)
python3 gpu_comparison/scripts/cim_request.py --config gpu_comparison/configs/<file>.json
python3 gpu_comparison/scripts/summarize.py
```

For a die variant, set `CIMSIM_FABRIC=models/fabric/variants/mlx300_multidie_m<N>.yaml` before `cim_request.py`; `run_all.sh` does this for you.

## Outputs (`results/gpu_comparison/`)

| file | content |
|---|---|
| `cim_requests_<id>.csv` | per input length: prefill and decode time, energy by component |
| `cim_requests_<id>_meta.json` | the placement used, the LM-head dies, the mesh including the LM head |
| `comparison_summary.csv` | per configuration: CIM and GPU time and energy, GPU/CIM energy ratio, the remaining background-power budget, time and energy shares of each component |
| `resources.csv` | the hardware of each configuration |

## The GPU baselines

| | OPT-13B | Gemma-7B |
|---|---|---|
| device | one A100 40 GB, FasterTransformer | Jetson AGX Thor, llama.cpp, 8-bit weights |
| request | 64 input, 1024 output tokens | 541 requests, 13–345 input, 500 output tokens |
| energy per request | 5473.7 J (253 W × 21.6 s) | 1898.7 J (board power × time, mean) |
| source | CXL-PNM, HPCA 2024 | Hydra, arXiv:2608.25053 |

`gpu_comparison/sources/README.md` documents every value. `scripts/gpu_baselines.py` recomputes the Gemma baseline from Hydra's published per-request data.

# 04 Models and their operator costs

This page shows how to add a model and measure what each of its operators costs on the CIM die. Isobar runs CiMLoop only in this step. The result is the model's **account**: a per-operator cost table with, for each operator of one transformer block and for prefill and decode, the compute time, write time and energy on the die. Evaluations and searches read the account and never call CiMLoop. An account is measured once per model, sequence length, die size and tiling.

## In short

```bash
# container, from /home/workspace
python3 scripts/measure_accounts.py gemma7b 512     # -> results/accounts/gemma7b_S512.json
```

## The models

`scripts/model_configs.py` holds the model registry:

| key | model | layers | hidden size | FFN size | heads (query / K-V) |
|---|---|---|---|---|---|
| `opt1.3b` | OPT-1.3B | 24 | 2048 | 8192 | 32 |
| `opt6.7b` | OPT-6.7B | 32 | 4096 | 16384 | 32 |
| `opt13b` | OPT-13B | 40 | 5120 | 20480 | 40 |
| `gemma7b` | Gemma-7B | 28 | 3072 | 24576, gated | 16 / 16, head size 256 |
| `qwen2.5-1.5b` | Qwen2.5-1.5B | 28 | 1536 | 8960, gated | 12 / 2 |
| `ref2p7b` | 2.7B-class reference | 32 | 2560 | 10240 | 32 |

To add a model, add an entry with the shapes from its `config.json`, the maximum context, the position encoding and the source:

```python
"mymodel": dict(
    cfg=dict(d_model=4096, n_heads=32, d_ff=11008, n_layers=32, name="my-model", vocab=32000,
             head_dim=128, n_kv_heads=8, ffn_gated=True, activation="swiglu"),
    max_positions=4096, positions="RoPE", norm="RMSNorm",
    sources=[{"url": "https://huggingface.co/<org>/<model>/blob/main/config.json", "retrieved": "<date>", "values": "..."}],
    notes="..."),
```

`head_dim` and `n_kv_heads` default to `d_model / n_heads` and `n_heads`. `ffn_gated=True` maps the gate and up projections side by side in the first FFN layer.

`python3 scripts/model_configs.py` (host) checks every entry. It writes, per model, the operator shapes, the dies per layer, and the context lengths at which attention still fits one CIM die (`results/accounts/models/`).

## Measuring an account

`measure_accounts.py` runs every operator of one transformer block through CiMLoop, for prefill and decode:

- the weight-resident projections: QKV, output projection, the two FFN layers;
- the attention operators, if they fit a die.

Per operator it records the compute time, the write time, the energy, the dies of its legal split, and the data each die sends.

```bash
# container, from /home/workspace
python3 scripts/measure_accounts.py gemma7b 512                    # -> results/accounts/gemma7b_S512.json
python3 scripts/measure_accounts.py gemma7b 128 256 1024           # several sequence lengths, one file each
python3 scripts/measure_accounts.py gemma7b 512 --phases prefill   # one phase only
python3 scripts/measure_accounts.py --die-macros 16 gemma7b 512    # on the 16-macro die -> gemma7b_S512_m16.json
python3 scripts/measure_accounts.py --tiling col opt13b 512        # column splits only  -> opt13b_S512_tlcol.json
```

- **`--die-macros N`** measures every operator on the N-macro die variant ([03 Hardware](03_hardware.md)). Deployments with `--macros N` read these accounts.
- **`--tiling NAME`** sets how a weight matrix may be split over dies; deployments select the same name with `--tiling`:
  - `colrow` (default): split by output columns whenever that gives a legal split, otherwise by input rows. A column split gives each die a slice of the output. A row split gives each die partial sums of the whole output, which the next operator adds up.
  - `col`: column splits only.
  - `row`, `mixed`, `mixed2`: other preferences, listed in `TILINGS` of `scripts/experiment.py`.
- An existing account is completed, not overwritten: phases already present are skipped. Delete the file to measure again.

CiMLoop's run folders go to `workspace/outputs/` and are wiped between runs.

## Long contexts: `--attention-die-macros`

```bash
python3 scripts/measure_accounts.py --attention-die-macros 16 gemma7b 2048   # -> gemma7b_S2048_attn16.json
```

This option exists because of how an account is measured, not because the hardware changes.

1. **Why a standard account fails.** A standard account measures every operator of the block, including attention on a CIM die. Past a certain length, the K and V of attention no longer fit one standard die, so the standard measurement fails (2048 and 4096 tokens for Gemma-7B).
2. **What the deployment actually uses.** In every deployment of the paper, attention runs on the digital unit. Only the static projections are read from the account; the unit's attention cost is computed separately from the model shapes and the unit's parameters (`offload.unit_layer_cost`).
3. **What the option produces.** An account whose projection entries are derived exactly from a standard account of the same model: the largest length already measured, scaled to the new length, since their compute, energy and traffic scale with the number of tokens. Its attention entries are measured on an N-macro die only so that the file is complete. **A standard account of the same model must exist first**, e.g. `gemma7b_S1024.json`.
4. **How deployments use it.** When a deployment with a digital unit needs `gemma7b_S2048.json` and it does not exist, `run_experiments.py` uses `gemma7b_S2048_attn*.json` instead. Its attention entries are ignored there.

## The reference account

```bash
python3 scripts/measure_reference_account.py     # container -> results/reference/reference_2p7b_S512.json
```

This measures one block of the 2.7B-class model. The BookSim libraries ([07 Validation](07_validation.md)) and the `ref2p7b` deployments use it.

## Weights and value distributions

Weights stay resident in the arrays: they are programmed once and not charged per inference. The analog energy of an operation depends on the values it processes. All accounts use the distributions of facebook/opt-2.7b in `models/workloads/opt_2p7b/`. `scripts/extract_value_histograms.py` regenerates them; it needs torch and transformers and downloads the model.

## The LM head

The accounts cover the repeated transformer blocks only. For the full-request energy of [09 GPU comparison](09_gpu_comparison.md), `measure_model_end.py` measures the LM head and adds the embedding read:

```bash
python3 scripts/measure_model_end.py                  # container: opt6.7b, gemma7b, opt13b
python3 scripts/measure_model_end.py mymodel          # adds or updates one model
```

The result goes to `results/accounts/model_end_costs.json`.

# 04 Workload: the per-operator account

The evaluator never runs the mapper. It reads a frozen per-operator
account: for each operator of one transformer block, in prefill and in
decode, the compute time, the weight-write time, the energy, the number
of dies the operator spans and its die-level flow volumes. This page says
how that account is produced and what changing the model involves.

## The shipped account

`analysis/scale_2p7b_per_op.json`, produced by `scripts/run_2p7b_block.py`
for the 2.7B class:

| field | value |
|---|---|
| model shape | d_model 2560, 32 heads, d_ff 10240, 32 layers |
| sequence | S = 512, batch 1, serial prefill; decode = one query row over a 512 cache |
| operators per block | qkv_proj, attention (one die), out_proj, ffn1, ffn2 |
| dies per operator | 4, 1, 2, 5, 5 (17 per layer, 544 for the model) |
| operand values | real histograms extracted from facebook/opt-2.7b (`models/workloads/opt_2p7b/`) |
| device | the calibrated NeuRRAM-class macro, 10.14 us per row |

Layer-level terms that the mapper does not produce (softmax, GELU,
LayerNorm, residual adds on the digital unit; the K/V write) are added by
the evaluator from closed forms in `scripts/llm_workload.py`, at the
digital unit declared in the fabric.

## Produce the account

```bash
python3 scripts/run_2p7b_block.py              # -> analysis/scale_2p7b_per_op.json (the frozen name)
python3 scripts/run_2p7b_block.py gpt2_medium  # -> analysis/scale_2p7b_per_op_gpt2_medium.json
```

The optional argument names the operand-histogram set under
`models/workloads/`; with any value other than `opt_2p7b` the output
file carries that name, so the frozen file is not touched. The run makes
ten mapper calls (five operators, two phases) and prints one line per
operator with its energy, compute time and die-level flow volumes. Each
call is a full Timeloop mapper search on a 2.7B-class operator; budget
hours for the whole run (on a busy host the first operator alone ran
for more than 45 minutes).

Two settings are read at the top of the script:

- `CFG = lw.GptConfig(d_model=2560, n_heads=32, d_ff=10240, n_layers=32,
  name="gpt-2.7B-class")` and `S=512` in the `block_ops` calls. Change
  them here for another model.
- `CIMSIM_FABRIC` defaults to `models/fabric/mlx300_multidie.yaml`
  inside this script. That is the fabric the mapper tiles each operator
  on; the die-set sizes are the tiling planner's answer on the
  power-of-two fan-out grid. The evaluator recomputes them with the same
  planner on its own fabric, and the two must agree; on the shipped
  account they do (4, 1, 2, 5, 5).

The value histograms for a new model come from a torch-only extraction
in the style of `scripts/extract_opt2p7b_hists.py`, which hooks one
forward pass of the Hugging Face model and writes the 31-bin histograms
per layer. It needs `torch` and network access to download the model;
run it in a separate process, never in the same interpreter as Timeloop.
Without real histograms, pass `gpt2_medium` to borrow that set; the
energy then carries a labelled approximation, the latency does not
change.

## Use a different account

Every `cimsim_cli.py` subcommand takes `--workload <account JSON>`; the
default is the frozen file. The account's `config` block carries the
model shape and S, so the die-set inventory, the baselines, the search
and the band all follow the new model without further edits:

```bash
python3 scripts/cimsim_cli.py baseline --workload analysis/scale_2p7b_per_op_gpt2_medium.json --rule random --out analysis/r_gpt2.json
python3 scripts/cimsim_cli.py evaluate --workload analysis/scale_2p7b_per_op_gpt2_medium.json --deployment analysis/r_gpt2.json --bandwidth 0.4 --phases prefill --loads 0
```

The fabric must have at least as many die slots as the model needs
(layers times dies per layer). In Python the same class the command line
uses is `cimsim_cli.Workload(fabric, path)`, a `Workload2p7B` on an
explicit fabric and account:

```python
import sys
sys.path.insert(0, "/home/workspace")
from scripts import fabric as fm, cimsim_cli as cli, search_eval as se, search_baselines as sb
W = cli.Workload(fm.from_yaml(cli.DEFAULT_FABRIC), "/home/workspace/analysis/scale_2p7b_per_op_gpt2hist.json")
W.port_ratio = 2.0
print(f"{se.score(sb.generate('random', W, seed=0), W, d2d_gbps=0.4).t_opt_s * 1e3:.2f} ms")
```

## Limits of the account

- **Sequence length and batch.** S is baked into the account (P = S rows
  in prefill). A different S is a new mapper run. Batch is 1; there is no
  batching axis in the evaluator.
- **Operator set.** The block chain is qkv, attention, out, ffn1, ffn2.
  Models with a different block structure (MoE, grouped-query attention
  with a separate KV projection) need the chain in
  `llm_workload.block_ops` and `block_chain` extended; that is a code
  change, not a configuration.
- **What is measured and what is assumed.** Compute time, write time and
  matrix energy are the mapper's on the calibrated macro. Digital-unit
  time and energy use the declared lanes, clock and per-op energies.
  Attention on the die is one die by construction; the offloaded
  variant prices the external unit from the fabric's `attention_unit`
  block.
- **Device speed.** The account is at the fabric's row time. The
  evaluator's `device_scale` divides the matrix compute part alone; the
  phase diagram uses it to sweep the device axis. It does not rerun the
  mapper.

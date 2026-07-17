"""Regenerate the sequence-length and KV-cache figures with a committed source.

These three SUMMARY figures previously had no generating script in the repo (they
came from ad-hoc code), and attention_share_vs_seqlen additionally predates the
append-only K/V write fix, so its decode-side energy was inflated 512x. This script
is now their single re-runnable source:

  analysis/attention_share_vs_seqlen.png   attention share of block energy/latency vs S
  analysis/kv_cache_vs_genlen.png          offloaded-KV DRAM traffic energy vs G
  analysis/energy_with_without_kv.png      decode energy with vs without the KV term

Usage: python3 analyze_seqlen_kv.py            (sequential, 1 core)
"""
import os, sys

sys.path.insert(0, "/home/workspace")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from scripts import llm_workload as lw

OUT = "/home/workspace/analysis"
os.makedirs(OUT, exist_ok=True)
cfg = lw.GptConfig()

SEQ_LENS = [64, 128, 256, 512, 1024]
ATTN = {"qk^t", "av"}

# ---------------------------------------------------------------- fig 1: vs S
share_E, share_L = [], []
for S in SEQ_LENS:
    print(f"=== prefill block, S={S} ===", flush=True)
    rs = lw.run_block(cfg, S=S, phase="prefill", verbose=False)
    e_att = sum(r["total_J"] for r in rs if r["op"].name in ATTN)
    e_tot = sum(r["total_J"] for r in rs)
    l_att = sum(r["compute_latency_s"] + r["dist_latency_s"] + r["write_latency_s"]
                for r in rs if r["op"].name in ATTN)
    l_tot = sum(r["compute_latency_s"] + r["dist_latency_s"] + r["write_latency_s"]
                for r in rs)
    share_E.append(100 * e_att / e_tot)
    share_L.append(100 * l_att / l_tot)
    print(f"    attention share: energy {share_E[-1]:.1f}%  latency {share_L[-1]:.1f}%")

plt.figure(figsize=(7, 4.5))
plt.plot(SEQ_LENS, share_E, "o-", label="energy share")
plt.plot(SEQ_LENS, share_L, "s--", label="latency share (stall-free)")
plt.xscale("log", base=2)
plt.xlabel("sequence length S (prefill)")
plt.ylabel("attention (QK$^T$+AV) share of block  [%]")
plt.title(f"Attention share vs sequence length ({cfg.name}, incl. K/V write)")
plt.grid(alpha=0.3); plt.legend()
p1 = os.path.join(OUT, "attention_share_vs_seqlen.png")
plt.tight_layout(); plt.savefig(p1, dpi=120); plt.close()
print(f"PNG -> {p1}")

# ---------------------------------------------------------------- fig 2: KV vs G
GENS = [64, 128, 256, 512, 1024, 2048]
kv = [lw.decode_kv_cost(cfg, g) for g in GENS]
plt.figure(figsize=(7, 4.5))
plt.plot(GENS, [k["read_energy_J"] for k in kv], "o-", label="KV read (~G$^2$)")
plt.plot(GENS, [k["write_energy_J"] for k in kv], "s--", label="KV write (~G)")
plt.xscale("log", base=2); plt.yscale("log")
plt.xlabel("generated tokens G")
plt.ylabel("DRAM traffic energy [J] (offloaded attention)")
plt.title(f"KV-cache traffic vs generation length ({cfg.name}, "
          f"{lw.E_DRAM_PER_WORD_J*1e12:.0f} pJ/word placeholder)")
plt.grid(alpha=0.3, which="both"); plt.legend()
p2 = os.path.join(OUT, "kv_cache_vs_genlen.png")
plt.tight_layout(); plt.savefig(p2, dpi=120); plt.close()
print(f"PNG -> {p2}")

# ------------------------------------------------- fig 3: decode +/- KV term
print("=== decode block, S=512 ===", flush=True)
rs = lw.run_block(cfg, S=512, phase="decode", verbose=False)
e_step = sum(r["total_J"] for r in rs) * cfg.n_layers   # whole model, one step
on_chip = [e_step * g for g in GENS]                     # resident attention (A)
with_kv = [e_step * g + k["kv_total_J"] for g, k in zip(GENS, kv)]  # offloaded (B side)
plt.figure(figsize=(7, 4.5))
plt.plot(GENS, on_chip, "o-", label="attention resident (no KV traffic)")
plt.plot(GENS, with_kv, "s--", label="attention offloaded (+KV DRAM traffic)")
plt.xscale("log", base=2); plt.yscale("log")
plt.xlabel("generated tokens G")
plt.ylabel("decode energy, whole model [J]")
plt.title(f"Decode energy with vs without the KV-cache term ({cfg.name})")
plt.grid(alpha=0.3, which="both"); plt.legend()
p3 = os.path.join(OUT, "energy_with_without_kv.png")
plt.tight_layout(); plt.savefig(p3, dpi=120); plt.close()
print(f"PNG -> {p3}")

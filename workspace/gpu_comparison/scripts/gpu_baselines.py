"""GPU baselines of the two groups (section 2): the A100 point of the CXL-PNM
paper (values as read by the author, carried with their derivation) and the
AGX Thor Gemma-7B Q8_0 per-request CSV of Hydra (recomputed from the raw
fields), plus the input-length frequency table.

    python3 gpu_comparison/scripts/gpu_baselines.py -> gpu_comparison/gpu_baselines.csv, sources/hydra_input_lengths.csv, sources/hydra_requests.csv
"""
import csv
import hashlib
import os
import statistics
from collections import Counter

G = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(G, "sources", "data", "hydra_unified", "media", "amir", "data", "hydra-results", "thor", "results_llamacpp_thor", "UNIFIED_gemma-7B_Q8_0_.csv")


def main():
    rows = list(csv.DictReader(open(CSV)))
    sha = hashlib.sha256(open(CSV, "rb").read()).hexdigest()
    reqs = []
    for r in rows:
        t = float(r["end_to_end_latency"]); pv = float(r["vin_cur_prompt_mean"]); pg = float(r["vdd_gpu_cur_prompt_mean"])
        reqs.append({"prompt_number": r["prompt_number"], "input_tokens": int(r["total_number_of_tokens_in_input"]), "output_tokens": int(r["total_number_of_tokens_in_output"]), "end_to_end_latency_s": t,
                     "prefill_time_s": float(r["prefill_time"]), "total_generation_time_s": float(r["total_generation_time"]), "execution_window_s": float(r["prefill_time"]) + float(r["total_generation_time"]),
                     "vin_cur_prompt_mean_mW": pv, "vdd_gpu_cur_prompt_mean_mW": pg, "E_board_J": pv / 1000 * t, "E_gpu_rail_J": pg / 1000 * t, "E_board_per_output_token_J": pv / 1000 * t / int(r["total_number_of_tokens_in_output"])})
    with open(os.path.join(G, "sources", "hydra_requests.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(reqs[0].keys())); w.writeheader(); w.writerows(reqs)
    cnt = Counter(r["input_tokens"] for r in reqs)
    with open(os.path.join(G, "sources", "hydra_input_lengths.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["input_tokens", "count", "output_tokens"]); [w.writerow([L, c, 500]) for L, c in sorted(cnt.items())]
    mT = statistics.mean(r["end_to_end_latency_s"] for r in reqs); mW = statistics.mean(r["execution_window_s"] for r in reqs); mE = statistics.mean(r["E_board_J"] for r in reqs); mG = statistics.mean(r["E_gpu_rail_J"] for r in reqs)
    base = [
        {"group": "A_opt13b_a100", "model": "OPT-13B", "device": "1 x NVIDIA A100 40 GB (DGX A100, 1.55 TB/s; section VII p. 978)", "backend": "FasterTransformer (section VII)", "workload": "single device, 64 input tokens, 1024 output tokens (section VII: 64 input and up to 1024 output tokens; section VIII-A: run on a single device to stress compute and bandwidth)", "quantity": "output throughput", "value": 47.33, "unit": "output tokens/s", "kind": "figure reading (Fig. 10)", "source": "CXL-PNM, HPCA 2024, Fig. 10(a) p. 980 (bar label 47.33 at [64:1024], GPU series); verified against the paper PDF 2026-10-21; Fig. 10(b) gives 0.19 token/J for the GPU at the same point", "boundary": "GPU device (reported GPU power)"},
        {"group": "A_opt13b_a100", "model": "OPT-13B", "device": "1 x NVIDIA A100 40 GB", "backend": "FasterTransformer", "workload": "same", "quantity": "GPU power", "value": 253.0, "unit": "W", "kind": "reported in text", "source": "CXL-PNM, HPCA 2024, section VIII-A p. 979: the CXL-PNM device consumes 69.91% lower power than the GPU (253 Watts vs. 77.1 Watts) for processing 1024 output tokens with OPT-13B; verified against the PDF", "boundary": "GPU device"},
        {"group": "A_opt13b_a100", "model": "OPT-13B", "device": "1 x NVIDIA A100 40 GB", "backend": "FasterTransformer", "workload": "same", "quantity": "request time T = 1024 / q", "value": 1024 / 47.33, "unit": "s", "kind": "derived", "source": "1024 output tokens / 47.33 tokens/s (throughput includes prefill and generation; denominator = output tokens)", "boundary": "GPU device"},
        {"group": "A_opt13b_a100", "model": "OPT-13B", "device": "1 x NVIDIA A100 40 GB", "backend": "FasterTransformer", "workload": "same", "quantity": "request energy E = P T", "value": 253.0 * 1024 / 47.33, "unit": "J", "kind": "derived", "source": "253 W x 21.635 s", "boundary": "GPU device"},
        {"group": "A_opt13b_a100", "model": "OPT-13B", "device": "1 x NVIDIA A100 40 GB", "backend": "FasterTransformer", "workload": "same", "quantity": "energy per output token", "value": 253.0 / 47.33, "unit": "J/token", "kind": "derived", "source": "E / 1024 = P / q (0.19 token/J in the figure)", "boundary": "GPU device"},
        {"group": "A_opt13b_a100", "model": "OPT-13B", "device": "1 x NVIDIA A100 40 GB", "backend": "FasterTransformer", "workload": "same", "quantity": "GPU dtype / beam", "value": "", "unit": "", "kind": "not reported", "source": "not stated in sections VII-VIII (the accelerator side uses FP16 MACs, Table II / section V-C); GPU dtype and beam are not reported", "boundary": ""},
        {"group": "B_gemma7b_thor", "model": "Gemma-7B (Q8_0 weights)", "device": "NVIDIA Jetson AGX Thor (whole board)", "backend": "llama.cpp, full GPU offload, greedy, KV cache reuse", "workload": f"541 IFEval requests, batch 1, {min(cnt)}-{max(cnt)} input tokens (mean {statistics.mean(r['input_tokens'] for r in reqs):.3f}, {len(cnt)} distinct), 500 output tokens each", "quantity": "mean request time (end_to_end_latency)", "value": mT, "unit": "s", "kind": "recomputed from the per-request CSV", "source": f"Hydra (arXiv:2608.25053) repo amirtaherin/hydra commit 1879bf8aff86ff8ed5388b245a351ff20a785f38, data/unified -> {os.path.relpath(CSV, G)}, sha256 {sha}", "boundary": "board"},
        {"group": "B_gemma7b_thor", "model": "Gemma-7B (Q8_0 weights)", "device": "NVIDIA Jetson AGX Thor", "backend": "llama.cpp", "workload": "same", "quantity": "mean execution window (prefill_time + total_generation_time)", "value": mW, "unit": "s", "kind": "recomputed", "source": "same CSV", "boundary": "board"},
        {"group": "B_gemma7b_thor", "model": "Gemma-7B (Q8_0 weights)", "device": "NVIDIA Jetson AGX Thor", "backend": "llama.cpp", "workload": "same", "quantity": "mean board request energy E = vin_cur_prompt_mean / 1000 x end_to_end_latency", "value": mE, "unit": "J", "kind": "recomputed (mean power x request time, per request, then averaged)", "source": "same CSV, fields vin_cur_prompt_mean (mW), end_to_end_latency (s)", "boundary": "whole board input (VIN)"},
        {"group": "B_gemma7b_thor", "model": "Gemma-7B (Q8_0 weights)", "device": "NVIDIA Jetson AGX Thor", "backend": "llama.cpp", "workload": "same", "quantity": "mean board energy per output token", "value": mE / 500, "unit": "J/token", "kind": "recomputed", "source": "same", "boundary": "whole board input"},
        {"group": "B_gemma7b_thor", "model": "Gemma-7B (Q8_0 weights)", "device": "NVIDIA Jetson AGX Thor", "backend": "llama.cpp", "workload": "same", "quantity": "mean GPU-rail request energy (vdd_gpu_cur_prompt_mean) -- a component of the board energy, diagnostic only", "value": mG, "unit": "J", "kind": "recomputed", "source": "same CSV, field vdd_gpu_cur_prompt_mean", "boundary": "GPU power rail (subset of board)"},
        {"group": "B_gemma7b_thor", "model": "Gemma-7B (Q8_0 weights)", "device": "NVIDIA Jetson AGX Thor", "backend": "llama.cpp", "workload": "same", "quantity": "activation / accumulation precision", "value": "", "unit": "", "kind": "backend property", "source": "llama.cpp Q8_0: 8-bit block-quantised weights (scale per 32); activations quantised to 8-bit (Q8_1 / Q8_K) for the dot products with 32-bit float accumulation on the GPU path", "boundary": ""},
    ]
    with open(os.path.join(G, "gpu_baselines.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(base[0].keys())); w.writeheader(); w.writerows(base)
    print(f"B: n {len(reqs)} T {mT:.5f} window {mW:.5f} E_board {mE:.5f} J/token {mE/500:.5f} E_gpu_rail {mG:.5f}; distinct lengths {len(cnt)}; sha {sha[:16]}")


if __name__ == "__main__":
    main()

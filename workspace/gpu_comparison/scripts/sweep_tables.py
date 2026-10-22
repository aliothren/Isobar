"""Combine the sweep files and write the pivot tables (markdown) of the report."""
import csv
import glob
import os

G = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rows = []
for p in sorted(glob.glob(os.path.join(G, "sweep", "sweep_*.csv"))):
    if p.endswith("sweep_all.csv"):
        continue
    rows += list(csv.DictReader(open(p)))
with open(os.path.join(G, "sweep", "sweep_all.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
F = lambda r, k: float(r[k])
L = ["# 配置扫描结果表（固定布局重新定价；GPU 基线 A100 21.64 s / 5474 J，Thor 24.83 s / 1899 J）", "", f"共 {len(rows)} 个点：模型 × 每 die 宏数 {{4,8,16,32}}（OPT-13B 另有 8 宏列切分）× 器件行速率 4 档 × mesh 带宽 4 档 × KV 带宽 3 档。完整数据 `sweep/sweep_all.csv`。表中每格为“请求时间 s / 加速比 ×”，能量只随宏数与切分变化，列在第一张表。", ""]
def tab(title, model, split, fix, rowkey, colkey, rowvals, colvals, fmt):
    L.append(f"## {title}"); L.append("")
    L.append("| " + rowkey + " | " + " | ".join(colvals) + " |"); L.append("| --- |" + " --- |" * len(colvals))
    for rv in rowvals:
        cells = []
        for cv in colvals:
            m = [r for r in rows if r["model"] == model and r["qkv_split"] == split and r[rowkey] == rv and r[colkey] == cv and all(r[k] == v for k, v in fix.items())]
            cells.append(fmt(m[0]) if m else "-")
        L.append(f"| {rv} | " + " | ".join(cells) + " |")
    L.append("")
for model, gpu in (("opt13b", "OPT-13B 对 A100"), ("gemma7b", "Gemma-7B 对 Thor")):
    # energy and dies per capacity
    L.append(f"## {gpu}：容量与能量（与速率、带宽无关）"); L.append(""); L.append("| 宏/die | 切分 | CIM die / 网格 | E_request (J) | J/token | 能效倍数 | 节能 |"); L.append("| --- | --- | --- | --- | --- | --- | --- |")
    seen = set()
    for r in rows:
        if r["model"] != model or (r["die_macros"], r["qkv_split"]) in seen:
            continue
        seen.add((r["die_macros"], r["qkv_split"]))
        L.append(f"| {r['die_macros']} | {r['qkv_split']} | {r['n_cim_dies']} / {r['grid']} | {F(r,'E_request_J'):.2f} | {F(r,'E_per_output_token_J'):.4f} | {F(r,'energy_advantage'):.0f}× | {F(r,'energy_saving')*100:.2f}% |")
    L.append("")
    fmt = lambda r: f"{F(r,'T_request_s'):.2f} / {F(r,'speedup'):.2f}×"
    macs = ["4", "8", "16", "32"]; mesh = ["0.4", "1.6", "4.0", "12.5"]; rates = ["neurram_10.14us", "isaac_1.6us", "hermes_4phase_0.52us", "hermes_1phase_0.133us"]; kvs = ["25.6", "51.2", "136.0"]
    tab(f"{gpu}：宏数 × mesh 带宽（NeuRRAM 速率，KV 25.6 GB/s）", model, "colrow", {"device_rate": "neurram_10.14us", "kv_gbps": "25.6"}, "die_macros", "mesh_gbps", macs, mesh, fmt)
    tab(f"{gpu}：器件速率 × mesh 带宽（8 宏，KV 25.6 GB/s）", model, "colrow", {"die_macros": "8", "kv_gbps": "25.6"}, "device_rate", "mesh_gbps", rates, mesh, fmt)
    tab(f"{gpu}：KV 带宽 × mesh 带宽（8 宏，NeuRRAM 速率）", model, "colrow", {"die_macros": "8", "device_rate": "neurram_10.14us"}, "kv_gbps", "mesh_gbps", kvs, mesh, fmt)
    tab(f"{gpu}：全部最快组合（HERMES 1-phase 速率，KV 136 GB/s）宏数 × mesh", model, "colrow", {"device_rate": "hermes_1phase_0.133us", "kv_gbps": "136.0"}, "die_macros", "mesh_gbps", macs, mesh, fmt)
    if model == "opt13b":
        tab("OPT-13B 列切分 QKV（8 宏）：器件速率 × mesh 带宽（KV 25.6 GB/s）", model, "col", {"die_macros": "8", "kv_gbps": "25.6"}, "device_rate", "mesh_gbps", rates, mesh, fmt)
        tab("OPT-13B 列切分 QKV（8 宏）：KV 带宽 × mesh 带宽（NeuRRAM 速率）", model, "col", {"die_macros": "8", "device_rate": "neurram_10.14us"}, "kv_gbps", "mesh_gbps", kvs, mesh, fmt)
# extremes
L.append("## 极值"); L.append("")
for model in ("opt13b", "gemma7b"):
    ms = [r for r in rows if r["model"] == model]
    lo = min(ms, key=lambda r: F(r, "speedup")); hi = max(ms, key=lambda r: F(r, "speedup"))
    L.append(f"- {model}: 最慢 {F(lo,'T_request_s'):.2f} s（{lo['die_macros']} 宏 {lo['qkv_split']}，{lo['device_rate']}，mesh {lo['mesh_gbps']}，KV {lo['kv_gbps']}；{F(lo,'speedup'):.2f}×），最快 {F(hi,'T_request_s'):.2f} s（{hi['die_macros']} 宏 {hi['qkv_split']}，{hi['device_rate']}，mesh {hi['mesh_gbps']}，KV {hi['kv_gbps']}；{F(hi,'speedup'):.2f}×）；超过 GPU 速度的点 {sum(1 for r in ms if F(r,'speedup') > 1)} / {len(ms)}。")
open(os.path.join(G, "sweep", "sweep_tables.md"), "w").write("\n".join(L) + "\n")
print(len(rows), "->", os.path.join(G, "sweep", "sweep_tables.md"))

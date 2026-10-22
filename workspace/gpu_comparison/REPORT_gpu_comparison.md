# GPU 文献基线对照：执行报告

> 2026-10-22 能耗账本核查后：最终汇报量为 **modeled dynamic energy**（每请求能耗、每输出 token 能耗、GPU/CIM 能耗比、分项构成），见 `AUDIT_energy.md`、`energy_breakdown.csv`；本报告中的时延只用于内部核算。LM head 能量已按词表 / 补齐宽度修正（OPT-13B −0.26%，Gemma −0.11%），每个配置增加 16-bit KV 对应行并以其为主比较（OPT-13B 58.61 J、93×；Gemma 11.45 J、166×）；互联能耗采用按通信量计价的模型（与 Gemini HPCA 2024 对 GRS / UCIe clock-forwarding 链路的处理一致），“全部链路常开”只作为情景估算保留。

日期：2026-10-21。目录 `workspace/gpu_comparison/`：`sources/`（来源记录、Hydra 原始 CSV 与长度频数）、`configs/`（8 个配置与资源表）、`scripts/`（取数 `gpu_baselines.py`、请求成本引擎 `cim_request.py`、`run_all.sh`、汇总 `summarize.py`）、`gpu_baselines.csv`、`cim_requests.csv`（每配置每输入长度一行，含阶段时间与能量分项）、`comparison_summary.csv`。复现：`python3 gpu_comparison/scripts/gpu_baselines.py && bash gpu_comparison/scripts/run_all.sh && python3 gpu_comparison/scripts/summarize.py`。

## 1. GPU 基线

| 组 | 设备 / 后端 | 负载 | 请求时间 | 请求能耗 | J / 输出 token | 能量边界 |
| --- | --- | --- | --- | --- | --- | --- |
| A | A100 40 GB，FasterTransformer | OPT-13B，64:1024，单请求 | 21.635 s（1024 / 47.33） | 5473.74 J（253 W × T） | 5.345 | GPU 器件功耗 |
| B | Jetson AGX Thor，llama.cpp Q8_0 | Gemma-7B，541 个 IFEval 请求，13–345 输入 token（84 种长度），各 500 输出 token | 24.82638 s（执行窗口 24.82547 s） | 1898.68 J（逐请求 vin_cur × 时间后取均值） | 3.797 | 整板输入；GPU 电源轨 794.70 J 仅作分项 |

A 组数值已对照论文 PDF 核实：§VII（p. 978）DGX A100 40 GB / 1.55 TB/s、FasterTransformer、单设备、64 输入 / 最多 1024 输出；§VIII-A（p. 979）"253 Watts vs. 77.1 Watts"；Fig. 10（p. 980）GPU 在 [64:1024] 为 47.33 tokens/s、0.19 token/J；B 组由 CSV 原始字段重算，与待办文件的核对值逐位一致，CSV 哈希一致。

## 2. CIM 侧请求模型

请求 = 一次 L token 的 prefill + (O−1) 次单 token forward，第 j 次 forward 的有效上下文为 L+j（首 token 复用 prefill logits，与 Hydra 的 `llama_n_eval` = 499 对应）。静态 CIM 算子、数字逐元素运算和交接流量与查询行数严格成正比（S=128/256/512/1024 的实测 account 核对：compute、能量、die flow 均 ×2 关系，decode 项恒定），因此各长度由 S=512 的确认记录定价，attention/KV 项按上下文闭式计算。固定映射为各记录 prefill 512 的确认代表布局，两阶段共用：在该布局下 decode 的通信时间与 decode 专门搜索的布局相差不到 1%（OPT-13B 20.37 对 20.42 ms/token，Gemma 4.04 对 4.07 ms/token），因此没有重新搜索。

完整模型补齐项：embedding 读取（单元内存，50 pJ/word）、OPT 的位置嵌入加法、末端 norm、LM head（CIM 常驻，vocab 补到 2 的幂，OPT-13B 64 die、Gemma-7B 128 die，每生成 token 计算一行，含进出单元的接口估计）、argmax、Gemma 的 RoPE。KV 容量在最大上下文处均满足（OPT-13B 1087 token 0.445 GB，Gemma 845 token 0.19 GB），decode 全程为 materialized 算法、每层读一次 KV。

能量为动态能量：CIM 阵列与外围（account）、数字逐元素、单元 attention 计算、KV 内存、互联（10 pJ/word 平摊 + 额外跳）、模型末端。**平台没有静态 / 后台功耗模型**（fabric 的 `idle_power_w` 未设定），因此给出已计能量和保留能效优势所容许的剩余平均功率 P_remaining,max = (E_GPU − E_CIM,accounted) / T_CIM。

## 3. 结果

| 配置 | 要点 | T_CIM（s） | 其中 prefill | E_CIM（J） | J / token | 能效倍数 E_GPU/E_CIM | 节能 | 加速比 T_GPU/T_CIM | P_remaining,max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A0_ref | 8 macros，0.4 GB/s | 33.558 | 1.402 | 46.64 | 0.0455 | 117.4× | 99.15% | 0.64× | 161.7 W |
| A1_m16 | 16 macros，0.4 GB/s | 24.758 | 0.886 | 36.56 | 0.0357 | 149.7× | 99.33% | 0.87× | 219.6 W |
| A2_grs | 8 macros，12.5 GB/s | 12.914 | 0.186 | 46.64 | 0.0455 | 117.4× | 99.15% | 1.68× | 420.3 W |
| A3_m16_grs_kv | 16 macros，12.5 GB/s，KV 51.2 GB/s | 7.568 | 0.151 | 36.56 | 0.0357 | 149.7× | 99.33% | 2.86× | 718.4 W |
| A4_col | 列切分 QKV（2400 die，49×49），0.4 GB/s | 18.405 | 0.507 | 45.02 | 0.0440 | 121.6× | 99.18% | 1.18× | 295.0 W |
| A5_col_grs | 列切分 QKV，12.5 GB/s | 11.958 | 0.127 | 45.02 | 0.0440 | 121.6× | 99.18% | 1.81× | 454.0 W |
| B0_ref | 8 macros，0.4 GB/s | 4.247 | 0.245 | 9.75 | 0.0195 | 194.7× | 99.49% | 5.85× | 444.8 W |
| B1_m16 | 16 macros，0.4 GB/s | 4.118 | 0.236 | 8.16 | 0.0163 | 232.8× | 99.57% | 6.03× | 459.1 W |
| B2_grs | 8 macros，12.5 GB/s | 2.181 | 0.066 | 9.75 | 0.0195 | 194.7× | 99.49% | 11.38× | 866.0 W |
| B3_m16_grs_kv | 16 macros，12.5 GB/s，KV 51.2 GB/s | 1.484 | 0.065 | 8.16 | 0.0163 | 232.8× | 99.57% | 16.73× | 1273.8 W |

B 组为 541 个请求按长度频次加权的均值，比值为均值之比；A 组为单请求。

**时间分项（请求占比）。** A0：互联 65.9%、KV 内存 28.1%、CIM 计算 5.3%；decode 每 token 约 31.5 ms，其中交接 20.4 ms、KV 重读 9.2 ms（上下文均值约 600 token，246 MB / 25.6 GB/s）、CIM 1.6 ms。交接的 20.4 ms 按类型分：qkv→数字单元 15.1 ms（40 层；行切分的 10 个 qkv die 各送一行 15360 列的 2 B 部分和，每层 307 KB，最忙链路 153,600 字 / 0.4 GB/s）、ffn1→ffn2 2.2 ms、out_proj→ffn1 1.6 ms、单元→out_proj 1.4 ms、跨层 0.08 ms。改用列切分 QKV（A4）后 qkv→单元每层只送 15 KB，decode 交接降到约 7.6 ms/token，请求时间 18.4 s，已快于 A100（1.18×），能量基本不变。prefill 只占 4%。B0：互联 51.8%、KV 31.4%、CIM 14.6%。把 mesh 提到 GRS 档后交接项缩到 6–12%，KV 重读成为主项（A2 73%、B2 61%）；再把 KV 带宽提到 51.2 GB/s 后 CIM 计算占比升到 23–42%。

**能量分项。** 所有配置中 CIM 阵列及外围占 50–66%，KV 内存 18–33%，互联 6–22%（0.4 与 12.5 GB/s 下互联能量相同，按字节计价），模型末端 1–6%（Gemma 的 LM head 128 die 每 token 1.0 mJ）。16 macros 使 die 数减半、互联能量降一半以上，总能量降 16–22%。

**解读。** 能耗差两个数量级是动态能量对 GPU 实测功率的比较：GPU 侧包含整卡 / 整板静态功耗，CIM 侧没有。按 P_remaining,max，只要整个 CIM 系统在请求期间的平均后台功率低于 162 W（A0）或 445 W（B0），能效优势仍然成立；对 2200 + 64 个 ReRAM die 加一个数字单元的封装，这个预算的量级是宽裕的，但需要静态功耗参数才能给出总能量估计。时间上，OPT-13B 在参考 0.4 GB/s mesh 下比 A100 慢（0.64×）：decode 每 token 的 199 次交接在 0.4 GB/s 链路上要 20 ms，这是通信敏感实验里同一个瓶颈；GRS 档链路和更宽的 die 把它压到 A100 的 2.9 倍速度；列切分 QKV 在 0.4 GB/s 下即可持平以上（1.18×）。Gemma 对 Thor 在参考配置就快 5.9×，因为 Thor 本身每 token 约 50 ms。

## 4. 边界与假设

- 精度：CIM 8-bit 权重/激活、2 B 部分和、16-bit 数字中间量、KV 1 B；A100 点的 dtype 未报告（PNM 为 FP16）；Hydra Q8_0 为 8-bit 块量化权重、8-bit 量化激活、FP32 累加。
- GRS 档配置复用 0.4 GB/s 下搜索的布局并重新定价（不重新搜索）；通信在这些配置里只占 6–12%，重新搜索的影响有限。
- 模型末端：LM head 额外 die 按常驻计容量，其交接按端口下界估计（placement-free）；embedding 表放在单元内存。
- 未建模：静态 / 后台功耗、PHY 常开功耗、阶段切换搬运（固定映射下为零）、GPU 侧 tokenizer / 采样之外的主机开销。
- 单元 KV 为单通道串行读写模型（读写不并发），与既有设定一致。

## 5. 交付清单

`gpu_baselines.csv`（12 行）、`sources/hydra_requests.csv`（541 行）、`sources/hydra_input_lengths.csv`（84 行）、`cim_requests.csv`（10 配置；A 组每配置 1 行，B 组 84 行）、每配置的 `cim_requests_<id>_meta.json`（布局 ID、T 复现核对、资源）、`comparison_summary.csv`（10 行，含分项占比与 P_remaining）、`configs/resources.csv`。

## 6. 配置扫描（2026-10-21 补充）

`scripts/sweep.py` 在固定布局上重新定价四个轴（无重新搜索）：每 die 宏数 4 / 8 / 16 / 32（各自的实测 account 与已确认 / 探索布局）；器件行速率 NeuRRAM 10.14 µs（参考）、ISAAC 1.6 µs（设计点）、HERMES 4-phase 0.52 µs、HERMES 1-phase 0.133 µs（由公开峰值推得；能量按每次运算不变处理）；mesh 每方向带宽 0.4（HERMES 类）、1.6、4.0（ISAAC 类片上链路）、12.5 GB/s（Simba GRS）；KV 内存带宽 25.6（LPDDR4 两通道）、51.2（LPDDR5 两通道）、136 GB/s（一个 LPDDR5X ×128 封装，CXL-PNM 论文 Table I）。OPT-13B 另含 8 宏列切分 QKV。共 432 点，数据 `sweep/sweep_all.csv`，透视表 `sweep/sweep_tables.md`。

要点：
- 能量只随容量与切分变化（速率与带宽不改变每次运算和每字节的能量）：OPT-13B 73.5 / 46.6 / 36.6 / 33.3 J（4 / 8 / 16 / 32 宏），Gemma 13.6 / 9.8 / 8.2 / 7.6 J；能效倍数 75–164×（OPT-13B）、140–252×（Gemma）。
- 时间上三条轴的作用顺序：mesh 带宽（0.4 → 1.6 GB/s 把 OPT-13B 参考点从 33.6 s 降到 17.1 s）、KV 带宽（decode 每 token 重读 KV：25.6 → 136 GB/s 在 12.5 GB/s mesh 下从 12.9 s 降到 5.3 s）、容量（32 宏在 0.4 GB/s 下 16.5 s）；器件速率影响最小（prefill 与 decode 的 CIM 计算只占 5–15%，四档速率在参考 mesh 下只差 5%）。
- OPT-13B 在 240 个点中 211 个快于 A100；慢于 A100 的都是 0.4 GB/s mesh 下的行切分配置（以及 4 宏在 1.6 GB/s 的一个点）。列切分 QKV 在 0.4 GB/s 下已达 1.18×。最快组合（32 宏、HERMES 1-phase、12.5 GB/s、136 GB/s KV）2.32 s，9.3×。
- Gemma 全部 192 点快于 Thor：参考 5.85×，最快 58.7×（0.42 s）。

# Isobar: the framework and its results

This document gives an account of Isobar and of what it shows, in the state of the final paper (*Scaling Up Analog CIM: A Simulation Framework for Topology-Aware Mapping*, [`../../Isobar_Arxiv.pdf`](../../Isobar_Arxiv.pdf)). [`paper_numbers.md`](paper_numbers.md) gives every number with its denominator, statistic and source file. [`../../formulation.md`](../../formulation.md) writes out the cost model. [`../../docs/02_final_pipeline.md`](../../docs/02_final_pipeline.md) lists the commands that produced the data.

## 1. The question

Analog compute-in-memory (CIM) runs matrix multiplications in place in ReRAM arrays. Deploying large language models therefore means spreading billions of resident weights over many dies. Each weight matrix is partitioned, and its blocks are assigned to physical CIM locations. With the model and the hardware held fixed, that assignment alone changes which links and ports the activations and partial sums share, and therefore how long the communication takes. We call the assignment of resident computations to locations within fixed hardware **topology-aware mapping**.

Existing simulators do not capture this dependence. Digital chiplet frameworks model pipelining and weight reloading, not the decomposition and communication of resident analog execution. Analog CIM simulators model local operators or prescribed chiplet organisations, and price communication by aggregate metrics such as total words or word-hops. These metrics cannot see contention on shared resources. Isobar derives communication from legal CIM decompositions and heterogeneous execution, prices contention on shared links and ports from the physical placement, and uses that model for three purposes:

- a phase analysis of when the mapping matters;
- a mapping search;
- system-level comparisons.

## 2. The framework

**Hardware.** Four levels: package, die, macro, crossbar array.

- **Package.** Homogeneous CIM dies on a 2-D mesh with XY routing. Digital units in reserved slots run the input-dependent attention and hold the K/V cache.
- **Die.** In the reference, 8 macros around a global buffer, plus a digital vector unit for the element-wise operators.
- **Macro.** 256 × 256 RRAM arrays with 4 bits per cell and differential weights, data converters, buffers and digital accumulation; CiMLoop's NeuRRAM-class model, one input row in 10.14 µs.

Array size, die capacity, mesh geometry and bandwidth, port ratio and the organisation of the digital resources are all configurable.

**Mapping space.** A mapping is p = (γ, α, β). γ chooses the layer groups and the legal tiling of every static operator onto dies; α places the logical dies on package slots; β assigns macros within each die. A column split (over output channels) sends the whole input to every consumer die. A row split (over input channels) produces partial sums that cross the network at partial-sum width and are reduced at the consumer.

**Costs.** R(s) is everything that is not package communication:

- CIM compute at row rate s, and writes;
- digital element-wise work;
- the units' attention compute;
- K/V-memory service.

The CIM terms come from per-operator accounts, one CiMLoop mapper run per operator. Every hand-off between consecutive operators is a stage of simultaneously ready transfers. These are routed onto directed links (bandwidth B), CIM die ports (κB) and digital-unit interfaces (fixed C_hub). A stage costs its propagation plus the load of its busiest resource divided by that resource's bandwidth, and H(p) is the sum over the stages. Package communication and local execution are serialised, T = R(s) + H(p). Inside a die, communication service overlaps with computation. Dynamic energy adds:

- CIM energy from the accounts;
- digital operations;
- the unit's MAC-equivalent operations (1 pJ each);
- K/V accesses (50 pJ per byte);
- 10 pJ per 8-bit word per hop on the mesh.

**Search.** Hierarchical DP–SA. An exact interval DP chooses the layer groups. Simulated annealing places the dies; incremental re-evaluation re-scores only the hand-offs a move touches. Small intra-die spaces are searched exhaustively. The baselines are the default fill (operators in chain order onto row-major slots), six prescribed rules (snake, least Manhattan, Gemini-style rectangular clustering, NMAP, heaviest first) and pools of random layouts. The main results use 500 random layouts and 10 annealer seeds with three starts each; the exploratory sweeps use 100 layouts and 5 seeds.

## 3. Phase analysis

For a mapping p and CIM rate s, the **inter-die boundary** B_c(p; s) is the lowest mesh bandwidth at which communication no longer exceeds the non-communication cost, H ≤ R(s). The **intra-die boundary** b(β; s) is the lowest bandwidth at which every operator's communication service hides under its computation. Over a set of evaluated mappings, the lowest and highest boundaries form an **envelope** B₋(s), B₊(s), which divides the bandwidth axis into three regions:

- below B₋, every mapping is communication-bound;
- above B₊, none is;
- in between, the mapping decides which side is reached.

At the reference CIM speed, B₊/B₋ is 2.67× across the 70 macro assignments of the FFN die and 4.17× across six Gemma-7B package layouts. Different mapping topologies therefore need substantially different bandwidths to reach the same boundary. A contour marks where the latency spread across mappings reaches 20%.

Projecting existing designs onto the diagrams relates the variation to real hardware: ISAAC, HERMES in its one- and four-phase modes, NeuRRAM, Mythic M1076, and Simba as the digital reference of ideal package provisioning. The NeuRRAM-derived configurations pair NeuRRAM's compute timing with HERMES's 0.4 GB/s link rate and Simba's 12.5 GB/s die-to-die rate. Most projected design points lie in regions sensitive to the mapping. Capacity expansion shifts the boundaries as well: when resident matrices span more dies, broadcasts, reductions and hand-offs change the shared-resource loads.

## 4. Exploration efficiency and validation

**Silicon.** Simba's seating experiment places one ResNet-50 layer on four chiplets moving from adjacent to the package corners. The measured latency rises to 2.53×. A pure resource bound stays flat (1.007×), because the busiest link does not change. Isobar's protocol estimate (round-serialised 17-flit packets paying the hop latency) gives 2.40×, a 5.1% relative error in the latency ratio.

**Packet-level simulation.** BookSim runs candidate libraries of a 2.7B-class layer on small meshes: a concentrated mesh with four terminals per node, dimension-order routing, 17-flit packets, 10 + 4 cycles per hop. Isobar's rankings agree with BookSim's (Spearman ρ 0.966, 0.984, 0.973 for one-layer prefill, one-layer decode and two-layer prefill).

Aggregate metrics cannot separate layouts that differ only in contention. Two layouts with identical word-hops load their busiest link with 4.2 M and 10.5 M words. Isobar predicts a 1.94× communication-time ratio, BookSim measures 1.82×, and word-hops sees no difference. When each metric selects a mapping from the same pool, Isobar's choice is 0.3–12.2% above the pool's BookSim minimum, against 40.4–51.7% for word-hops; max-hops is also worse in all three workloads.

**Evaluation cost.** On 512 to 2,200 dies, an incremental update takes 1.4–15.9 ms, 26–38× faster than a full evaluation. One representative search takes 2.5 s (2.7B reference, 512 dies) to 127.7 s (OPT-13B, 2,200 dies).

## 5. Mapping results

**Gemma-7B prefill** (1,232 dies, 36 × 36 mesh, 0.4 GB/s links, central unit):

| layout | latency T (s) |
|---|---|
| default fill | 12.00 |
| snake | 11.21 |
| NMAP | 4.33 |
| least Manhattan | 4.25 |
| heaviest first (best prescribed rule) | 3.61 |
| best of 500 random layouts (best baseline) | 3.29 |
| Isobar search (median seed) | 2.68 |

The search cuts communication by 23.3% and end-to-end latency by 18.6% against the best baseline, and latency by 77.7% against the default fill. Dynamic energy falls by 0.65%. Least Manhattan lowers energy by 14.4% but raises latency by 29.1%: the two objectives favour different mappings. The transfers from the attention output to FFN1 and from FFN1 to FFN2 account for 81.8% of the saving, so the gains come from relieving shared links along the FFN paths. At the same communication time, the best baseline needs 0.52 GB/s, 30.4% more mesh bandwidth than the searched mapping.

**Across models and configurations.** The comparison covers four models in three configurations: 8 macros per die with one central unit; 16 macros per die; four units on head groups sharing the reference resources. For OPT-6.7B, Gemma-7B and OPT-13B in all three configurations, the search saves 14.8–24.0% of communication time and 10.6–18.7% of end-to-end latency (seed medians) against the best baseline. For OPT-1.3B, the 16-macro configuration consolidates the operators so far that no competing hand-off flows remain, and the search finds nothing to improve. The gain depends on the communication structure the configuration produces.

**QKV partitioning (OPT-13B prefill, same 49 × 49 mesh).**

| QKV split | CIM dies | QKV-to-unit traffic (GB) | T baseline (s) | T search (s) | η (%) |
|---|---|---|---|---|---|
| row | 2,200 | 6.29 | 13.39 | 11.22 | 17.5 |
| column | 2,400 | 0.315 | 5.16 | 4.10 | 25.1 |

Column partitioning uses more dies but replaces repeated partial-sum transfers with disjoint QKV outputs. It cuts the QKV-to-unit traffic about 20× and lowers latency substantially. Capacity, decomposition and topology-aware mapping have to be evaluated jointly.

## 6. Configuration dependence

The exploration protocol is used for this section.

- **CIM capacity.** Raising the macros per die (4 → 32) does not reduce the mapping gain uniformly. In OPT-1.3B, consolidation removes the competing hand-offs. In Gemma-7B, wide fan-out hand-offs keep concentrated contention. On a common 36 × 36 mesh, Gemma keeps the non-monotonic trend, so mesh size alone does not explain it.
- **Resource organisation.** Gemma-7B with the same total digital resources: baseline → search backbone time is 3.33 → 2.68 s with one central unit, 3.46 → 2.88 s with four layer-group units, and 3.03 → 2.46 s with four head-group units. Head groups spread the communication while keeping the aggregate throughput. Layer groups leave part of the digital capacity idle. At longer contexts, dividing the workspace among units needs more query tiles and repeated K/V reads, which offsets part of the communication benefit.
- **Bandwidth response.** For the fixed Gemma pair, the communication saving stays near 23% as the mesh bandwidth rises, while the baseline's communication share r₀ falls (79.7% at 0.4 GB/s), so the end-to-end saving G = η r₀ declines. Once the fixed 12.5 GB/s unit interface binds, the communication saving declines as well.
- **Context length.** Gemma-7B prefill keeps an end-to-end saving of about 17.5% up to 4,096 tokens. In decode, the communication saving stays similar but the growing K/V service shrinks its share, and the end-to-end saving falls to 2.6% at 4,096 tokens. Long-context decode needs memory service alongside communication optimisation; prefill offers more room for acceleration through mapping.

## 7. Energy against GPUs

Complete requests (prefill, decode with a growing 16-bit K/V cache, embeddings, the LM head on resident CIM dies) at batch 1, on the searched mapping of each capacity configuration:

| model | macros per die | GPU energy (J) | CIM energy (J) | GPU / CIM |
|---|---|---|---|---|
| OPT-13B (A100, 64 : 1024 tokens) | 8 | 5,473.7 | 58.61 | 93× |
| OPT-13B | 16 | 5,473.7 | 48.53 | 113× |
| Gemma-7B (Jetson AGX Thor, 13–345 : 500 tokens) | 8 | 1,898.7 | 11.45 | 166× |
| Gemma-7B | 16 | 1,898.7 | 9.85 | 193× |

The CIM values are modeled dynamic energy; the GPU values are reported device or board energy and include static power. Modeled CIM dynamic energy remains far below the GPU energy after accounting for communication and non-CIM execution. `../gpu_comparison/REPORT_gpu_comparison.md` and `AUDIT_energy.md` document the energy boundary and every component.

## 8. Scope

- Communication is priced by the busiest-resource bound per stage, plus propagation. This matches Simba's measurements and BookSim's rankings, but it is not a cycle-level simulation of queueing.
- Package stages are serialised; overlap across hand-offs is not modelled.
- Energy is dynamic only: no array or periphery leakage, unit idle power, memory refresh, clock or host.
- Weights are resident and programmed once.
- The backbone is the transformer block stack; embedding, LM head and final norm enter only the full-request energy comparison.
- Batch 1.

## 9. Data

| data | location |
|---|---|
| per-operator accounts | `scale_2p7b_per_op.json`, `v4/accounts/`, `v4/models/model_end_costs.json` |
| deployment records | `v4/<unit>/configs.jsonl` |
| BookSim libraries | `v3/e3_offload/`, `v3/e3_k2/` |
| tables behind the figures and tables | `v6/`, `v7/` |
| figures | `figures_dac2027/20261019_v3/` |
| GPU comparison | `../gpu_comparison/` |

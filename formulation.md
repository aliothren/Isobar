# The cost model

This is the model of the paper (Section II), as implemented in `workspace/scripts/search_eval.py`, `v3_sweep.py`, `cimsim_cli.py` and `offload.py`.

## System and mapping space

The system has four hardware levels: package, die, macro and crossbar array.

- **Package.** Homogeneous CIM dies on a 2-D mesh with XY routing, plus K digital units in reserved mesh slots. The units run the input-dependent attention and hold the K/V cache in their own memory.
- **Die.** Macros on an intra-die network around a global buffer, and a digital vector unit for the element-wise operators.
- **Macro.** ReRAM crossbars with converters, buffers and digital accumulation. Weights are resident.

For the static (weight-resident) operators, weight precision, cell encoding, array size and die capacity constrain the legal tilings. A column split over output channels gives disjoint outputs, and every consumer die receives the whole input. A row split over input channels gives partial sums that are reduced at the consumer, at partial-sum width.

A mapping is p = (γ, α, β) ∈ F:

- **γ**: the layer groups G_k with their die allocations A_k, fixed by the operator tilings and allocation rules;
- **α**: logical die → package slot;
- **β = {β_d}**: logical macro → macro slot within die d.

Every slot hosts at most one die or macro, and unused slots are allowed.

## Execution costs

**Non-communication cost**, with s = 1/t_row the CIM row-processing rate:

    R(s) = R_CIM(s) + R_digital + R_KV + R_other

`R_CIM` is CIM compute and write from the per-operator accounts (one CiMLoop mapper run per operator). `R_digital` covers the element-wise work and the units' attention compute, and `R_KV` the K/V-memory service.

**Communication.** A stage j is a hand-off whose transfers are ready at the same time. Its transfers are routed onto the resources R_j: directed mesh links, CIM die injection and ejection ports, and digital-unit interfaces. V_{j,r}(p) is the load on resource r under p, C_r its bandwidth and P_j(p) the stage's propagation delay (20 ns per hop):

    H(p; C) = Σ_j [ P_j(p) + max_{r ∈ R_j} V_{j,r}(p) / C_r ]

The maximum is a lower bound on the stage's service time and serves as its estimate under the reference static model.

**Package latency.** Package communication and local execution are serialised:

    T_pkg(p; s, C) = R(s) + H(p; C)

With mesh links at B, CIM ports at κB and fixed digital-interface bandwidths:

    H(p; B, κ) = Σ_j [ P_j(p) + max{ A_j(p; κ) / B, U_j(p) } ]

where A_j is the maximum over mesh-link and CIM-port loads (in link-time units) and U_j is the largest service time among the fixed-bandwidth interfaces of stage j. Once U_j binds, a higher B no longer shortens the stage.

**Die latency.** Inside a die, computation and communication service overlap:

    T_die(β; s, B) = Σ_j [ D_j(β) + max{ C_j(s), H_j(β; B) } ]

with D_j the non-overlapped writes and propagation.

**Dynamic energy.**

    E = E_CIM + E_digital + E_unit + E_KV + E_net

- E_CIM: CiMLoop per-operator energy;
- E_digital: element-wise operations at 16 bit plus global-buffer passes;
- E_unit: 1 pJ per MAC-equivalent operation;
- E_KV: 50 pJ per byte;
- E_net: 10 pJ per 8-bit word per hop.

Static and idle power are not modelled.

## Boundaries and envelopes

Inter-die boundary of a mapping, for fixed s, κ and interface bandwidths (B_c = +∞ if the set is empty):

    B_c(p; s) = inf { B > 0 : H(p; B, κ) ≤ R(s) }

Intra-die boundary, where communication service hides under computation for every co-resident operator:

    b(β; s) = inf { B > 0 : H_j(β; B) ≤ C_j(s)  for all j }

Over a set of evaluated mappings P, the envelope is B₋(s) = min_p B_c(p; s) and B₊(s) = max_p B_c(p; s). The intra-die envelope is the same over the macro assignments. Below B₋ every mapping is communication-dominated; above B₊ none is; inside it, the mapping decides. A second contour marks the total-latency spread (T_max − T_min)/T_min = 20% across the evaluated mappings.

## Metrics

- Best baseline b: the lowest-T layout among the prescribed rules and the random pool. The default fill places operators in chain order onto the slots in row-major order.
- Communication saving η = 1 − H_s / H_b.
- Baseline communication share r₀ = H_b / T_b.
- End-to-end saving G = 1 − T_s / T_b = η r₀.
- Equivalent bandwidth B_eq: the mesh bandwidth at which H_b(B) equals H_s at the reference bandwidth, with the interfaces and resources fixed and the ports at κB.

## Search

Hierarchical DP–SA:

- An exact interval DP over consecutive layer groups (γ).
- Simulated annealing over the die seats (α) with exchange, migrate and swap moves and incremental re-evaluation of the touched hand-offs. Each run starts from the strongest prescribed rule, the strongest random layout of the pool or random layout 0. Cooling is geometric, t₀ = 20 ms / 2118.71 ms (dimensionless), α = 0.996. The budget is max(1200, ⌈1200 n / 544⌉) steps for n movable dies. The annealer seed is 1000003 s + start index.
- Exhaustive enumeration of small intra-die spaces (β).

Protocols:

| protocol | random pool | seeds | objective |
|---|---|---|---|
| confirmation (main results) | 500 | 5–14 | H / H_b |
| exploration (sweeps) | 100 | 0–4 | T / T_b |

Per seed, the best of the three starts is kept. The representative is the median seed's best run.

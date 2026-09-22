# The cost model, as frozen (2026-09-22)

This is the model every result in the repository is computed with. It is
implemented in `workspace/scripts/search_eval.py` (package level) and
`workspace/scripts/search_withindie.py` (intra-die level); the phase
diagram in `workspace/scripts/fig_phase_isobar.py` draws its boundaries
from the same functions.

## Objects

A deployment of a layer stack on the package is a triple $(\gamma, \alpha, \beta)$:
$\gamma$ the partition of the operator chain into contiguous blocks with
their die groups, $\alpha$ the placement of every operator's dies on the
die mesh, $\beta$ the assignment of an operator's macros inside a die. The
operator tiling comes from CiMLoop's mapper and is taken as given.

The hardware is a fabric of levels (package, die, macro, core, crossbar).
At the package level the die mesh has a link bandwidth $B$ per direction
and each die has one injection and one ejection port of capacity $\kappa B$;
routing is the fixed XY rule. The device is characterised by its row
processing rate $s = 1/t_{\mathrm{row}}$.

## Communication

Every boundary $k$ between consecutive operators is an R-split multicast:
each producer die holds one piece of the output and ships it to every
consumer die, so a hand-off from $n_p$ to $n_c$ dies is $n_p n_c$ flows and
every consumer receives the whole tensor $V_k$. Each flow is routed on the
mesh; its volume is added to every link direction on its path and to the
producer's injection port and the consumer's ejection port. The service
time of the boundary is its busiest resource,
$$
L_k(\alpha) = \max\Big\{\max_e \frac{Q_{k,e}}{B},\;
\max_v \frac{Q^{\mathrm{inj}}_{k,v}}{\kappa B},\;
\max_v \frac{Q^{\mathrm{ej}}_{k,v}}{\kappa B}\Big\},
$$
with port loads in link-time units. Because every consumer must receive
$V_k$ through its own ejection port, $L_k \ge V_k/(\kappa B)$: the port
floor, a property of the mapping that no placement can go below.

## Latency

The non-communication cost separates from the communication cost,
$$
R(s) = \frac{N}{s} + F, \qquad H(\alpha; B, \kappa) = \sum_k L_k(\alpha) + P(\alpha),
$$
with $N$ the compute that scales with the device, $F$ the weight-write and
digital-unit terms that do not, and $P$ the propagation of each
boundary's longest path (20 ns per hop). A batch-one serial prefill
executes the boundaries one after another, so the package latency is the sum
$$
T_{\mathrm{pkg}} = R(s) + H(\alpha; B, \kappa).
$$
Inside a die each operator overlaps its serialization with its own compute,
$$
T_{\mathrm{die}}(\beta) = \sum_j \big[D_j + \max\{C_j(s),\, H_j(\beta; B)\}\big],
$$
with $D_j$ the write and propagation terms that do not overlap. The two
levels are separable in the frozen model: a die placement moves only the
propagation term of the intra-die instance, and no term couples a die's
macro seating to the hand-offs entering it.

## Dynamic energy

$$
E = E_{\mathrm{ops}} + E_{\mathrm{elem}} + \sum_{\mathrm{flows}} \mathrm{words} \times \max(\mathrm{hops}, 1) \times 10\ \mathrm{pJ},
$$
the per-operator CiMLoop energy, the digital-unit energy, and every
delivered payload word charged once per link hop at the midpoint of the
measured Simba GRS band. Static power is not modelled; the energy does not
depend on $B$ or $\kappa$. Only the surplus hops depend on the placement.

## The phase diagram

For a comparison object that separates, a boundary is the cost equality
$B_c(\alpha; s) = A(\alpha)/R(s)$ with $A$ the aggregate bottleneck load in
words. Over a declared placement set $\mathcal{P}$ the extrema
$B_-(s) = \min_{\mathcal{P}} B_c$ and $B_+(s) = \max_{\mathcal{P}} B_c$
bound the band in which the placement decides which cost leads; above $B_+$
every placement is compute-dominated, below $B_-$ communication dominates
for every placement and the placement sets how severe. Under the intra-die
overlap model the boundaries are the per-operator masking thresholds
$A_{\min}/C$ and $A_{\max}/C$. For two placements with the same $R$ the
whole-model gain factorises as
$$
G = \eta\, r, \qquad \eta = 1 - \frac{H_{\mathrm{sel}}}{H_{\mathrm{ref}}}, \qquad r = \frac{H_{\mathrm{ref}}}{T_{\mathrm{ref}}}.
$$

## The search

The objective is $T_{\mathrm{pkg}}$ at the main bandwidth. A dynamic
program over cut positions and group sizes prices the blocks with the
evaluator's own per-layer costs; simulated annealing with exchange, migrate
and whole-set swap moves searches the die placement, re-scoring only the
boundaries a move touches; the macro assignment inside a die is enumerated.
The frozen protocol is three start families times three seeds, 1200 steps,
$\alpha = 0.996$, $t_0 = 20$ ms, the best of the starts per seed, and the
median seed as the representative.

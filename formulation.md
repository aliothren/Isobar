# Problem Formulation

The die is a set of crossbar slots $\mathcal{P} = \{(a,c,x)\}$ organized as $A=8$ macros
× $N_c=4$ cores × $N_x=8$ crossbars ($|\mathcal{P}|=256$), with capacities
$\kappa_{\mathrm{core}}=8$ and $\kappa_{\mathrm{macro}}=32$. Each crossbar holds an
$R \times K = 256 \times 128$ weight tile. Each projection $\ell \in \mathcal{L}$ is
tiled onto $m_\ell = \lceil M_\ell / K \rceil$ M-blocks ×
$n_\ell = \lceil C_\ell / R \rceil$ C-tiles, giving tiles $t = (\ell, i, j) \in T$.
Since all inter-projection traffic routes through the host, the only on-die
communication is the intra-matmul partial-sum reduction: for each M-block $i$, its
$n_\ell$ C-tiles form one reduction hyperedge
$e_{\ell,i} = \{(\ell,i,j)\}_{j=1}^{n_\ell}$ feeding a single reduction tree.

We seek a time-invariant (weight-stationary) injective placement $\pi : T \to \mathcal{P}$,
encoded by $x_{t,p} = \mathbb{1}[\pi(t) = p]$, subject to

$$
\sum_{p} x_{t,p} = 1 \ \ \forall t, \qquad
\sum_{t} x_{t,p} \le 1 \ \ \forall p, \qquad
\sum_{t,\, p \in c} x_{t,p} \le \kappa_{\mathrm{core}} \ \ \forall c, \qquad
\sum_{t,\, p \in a} x_{t,p} \le \kappa_{\mathrm{macro}} \ \ \forall a .
$$

Partial sums reduce for free within a core (analog bitline + local shift-add), and the
reduction tree pays once per additional core or macro it spans. With
$\lambda_{\mathrm{core}}(e)$ and $\lambda_{\mathrm{macro}}(e)$ the number of distinct
cores and macros hyperedge $e$ touches under $\pi$, and boundary energy weights
$0 = w_{\text{within-core}} \ll w_{\mathrm{core}} \ll w_{\mathrm{macro}}$ (pJ/byte), the
reduction cost is the hierarchical connectivity ($\lambda{-}1$) metric

$$
\mathrm{Red}(e) =
\Big( w_{\mathrm{core}} \big( \lambda_{\mathrm{core}}(e) - 1 \big)
    + w_{\mathrm{macro}} \big( \lambda_{\mathrm{macro}}(e) - 1 \big) \Big)
\cdot K P \, b_{\mathrm{out}},
$$

which counts exactly the cross-boundary merges in the tree — unlike a pairwise distance
sum, which overcounts by charging co-resident tiles. The placement problem is

$$
\min_{\pi} \;
\alpha \sum_{\ell} \sum_{i} \mathrm{Red}(e_{\ell,i})
\; + \;
\beta \cdot \mathrm{Frag}(\pi),
$$

where $\mathrm{Frag}(\pi)$ is the allocated-but-unused crossbar count at core
granularity (touched cores × $\kappa_{\mathrm{core}} - |T|$). Since projections exchange
no on-die traffic, the first term separates per matmul; only fragmentation couples them.
This is a capacity-constrained, hierarchically weighted $(\lambda{-}1)$-connectivity
hypergraph partitioning problem: assigning a tile to a core is simultaneously a
partition decision (which tiles co-reside) and a placement decision (which boundary a
merge crosses).

Capacity gives a per-M-block lower bound,

$$
\mathrm{Red}(e_{\ell,i}) \;\ge\;
w_{\mathrm{core}} \big( \lceil n_\ell / \kappa_{\mathrm{core}} \rceil - 1 \big)
\cdot K P \, b_{\mathrm{out}} ,
$$

which is $0$ for the depth-3 projections ($n_\ell = 3 \le 8$: each reduction fits one
core) and $w_{\mathrm{core}} K P b_{\mathrm{out}}$ — one cross-core merge — for ffn2
($n_\ell = 12$). The $8{+}4$ split with paired tail cores (9 cores, zero fragmentation)
attains this bound, certifying it optimal.

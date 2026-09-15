# Ergodicity of the SA proposal chain (spec §8(c), one page)

**State space.** Legal seatings at fixed cuts: `seat` assigns every
declared set its inventory-sized, pairwise-disjoint tuple of die
slots; cuts, hub, attach, beta are frozen at this level (the chain
partition belongs to the S4 DP). Legality never degrades along a
trajectory: every operator preserves set sizes and slot disjointness
by construction (gate G1 pins it on random walks anyway).

**Proposal families** (`scripts/search_sa.py::propose`): *exchange* —
one slot of set a for one slot of set b; *migrate* — one slot of a set
to a target slot, plain move if the target is free, TWO-STEP
evict+place if occupied (the displaced slot returns to the vacated
seat); *swap* — two whole sets of equal size. Each family draws
uniformly over its instances; a family with no legal instance (swap
when all sizes are distinct) returns no proposal and the step is a
self-loop.

**Constructive path (irreducibility).** For any two legal seatings
Π_a, Π_b of the same inventory, `constructive_path` produces a finite
sequence of exchange/migrate deltas from Π_a to Π_b: while some slot s
that Π_b assigns to set B has a different current owner, pick
x ∈ seat[B] that B does not keep in Π_b (it exists by counting, since
|seat[B]| is fixed); if s is currently owned by A, exchange s↔x; if s
is currently free, migrate x→s. Each step fixes s permanently and
never unfixes a fixed slot, so the path length is at most the initial
mismatched-slot count (≤ the slot count). Every path step is an
instance of a proposal family and is drawn with positive probability
at every temperature, so the proposal chain is IRREDUCIBLE over the
legal seatings at fixed cuts; gate G4 pins path exactness, per-step
legality and the length bound on random legal pairs of both workload
classes.

**Aperiodicity.** Rejected proposals (Metropolis rejection, the
constrained mode's feasibility rejection, and no-instance draws) are
self-loops with positive probability, so the chain is aperiodic;
with irreducibility, the finite chain is ergodic at any fixed t > 0.

**From the proposal chain to the annealing chain** (the implicit step,
now explicit): irreducibility above is a property of the PROPOSAL
chain; the annealing chain inherits it because at any fixed t > 0 the
Metropolis acceptance probability of a proposed move with finite ΔJ is
strictly positive — min(1, exp(−ΔJ/t)) > 0, and every ΔJ on the finite
state space is finite — so every proposal-chain transition is also an
annealing-chain transition with positive probability. (The greedy mode
t0 = 0 is a descent mode and makes no ergodicity claim.)

**Scope of the claim + the usage template for constrained instances.**
The constructive path argues connectedness of the FULL structurally
legal space. Under rejection semantics the chain walks only the
feasible region; if an instance's feasibility predicate narrows that
region, the path may cross infeasible intermediates and connectedness
does NOT inherit automatically. Every constrained instance therefore
fills exactly one of: (a) "this instance walks the full space — no
feasibility predicate beyond structural legality"; or (b) "this
instance's feasible region is connected because ⟨instance-specific
argument⟩". The S4 cuts axis — the tiler-feasible SPARSE size set —
was the first expected client of (b); FILLED at S4 day 9 with a
third legitimate answer: the sparse cuts/size axis hosts NO Markov
chain at all — the interval DP enumerates it EXACTLY (spec §8 level
1; `scripts/search_dp.py`, optimality gated against brute force), so
feasible-region connectedness is moot on that axis; the only chains
S4 runs are the linkage's SA-seating legs, and those fill option (a)
— the full structurally-legal seating space, no feasibility
predicate.

**Saturated hosts.** The 355M class is capacity-saturated (48
one-die units on 48 slots): no slot is ever free, so the migration
family degenerates to its two-step form by construction — declared,
not special-cased — and exchange = swap = two-step migrate on one-die
sets; the constructive path uses exchanges only. The 2.7B class has
32 free slots (544 of 576 used), so plain migration is live and the
reachable space includes all choices of WHICH slots stay empty.

**Declared degenerate configurations** (where the space, not the
chain, is the limit): (i) the within-die level is ZEROED by the A1
degeneracy theorem absent co-residency — the within-die instance
therefore runs under the A3 co-residency condition (spec §2 internal
citations; §10 S3); where A1 applies, there is nothing to search and
we say so rather than run; (ii) the 355M uniform pipeline chain is a
SOLVED DEGENERATE CORNER for the ordering level (§10 [AMENDED 10]:
six named baselines tie at the 1.00-hop chain-adjacency lower bound)
— the chain is ergodic there too, but the instance is filed as
solved, never a search demonstration; the ordering instance runs
under the declared cross-traffic class load.

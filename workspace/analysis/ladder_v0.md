# Ladder table v0 — figure group README

Generators: `scripts/ladder_v0.py` (table, seed pool, three-panel figure),
`scripts/check_c_crosstraffic.py` (the check-C reinforcement figure). Data:
`ladder_v0.json` (the official readings AND the §6 anti-stranding seed
pool: all seven named Π serialized per workload class). All three ladder
panels share one baseline order: the 2.7B safe-cell T ladder.

**Regime (read this first).** The ladder is drawn at **κ = 1**, ports at
the link rate, on the 2.7B stack. That is a declared sensitivity cell, not
the main configuration: the paper's main configuration is κ = 2, where the
same seven rules span 2.66× and the search gains 9.91% over the strongest
of them. The κ = 1 cell is where the port floor binds, which is why its
spread is narrower and its search gain is 1.86%.

- `ladder_v0.png` left: whole-model `T_single` per cell as the **percent
  excess over that cell's best rule**, for three cells (safe 12.5 GB/s,
  weak D2D 0.4 GB/s, fast device). The weak-D2D cell spreads to ~82%
  (sequential over random); the safe cell to ~6%; the fast-device cell to
  ~24%. Seating reaches T through the busiest-resource term, not through
  propagation.
- `ladder_v0.png` middle: the share of the delivered words that stacks on
  **one link** (busiest-link words ÷ total words). The total is
  seat-invariant by construction, every producer die ships its piece to
  every consumer die wherever they sit; this ratio is not. It runs from
  0.39 (random) to 0.93 (sequential), which is the mechanism behind the
  left panel.
- `ladder_v0.png` right: the 355M wire-time caliber in the same order: the
  named rules tie at the chain-adjacency lower bound and the random fill
  pays 4.0×. Note the direction reverses between the panels: on the 2.7B
  stack dispersion wins because it unstacks the links, on the 355M unit
  chain adjacency wins because there is nothing to unstack.
- `check_c_crosstraffic.png`: the busiest die wire under pure-chain vs
  fan-out traffic; the condition-bound flip registered in `MATERIALS.md`
  and SEARCH_SPEC §7 [AMENDED 11].

Reading the groups side by side: the ladder reads the **package
busiest-resource** lever on the 2.7B stack, the check-C figure reads the
**die-mesh busiest-wire occupancy** lever on a synthetic load. Two levers
at two levels; any juxtaposition of the two must say so.

**History.** Before the 2026-09-15 hand-off-term correction this README
described a left panel in ppm and cited findings F-L1/F-L2 ("the seating
lever is a propagation effect; the placement sensitivity lives in the
energy column"). Both were artifacts of the pre-correction term and are
recorded as superseded in `FIXLIST.en.md`; the panels above are the
current figure.

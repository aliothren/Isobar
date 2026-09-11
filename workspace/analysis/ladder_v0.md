# Ladder table v0 — figure group README

Generators: `scripts/ladder_v0.py` (table, seed pool, three-panel
figure), `scripts/check_c_crosstraffic.py` (the check-C reinforcement
figure). Data: `ladder_v0.json` (the official readings AND the §6
anti-stranding seed pool: all seven named Π serialized per workload
class). All three ladder panels share one baseline order — the 2.7B
safe-cell T ladder.

- `ladder_v0.png` left: T_single per cell as EXCESS OVER THE CELL BEST,
  in ppm (+1 offset notation). The whole seven-seat spread is 16–224
  ppm depending on the cell (safe 70, weak-D2D 16, fast-device 224):
  seating reaches T only through the propagation term.
- `ladder_v0.png` middle: the D2D word count — seat-invariant, set by
  construction (every producer die ships its piece to every consumer
  die wherever they sit). This is the invariance that makes the left
  panel ppm-flat and moves the placement sensitivity to the energy
  column (8.0% spread) — findings F-L1/F-L2.
- `ladder_v0.png` right: the 355M wire-time caliber (same order):
  named baselines tie at the chain-adjacency lower bound, random pays
  4.0×.
- `check_c_crosstraffic.png`: the busiest die wire under pure-chain vs
  fan-out traffic; the condition-bound flip registered in
  `MATERIALS.md` and SEARCH_SPEC §7 [AMENDED 11].

Reading the groups side by side: the ladder's left/middle panels read
the PACKAGE-SEAT lever through the propagation term — a µs-scale
effect on T; the check-C figure reads the die-mesh BUSIEST-WIRE
OCCUPANCY lever — a multiple-fold effect. Two different levers at two
different magnitudes; any juxtaposition of the two must say so.

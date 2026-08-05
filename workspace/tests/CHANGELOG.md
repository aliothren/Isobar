# Golden re-baselines

Every entry: which goldens moved, why the move is legitimate, what stayed pinned.

## v0 -> v1 (workstream B: TrafficExtraction), 2026-08-05

**What changed:** per-crossbar and per-link traffic switched from the uniform
placeholder (`total / n_crossbars`, subtree-summed trunks) to the mapping's real
multicast/reduction structure (`scripts/traffic.py`). A multicast slice now
crosses an upper edge once instead of once per leaf; idle instances carry zero.

**Goldens moved:**
- `slow_golden_v0.json` (tiny2x2 max/min 3.579, uniform) retired ->
  `slow_golden_v1.json` (active-crossbar spread under structured volumes).
- per-level volume equality (an artifact of the uniform division) replaced by
  leaf-level == stats-counters conservation.
- downstream: comm dumps, the heatmap spread (ffn1 3.58x is superseded), and the
  per-level volume x distance distribution ("~65% at glb<->macro" rested on a
  ~32x multicast overcount of the trunk).

**Stayed pinned (must NOT move):** the 12 system-scenario totals
(`system_golden_v0.json`, checked via tests/compare_baseline.py) -- B touches the
communication ANALYSIS layer only; energy/latency totals do not flow through
build_flows.

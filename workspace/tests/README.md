# tests: the guardrail suite

Every published number is pinned here against the artifact it comes from,
so a model change that moves a number fails a test before it reaches a
document. Run inside the container:

```bash
cd /home/workspace && python3 tests/run_tests.py          # 443 tests in the default run
cd /home/workspace && python3 tests/run_tests.py --slow   # adds the end-to-end mapper run and the BookSim gates
```

The runner prints one line per test and a summary; expected failures are
listed as known gaps (none at present). Groups follow the platform's
history: the low groups pin the macro- and crossbar-level models, groups
in the twenties and thirties the anchors, the device plane, the scaling
law and the Simba reproduction, the forties the energy models and weaves,
groups 49 to 55 the search (space, evaluator, annealer, dynamic
program, instances, referee), and group 56 the command line (`test_cli.py`). `test_anchor_registry.py` pins the published
reference figures (HERMES, ISAAC, M1076) as read from their sources.

`fixtures/` holds the frozen per-operator accounts and mapper outputs the
tests read (`make_fixtures.py` rebuilds them); `compare_baseline.py`
compares two golden files. [`CHANGELOG.md`](CHANGELOG.md) records every
re-baseline: which goldens moved, why the move is legitimate, and what
stayed pinned.

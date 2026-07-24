#!/usr/bin/env python3
"""D8 guardrail suite runner.

Usage (inside the container):
    python3 tests/run_tests.py            # fast suite (< a few seconds)
    python3 tests/run_tests.py --slow     # also run end-to-end mapper tests (minutes)

Test semantics:
    test_*   must pass.
    xfail_*  EXPECTED to fail today -- each one documents a known modeling gap
             (see workstreams A/B/C). If an xfail starts PASSING, the runner
             flags it as XPASS: promote it to a must-pass test in the same PR
             that closed the gap.

Scope: these tests verify that the CODE is faithful to the declared MODEL
(invariants, golden reproduction, properties). They are development guardrails,
not part of the future placement evaluator; the evaluator will additionally be
held to the same property assertions (group 4) plus its own Spearman harness.

Golden files are versioned (fixtures/*_v0.json = the uniform-traffic model).
When TrafficExtraction (workstream B) lands, numbers legitimately change:
re-baseline to *_v1.json with a changelog entry; conservation and property
tests stay unchanged across versions.
"""
import importlib.util
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # -> `from scripts import ...`
sys.path.insert(0, HERE)                           # -> `from _util import ...`
from _util import SkipTest                         # noqa: E402


def _load(path):
    name = os.path.basename(path)[:-3]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    slow = "--slow" in sys.argv
    files = sorted(f for f in os.listdir(HERE)
                   if f.startswith("test_") and f.endswith(".py"))
    if not slow:
        files = [f for f in files if "_slow_" not in f]

    results = {"PASS": [], "FAIL": [], "XFAIL": [], "XPASS": [], "SKIP": []}
    for fname in files:
        mod = _load(os.path.join(HERE, fname))
        for attr in sorted(dir(mod)):
            fn = getattr(mod, attr)
            if not callable(fn):
                continue
            tag = f"{fname}::{attr}"
            if attr.startswith("test_"):
                try:
                    fn()
                    results["PASS"].append(tag)
                except SkipTest as e:
                    results["SKIP"].append(f"{tag}  ({e})")
                except Exception:
                    results["FAIL"].append(tag)
                    print(f"\n--- FAIL {tag} ---")
                    traceback.print_exc()
            elif attr.startswith("xfail_"):
                try:
                    fn()
                    results["XPASS"].append(tag)
                except Exception:
                    results["XFAIL"].append(tag)

    print("\n================ D8 summary ================")
    for k in ("PASS", "XFAIL", "SKIP", "XPASS", "FAIL"):
        for t in results[k]:
            print(f"  {k:<6} {t}")
    print(f"\n  {len(results['PASS'])} passed, {len(results['FAIL'])} failed, "
          f"{len(results['XFAIL'])} expected-fail (known gaps), "
          f"{len(results['XPASS'])} XPASS, {len(results['SKIP'])} skipped")
    if results["XPASS"]:
        print("  !! XPASS: a known gap seems closed -- promote these to test_* "
              "in the PR that closed it.")
    sys.exit(1 if results["FAIL"] else 0)


if __name__ == "__main__":
    main()
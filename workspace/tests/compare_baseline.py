#!/usr/bin/env python3
"""Tier-1 gate: diff fresh system-level totals against the frozen golden.

NOT part of the automatic suite (a full run costs ~45 min of mapper time).
Manual procedure:

    # inside the container
    python3 scripts/analyze_system_gpt2.py 512 prefill
    python3 scripts/analyze_system_gpt2.py 512 decode
    python3 tests/compare_baseline.py

Use it as the acceptance gate for re-plumbing work (workstream A): every number
must reproduce within tolerance. When a MODEL change lands (e.g. workstream B's
real traffic structure), numbers move legitimately: re-freeze with

    python3 tests/compare_baseline.py --freeze v1

and record the move in a changelog entry. Never re-freeze to make a red compare
green without knowing why it moved.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYSIS = os.path.join(HERE, "..", "analysis")
GOLDEN_DIR = os.path.join(HERE, "fixtures")

# mapper is single-threaded/deterministic; identical inputs reproduce exactly.
# The loose-ish default absorbs float printing, not model drift.
RTOL = 1e-6

# scenario keys, in reading order
KEYS = ["C_E", "A_E", "B_E", "C_L", "A_L", "B_L"]


def load_fresh():
    fresh = {}
    for phase in ("prefill", "decode"):
        p = os.path.join(ANALYSIS, f"gpt2_system_totals_{phase}.json")
        if not os.path.exists(p):
            sys.exit(f"missing {p} -- run analyze_system_gpt2.py 512 {phase} first")
        with open(p) as f:
            fresh[phase] = json.load(f)
    return fresh


def freeze(fresh, version):
    out = os.path.join(GOLDEN_DIR, f"system_golden_{version}.json")
    with open(out, "w") as f:
        json.dump(fresh, f, indent=1)
    print(f"frozen -> {out}")
    print("record WHY the numbers moved in a changelog entry.")


def compare(fresh, version):
    gp = os.path.join(GOLDEN_DIR, f"system_golden_{version}.json")
    if not os.path.exists(gp):
        sys.exit(f"no golden {gp} -- freeze one first (--freeze {version})")
    with open(gp) as f:
        golden = json.load(f)

    bad = 0
    print(f"{'phase':<9}{'key':<6}{'golden':>14}{'fresh':>14}{'rel diff':>12}")
    for phase in ("prefill", "decode"):
        for k in KEYS:
            g = golden[phase]["scenarios"][k]
            v = fresh[phase]["scenarios"][k]
            rel = abs(v - g) / max(abs(g), 1e-30)
            flag = "" if rel <= RTOL else "   <-- MOVED"
            if rel > RTOL:
                bad += 1
            print(f"{phase:<9}{k:<6}{g:>14.6e}{v:>14.6e}{rel:>12.2e}{flag}")
    print(f"\n{'ALL MATCH' if bad == 0 else f'{bad} NUMBERS MOVED'} "
          f"(golden {version}, rtol {RTOL})")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    args = sys.argv[1:]
    fresh = load_fresh()
    if args[:1] == ["--freeze"]:
        freeze(fresh, args[1] if len(args) > 1 else "v0")
    else:
        compare(fresh, args[1] if len(args) > 1 else "v0")
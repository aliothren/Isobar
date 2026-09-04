"""Group 39 -- the robustness table (C54, step 5), pinned against its
pre-registered criteria (ROBUSTNESS_CRITERIA.md, review-amended). The
red rows ARE the table's credibility: a change that greens them without
a model change re-opens the criteria."""
import json
import os

from _util import approx

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)


def _load():
    return {r["id"]: r for r in
            json.load(open(os.path.join(WS, "analysis", "robustness.json")))["rows"]}


def test_all_fifteen_rows_present_with_calibers():
    rows = _load()
    assert len(rows) == 15
    assert rows["R11"]["caliber"] == "THRESHOLD-GATE"          # review fix 1
    assert "stress, not property" in rows["R15"]["caliber"]    # review fix 2
    assert "tiling" in rows["R12"]["note"]                     # review fix 3


def test_survival_verdicts():
    rows = _load()
    # region calls at the digital anchors: survive 5x AND the worst overlay
    assert rows["R1"]["verdicts"] == {"2x": "SURVIVES", "5x": "SURVIVES",
                                      "overlay": "SURVIVES"}
    assert rows["R6"]["verdicts"]["5x"] == "SURVIVES"
    # the honest reds, pinned as reds
    assert "fails AT THAT POINT" in rows["R12"]["verdicts"]["2x"]
    assert "BLIND beyond 1.36x" in rows["R11"]["verdicts"]["2x"]
    assert rows["R13"]["verdicts"]["2x"] == "SURVIVES"
    assert "fails" in rows["R13"]["verdicts"]["5x"]            # a bracket should
    # straddle failure directions are stated, not bare
    assert "STRENGTHENS" in rows["R2"]["verdicts"]["5x"]
    assert "exposed EVERYWHERE" in rows["R3"]["verdicts"]["2x"]
    # immune class
    for rid in ("R7", "R9", "R10", "R14"):
        assert rows[rid]["verdicts"]["2x"] == "immune"


def test_key_margins():
    rows = _load()
    assert "1.68x at T3 res3a n=4" in rows["R12"]["test"]
    assert "2.51" in rows["R13"]["test"]
    assert "1.36" in rows["R11"]["test"]
    assert "4.3x" in rows["R15"]["verdicts"]["overlay"]
    assert "ENDPOINT-DESIGN" in rows["R15"]["note"]            # counter-note


def test_table_exists():
    t = open(os.path.join(WS, "analysis", "robustness_table.md")).read()
    for want in ("A robustness table with no red would",
                 "itself be suspect", "resolution", "1.36x"):
        assert want in t, want

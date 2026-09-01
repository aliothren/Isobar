"""Hygiene 24 (C40): no make_figures stage regenerates a deleted figure --
every declared stage output exists under analysis/. The C27-era offenders
(the _2x4-suffixed twins) were removed with the output-list updates; this
guard keeps the driver and the directory in sync from now on."""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)


def test_every_declared_stage_output_exists():
    src = open(os.path.join(WS, "scripts", "make_figures.py")).read()
    outs = sorted(set(re.findall(r'"([\w.]+\.(?:png|json|csv|txt|md))"', src)))
    assert len(outs) > 25                      # the driver still declares its outputs
    missing = [o for o in outs
               if not os.path.exists(os.path.join(WS, "analysis", o))]
    assert not missing, f"stage outputs with no file on disk: {missing}"

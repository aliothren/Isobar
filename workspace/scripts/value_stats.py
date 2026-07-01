"""
Operand value-distribution (histogram) loader -- so a SYNTHETIC workload borrows
the CORRECT data-value-dependent energy statistics from a real workload instead
of whatever unrelated layer was used as a shape scaffold.

Background: CiMLoop's energy is data-value-dependent -- the ReRAM analog current,
ADC activity and cell conduction are computed from per-layer `histograms`
(Inputs / Weights / Outputs value distributions). If a synthetic op reuses an
unrelated layer's histograms (e.g. a ResNet conv), its value-dependent energy is
wrong. This module loads representative histograms from ANY named workload so the
distribution matches the model actually being simulated.

GENERAL: pass any `dnn_name` under models/workloads/. Optionally filter by layer
type (the `name:` field, e.g. Conv1D / Linear / GPT2Attention) so different op
kinds get matching distributions. Histograms are averaged over the matching
layers and renormalized to sum to 1.0.
"""
import os
import re
import ast
from functools import lru_cache

from scripts import utils as utl

_KEYS = ("Inputs", "Weights", "Outputs")


def _parse_layer(path):
    """Return ({Inputs/Weights/Outputs: [floats]}, layer_type) for one YAML."""
    txt = open(path).read()
    hists = {}
    for key in _KEYS:
        m = re.search(rf"{key}:\s*(\[[^\]]*\])", txt)
        if m:
            hists[key] = ast.literal_eval(m.group(1))
    tname = re.search(r"name:\s*(\w+)", txt)
    return hists, (tname.group(1) if tname else "")


@lru_cache(maxsize=None)
def representative_histograms(dnn_name, layer_types=None):
    """Average operand histograms over a workload's layers (optionally only the
    layers whose `name:` is in `layer_types`, a tuple). Renormalized to sum 1.0.

    Returns {Inputs, Weights, Outputs: [floats]} or None if nothing matched.
    Cached, so repeated calls in a run are free.
    """
    d = utl.path_from_model_dir(f"workloads/{dnn_name}")
    files = [os.path.join(d, f) for f in os.listdir(d)
             if f.endswith(".yaml") and f != "index.yaml"]
    acc, n = {}, 0
    for f in sorted(files):
        hists, tname = _parse_layer(f)
        if layer_types and tname not in layer_types:
            continue
        if not hists:
            continue
        for k, v in hists.items():
            if k not in acc:
                acc[k] = [0.0] * len(v)
            if len(v) == len(acc[k]):
                acc[k] = [a + b for a, b in zip(acc[k], v)]
        n += 1
    if not acc:
        # fall back to the type-agnostic average if the type filter was too strict
        if layer_types is not None:
            return representative_histograms(dnn_name, None)
        return None
    for k in acc:
        s = sum(acc[k]) or 1.0
        acc[k] = [x / s for x in acc[k]]
    return acc

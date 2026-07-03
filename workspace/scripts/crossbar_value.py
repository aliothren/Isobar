"""
Per-crossbar value-dependent energy — a selectable MODE.

CiMLoop's energy is data-value-dependent: analog column current / ADC toggling /
cell conduction scale with operand magnitude, computed from per-op `histograms`.
By default there is ONE histogram per op, so every crossbar gets the SAME average
value-dependent energy (symmetric). This module adds a per-crossbar mode so that
crossbars holding larger/smaller weight tiles (or seeing different input slices)
differ — the value-dependent side of crossbar-aware modeling.

Measured split (not assumed) — for the wan crossbar the value-dependent part is
~25% of compute energy:
    E_floor : energy with a degenerate zero-activity distribution (all mass at 0)
              -> the fixed peripheral / clocking cost, value-independent.
    E_value : E_real - E_floor  -> the value-dependent (analog activity) part.
Per crossbar i, scaling ONLY the value part by that crossbar's activity:
    E_i = E_floor/N + (E_value/N) * (activity_i / mean_activity)
so  sum_i E_i = E_real (conserved), but E_i varies with the distribution.

MODES (value_mode):
    "uniform"      -> every crossbar = the layer histogram; no variation (exact,
                      the current behavior).
    "per_crossbar" -> each crossbar's value energy scaled by its own activity,
                      drawn from a PLUGGABLE source (see per_crossbar_activities).

The per-crossbar distribution source is pluggable so the SAME machinery serves the
placeholder today and real weights later:
    source="uniform"   -> all equal (sanity: reduces to uniform mode).
    source="synthetic" -> deterministic tile-to-tile magnitude spread (PLACEHOLDER).
    source="weights"    -> (future) tile a real weight tensor per the mapping and
                           histogram each 256x256 block. Interface ready.
"""

DEFAULT_NBINS = 31
DEFAULT_SPREAD = 0.5          # synthetic tile-to-tile activity spread (placeholder)


def zero_histograms(nbins=DEFAULT_NBINS):
    """Degenerate all-mass-at-zero distribution -> the analog-activity floor."""
    d = [0.0] * nbins
    d[nbins // 2] = 1.0
    return {"Inputs": d[:], "Weights": d[:], "Outputs": d[:]}


def _bin_values(nbins):
    c = (nbins - 1) / 2.0
    return [b - c for b in range(nbins)]      # symmetric, zero-centered


def activity(hist):
    """Scalar analog activity of one operand distribution = mean |value| over its
    (zero-centered, normalized) histogram. Higher -> more analog current."""
    vals = _bin_values(len(hist))
    s = sum(hist) or 1.0
    return sum(p * abs(v) for p, v in zip(hist, vals)) / s


def operand_activity(histograms):
    """Combined Inputs+Weights activity (both drive the value-dependent energy)."""
    keys = [k for k in ("Inputs", "Weights") if k in histograms]
    return sum(activity(histograms[k]) for k in keys) / max(len(keys), 1)


def per_crossbar_activities(n, source="synthetic", spread=DEFAULT_SPREAD,
                            tile_histograms=None):
    """Per-crossbar activity SCALES (relative, mean == 1.0), length n.

    source="uniform"   : all 1.0 (no variation).
    source="synthetic" : deterministic ramp in [1-spread, 1+spread] modelling
                         tile-to-tile magnitude variation (placeholder, reproducible).
    source="weights"   : use `tile_histograms` (list of n per-crossbar histograms,
                         e.g. from a real tiled weight tensor); scales = each tile's
                         activity normalized to mean 1.
    """
    if n <= 1:
        return [1.0] * max(n, 1)
    if source == "uniform":
        return [1.0] * n
    if source == "synthetic":
        return [1.0 + spread * (2.0 * i / (n - 1) - 1.0) for i in range(n)]
    if source == "weights":
        if not tile_histograms or len(tile_histograms) != n:
            raise ValueError("source='weights' needs n per-crossbar tile_histograms")
        acts = [operand_activity(h) for h in tile_histograms]
        mean = sum(acts) / n or 1.0
        return [a / mean for a in acts]
    raise ValueError(f"unknown per-crossbar distribution source: {source}")


def per_crossbar_energy(E_real, E_floor, activity_scales):
    """Split total energy per crossbar: fixed floor (uniform) + value part scaled by
    each crossbar's activity. Sum conserved (== E_real). Returns array + spread."""
    n = len(activity_scales)
    E_value = max(E_real - E_floor, 0.0)
    mean_scale = (sum(activity_scales) / n) or 1.0
    per = [E_floor / n + (E_value / n) * (s / mean_scale) for s in activity_scales]
    lo, hi = min(per), max(per)
    return {
        "per_crossbar": per,
        "total": sum(per),
        "E_floor": E_floor,
        "E_value": E_value,
        "value_frac": (E_value / E_real) if E_real else 0.0,
        "min": lo, "max": hi, "ratio": hi / max(lo, 1e-30),
    }
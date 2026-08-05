"""Group 7 -- value-dependent energy: the pure-function invariants.

The heavy per-tile re-simulation pipeline is validated by its committed script +
frozen figure; here we pin the light approximation's declared properties, above
all the conservation claim ("total conserved") that was documented but never
tested.
"""
from _util import approx

from scripts import crossbar_value as cv


def test_zero_histograms_are_normalized_point_masses():
    h = cv.zero_histograms()
    for name, d in h.items():
        approx(sum(d), 1.0, 1e-12)
        assert d[len(d) // 2] == 1.0, f"{name}: mass not at the zero bin"
        assert cv.activity(d) == 0.0, f"{name}: zero distribution has activity"


def test_activity_monotone_in_magnitude():
    """wider (larger |value|) distributions must have larger activity."""
    n = 11
    center = [0.0] * n
    center[n // 2] = 1.0
    mid = [0.0] * n
    mid[n // 2 - 1] = mid[n // 2 + 1] = 0.5
    wide = [0.0] * n
    wide[0] = wide[-1] = 0.5
    a0, a1, a2 = cv.activity(center), cv.activity(mid), cv.activity(wide)
    assert a0 < a1 < a2, f"activity not monotone: {a0}, {a1}, {a2}"


def test_per_crossbar_energy_conserves_total():
    for scales in ([1.0] * 8,
                   [0.5, 1.5] * 4,
                   [1.0 + 0.1 * i for i in range(8)]):
        r = cv.per_crossbar_energy(E_real=2.7e-3, E_floor=2.0e-3,
                                   activity_scales=scales)
        approx(r["total"], 2.7e-3, 1e-12)
        assert all(p >= 0 for p in r["per_crossbar"])


def test_uniform_scales_give_uniform_energy():
    r = cv.per_crossbar_energy(E_real=1.0, E_floor=0.75,
                               activity_scales=[1.0] * 16)
    approx(r["ratio"], 1.0, 1e-12)


def test_floor_caps_the_spread():
    """only the value part redistributes: with floor = total, spread must vanish
    no matter how skewed the activities are."""
    r = cv.per_crossbar_energy(E_real=1.0, E_floor=1.0,
                               activity_scales=[0.1, 10.0])
    approx(r["ratio"], 1.0, 1e-12)
    assert r["value_frac"] == 0.0

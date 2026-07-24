"""Shared helpers for the D8 suite."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")


class SkipTest(Exception):
    pass


def fixture(name):
    p = os.path.join(FIXTURES, name)
    if not os.path.exists(p):
        raise SkipTest(f"fixture {name} missing -- run tests/make_fixtures.py")
    return p


def golden(name):
    with open(fixture(name)) as f:
        return json.load(f)


def approx(a, b, rtol=1e-3):
    assert b != 0 or abs(a) < 1e-30, f"{a} vs {b}"
    assert abs(a - b) <= rtol * abs(b), f"{a} != {b} (rtol {rtol})"
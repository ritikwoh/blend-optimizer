import itertools, numpy as np
from blend_optimizer import optimise, precheck

EL = ["C", "Mn"]


def test_hand_worked_two_material_blend():
    # A: 2% C, cost 10/kg.  B: 0% C, cost 4/kg.  Need exactly 1% C in 100 kg.
    # 50 kg A + 50 kg B -> cost 50*10 + 50*4 = 700
    m = {"A": {"cost": 10, "pct": [2.0, 0.0]}, "B": {"cost": 4, "pct": [0.0, 0.0]}}
    r = optimise(m, EL, {"C": (1.0, 1.0), "Mn": (0.0, 5.0)}, 100)
    assert r.ok and r.kg == {"A": 50.0, "B": 50.0} and r.cost == 700.0
    assert r.composition["C"] == 1.0


def test_matches_brute_force_grid():
    m = {"A": {"cost": 30, "pct": [1.0, 2.0]}, "B": {"cost": 12, "pct": [0.2, 0.5]},
         "C": {"cost": 55, "pct": [3.0, 0.1]}}
    t = {"C": (0.8, 1.2), "Mn": (0.6, 1.5)}
    r = optimise(m, EL, t, 100)
    best = None
    for a, b in itertools.product(np.arange(0, 101, 1.0), repeat=2):
        c = 100 - a - b
        if c < 0:
            continue
        c_pct = (a * 1.0 + b * 0.2 + c * 3.0) / 100
        mn_pct = (a * 2.0 + b * 0.5 + c * 0.1) / 100
        if 0.8 <= c_pct <= 1.2 and 0.6 <= mn_pct <= 1.5:
            cost = a * 30 + b * 12 + c * 55
            best = cost if best is None else min(best, cost)
    assert r.ok and r.cost <= best + 1e-6          # LP is at least as good as any grid point
    assert abs(r.cost - best) < 0.05 * best        # and the grid is close to it


def test_warns_when_element_missing():
    m = {"A": {"cost": 1, "pct": [0.0, 0.0]}}
    w = precheck(m, EL, {"C": (1.0, 2.0), "Mn": (0.0, 1.0)}, 100)
    assert any("C: no selected material" in x for x in w)
    r = optimise(m, EL, {"C": (1.0, 2.0), "Mn": (0.0, 1.0)}, 100)
    assert not r.ok


def test_usage_restriction_respected():
    m = {"A": {"cost": 1, "pct": [2.0, 0.0]}, "B": {"cost": 9, "pct": [2.0, 0.0]}}
    r = optimise(m, EL, {"C": (2.0, 2.0), "Mn": (0.0, 1.0)}, 100, max_share={"A": 0.3})
    assert r.ok and r.kg["A"] <= 30.0 + 1e-6 and r.kg["B"] >= 70.0 - 1e-6

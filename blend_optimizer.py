"""Lowest-cost blend optimiser (portfolio demo).

Pick kg of each raw material for one batch so that the final chemical composition
meets the target at minimum cost. Linear programming (SciPy HiGHS, simplex family).

Model (x_i = kg of material i, batch size B kg):
  minimise   sum(cost_i * x_i)
  subject to sum(x_i) = B
             lo_j * B <= sum(x_i * pct_ij / 100) <= hi_j * B   for each element j (target in %)
             0 <= x_i <= max_share_i * B                       (usage restriction, optional)
"""
from dataclasses import dataclass
import numpy as np
from scipy.optimize import linprog


@dataclass
class Result:
    ok: bool
    message: str
    kg: dict            # material -> kg
    cost: float
    composition: dict   # element -> achieved %
    warnings: list
    unconstrained: list = None   # elements with no range in the composition


def precheck(materials, elements, target, batch_kg):
    """Warnings BEFORE solving: element not present anywhere, or max reachable % below target minimum."""
    warns = []
    for j, el in enumerate(elements):
        lo, hi = target[el]
        best = max(m["pct"][j] for m in materials.values())
        worst = min(m["pct"][j] for m in materials.values())
        if best <= 0 and lo > 0:
            warns.append(f"{el}: no selected material contains it (target min {lo}%).")
        elif best < lo:
            warns.append(f"{el}: shortfall, best material has {best}% but target min is {lo}%.")
        if worst > hi:
            warns.append(f"{el}: every material is above the target max {hi}% (min available {worst}%).")
    return warns


def _solve(materials, elements, target, batch_kg, max_share=None):
    names = list(materials)
    cost = np.array([materials[n]["cost"] for n in names], dtype=float)
    pct = np.array([materials[n]["pct"] for n in names], dtype=float)
    A_ub, b_ub = [], []
    for j, el in enumerate(elements):
        lo, hi = target[el]
        A_ub.append(-pct[:, j] / 100.0); b_ub.append(-lo / 100.0 * batch_kg)
        A_ub.append(pct[:, j] / 100.0);  b_ub.append(hi / 100.0 * batch_kg)
    bounds = [(0.0, (max_share or {}).get(n, 1.0) * batch_kg) for n in names]
    return linprog(cost, A_ub=np.array(A_ub) if A_ub else None, b_ub=np.array(b_ub) if b_ub else None,
                   A_eq=np.ones((1, len(names))), b_eq=[batch_kg], bounds=bounds, method="highs")


def explain_infeasible(materials, elements, target, batch_kg, max_share=None):
    """Client-readable reason. Caps sum first, then single-element reasons, else relax one element at a time."""
    if max_share:
        cap_sum = sum(max_share.get(n, 1.0) for n in materials)
        if cap_sum < 1.0 - 1e-9:
            shown, nd = cap_sum * 100, 4
            while float(f"{shown:.{nd}g}") >= 100 and nd < 15:
                nd += 1
            return (f"the max_share caps of the selected materials add up to {shown:.{nd}g}% of the batch; "
                    "they must add up to at least 100%.")
    single = []
    for j, el in enumerate(elements):
        lo, hi = target[el]
        best = max(m["pct"][j] for m in materials.values())
        worst = min(m["pct"][j] for m in materials.values())
        if best < lo:
            single.append(f"{el} min {lo}% cannot be met: best selected material has only {best}%")
        if worst > hi:
            single.append(f"{el} max {hi}% cannot be met: lowest selected material already has {worst}%")
    if single:
        return "; ".join(single) + "."
    binding = []
    for el in elements:
        relaxed = dict(target); relaxed[el] = (0.0, 100.0)
        if _solve(materials, elements, relaxed, batch_kg, max_share).status == 0:
            binding.append(el)
    targets = ", ".join(f"{e}={target[e][0]}:{target[e][1]}" for e in elements if target[e] != (0.0, 100.0))
    msg = f"the combined constraints conflict (targets: {targets}"
    if max_share:
        msg += "; max_share caps apply"
    msg += ")."
    caps_only = False
    if max_share and not binding:
        caps_only = _solve(materials, elements, target, batch_kg, None).status == 0
    if caps_only:
        msg += (" No single element is to blame: the targets can be met only by loosening the max_share caps"
                " of the selected materials.")
    elif binding:
        msg += f" Binding element(s): {', '.join(binding)} - relaxing any one of these alone makes it feasible."
    else:
        msg += " No single element's relaxation makes it feasible."
    return msg


def optimise(materials, elements, target, batch_kg, max_share=None):
    names = list(materials)
    cost = np.array([materials[n]["cost"] for n in names], dtype=float)
    pct = np.array([materials[n]["pct"] for n in names], dtype=float)      # n_mat x n_el
    warns = precheck(materials, elements, target, batch_kg)
    r = _solve(materials, elements, target, batch_kg, max_share)
    if r.status == 2:
        return Result(False, explain_infeasible(materials, elements, target, batch_kg, max_share), {}, 0.0, {}, warns)
    if not r.success:
        return Result(False, f"solver could not finish ({r.message})", {}, 0.0, {}, warns)
    kg = {}
    for n, v in zip(names, r.x):
        if v > 1e-9 * batch_kg:
            v = float(v)
            r3 = round(v, 3)   # 3 decimals unless that distorts a small amount by more than 0.1 %
            kg[n] = r3 if abs(r3 - v) <= 1e-3 * v else round(v, 9)
    if not kg:
        return Result(False, "solver returned an empty blend; check the batch size and inputs", {}, 0.0, {}, warns)
    comp = {el: round(float((r.x * pct[:, j]).sum() / batch_kg), 4) for j, el in enumerate(elements)}
    return Result(True, "optimal", kg, round(float(r.fun), 2), comp, warns)

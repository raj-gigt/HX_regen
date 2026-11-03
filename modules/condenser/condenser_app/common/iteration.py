"""Numerical iteration with a recorded history, so every design can show how it converged."""
from __future__ import annotations

from typing import Callable

from scipy.optimize import brentq

from ..schemas import ConvergenceError, ConvergenceInfo


def fixed_point(
    update: Callable[[float], float],
    x0: float,
    *,
    name: str,
    tol: float = 1e-3,
    max_iter: int = 100,
    relaxation: float = 1.0,
) -> tuple[float, ConvergenceInfo]:
    """Iterate ``x = update(x)`` until the change is below ``tol`` (absolute, in the units of x).

    Raises :class:`ConvergenceError` if the tolerance is not met; the error carries the history.
    """
    x = x0
    history = [x0]
    residual = float("inf")
    for i in range(1, max_iter + 1):
        new = update(x)
        new = x + relaxation * (new - x)
        residual = abs(new - x)
        history.append(new)
        x = new
        if residual < tol:
            return x, ConvergenceInfo(name, True, i, tol, residual, history)
    info = ConvergenceInfo(name, False, max_iter, tol, residual, history)
    raise ConvergenceError(f"{name}: no convergence after {max_iter} iterations (residual {residual:.3g}).", info)


def solve_bracketed(
    func: Callable[[float], float],
    low: float,
    high: float,
    *,
    name: str,
    tol: float = 1e-6,
    max_iter: int = 200,
) -> tuple[float, ConvergenceInfo]:
    """Find the root of ``func`` inside ``[low, high]`` (Brent). Raises if the root is not bracketed."""
    f_low, f_high = func(low), func(high)
    if f_low * f_high > 0:
        info = ConvergenceInfo(name, False, 0, tol, min(abs(f_low), abs(f_high)), [low, high])
        raise ConvergenceError(f"{name}: no root between {low:g} and {high:g} (f = {f_low:.3g}, {f_high:.3g}).", info)
    history: list[float] = []

    def tracked(x: float) -> float:
        history.append(x)
        return func(x)

    root, res = brentq(tracked, low, high, xtol=tol, maxiter=max_iter, full_output=True)
    return root, ConvergenceInfo(name, bool(res.converged), res.iterations, tol, abs(func(root)), history)

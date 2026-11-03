from .properties import get_fluid_properties
from .engine import Fluid, resolve_duty

# ==============================================================================
# CELL 3: STREAM PREPARATION  (user inputs + property engine -> Bell-Delaware Fluid objects)
# ==============================================================================
# Your Fluid class needs rho, mu, cp, k "at mean temperature" and exactly one missing
# value (flow or outlet temperature) to solve from the duty.  This bridge:
#   * looks the properties up from Cell 1 at the stream's mean bulk temperature,
#   * iterates because the mean temperature itself depends on the (possibly unknown) outlet,
#   * treats an input of 0 as "unknown" (same convention as the PHE dashboard),
#   * applies the PHE "assumed effectiveness" rule when BOTH outlets are unknown,
#   * hands each stream a mu_of_T() so your wall-temperature iteration (Step 9) works
#     with the same property model.
# ==============================================================================

def _none_if_unknown(v):
    return None if (v is None or float(v) <= 0.0) else float(v)


def _make_mu_of_T(key: str, P_bar: float):
    """Viscosity-vs-temperature callable for Fluid.mu_of_T (no phase check at the wall)."""
    return lambda T, _k=key, _p=P_bar: get_fluid_properties(_k, T, _p, check_phase=False)[3]


def _build_fluid(spec: dict, T_mean: float) -> Fluid:
    key, P = spec["fluid"], spec.get("P_bar", 2.0)
    rho, cp, k, mu = get_fluid_properties(key, T_mean, P)
    return Fluid(name=spec.get("label", key), T_in=float(spec["T_in"]),
                 T_out=_none_if_unknown(spec.get("T_out")), m=_none_if_unknown(spec.get("m")),
                 rho=rho, mu=mu, cp=cp, k=k, Rf=float(spec.get("Rf", 0.0)),
                 mu_of_T=_make_mu_of_T(key, P))


def prepare_streams(hot_spec: dict, cold_spec: dict, eps_assumed: float = 0.85,
                    max_iter: int = 12, tol: float = 0.01):
    """
    hot_spec / cold_spec keys: label, fluid, T_in, T_out (<=0 -> unknown), m (<=0 -> unknown),
                               P_bar, Rf.
    Supported specifications (same logic as resolve_duty, plus the epsilon rule):
      * one stream fully known (flow + both temperatures), other stream missing flow OR outlet
      * both flows known and both outlets unknown -> duty from assumed effectiveness eps
    Returns (hot, cold, notes, eps_used_or_None) with every field of both Fluids filled in and the
    properties evaluated at the converged mean bulk temperatures.
    """
    if float(hot_spec["T_in"]) <= float(cold_spec["T_in"]):
        raise ValueError("Hot inlet temperature must exceed cold inlet temperature.")
    Thm = float(hot_spec["T_in"]) - 10.0 if _none_if_unknown(hot_spec.get("T_out")) is None else \
        0.5 * (float(hot_spec["T_in"]) + float(hot_spec["T_out"]))
    Tcm = float(cold_spec["T_in"]) + 10.0 if _none_if_unknown(cold_spec.get("T_out")) is None else \
        0.5 * (float(cold_spec["T_in"]) + float(cold_spec["T_out"]))
    notes, eps_used = [], None
    for _ in range(max_iter):
        h, c = _build_fluid(hot_spec, Thm), _build_fluid(cold_spec, Tcm)
        eps_used = None
        if h.T_out is None and c.T_out is None and h.m is not None and c.m is not None:
            Cmin = min(h.m * h.cp, c.m * c.cp)
            Q = eps_assumed * Cmin * (h.T_in - c.T_in)
            h.T_out = h.T_in - Q / (h.m * h.cp)
            c.T_out = c.T_in + Q / (c.m * c.cp)
            eps_used = eps_assumed
        try:
            Q, resolve_notes = resolve_duty(h, c)
        except ValueError as e:
            raise ValueError(
                f"{e}  Give flow + both temperatures for one stream and flow OR outlet for the other "
                "(or both flows with both outlets = 0 to use the assumed effectiveness).")
        if None in (h.m, h.T_out, c.m, c.T_out):
            raise ValueError("Under-specified duty: could not resolve all flows and temperatures.")
        if Q <= 0:
            raise ValueError(f"Non-positive duty ({Q / 1e3:.1f} kW): check the inlet/outlet temperatures.")
        Thm_new, Tcm_new = h.T_mean, c.T_mean
        done = abs(Thm_new - Thm) < tol and abs(Tcm_new - Tcm) < tol
        Thm, Tcm = Thm_new, Tcm_new
        if done:
            break
    if eps_used is not None:
        notes.append(f"Only inlet temperatures given: assumed effectiveness eps = {eps_used:.2f} "
                     f"-> Q = {Q / 1e3:,.1f} kW, outlets {h.T_out:.1f} / {c.T_out:.1f} degC")
    return h, c, notes, eps_used


def stream_property_table(hot: Fluid, cold: Fluid) -> str:
    rows = [f"  {'stream':<28}{'Tmean':>7}{'rho':>9}{'cp':>8}{'k':>8}{'mu [mPa s]':>12}{'Pr':>7}{'Rf':>10}"]
    for f in (hot, cold):
        rows.append(f"  {f.name:<28}{f.T_mean:7.1f}{f.rho:9.1f}{f.cp:8.0f}{f.k:8.3f}{f.mu * 1e3:12.3f}{f.Pr:7.2f}{f.Rf:10.2e}")
    return "\n".join(rows)

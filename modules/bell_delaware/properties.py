# ==============================================================================
# CELL 1: THERMOPHYSICAL PROPERTY ENGINE (water, industrial fluids, CoolProp, custom)
# ==============================================================================
# Same architecture as the Plate Heat Exchanger notebook:
#   1. Built-in calibrated models: water, ISO VG 46 oil, wort, 50 wt% ethanol, brine.
#   2. Dynamic CoolProp bridge (optional) for pure fluids - keys start with "CP::".
#   3. User-registered custom fluids (constant properties) from the dashboard.
#
# Differences from the PHE notebook (deliberate fixes):
#   * Water cp and k are now polynomial fits to IAPWS-95 (CoolProp), 1-150 degC,
#     max error < 0.05 %.  The earlier cp / k polynomials were up to 9 % / 4 % off.
#   * The CoolProp "Ethanol" entry no longer collides with the built-in 50 wt% mix
#     (built-in key is now "ethanol50").
#   * An unknown fluid name raises an error instead of silently returning water.
#   * CoolProp fluids are checked to be LIQUID at the given pressure (Bell-Delaware
#     as coded here is a single-phase liquid method).
# ==============================================================================

import math
import warnings
from typing import Tuple

try:
    import CoolProp.CoolProp as CP
    COOLPROP_AVAILABLE = True
except ImportError:
    CP = None
    COOLPROP_AVAILABLE = False
    # In Colab:  !pip install CoolProp   (then restart / re-run)

# Registered custom fluids: name -> (rho [kg/m3], cp [J/kgK], k [W/mK], mu [Pa s])
CUSTOM_FLUIDS = {}

BUILTIN_FLUIDS = ("water", "oil", "wort", "ethanol50", "brine")

# Polynomial fits (x = T/100, T in degC) to IAPWS-95 liquid water at 10 bar, 1-150 degC
_WATER_CP_COEF = [-99.1872961178, 462.009015673, -780.799677192, 684.696471667, -266.263599752, 4212.90020959]
_WATER_K_COEF = [0.0145453911672, -0.0686051978, 0.134773445647, -0.205009261923, 0.245407482262, 0.556648283424]


def _horner(coef, x):
    acc = 0.0
    for c in coef:
        acc = acc * x + c
    return acc


def water_properties(T_C: float) -> Tuple[float, float, float, float]:
    """
    Liquid water, 1-150 degC.
      rho : Kell (1975) formulation                         (< 0.15 % vs IAPWS-95)
      cp  : polynomial fit to IAPWS-95                      (< 0.05 %)
      k   : polynomial fit to IAPWS-95                      (< 0.05 %)
      mu  : Andrade-Vogel  mu = 2.414e-5 * 10^(247.8/(T-140))  (< 2 %)
    Returns (rho [kg/m3], cp [J/kgK], k [W/mK], mu [Pa s]).
    Temperatures outside 1-150 degC are clamped (with a warning).
    """
    T_in = float(T_C)
    if T_in < 1.0 or T_in > 150.0:
        warnings.warn(f"Water temperature {T_in:.1f} degC outside the 1-150 degC fit range; value clamped.")
    T = max(1.0, min(150.0, T_in))
    num = (999.83952 + 16.945176 * T - 7.9870401e-3 * T**2 - 46.170461e-6 * T**3
           + 105.56302e-9 * T**4 - 280.54253e-12 * T**5)
    rho = num / (1.0 + 16.897850e-3 * T)
    cp = _horner(_WATER_CP_COEF, T / 100.0)
    k = _horner(_WATER_K_COEF, T / 100.0)
    mu = 2.414e-5 * (10.0 ** (247.8 / (T + 273.15 - 140.0)))
    return float(rho), float(cp), float(k), float(mu)


def get_fluid_properties(name: str, T_C: float, P_bar: float = 2.0,
                         check_phase: bool = True) -> Tuple[float, float, float, float]:
    """
    Unified fluid property router.
      name    : "water" | "oil" | "wort" | "ethanol50" | "brine" | "CP::<CoolPropName>" | custom name
      T_C     : bulk temperature [degC]
      P_bar   : operating pressure [bar] (used by CoolProp fluids only)
      check_phase : CoolProp fluids must be liquid at (T, P); set False for wall-temperature lookups
    Returns (rho [kg/m3], cp [J/kgK], k [W/mK], mu [Pa s]).
    """
    clean = name.strip()

    # 1. user-defined custom fluids (constant properties)
    if clean in CUSTOM_FLUIDS:
        return CUSTOM_FLUIDS[clean]

    # 2. CoolProp pure fluids
    if clean.startswith("CP::"):
        if not COOLPROP_AVAILABLE:
            raise RuntimeError("CoolProp is not installed: run  pip install CoolProp  and re-run Cell 1.")
        fluid = clean[4:]
        T_K, P_Pa = float(T_C) + 273.15, float(P_bar) * 1e5
        try:
            if check_phase:
                phase = CP.PhaseSI("T", T_K, "P", P_Pa, fluid)
                if phase not in ("liquid", "supercritical_liquid"):
                    raise ValueError(f"{fluid} is '{phase}' at {T_C:.1f} degC and {P_bar:.2f} bar - "
                                     "this method needs a liquid; raise the stream pressure.")
            rho = CP.PropsSI("D", "T", T_K, "P", P_Pa, fluid)
            cp = CP.PropsSI("C", "T", T_K, "P", P_Pa, fluid)
            k = CP.PropsSI("L", "T", T_K, "P", P_Pa, fluid)
            mu = CP.PropsSI("V", "T", T_K, "P", P_Pa, fluid)
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"CoolProp could not evaluate {fluid} at {T_C:.1f} degC / {P_bar:.2f} bar: {e}")
        return float(rho), float(cp), float(k), float(mu)

    # 3. built-in calibrated models
    key = clean.lower()
    if key == "water":
        return water_properties(T_C)
    if key == "oil":                       # ISO VG 46 industrial hydraulic oil
        T = max(10.0, min(120.0, float(T_C)))
        rho = 875.0 - 0.65 * (T - 15.0)
        cp = 1900.0 + 3.5 * T
        k = 0.132 - 0.00008 * T
        mu = 0.120 * math.exp(-0.042 * T)
        return rho, cp, k, mu
    if key == "wort":                      # 12 Plato brewer's wort
        rho_w, cp_w, k_w, mu_w = water_properties(T_C)
        return rho_w * 1.045, cp_w * 0.92, k_w * 0.94, mu_w * 1.55
    if key == "ethanol50":                 # 50 wt% ethanol-water
        T = max(10.0, min(90.0, float(T_C)))
        rho = 920.0 - 0.75 * T
        cp = 3600.0 + 4.2 * T
        k = 0.38 - 0.0005 * T
        mu = 0.0035 * math.exp(-0.022 * T)
        return rho, cp, k, mu
    if key == "brine":                     # geothermal / industrial saline brine
        rho_w, cp_w, k_w, mu_w = water_properties(T_C)
        return rho_w * 1.06, cp_w * 0.95, k_w * 0.97, mu_w * 1.15

    raise ValueError(f"Unknown fluid '{name}'. Use a built-in key {BUILTIN_FLUIDS}, 'CP::<name>' "
                     "or register a custom fluid.")


def fluid_menu():
    """(label, key) pairs for the dashboard dropdowns."""
    menu = [("Water (IAPWS fits)", "water"),
            ("ISO VG 46 Hydraulic Oil", "oil"),
            ("Brewer's Wort (12 Plato)", "wort"),
            ("50 wt% Ethanol-Water", "ethanol50"),
            ("Geothermal Saline Brine", "brine")]
    if COOLPROP_AVAILABLE:
        menu += [("Water (CoolProp IAPWS-95)", "CP::Water"),
                 ("Ethanol (CoolProp)", "CP::Ethanol"),
                 ("Methanol (CoolProp)", "CP::Methanol"),
                 ("Ethylene Glycol (CoolProp)", "CP::EthyleneGlycol"),
                 ("Acetone (CoolProp)", "CP::Acetone"),
                 ("Toluene (CoolProp)", "CP::Toluene")]
    return menu

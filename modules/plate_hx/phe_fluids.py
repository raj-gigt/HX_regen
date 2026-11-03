"""MOD-PHE liquid properties from CoolProp (optional; see README.md)."""
P_ATM = 1.01325

try:
    import CoolProp.CoolProp as _CP
    AVAILABLE = True
except ImportError:
    _CP = None
    AVAILABLE = False

COMMON = ["Water", "Ethanol", "Methanol", "Acetone", "Toluene", "Benzene", "n-Heptane", "n-Octane",
          "EthyleneGlycol", "R134a", "Ammonia",
          "INCOMP::MEG-30%", "INCOMP::MEG-50%", "INCOMP::MPG-30%", "INCOMP::MPG-50%",
          "INCOMP::T66", "INCOMP::TVP1", "INCOMP::DowQ", "INCOMP::S800", "INCOMP::NaK"]


class FluidError(ValueError):
    pass


def props(name, T_C, P_bar_abs=P_ATM):
    if not AVAILABLE:
        raise FluidError("CoolProp is not installed (pip install CoolProp); give rho, cp, k, mu instead")
    T, P = T_C + 273.15, P_bar_abs * 1e5
    try:
        if not name.upper().startswith("INCOMP::"):
            phase = _CP.PhaseSI("T", T, "P", P, name)
            if phase.startswith("unknown"):
                raise FluidError(f"'{name}' is not a CoolProp fluid name (examples: {', '.join(COMMON[:6])}, "
                                 f"INCOMP::MEG-30%)")
            if phase not in ("liquid", "supercritical_liquid"):
                raise FluidError(f"{name} is '{phase}' at {T_C:.1f} °C, {P_bar_abs:.3g} bar abs; MOD-PHE needs a "
                                 f"liquid — give a higher stream P_bar or check the fluid")
        return tuple(_CP.PropsSI(q, "T", T, "P", P, name) for q in ("D", "C", "L", "V"))
    except FluidError:
        raise
    except Exception as e:
        raise FluidError(f"CoolProp could not evaluate '{name}' at {T_C:.1f} °C, {P_bar_abs:.3g} bar abs: "
                         f"{str(e).splitlines()[0]}")

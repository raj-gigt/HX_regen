"""Expand human-facing engineering abbreviations without changing payload keys."""

import re

ABBREVIATIONS = {
    "HX": "Heat Exchanger", "PHE": "Plate Heat Exchanger", "STHE": "Shell and Tube Heat Exchanger",
    "PFHE": "Plate Fin Heat Exchanger", "TFHE": "Tube Fin Heat Exchanger",
    "MOD-PHE": "Plate Heat Exchanger Module", "MOD-STHE": "Shell and Tube Heat Exchanger Module",
    "MOD-PFHE": "Plate Fin Heat Exchanger Module", "MOD-TFHE": "Tube Fin Heat Exchanger Module",
    "MOD-REGEN": "Regenerator Module", "MOD-COND": "Condenser Module", "MOD-EVAP": "Evaporator Module",
    "LMTD": "Logarithmic Mean Temperature Difference", "NTU": "Number of Transfer Units",
    "NTUc": "Cold-side Number of Transfer Units", "HTC": "Heat Transfer Coefficient",
    "CHF": "Critical Heat Flux", "CAPEX": "Capital Expenditure",
    "TEMA": "Tubular Exchanger Manufacturers Association", "ASME": "American Society of Mechanical Engineers",
    "HSB": "Hewitt, Shires and Bott", "HEDH": "Heat Exchanger Design Handbook",
    "VDI": "Association of German Engineers", "ISO": "International Organization for Standardization",
    "VG": "Viscosity Grade", "NBR": "Nitrile Butadiene Rubber", "EPDM": "Ethylene Propylene Diene Monomer",
    "OD": "Outside Diameter", "ID": "Inside Diameter", "SI": "International System of Units",
    "JSON": "JavaScript Object Notation", "CSV": "Comma Separated Values",
    "U": "Overall Heat-transfer Coefficient", "Uo": "Overall Heat-transfer Coefficient, Outside Area Basis",
    "Re": "Reynolds Number", "Pr": "Prandtl Number", "Nu": "Nusselt Number",
    "Rf": "Fouling Resistance", "Ft": "Logarithmic Mean Temperature Difference Correction Factor",
    "Q": "Heat Duty", "rho": "Density", "mu": "Dynamic Viscosity", "cp": "Specific Heat Capacity",
    "Fn": "Tube-row Correction Factor", "Fw": "Baffle-window Correction Factor",
    "Fb": "Bundle-bypass Correction Factor", "FL": "Baffle-leakage Correction Factor",
    "dP": "Pressure Drop", "Δp": "Pressure Drop", "ΔP": "Pressure Drop",
    "DP": "Pressure Drop", "CP": "CoolProp", "Cp": "Specific Heat Capacity",
    "Ds": "Shell Inside Diameter", "Db": "Tube Bundle Diameter", "Nt": "Number of Tubes",
    "Pt": "Tube Pitch", "Bc": "Baffle Cut Fraction", "lB": "Baffle Spacing",
    "Re_t": "Tube-side Reynolds Number", "Re_s": "Shell-side Reynolds Number",
    "h_i": "Tube-side Heat-transfer Coefficient", "h_s": "Shell-side Heat-transfer Coefficient",
    "h_oc": "Ideal Shell-side Cross-flow Heat-transfer Coefficient",
    "dP_s": "Shell-side Pressure Drop", "dP_t": "Tube-side Pressure Drop",
    "CA": "Corrosion Allowance", "Fprod": "Product of Shell-side Correction Factors",
}
_PATTERN = re.compile(r"(?<![\w])(" + "|".join(re.escape(key) for key in sorted(ABBREVIATIONS, key=len, reverse=True)) + r")(?![\w])")


def expand(text):
    text = str(text)
    def replace(match):
        full = ABBREVIATIONS[match.group()]
        # Keep labels that already carry a bracketed full form stable on reruns.
        suffix = text[match.end():].lstrip()
        if suffix.lower().startswith("(" + full.lower() + ")"):
            return match.group()
        return f"{match.group()} ({full})"
    return _PATTERN.sub(replace, text)

"""Tabulated fluid properties, returning the shared dataclasses. Never extrapolates: out-of-table raises ValueError.

Sources, read from the page images:
    Water/steam, saturated: HEDH Sec. 5.5.3 (NBS/NRC steam tables), Table 1 (P, rho, r = h_fg) and Table 8 (viscosity, conductivity,
        Prandtl number, surface tension). HSB Table II.1 has water only from 373.15 K, so it cannot serve vacuum condensers; it is used
        as a cross-check in the tests.
    Water, liquid: Incropera and DeWitt Appendix A as verified in HX_Notes/exam_guide/chapters/app_props.tex.
    Air, 1 atm: HSB Table II.2 (taken there from Incropera and DeWitt); 250-600 K agrees with app_props.tex.
    Other saturated fluids: HSB Table II.1 (from HEDH Sec. 5.5.1, Maddox). The last column of each table (the critical point) is left out,
        because h_fg and c_p are blank or zero there. Printed anomalies are kept, not smoothed; see the notes on each table and the test report.

Interpolation between nodes (HSB Appendix II preamble):
    ln(p_sat) and ln(mu_l) are linear in 1/T, as HSB says. HSB says vapour density "should plot as a reasonably straight line with temperature",
    but ln(rho_v) against 1/T is used instead because held-out HEDH steam-table rows show it is more accurate: at 37 degC between the 35 and 40 degC
    nodes it is 0.02% from the printed value, where the straight line is 0.7% high; tests/test_properties.py records this. Everything else is linear in T.
    Air density: rho*T is linear in T (ideal gas, app_props.tex caption), so the 50 K nodes are not bridged by a straight chord in rho.

Temperatures are in degC at the interface, kelvin inside the tables.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from typing import Callable, Sequence

from ..schemas import CondensingFluidProperties, SinglePhaseFluidProperties
from .units import c_to_k

ATM = 101325.0


# --------------------------------------------------------------------------- interpolation
def _segment(t: float, nodes: Sequence[float], what: str) -> int:
    if not nodes[0] <= t <= nodes[-1]:
        raise ValueError(f"{what}: {t - 273.15:.2f} degC is outside the table range "
                         f"{nodes[0] - 273.15:.2f} to {nodes[-1] - 273.15:.2f} degC; not extrapolating.")
    return min(bisect_right(nodes, t) - 1, len(nodes) - 2)


def _linear(t: float, nodes: Sequence[float], values: Sequence[float], what: str) -> float:
    i = _segment(t, nodes, what)
    return values[i] + (values[i + 1] - values[i]) * (t - nodes[i]) / (nodes[i + 1] - nodes[i])


def _log_reciprocal(t: float, nodes: Sequence[float], values: Sequence[float], what: str) -> float:
    i = _segment(t, nodes, what)
    fraction = (1.0 / t - 1.0 / nodes[i]) / (1.0 / nodes[i + 1] - 1.0 / nodes[i])
    return math.exp(math.log(values[i]) + (math.log(values[i + 1]) - math.log(values[i])) * fraction)


# --------------------------------------------------------------------------- saturation tables
@dataclass(frozen=True)
class SaturationTable:
    """One fluid from HSB Table II.1, in the book's units: T K, p kPa, h_fg and c_p kJ/kg(.K), eta uPa.s, lambda mW/(m.K), sigma mN/m."""

    label: str
    source: str
    t: tuple[float, ...]
    p: tuple[float, ...]
    rho_l: tuple[float, ...]
    rho_v: tuple[float, ...]
    h_fg: tuple[float, ...]
    cp_l: tuple[float, ...]
    cp_v: tuple[float, ...]
    mu_l: tuple[float, ...]
    mu_v: tuple[float, ...]
    k_l: tuple[float, ...]
    k_v: tuple[float, ...]
    sigma: tuple[float, ...]
    molecular_weight: float | None = None
    critical_temperature_k: float | None = None
    notes: str = ""


def _hsb(page: int) -> str:
    return f"HSB Table II.1, p. {page} (from HEDH Sec. 5.5.1, Maddox)"


N_PENTANE = SaturationTable(
    "n-pentane", _hsb(986),
    t=(309.2, 335, 350, 365, 380, 395, 410, 425, 440),
    p=(101.3, 227, 341, 492, 688, 935, 1249, 1634, 2103),
    rho_l=(610.2, 582.9, 566.0, 548.0, 528.9, 507.9, 484.1, 456.5, 423.5),
    rho_v=(3.00, 6.36, 9.41, 13.51, 18.99, 26.11, 36.21, 49.73, 68.96),
    h_fg=(358.2, 337.3, 321.0, 309.4, 286.1, 267.5, 248.9, 218.6, 190.7),
    cp_l=(2.34, 2.52, 2.62, 2.72, 2.82, 2.94, 3.06, 3.20, 3.44),
    cp_v=(1.79, 1.96, 2.05, 2.16, 2.28, 2.48, 2.66, 2.96, 3.37),
    mu_l=(196, 159, 140, 123, 108, 95, 83, 72, 60),
    mu_v=(6.9, 7.6, 8.1, 8.5, 9.0, 9.5, 10.2, 11.1, 12.4),
    k_l=(107, 98, 93, 88, 83, 79, 75, 71, 69),
    k_v=(16.7, 19.3, 21.0, 22.8, 24.8, 26.7, 29.0, 31.7, 34.9),
    sigma=(14.3, 11.3, 9.4, 8.1, 6.7, 5.2, 3.8, 2.8, 1.6),
    molecular_weight=72.151, critical_temperature_k=469.6,
    notes="h_fg at 365 K (309.4) and 410 K (248.9) sit about 6 kJ/kg above the chord of their neighbours; printed values kept.",
)
ISOPENTANE = SaturationTable(
    "isopentane", _hsb(986),
    t=(301.0, 325, 340, 355, 370, 385, 400, 415, 430),
    p=(101.3, 217, 328, 476, 667, 913, 1222, 1603, 2070),
    rho_l=(613, 586, 569, 552, 532, 511, 488, 461, 428),
    rho_v=(3.07, 6.30, 9.41, 13.5, 18.9, 26.2, 36.0, 49.3, 68.3),
    h_fg=(341.9, 321.0, 309.3, 293.1, 274.5, 260.6, 237.3, 218.6, 186.0),
    cp_l=(2.29, 2.43, 2.53, 2.62, 2.71, 2.80, 2.91, 3.05, 3.24),
    cp_v=(1.72, 1.86, 1.96, 2.08, 2.20, 2.34, 2.54, 2.81, 3.28),
    mu_l=(201, 163, 146, 126, 111, 97, 84, 71, 60),
    mu_v=(7.4, 8.0, 8.5, 9.0, 9.5, 9.9, 10.5, 11.2, 12.2),
    k_l=(103, 95, 91, 87, 84, 80, 75, 70, 63),
    k_v=(14.7, 17.4, 19.3, 21.5, 23.4, 25.0, 27.6, 29.4, 33.4),
    sigma=(14.0, 11.5, 9.9, 8.4, 7.0, 5.6, 4.3, 3.0, 1.9),
    molecular_weight=72.146, critical_temperature_k=460.4,
)
N_HEXANE = SaturationTable(
    "n-hexane", _hsb(987),
    t=(341.88, 370, 385, 400, 415, 430, 445, 460, 475),
    p=(101.3, 228, 331, 465, 638, 854, 1124, 1457, 1859),
    rho_l=(613, 585, 568, 551, 532, 511, 488, 463, 432),
    rho_v=(3.3, 7.0, 10.0, 14.1, 19.5, 26.7, 34.7, 48.6, 66.2),
    h_fg=(332.6, 311.7, 295.4, 283.8, 269.8, 246.5, 230.2, 204.7, 179.1),
    cp_l=(2.39, 2.58, 2.68, 2.78, 2.89, 3.00, 3.12, 3.26, 3.46),
    cp_v=(1.91, 2.07, 2.18, 2.28, 2.39, 2.51, 2.66, 2.92, 3.32),
    mu_l=(202.2, 158.9, 145.7, 128.5, 113.6, 99.9, 87.4, 75.6, 64.3),
    mu_v=(7.3, 7.9, 8.4, 8.8, 9.4, 10.1, 10.9, 11.9, 13.3),
    k_l=(100.4, 91.0, 87, 82, 78, 74.5, 67.8, 63.0, 56.0),
    k_v=(16.7, 18.8, 20.4, 22.4, 24.2, 26.2, 28.5, 30.4, 33.8),
    sigma=(13.33, 10.57, 9.13, 7.71, 6.35, 5.02, 3.78, 2.66, 1.63),
    molecular_weight=86.178, critical_temperature_k=507.44,
)
N_HEPTANE = SaturationTable(
    "n-heptane", _hsb(987),
    t=(371.6, 380, 400, 420, 440, 460, 480, 500, 520),
    p=(101.3, 130, 219, 349, 529, 721, 1094, 1513, 2046),
    rho_l=(614, 606, 585, 563, 540, 512, 484, 448, 397),
    rho_v=(3.46, 4.36, 7.23, 11.5, 17.4, 25.6, 37.8, 56.5, 88.3),
    h_fg=(319.7, 311.7, 293.1, 274.4, 258.1, 234.9, 211.7, 183.8, 139.6),
    cp_l=(2.57, 2.61, 2.72, 2.82, 2.93, 3.03, 3.19, 3.39, 3.85),
    cp_v=(1.98, 2.01, 2.15, 2.26, 2.41, 2.51, 2.72, 3.05, 3.60),
    mu_l=(201, 186, 159, 135, 115, 97, 82, 67, 54),
    mu_v=(7.3, 7.7, 8.3, 9.0, 9.7, 10.7, 12.1, 14.0, 17.6),
    k_l=(98.0, 95.5, 88.8, 82.9, 76.1, 69.9, 61.1, 52.0, 41.8),
    k_v=(18.0, 18.4, 20.1, 22.6, 24.9, 27.7, 29.9, 33.0, 36.0),
    sigma=(12.6, 11.8, 10.0, 8.3, 6.6, 5.1, 3.6, 2.2, 0.8),
    molecular_weight=100.198, critical_temperature_k=540.61,
    notes="p_sat at 460 K (721 kPa) is low against its neighbours on ln p vs 1/T; printed value kept.",
)
METHANOL = SaturationTable(
    "methanol", _hsb(997),
    t=(337.85, 353.2, 373.2, 393.2, 413.2, 433.2, 453.2, 473.2),
    p=(101.3, 178.4, 349.4, 633.3, 1076, 1736, 2678, 3970),
    rho_l=(751.0, 735.5, 714.0, 690.0, 664.0, 634.0, 598.0, 553.0),
    rho_v=(1.222, 2.084, 3.984, 7.142, 12.16, 19.94, 31.86, 50.75),
    h_fg=(1101, 1070, 1022, 968, 922, 843, 756, 645),
    cp_l=(2.88, 3.03, 3.26, 3.52, 3.80, 4.11, 4.45, 4.81),
    cp_v=(1.55, 1.61, 1.69, 1.83, 1.99, 2.20, 2.56, 3.65),
    mu_l=(326, 271, 214, 170, 136, 109, 88.3, 71.6),
    mu_v=(11.1, 11.6, 12.4, 13.1, 14.0, 14.9, 16.0, 17.4),
    k_l=(191.4, 187.0, 181.3, 178.5, 170.0, 164.0, 158.7, 153.0),
    k_v=(18.3, 20.6, 23.2, 26.2, 29.7, 33.8, 39.4, 46.9),
    sigma=(18.75, 17.5, 15.7, 13.6, 11.5, 9.3, 6.9, 4.5),
    molecular_weight=32.00, critical_temperature_k=513.15,
    notes="Stops at 473.2 K: c_p,l is blank at 493.2 K in the book.",
)
ETHANOL = SaturationTable(
    "ethanol", _hsb(997),
    t=(351.45, 373, 393, 413, 433, 453, 473, 483),
    p=(101.3, 226, 429, 753, 1256, 1960, 2940, 3560),
    rho_l=(757.0, 733.7, 709.0, 680.3, 648.5, 610.5, 564.0, 537.6),
    rho_v=(1.435, 3.175, 5.841, 10.25, 17.15, 27.65, 44.40, 56.85),
    h_fg=(963.0, 927.0, 885.5, 834.0, 772.9, 698.9, 598.3, 536.7),
    cp_l=(3.00, 3.30, 3.61, 3.96, 4.65, 5.51, 6.16, 6.61),
    cp_v=(1.83, 1.92, 2.02, 2.11, 2.31, 2.80, 3.18, 3.78),
    mu_l=(428.7, 314.3, 240.0, 185.5, 144.6, 113.6, 89.6, 79.7),
    mu_v=(10.4, 11.1, 11.7, 12.3, 12.9, 13.7, 14.5, 15.1),
    k_l=(153.6, 150.7, 146.5, 141.9, 137.2, 134.8, 129.1, 125.6),
    k_v=(19.9, 22.4, 24.5, 26.8, 29.3, 32.1, 35.3, 37.8),
    sigma=(17.7, 15.7, 13.6, 11.5, 9.3, 6.9, 4.5, 3.3),
    molecular_weight=46.1, critical_temperature_k=516.25,
    notes="Stops at 483 K: c_p,l is blank at 503 K in the book.",
)
AMMONIA = SaturationTable(
    "ammonia", _hsb(1009),
    t=(239.75, 250, 270, 290, 310, 330, 350, 370, 390),
    p=(101.3, 165.4, 381.9, 775.3, 1424.9, 2422, 3870, 5891, 8606),
    rho_l=(682, 669, 643, 615, 584, 551, 512, 466, 400),
    rho_v=(0.86, 1.41, 3.09, 6.08, 11.0, 18.9, 31.5, 52.6, 93.3),
    h_fg=(1368, 1338, 1273, 1200, 1115, 1019, 899, 744, 508),
    cp_l=(4.472, 4.513, 4.585, 4.649, 4.857, 5.066, 5.401, 5.861, 7.74),
    cp_v=(2.12, 2.32, 2.69, 3.04, 3.44, 3.90, 4.62, 6.21, 8.07),
    mu_l=(285, 246, 190, 152, 125, 105, 88.5, 70.2, 50.7),
    mu_v=(9.25, 9.59, 10.30, 11.05, 11.86, 12.74, 13.75, 15.06, 17.15),
    k_l=(614, 592, 569, 501, 456, 411, 365, 320, 275),
    k_v=(18.8, 19.8, 22.7, 25.2, 28.9, 34.3, 39.5, 50.4, 69.2),
    sigma=(33.9, 31.5, 26.9, 22.4, 18.0, 13.7, 9.60, 5.74, 2.21),
    molecular_weight=17.032, critical_temperature_k=405.55,
    notes="The book prints c_p,v at 310 K as 'S3.44' (a misprint for 3.44).",
)
R22 = SaturationTable(
    "refrigerant 22", _hsb(1002),
    t=(250, 265, 280, 295, 310, 325, 340, 355),
    p=(218, 376, 619, 958, 1420, 2020, 2800, 3800),
    rho_l=(1360, 1313, 1260, 1206, 1146, 1076, 991, 877),
    rho_v=(9.59, 16.1, 26.3, 40.6, 60.9, 90.2, 134, 208),
    h_fg=(225.6, 210.8, 198.6, 185.2, 169.8, 151.6, 128.7, 95.7),
    cp_l=(1.13, 1.16, 1.19, 1.24, 1.30, 1.41, 1.65, 2.43),
    cp_v=(0.646, 0.691, 0.747, 0.820, 0.930, 1.09, 1.40, 2.31),
    mu_l=(282, 251, 225, 204, 187, 172, 150, 119),
    mu_v=(10.9, 11.7, 12.3, 13.2, 14.2, 15.7, 16.4, 18.8),
    k_l=(109, 101, 94.2, 86.6, 78.8, 70.2, 59.2, 44.0),
    k_v=(8.22, 9.10, 10.1, 11.2, 12.4, 14.0, 16.0, 18.8),
    sigma=(15.5, 13.0, 10.6, 8.4, 6.2, 4.3, 2.5, 1.0),
    molecular_weight=86.48, critical_temperature_k=369.3,
    notes="The book's first column (242.4 K, 101.3 kPa) is omitted: from it to 250 K the slope of ln p vs 1/T is about 2.5 times "
          "that of the next interval, so the book's own numbers disagree there.",
)

_TABLES: dict[str, SaturationTable] = {
    "n_pentane": N_PENTANE,
    "isopentane": ISOPENTANE,
    "n_hexane": N_HEXANE,
    "n_heptane": N_HEPTANE,
    "methanol": METHANOL,
    "ethanol": ETHANOL,
    "ammonia": AMMONIA,
    "r22": R22,
}

# ---- water/steam: HEDH Sec. 5.5.3 (NBS/NRC). Table 1 at 5 K to 100 degC, then 10 K. P bar, rho kg/m3, r kJ/kg.
_W1_T = (0.01, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100,
         110, 120, 130, 140, 150, 160, 170, 180, 190, 200, 210, 220, 230, 240, 250, 260, 270, 280, 290, 300)
_W1_P = (0.0061173, 0.0087260, 0.012281, 0.017056, 0.023388, 0.031691, 0.042455, 0.056267, 0.073814, 0.095898, 0.12344,
         0.15752, 0.19932, 0.25022, 0.31176, 0.38563, 0.47373, 0.57815, 0.70117, 0.84529, 1.0132,
         1.4324, 1.9848, 2.7002, 3.6119, 4.7572, 6.1766, 7.9147, 10.019, 12.542, 15.537, 19.062, 23.178, 27.951, 33.447,
         39.737, 46.895, 54.999, 64.132, 74.380, 85.838)
_W1_RHO_L = (999.78, 999.94, 999.69, 999.09, 998.19, 997.02, 995.61, 993.99, 992.17, 990.17, 987.99,
             985.65, 983.16, 980.53, 977.75, 974.84, 971.79, 968.62, 965.33, 961.92, 958.39,
             951.00, 943.16, 934.88, 926.18, 917.06, 907.50, 897.51, 887.06, 876.15, 864.74, 852.82, 840.34, 827.25, 813.52,
             799.07, 783.83, 767.68, 750.52, 732.16, 712.41)
_W1_RHO_V = (0.004855, 0.006802, 0.009405, 0.012837, 0.017308, 0.023065, 0.030399, 0.039650, 0.05121, 0.06552, 0.08308,
             0.10446, 0.13030, 0.16130, 0.19823, 0.24194, 0.29336, 0.35349, 0.42343, 0.5043, 0.5975,
             0.8260, 1.1208, 1.4954, 1.9647, 2.5454, 3.2564, 4.1181, 5.154, 6.390, 7.854, 9.581, 11.607, 13.976, 16.739,
             19.956, 23.700, 28.061, 33.152, 39.119, 46.154)
_W1_R = (2500.5, 2488.7, 2476.9, 2465.1, 2453.3, 2441.5, 2429.7, 2417.8, 2405.9, 2393.9, 2381.9,
         2369.8, 2357.6, 2345.4, 2333.1, 2320.7, 2308.1, 2295.5, 2282.7, 2269.8, 2256.7,
         2229.9, 2202.4, 2174.0, 2144.6, 2114.1, 2082.3, 2049.2, 2014.5, 1978.2, 1940.1, 1900.0, 1857.8, 1813.1, 1765.7,
         1715.4, 1661.9, 1604.6, 1543.1, 1476.7, 1404.7)
# Table 8 at 10 K. eta uPa.s, lambda mW/(m.K), sigma mN/m. c_p is not in Table 8, so c_p = Pr lambda / eta is derived at the nodes.
_W8_T = (0.01, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 170, 180, 190, 200,
         210, 220, 230, 240, 250, 260, 270, 280, 290, 300)
_W8_MU_L = (1791, 1308, 1003, 798, 653, 547.1, 466.8, 404.5, 355.0, 315.1, 282.3, 255.1, 232.2, 212.8, 196.3, 182.0, 169.6, 158.9,
            149.4, 141.0, 133.6, 127.0, 121.0, 115.5, 110.5, 105.8, 101.5, 97.4, 93.4, 89.6, 85.8)
_W8_MU_V = (9.22, 9.46, 9.73, 10.01, 10.31, 10.62, 10.94, 11.26, 11.60, 11.93, 12.28, 12.62, 12.97, 13.32, 13.67, 14.02, 14.37, 14.72,
            15.07, 15.42, 15.78, 16.13, 16.49, 16.85, 17.22, 17.59, 17.98, 18.38, 18.80, 19.25, 19.74)
_W8_K_L = (561.0, 580.0, 598.4, 615.4, 630.5, 643.5, 654.3, 663.1, 670.0, 675.3, 679.1, 681.7, 683.2, 683.7, 683.3, 682.1, 680.0, 677.1,
           673.4, 668.8, 663.4, 657.1, 649.8, 641.4, 632.0, 621.4, 609.4, 596.1, 581.4, 565.2, 547.7)
_W8_K_V = (17.07, 17.62, 18.23, 18.89, 19.60, 20.36, 21.19, 22.07, 23.01, 24.02, 25.09, 26.24, 27.46, 28.76, 30.14, 31.59, 33.12, 34.74,
           36.44, 38.23, 40.10, 42.07, 44.15, 46.35, 48.70, 51.22, 53.98, 57.04, 60.51, 64.57, 69.47)
_W8_PR_L = (13.50, 9.444, 7.010, 5.423, 4.332, 3.555, 2.984, 2.554, 2.223, 1.962, 1.753, 1.584, 1.444, 1.328, 1.232, 1.151, 1.082, 1.025,
            0.977, 0.937, 0.904, 0.878, 0.857, 0.842, 0.832, 0.827, 0.828, 0.835, 0.848, 0.870, 0.901)
_W8_PR_V = (1.008, 1.006, 1.004, 1.003, 1.002, 1.001, 1.000, 0.999, 0.999, 0.999, 1.000, 1.001, 1.004, 1.007, 1.013, 1.020, 1.030, 1.042,
            1.058, 1.077, 1.101, 1.128, 1.161, 1.200, 1.244, 1.296, 1.355, 1.423, 1.502, 1.593, 1.699)
_W8_SIGMA = (75.65, 74.22, 72.74, 71.20, 69.60, 67.95, 66.24, 64.49, 62.68, 60.82, 58.92, 56.97, 54.97, 52.94, 50.86, 48.75, 46.60, 44.41,
             42.20, 39.95, 37.68, 35.39, 33.08, 30.75, 28.40, 26.05, 23.70, 21.35, 19.00, 16.67, 14.37)
_W1_TK = tuple(c_to_k(v) for v in _W1_T)
_W8_TK = tuple(c_to_k(v) for v in _W8_T)
_W8_CP_L = tuple(p * k * 1e-3 / (mu * 1e-6) for p, k, mu in zip(_W8_PR_L, _W8_K_L, _W8_MU_L))  # J/(kg.K)
_W8_CP_V = tuple(p * k * 1e-3 / (mu * 1e-6) for p, k, mu in zip(_W8_PR_V, _W8_K_V, _W8_MU_V))  # J/(kg.K)
WATER_SATURATED_SOURCE = "HEDH Sec. 5.5.3 Tables 1 and 8 (NBS/NRC Steam Tables); c_p = Pr k / mu derived from Table 8"

# ---- liquid water, app_props.tex (Incropera and DeWitt Appendix A)
_WL_T = (275, 280, 285, 290, 295, 300, 305, 310, 315, 320, 325, 330, 335, 340, 345, 350, 355, 360, 365, 370, 373.15, 380, 390, 400)
_WL_RHO = (1000, 1000, 1000, 999, 998, 997, 995, 993, 991, 989, 987, 984, 982, 979, 977, 974, 971, 967, 963, 961, 958, 953, 945, 937)
_WL_CP = (4211, 4198, 4189, 4184, 4181, 4179, 4178, 4178, 4179, 4180, 4182, 4184, 4186, 4188, 4191, 4195, 4199, 4203, 4209, 4214, 4217, 4226, 4239, 4256)
_WL_MU = (1652, 1422, 1225, 1080, 959, 855, 769, 695, 631, 577, 528, 489, 453, 420, 389, 365, 343, 324, 306, 289, 279, 260, 237, 217)
_WL_K = (574, 582, 590, 598, 606, 613, 620, 628, 634, 640, 645, 650, 656, 660, 664, 668, 671, 674, 677, 679, 680, 683, 686, 688)
WATER_LIQUID_SOURCE = "Incropera and DeWitt, Appendix A, as verified in HX_Notes/exam_guide/chapters/app_props.tex"

# ---- air at 1 atm, HSB Table II.2 p. 1018 (Incropera and DeWitt)
_AIR_T = (200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 800, 850, 900, 950, 1000)
_AIR_RHO = (1.7458, 1.3947, 1.1614, 0.9950, 0.8711, 0.7740, 0.6964, 0.6329, 0.5804, 0.5356, 0.4975, 0.4643, 0.4354, 0.4097, 0.3868, 0.3666, 0.3482)
_AIR_CP = (1.007, 1.006, 1.007, 1.009, 1.014, 1.021, 1.030, 1.040, 1.051, 1.063, 1.075, 1.087, 1.099, 1.110, 1.121, 1.131, 1.141)
_AIR_MU = (132.5, 159.6, 184.6, 208.2, 230.1, 250.7, 270.1, 288.4, 305.8, 322.5, 338.8, 354.6, 369.8, 384.3, 398.1, 411.3, 424.4)
_AIR_K = (18.1, 22.3, 26.3, 30.0, 33.8, 37.3, 40.7, 43.9, 46.9, 49.7, 52.4, 54.9, 57.3, 59.6, 62.0, 64.3, 66.7)
AIR_SOURCE = "HSB Table II.2, p. 1018 (from Incropera and DeWitt); 250-600 K agrees with app_props.tex"


# --------------------------------------------------------------------------- public functions
def water_saturated(t_c: float) -> CondensingFluidProperties:
    """Saturated water and steam at ``t_c`` degC, 0.01 to 300 degC (HEDH 5.5.3 Tables 1, 8). Raises ValueError outside.

    Covers vacuum duties, which HSB Table II.1 (from 100 degC) cannot.
    """
    t = c_to_k(t_c)
    what = "water_saturated"
    return CondensingFluidProperties(
        name="water/steam",
        T_sat=t_c,
        h_fg=_linear(t, _W1_TK, _W1_R, what) * 1e3,
        rho_l=_linear(t, _W1_TK, _W1_RHO_L, what),
        rho_v=_log_reciprocal(t, _W1_TK, _W1_RHO_V, what),
        mu_l=_log_reciprocal(t, _W8_TK, _W8_MU_L, what) * 1e-6,
        mu_v=_linear(t, _W8_TK, _W8_MU_V, what) * 1e-6,
        k_l=_linear(t, _W8_TK, _W8_K_L, what) * 1e-3,
        cp_l=_linear(t, _W8_TK, _W8_CP_L, what),
        sigma=_linear(t, _W8_TK, _W8_SIGMA, what) * 1e-3,
    )


def water_liquid(t_c: float) -> SinglePhaseFluidProperties:
    """Saturated liquid water as a single-phase coolant, 275 to 400 K, i.e. 1.85 to 126.85 degC (Incropera Appendix A via app_props.tex). Raises ValueError outside."""
    t = c_to_k(t_c)
    what = "water_liquid"
    return SinglePhaseFluidProperties(
        name="water",
        rho=_linear(t, _WL_T, _WL_RHO, what),
        cp=_linear(t, _WL_T, _WL_CP, what),
        mu=_log_reciprocal(t, _WL_T, _WL_MU, what) * 1e-6,
        k=_linear(t, _WL_T, _WL_K, what) * 1e-3,
    )


def air(t_c: float, p_pa: float = ATM) -> SinglePhaseFluidProperties:
    """Dry air, 200 to 1000 K, i.e. -73.15 to 726.85 degC (HSB Table II.2). Raises ValueError outside.

    Tabulated at 1 atm. rho scales as p/T for an ideal gas (app_props.tex); other properties are held at their 1 atm values, so ``p_pa`` is for near-atmospheric air only.
    """
    if p_pa <= 0:
        raise ValueError("Air pressure must be positive.")
    t = c_to_k(t_c)
    what = "air"
    rho_t = tuple(r * n for r, n in zip(_AIR_RHO, _AIR_T))
    return SinglePhaseFluidProperties(
        name="air",
        rho=_linear(t, _AIR_T, rho_t, what) / t * p_pa / ATM,
        cp=_linear(t, _AIR_T, _AIR_CP, what) * 1e3,
        mu=_linear(t, _AIR_T, _AIR_MU, what) * 1e-7,
        k=_linear(t, _AIR_T, _AIR_K, what) * 1e-3,
    )


def _table(key: str) -> SaturationTable:
    if key not in _TABLES:
        raise ValueError(f"No saturation table {key!r}; available: {sorted(_TABLES)} and 'water'.")
    return _TABLES[key]


def saturated(key: str, t_c: float) -> CondensingFluidProperties:
    """Saturated properties of a named fluid ('water' or a key of HSB Table II.1 fluids below) at ``t_c`` degC. Raises ValueError outside the table."""
    if key == "water":
        return water_saturated(t_c)
    table = _table(key)
    t = c_to_k(t_c)
    what = table.label
    return CondensingFluidProperties(
        name=table.label,
        T_sat=t_c,
        h_fg=_linear(t, table.t, table.h_fg, what) * 1e3,
        rho_l=_linear(t, table.t, table.rho_l, what),
        rho_v=_log_reciprocal(t, table.t, table.rho_v, what),
        mu_l=_log_reciprocal(t, table.t, table.mu_l, what) * 1e-6,
        mu_v=_linear(t, table.t, table.mu_v, what) * 1e-6,
        k_l=_linear(t, table.t, table.k_l, what) * 1e-3,
        cp_l=_linear(t, table.t, table.cp_l, what) * 1e3,
        sigma=_linear(t, table.t, table.sigma, what) * 1e-3,
    )


def saturated_vapour(key: str, t_c: float) -> SinglePhaseFluidProperties:
    """Saturated vapour as a single-phase stream (for alpha_G or desuperheating): rho_v, c_p,v, mu_v, k_v at ``t_c`` degC. Raises ValueError outside the table."""
    t = c_to_k(t_c)
    if key == "water":
        what = "water vapour"
        return SinglePhaseFluidProperties(
            name="steam",
            rho=_log_reciprocal(t, _W1_TK, _W1_RHO_V, what),
            cp=_linear(t, _W8_TK, _W8_CP_V, what),
            mu=_linear(t, _W8_TK, _W8_MU_V, what) * 1e-6,
            k=_linear(t, _W8_TK, _W8_K_V, what) * 1e-3,
        )
    table = _table(key)
    what = table.label + " vapour"
    return SinglePhaseFluidProperties(
        name=what,
        rho=_log_reciprocal(t, table.t, table.rho_v, what),
        cp=_linear(t, table.t, table.cp_v, what) * 1e3,
        mu=_linear(t, table.t, table.mu_v, what) * 1e-6,
        k=_linear(t, table.t, table.k_v, what) * 1e-3,
    )


def _pressure_table(key: str) -> tuple[Sequence[float], list[float], str]:
    if key == "water":
        return _W1_TK, [v * 1e5 for v in _W1_P], "water"
    table = _table(key)
    return table.t, [v * 1e3 for v in table.p], table.label


def saturation_pressure(key: str, t_c: float) -> float:
    """Saturation pressure [Pa] at ``t_c`` degC; ln p linear in 1/T (HSB Appendix II preamble). Raises ValueError outside the table."""
    nodes, pressure, what = _pressure_table(key)
    return _log_reciprocal(c_to_k(t_c), nodes, pressure, what)


def saturation_temperature(key: str, p_pa: float) -> float:
    """Saturation temperature [degC] at ``p_pa``, the exact inverse of saturation_pressure. Raises ValueError outside the table."""
    nodes, pressure, what = _pressure_table(key)
    if not pressure[0] <= p_pa <= pressure[-1]:
        raise ValueError(f"{what}: {p_pa:g} Pa is outside the table range {pressure[0]:g} to {pressure[-1]:g} Pa; not extrapolating.")
    i = min(bisect_right(pressure, p_pa) - 1, len(pressure) - 2)
    fraction = (math.log(p_pa) - math.log(pressure[i])) / (math.log(pressure[i + 1]) - math.log(pressure[i]))
    return 1.0 / (1.0 / nodes[i] + fraction * (1.0 / nodes[i + 1] - 1.0 / nodes[i])) - 273.15


# --------------------------------------------------------------------------- fixed data sets from worked examples
def pentane_hsb_example_16_2() -> CondensingFluidProperties:
    """n-pentane at 335 K exactly as stated for HSB Ex. 16.2 (p. 584), used in Ex. 16.3, 16.5, 16.6, 19.1, 19.2.

    The book's data line prints c_pL as ".52 kJ/(kg K)": a misprint; its solution and Table II.1 use 2.52.
    """
    return CondensingFluidProperties(
        name="n-pentane (HSB Ex. 16.2)", T_sat=335.0 - 273.15, h_fg=337.3e3, rho_l=582.9, rho_v=6.36,
        mu_l=159e-6, mu_v=7.6e-6, k_l=98e-3, cp_l=2520.0, sigma=11.3e-3,
    )


# --------------------------------------------------------------------------- registry
@dataclass(frozen=True)
class FluidPreset:
    """One entry of :data:`PRESETS`. ``at(t_c)`` returns the shared dataclass for that state."""

    key: str
    label: str
    kind: str  # 'saturated' -> CondensingFluidProperties; 'single_phase' -> SinglePhaseFluidProperties; 'fixed' -> one stated state
    t_min_c: float
    t_max_c: float
    source: str
    function: Callable[[float], object]
    notes: str = ""

    def at(self, t_c: float):
        return self.function(t_c)


def _fixed_pentane(t_c: float) -> CondensingFluidProperties:
    state = pentane_hsb_example_16_2()
    if abs(t_c - state.T_sat) > 1e-6:
        raise ValueError(f"This data set exists only at {state.T_sat:.2f} degC (335 K); use 'n_pentane' for other temperatures.")
    return state


def _saturated_function(key: str) -> Callable[[float], CondensingFluidProperties]:
    return lambda t_c: saturated(key, t_c)


PRESETS: dict[str, FluidPreset] = {
    "water_saturated": FluidPreset("water_saturated", "Water / steam (saturated)", "saturated", 0.01, 300.0, WATER_SATURATED_SOURCE, water_saturated),
    "water_liquid": FluidPreset("water_liquid", "Water (liquid coolant)", "single_phase", 275.0 - 273.15, 400.0 - 273.15, WATER_LIQUID_SOURCE, water_liquid),
    "air": FluidPreset("air", "Air, 1 atm", "single_phase", 200.0 - 273.15, 1000.0 - 273.15, AIR_SOURCE, air),
    "n_pentane_hsb_ex16_2": FluidPreset(
        "n_pentane_hsb_ex16_2", "n-pentane, 335 K (HSB Ex. 16.2)", "fixed", 335.0 - 273.15, 335.0 - 273.15,
        "HSB Example 16.2, p. 584", _fixed_pentane,
    ),
}
for _key, _tbl in _TABLES.items():
    PRESETS[_key] = FluidPreset(
        _key, f"{_tbl.label} (saturated)", "saturated", _tbl.t[0] - 273.15, _tbl.t[-1] - 273.15, _tbl.source, _saturated_function(_key), _tbl.notes,
    )
del _key, _tbl

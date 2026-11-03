"""Source catalogue. Modules cite these keys, so the report can list what each result rests on."""
from __future__ import annotations

REFERENCES = {
    "HSB": "Hewitt, G.F., Shires, G.L. and Bott, T.R., Process Heat Transfer, CRC Press / Begell House, 1994.",
    "HEDH": "Heat Exchanger Design Handbook, Hemisphere Publishing (Hewitt, ed.).",
    "KL": "Kays, W.M. and London, A.L., Compact Heat Exchangers.",
    "ME6220-L": "Das, S.K., ME6220 Heat Exchanger Design lecture slides, IIT Madras, 2026 (Lectures 1-28).",
    "ME6220-T": "ME6220 Tutorials 1-4, IIT Madras, 2026.",
    "INCROPERA": "Incropera, F.P. and DeWitt, D.P., Fundamentals of Heat and Mass Transfer, Appendix A property tables.",
}


def cite(*keys: str) -> list[str]:
    return [REFERENCES[k] for k in keys]

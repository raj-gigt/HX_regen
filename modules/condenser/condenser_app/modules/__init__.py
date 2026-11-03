"""Module registry. A module registers itself: add a file here with a CondenserModule subclass.

Discovery avoids merge conflicts on a shared registry list when teammates work on separate modules.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil

from .base import CondenserModule

# Display order in the app. Discovered modules not listed here follow, alphabetically.
ORDER = ("selection", "direct_contact", "plate", "vertical_shell_tube", "air_cooled")


def _discover() -> dict[str, CondenserModule]:
    found: dict[str, CondenserModule] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name == "base":
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if issubclass(cls, CondenserModule) and cls is not CondenserModule and cls.__module__ == mod.__name__:
                instance = cls()
                found[instance.key] = instance
    ranked = sorted(found, key=lambda k: (ORDER.index(k) if k in ORDER else len(ORDER), k))
    return {k: found[k] for k in ranked}


MODULES: dict[str, CondenserModule] = _discover()

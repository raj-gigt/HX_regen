"""Consistent terminal presentation for module result envelopes."""

import json
from typing import Callable, Optional

from core.contracts import ModuleResult


class TerminalResultPresenter:
    def __init__(self, output_fn: Optional[Callable[[str], None]] = None) -> None:
        self._output_fn = output_fn

    @staticmethod
    def to_payload(result: ModuleResult) -> dict:
        return {
            "status": result.status,
            "results": result.results,
            "warnings": result.warnings,
            "errors": result.errors,
            "artifacts": [str(path) for path in result.artifacts],
        }

    def present(self, result: ModuleResult) -> None:
        rendered = json.dumps(self.to_payload(result), indent=2, default=str)
        (self._output_fn or print)(rendered)

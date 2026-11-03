"""The interface every condenser module implements. Change it only after agreeing with the team."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..schemas import DesignResult, InputIssue


class CondenserModule(ABC):
    key: str            # registry key, e.g. "plate"
    title: str          # shown in the UI and report
    description: str
    input_class: type   # dataclass built from schemas.inp / schemas.group

    def new_inputs(self) -> Any:
        return self.input_class()

    @abstractmethod
    def example_inputs(self) -> Any:
        """A complete, valid input set from a cited source, used by "Load example" and the benchmarks."""

    def relevant_fields(self, inputs: Any) -> set[str] | None:
        """Dotted input paths to show for the current entries, or None to show every field.

        Override when some inputs only apply to one variant, so the form stays short.
        A hidden field must not be required for the variant that hides it.
        """
        return None

    def validate(self, inputs: Any) -> list[InputIssue]:
        """Physics checks beyond the generic required/range validation. Return [] when fine."""
        return []

    @abstractmethod
    def design(self, inputs: Any) -> DesignResult:
        """Run the algorithm on validated inputs. Must not hardcode benchmark answers."""

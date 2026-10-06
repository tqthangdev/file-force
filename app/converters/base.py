"""BaseConverter — the single conversion contract.

This module is the *only* place the converter interface is defined. New formats and
new engines implement this class and are registered with the FormatRegistry.
"""
from __future__ import annotations

from pathlib import Path

from app.models.conversion_context import ConversionContext


class ConversionError(Exception):
    """A conversion failed for a reason that should be shown to the user."""


class ConversionCancelled(ConversionError):
    """The conversion was cancelled before it completed."""


class BaseConverter:
    name: str = ""
    priority: int = 0  # higher wins when several engines support the same pair

    # ------------------------------------------------------------------ capability
    def supported_pairs(self) -> set[tuple[str, str]]:
        """Every (source_format, target_format) this engine can perform."""
        raise NotImplementedError

    def is_available(self) -> bool:
        """False if a required external tool is missing."""
        raise NotImplementedError

    def unavailable_reason(self) -> str | None:
        """Human-readable reason ``is_available`` is False, or None."""
        return None

    # -------------------------------------------------------------------- runtime
    def max_parallel_jobs(self) -> int:
        return 2

    def validate(
        self,
        source_format: str,
        target_format: str,
        source: Path,
        options: dict,
    ) -> list[str]:
        """Return human-readable problems, or [] if the job is fine.

        Example: 'ICO images cannot exceed 256x256.'
        """
        return []

    def options_schema(self, source_format: str, target_format: str) -> dict:
        """Describe the user-adjustable options for a pair.

        Returns a mapping of option name -> spec. An empty mapping means the pair has
        no options. ``convert_dialog.py`` renders its widgets from this, so converters
        declare their options without knowing anything about the UI.

        Spec keys:

            type:    "int" | "float" | "bool" | "choice" | "string" | "color"
            default: the value used when the user sets nothing
            label:   optional display label (defaults to a prettified option name)
            min/max/step:      for "int" and "float"
            choices:           list[(value, label)] for "choice"
            placeholder:       for "string"
        """
        return {}

    def effective_options(
        self, source_format: str, target_format: str, provided: dict
    ) -> dict:
        """Merge provided options over the schema defaults for a pair.

        Converters use this so the default lives in exactly one place (the schema).
        """
        resolved = {}
        for name, spec in self.options_schema(source_format, target_format).items():
            resolved[name] = provided.get(name, spec.get("default"))
        return resolved

    def convert(self, context: ConversionContext) -> Path:
        """Perform the conversion. Returns the final output path."""
        raise NotImplementedError

    # -------------------------------------------------------------------- helpers
    def supports(self, source_format: str, target_format: str) -> bool:
        return (source_format, target_format) in self.supported_pairs()

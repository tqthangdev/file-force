"""ConverterManager — the only place that maps a format pair to a converter.

Chooses the highest-priority *available* engine, unless the user has forced a
specific engine in Settings.
"""
from __future__ import annotations

from app.converters.base import BaseConverter
from app.core.format_registry import FormatRegistry
from app.services.external_tools import ExternalTools


class ConverterManager:
    def __init__(
        self,
        registry: FormatRegistry,
        external_tools: ExternalTools | None = None,
        forced_engine: str | None = None,
    ) -> None:
        self.registry = registry
        self.external_tools = external_tools
        self.forced_engine = forced_engine

    def set_forced_engine(self, name: str | None) -> None:
        self.forced_engine = name or None

    # ------------------------------------------------------------------ selection
    def select(self, source_format: str, target_format: str) -> str | None:
        """Return the chosen engine name for a pair, or None if none is available."""
        converter = self.select_converter(source_format, target_format)
        return converter.name if converter else None

    def select_converter(
        self, source_format: str, target_format: str
    ) -> BaseConverter | None:
        if self.forced_engine:
            forced = self.registry.get(self.forced_engine)
            if (
                forced is not None
                and forced.supports(source_format, target_format)
                and forced.is_available()
            ):
                return forced

        available = self.registry.available_engines_for(source_format, target_format)
        return available[0] if available else None

    def reason_unavailable(self, source_format: str, target_format: str) -> str | None:
        return self.registry.disabled_reason(source_format, target_format)

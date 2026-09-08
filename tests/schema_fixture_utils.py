from __future__ import annotations

from pathlib import Path


CONTEXTUAL_SEED_MARKER = "-- Contextual intelligence governed rule seed 1.0.0."
SCHEMA_META_MARKER = "INSERT INTO schema_meta(schema_key, schema_value) VALUES"


def seed_before_contextual(seed_path: Path, *, legacy_version: str | None = None) -> str:
    """Return the historical seed body without post-3.8 contextual rows."""
    text = seed_path.read_text(encoding="utf-8")
    prefix, remainder = text.split(CONTEXTUAL_SEED_MARKER, 1)
    _, schema_meta = remainder.split(SCHEMA_META_MARKER, 1)
    historical = prefix + SCHEMA_META_MARKER + schema_meta
    if legacy_version == "2.4.0":
        keep = (
            "LP_MANDATE_REPORTED_SELECTED_MANAGER",
            "LP_MANDATE_REPORTED_MANAGER_ALLOCATION",
        )
        historical = "\n".join(
            line
            for line in historical.splitlines()
            if "('LP_MANDATE_" not in line or any(code in line for code in keep)
        ) + "\n"
    return historical

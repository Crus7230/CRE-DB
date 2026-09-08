"""Status-only policy for the Supabase active serving subset.

This module defines *roots*. Rows needed as evidence, lineage, taxonomy, or
foreign-key support are retained by relational closure and are not active roots
merely because their own processing status is terminal.
"""
from __future__ import annotations

from collections.abc import Mapping, Set
from typing import Any

ACTIVE_ROOT_VALUES: dict[str, dict[str, frozenset[Any]]] = {
    "events": {"lifecycle_status": frozenset({"ACTIVE"})},
    "sale_processes": {
        "process_status": frozenset(
            {
                "OPEN",
                "MARKETED",
                "BIDDING",
                "DUE_DILIGENCE",
                "PREFERRED_NEGOTIATION",
                "SPA_NEGOTIATION",
                "REAUCTION",
                "SUSPENDED",
            }
        )
    },
    # UNKNOWN is unresolved and therefore remains in the review working set.
    "lp_mandates": {"mandate_status": frozenset({"OPEN", "UNKNOWN", "REVIEW"})},
    "review_tasks": {"status_code": frozenset({"PENDING", "IN_PROGRESS"})},
    "event_mentions": {"status_code": frozenset({"REVIEW_READY", "EXTRACTED"})},
    "mention_resolutions": {"resolution_status": frozenset({"CANDIDATE"})},
    "claims": {"verification_status": frozenset({"PENDING"})},
    "assets": {"status_code": frozenset({"ACTIVE"})},
    "organizations": {"status_code": frozenset({"ACTIVE"})},
    "collection_jobs": {"is_active": frozenset({1, True})},
    "collection_sources": {"is_active": frozenset({1, True})},
    "event_categories": {"is_active": frozenset({1, True})},
    "macro_series": {"is_active": frozenset({1, True})},
    "measurement_definitions": {"status_code": frozenset({"ACTIVE"})},
    "measurement_dimension_definitions": {"status_code": frozenset({"ACTIVE"})},
}

ACTIVE_MENTION_STATUSES = ACTIVE_ROOT_VALUES["event_mentions"]["status_code"]


def is_active_root(table: str, row: Mapping[str, Any]) -> bool:
    """Return whether a row is an explicit active serving root."""
    predicates = ACTIVE_ROOT_VALUES.get(table)
    if not predicates:
        return False
    return any(row.get(column) in accepted for column, accepted in predicates.items())


def document_active_reasons(
    *,
    scope_status: str | None,
    mention_statuses: Set[str],
    pending_review: bool,
    latest_active_job_run: bool,
) -> set[str]:
    """Return explicit reasons that make a source document active."""
    reasons: set[str] = set()
    if scope_status and scope_status.startswith("CRE_REVIEW"):
        reasons.add("SCOPE_REVIEW")
    if ACTIVE_MENTION_STATUSES.intersection(mention_statuses):
        reasons.add("MENTION_REVIEW")
    if pending_review:
        reasons.add("PENDING_REVIEW_TASK")
    if latest_active_job_run:
        reasons.add("LATEST_ACTIVE_JOB_RUN")
    return reasons

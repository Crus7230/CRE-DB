from collector.active_serving_policy import (
    ACTIVE_ROOT_VALUES,
    document_active_reasons,
    is_active_root,
)


def test_domain_active_roots_are_status_based_without_date_cutoff() -> None:
    assert is_active_root("events", {"lifecycle_status": "ACTIVE"})
    assert not is_active_root("events", {"lifecycle_status": "COMPLETED"})
    assert is_active_root("sale_processes", {"process_status": "PREFERRED_NEGOTIATION"})
    assert not is_active_root("sale_processes", {"process_status": "CLOSED"})
    assert is_active_root("lp_mandates", {"mandate_status": "OPEN"})
    assert is_active_root("lp_mandates", {"mandate_status": "UNKNOWN"})
    assert not is_active_root("lp_mandates", {"mandate_status": "SELECTED"})
    assert is_active_root("review_tasks", {"status_code": "PENDING"})
    assert not is_active_root("review_tasks", {"status_code": "REJECTED"})


def test_pipeline_review_states_are_active_but_terminal_rows_are_not_roots() -> None:
    assert is_active_root("event_mentions", {"status_code": "REVIEW_READY"})
    assert is_active_root("event_mentions", {"status_code": "EXTRACTED"})
    assert not is_active_root("event_mentions", {"status_code": "REJECTED"})
    assert not is_active_root("event_mentions", {"status_code": "APPROVED"})
    assert is_active_root("mention_resolutions", {"resolution_status": "CANDIDATE"})
    assert not is_active_root("mention_resolutions", {"resolution_status": "RESOLVED"})


def test_master_roots_keep_only_current_active_rows() -> None:
    assert is_active_root("assets", {"status_code": "ACTIVE"})
    assert is_active_root("organizations", {"status_code": "ACTIVE"})
    assert is_active_root("collection_jobs", {"is_active": 1})
    assert is_active_root("macro_series", {"is_active": True})
    assert not is_active_root("organizations", {"status_code": "INACTIVE"})


def test_document_is_kept_only_for_explicit_active_reasons() -> None:
    assert document_active_reasons(scope_status="CRE_REVIEW", mention_statuses=set(), pending_review=False, latest_active_job_run=False) == {"SCOPE_REVIEW"}
    assert document_active_reasons(scope_status="CRE_CONFIRMED", mention_statuses={"REVIEW_READY"}, pending_review=False, latest_active_job_run=False) == {"MENTION_REVIEW"}
    assert document_active_reasons(scope_status="CRE_CONFIRMED", mention_statuses=set(), pending_review=True, latest_active_job_run=False) == {"PENDING_REVIEW_TASK"}
    assert document_active_reasons(scope_status="CRE_CONFIRMED", mention_statuses=set(), pending_review=False, latest_active_job_run=True) == {"LATEST_ACTIVE_JOB_RUN"}
    assert document_active_reasons(scope_status="CRE_CONFIRMED", mention_statuses=set(), pending_review=False, latest_active_job_run=False) == set()


def test_policy_declares_no_time_window() -> None:
    assert "date_cutoff" not in ACTIVE_ROOT_VALUES

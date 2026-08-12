from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opportunity_radar.classification.engine import classify_role
from opportunity_radar.models import (
    EmployerConfig,
    ProgrammeStatus,
    RawRole,
    RoleRecord,
    SourceAuthority,
    SourceHealth,
    SourceHealthStatus,
)
from opportunity_radar.pipeline.changes import detect_role_changes
from opportunity_radar.pipeline.deduplication import deduplicate
from opportunity_radar.pipeline.lifecycle import apply_closure_safeguards, should_increment_missing
from opportunity_radar.pipeline.scanner import (
    _policy_close_match,
    _poll_due,
    compare_source_health,
    reconcile_source_health,
    scan,
)


def make_role(
    employer: EmployerConfig, identifier: str = "1", url: str = "https://example.invalid/jobs/1"
) -> RoleRecord:
    raw = RawRole(
        source_identifier=identifier,
        employer=employer.canonical_name,
        title="Summer 2027 Policy Internship",
        source_url=url,
        application_url=url,
        source_type="greenhouse",
        source_authority=SourceAuthority.OFFICIAL_ATS,
        location="London",
        description="Paid policy research and analysis.",
        eligibility_text="Penultimate-year students from any degree.",
        paid=True,
        cycle_hint="Summer 2027",
    )
    return classify_role(raw, employer, observed_at=datetime(2026, 8, 10, tzinfo=UTC))


def test_discovery_copy_cannot_policy_close_stronger_official_record(
    employer: EmployerConfig,
) -> None:
    official = make_role(employer)
    discovery_copy = official.model_copy(
        update={
            "source_registry_id": "targetjobs-london-early-careers",
            "source_identifier": "board-copy",
            "source_authority": SourceAuthority.DISCOVERY_ONLY_SOURCE,
        }
    )
    assert _policy_close_match(discovery_copy, [official]) is None
    assert _policy_close_match(official, [official]) == official


def test_deduplication_collapses_tracking_and_alias_sources(employer: EmployerConfig) -> None:
    first = make_role(employer, "one", "https://example.invalid/jobs/1?utm_source=a")
    second = make_role(employer, "two", "https://example.invalid/jobs/1?ref=board")
    second = second.model_copy(
        update={"source_type": "trusted_board", "all_source_urls": ["https://board.invalid/1"]}
    )
    result = deduplicate([first, second])
    assert len(result) == 1
    assert "https://board.invalid/1" in result[0].all_source_urls


def test_deduplication_collapses_same_external_ats_requisition_across_board_aliases(
    employer: EmployerConfig,
) -> None:
    first = make_role(
        employer,
        "board-one",
        "https://board.invalid/jobs/one",
    ).model_copy(
        update={
            "application_url": (
                "https://example.wd1.myworkdayjobs.com/en-US/Careers/job/London/Internship_REQ12345"
            )
        }
    )
    second = make_role(
        employer,
        "board-two",
        "https://board.invalid/jobs/two",
    ).model_copy(
        update={
            "canonical_employer": "Employer Alias Ltd",
            "application_url": (
                "https://example.wd1.myworkdayjobs.com/Careers/job/GBR-London/Internship_REQ12345"
            ),
        }
    )
    assert len(deduplicate([first, second])) == 1


def test_materially_different_location_remains_separate(employer: EmployerConfig) -> None:
    first = make_role(employer, "one", "https://example.invalid/jobs/1")
    second = make_role(employer, "two", "https://example.invalid/jobs/2").model_copy(
        update={"location": "Edinburgh"}
    )
    assert len(deduplicate([first, second])) == 2


def test_failed_or_capped_source_cannot_increment_missing(employer: EmployerConfig) -> None:
    role = make_role(employer)
    for status, capped in ((SourceHealthStatus.FAILED, False), (SourceHealthStatus.HEALTHY, True)):
        health = SourceHealth(
            source_id="greenhouse", status=status, checked_at=datetime.now(UTC), capped=capped
        )
        retained, closed = apply_closure_safeguards([role], [], {"greenhouse": health})
        assert retained[0].consecutive_missing_count == 0
        assert not closed
        assert not should_increment_missing(health)


def test_three_healthy_uncapped_absences_close_role(employer: EmployerConfig) -> None:
    role = make_role(employer).model_copy(update={"consecutive_missing_count": 2})
    health = SourceHealth(
        source_id="greenhouse", status=SourceHealthStatus.HEALTHY, checked_at=datetime.now(UTC)
    )
    retained, closed = apply_closure_safeguards([role], [], {"greenhouse": health})
    assert not retained
    assert closed[0].status == ProgrammeStatus.CLOSED
    assert "three consecutive" in (closed[0].closure_reason or "")


def test_material_changes_are_explicitly_recorded(employer: EmployerConfig) -> None:
    previous = make_role(employer)
    current = previous.model_copy(
        update={
            "application_url": "https://example.invalid/jobs/1/apply",
            "location": "London and Manchester",
            "deadline": previous.first_seen_at.date(),
        }
    )
    changes = detect_role_changes(previous, current)
    assert "application_link_changed" in changes
    assert "location_changed" in changes
    assert "closing_date_changed" in changes


def test_reopening_is_detected(employer: EmployerConfig) -> None:
    current = make_role(employer)
    previous = current.model_copy(update={"status": ProgrammeStatus.CLOSED})
    assert "applications_reopened" in detect_role_changes(previous, current)


def test_source_page_change_degrades_health_and_blocks_closure() -> None:
    checked_at = datetime.now(UTC)
    previous = SourceHealth(
        source_id="official-page",
        status=SourceHealthStatus.HEALTHY,
        checked_at=checked_at,
        content_hash="old",
    )
    current = previous.model_copy(update={"content_hash": "new"})
    compared = compare_source_health(current, previous)
    assert compared.status == SourceHealthStatus.DEGRADED
    assert compared.changed_since_last_success
    assert not should_increment_missing(compared)


def test_live_feed_inventory_change_remains_healthy(employer: EmployerConfig) -> None:
    checked_at = datetime.now(UTC)
    previous = SourceHealth(
        source_id=employer.id,
        status=SourceHealthStatus.HEALTHY,
        checked_at=checked_at,
        content_hash="old",
    )
    current = previous.model_copy(update={"content_hash": "new"})
    assert reconcile_source_health(employer, current, previous).status == SourceHealthStatus.HEALTHY
    monitor = employer.model_copy(update={"monitor_only": True})
    assert reconcile_source_health(monitor, current, previous).status == SourceHealthStatus.DEGRADED


def test_failed_health_keeps_last_success_evidence(employer: EmployerConfig) -> None:
    prior_success = datetime(2026, 8, 11, 8, 0, tzinfo=UTC)
    previous = SourceHealth(
        source_id=employer.id,
        status=SourceHealthStatus.HEALTHY,
        checked_at=prior_success,
        last_success_at=prior_success,
        content_hash="last-good-hash",
    )
    current = SourceHealth(
        source_id=employer.id,
        status=SourceHealthStatus.FAILED,
        checked_at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
        parser_ok=False,
        message="Transient challenge page",
    )
    reconciled = reconcile_source_health(employer, current, previous)
    assert reconciled.status == SourceHealthStatus.FAILED
    assert reconciled.last_success_at == prior_success
    assert reconciled.content_hash == "last-good-hash"


def test_expensive_board_poll_cadence_skips_until_due(employer: EmployerConfig) -> None:
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    source = employer.model_copy(update={"poll_interval_minutes": 360})
    recent = SourceHealth(
        source_id=source.id,
        status=SourceHealthStatus.HEALTHY,
        checked_at=datetime(2026, 8, 11, 8, 0, tzinfo=UTC),
    )
    old = recent.model_copy(update={"checked_at": datetime(2026, 8, 11, 5, 0, tzinfo=UTC)})
    assert not _poll_due(source, recent, now=now)
    assert _poll_due(source, old, now=now)
    assert _poll_due(
        source,
        recent.model_copy(update={"status": SourceHealthStatus.FAILED}),
        now=now,
    )
    assert _poll_due(source.model_copy(update={"poll_interval_minutes": 0}), recent, now=now)


@pytest.mark.asyncio
async def test_complete_fixture_pipeline(isolated_root: Path) -> None:
    summary = await scan(isolated_root, fixture_mode=True)
    assert summary.sources_succeeded == 8
    assert summary.observations >= 28
    assert summary.public_roles >= 8
    assert summary.possible_roles >= 1
    fixture_data = isolated_root / "build" / "fixture-data"
    open_roles = json.loads((fixture_data / "open_roles.json").read_text())
    recent = json.loads((fixture_data / "recent_roles.json").read_text())
    review = json.loads((fixture_data / "review_queue.json").read_text())
    possible = json.loads((fixture_data / "possible_roles.json").read_text())
    assert any("Corporate Finance" in item["title"] for item in open_roles)
    assert any("Vacation Scheme" in item["title"] for item in open_roles)
    assert any(item["programme_type"] == "cycle_unstated_recent_role" for item in recent)
    assert all(item["eligibility_status"] == "uncertain" for item in review)
    assert any(item["eligibility_status"] == "uncertain" for item in possible)
    assert any("Policy Research Internship" in item["title"] for item in possible)
    assert any("Policy Administrator" in item["title"] for item in possible)
    assert any("Policy Support Officer" in item["title"] for item in possible)
    assert any("Research and Policy Assistant" in item["title"] for item in possible)
    assert not any("Registered Nurse" in item["title"] for item in possible)
    assert not any("Assistant Professor" in item["title"] for item in possible)
    assert not any("Machine Learning" in item["title"] for item in possible)
    assert not any("Software Engineering" in item["title"] for item in open_roles)

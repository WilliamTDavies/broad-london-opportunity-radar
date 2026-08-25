from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opportunity_radar.config import (
    ConfigurationError,
    load_employers,
    load_radar,
    validate_all_config,
)
from opportunity_radar.email.digest import InMemoryTransport, build_digest, run_digest
from opportunity_radar.models import RoleRecord
from opportunity_radar.pipeline.scanner import scan
from opportunity_radar.site import build_site


@pytest.mark.asyncio
async def test_static_site_generation_and_filter_assets(isolated_root: Path) -> None:
    await scan(isolated_root, fixture_mode=True)
    output = build_site(
        isolated_root,
        build_time=datetime(2026, 8, 10, 13, tzinfo=UTC),
        fixture_mode=True,
    )
    html = output.read_text(encoding="utf-8")
    javascript = (output.parent / "app.js").read_text(encoding="utf-8")
    public_data = json.loads((output.parent / "roles.json").read_text())
    possible_data = json.loads((output.parent / "possible-roles.json").read_text())
    index_data = json.loads((output.parent / "role-index.json").read_text())
    detail_data = json.loads((output.parent / "role-details.json").read_text())
    assert "All plausible open jobs" in html
    assert "Upcoming and drop radar" in html
    assert "Recent Relevant Opportunities — Cycle Not Stated" in html
    assert "localStorage" in javascript
    assert 'data-filter="category"' in html
    assert 'id="company-search"' in html
    assert 'id="employer-suggestions"' in html
    assert "Test preview:" in html
    assert "Employer type" in html
    assert "Organisation</dt>" not in html
    assert "<style>:root {" in html
    assert '<link rel="stylesheet" href="styles.css">' not in html
    assert 'class="open-jobs-table"' in html
    assert 'id="show-more"' in html
    assert 'id="role-detail-panel"' in html
    assert 'class="role-card' not in html
    assert html.count('class="role-row') == min(100, len(public_data) + len(possible_data))
    assert {item["id"] for item in index_data} == {
        item["id"] for item in [*public_data, *possible_data]
    }
    assert all(item["dataset"].get("title") for item in index_data)
    assert set(detail_data) == {item["id"] for item in [*public_data, *possible_data]}
    assert all('class="role-card' in value for value in detail_data.values())
    assert "All plausible open jobs" in html
    assert "Possible — check" in html
    assert "{{" not in html
    assert all(
        item["eligibility_status"] not in {"uncertain", "ineligible"} for item in public_data
    )


@pytest.mark.asyncio
async def test_site_build_reapplies_editable_filters_to_stale_possible_data(
    isolated_root: Path,
) -> None:
    await scan(isolated_root, fixture_mode=True)
    possible_path = isolated_root / "build" / "fixture-data" / "possible_roles.json"
    possible = json.loads(possible_path.read_text(encoding="utf-8"))
    stale = {
        **possible[0],
        "id": "stale-front-of-house-role",
        "source_identifier": "stale-front-of-house-role",
        "title": "Front of House Assistant",
    }
    possible_path.write_text(json.dumps([*possible, stale]), encoding="utf-8")
    output = build_site(isolated_root, fixture_mode=True)
    generated = json.loads((output.parent / "possible-roles.json").read_text(encoding="utf-8"))
    assert not any(item["id"] == stale["id"] for item in generated)


@pytest.mark.asyncio
async def test_verified_production_snapshots_publish_real_official_roles(
    isolated_root: Path,
) -> None:
    await scan(isolated_root, source_filter="blackrock")
    await scan(isolated_root, source_filter="blackstone")
    await scan(isolated_root, source_filter="bank-of-america")
    roles = json.loads((isolated_root / "data" / "open_roles.json").read_text())
    assert len(roles) == 16
    assert {item["canonical_employer"] for item in roles} == {
        "Bank of America",
        "BlackRock",
        "Blackstone",
    }
    assert sum(item["canonical_employer"] == "Blackstone" for item in roles) == 11
    assert sum(item["canonical_employer"] == "Bank of America" for item in roles) == 3
    assert all(item["source_authority"] == "official_ats" for item in roles)
    assert all(item["eligibility_status"] == "verified_eligible" for item in roles)
    assert all("fixture" not in item["canonical_employer"].casefold() for item in roles)
    metrics = json.loads((isolated_root / "data" / "metrics.json").read_text())
    assert metrics["employers_monitored"] == 34
    assert metrics["publishing_sources"] == 16
    assert metrics["monitor_only_sources"] == 18
    assert "16 role-producing sources" in metrics["coverage_warning"]

    output = build_site(isolated_root, build_time=datetime(2026, 8, 10, 15, tzinfo=UTC))
    html = output.read_text(encoding="utf-8")
    assert "Test preview:" not in html
    assert "Bank of America" in html and "BlackRock" in html and "Blackstone" in html
    assert "Verified snapshot" in html
    assert html.count('class="role-row"') == 16
    assert "22 programmes across official pages" in html


@pytest.mark.asyncio
async def test_goldman_sachs_compliance_and_risk_summer_roles_are_published(
    isolated_root: Path,
) -> None:
    summary = await scan(isolated_root, source_filter="goldman-sachs-current-roles")
    roles = json.loads((isolated_root / "data" / "open_roles.json").read_text())
    titles = {item["title"] for item in roles}
    assert summary.public_roles == 9
    assert "2027 | EMEA | London | Compliance | Summer Analyst" in titles
    assert "2027 | EMEA | London | Risk | Summer Analyst" in titles
    assert "2027 | EMEA | London | Internal Audit | Summer Analyst" in titles
    assert "2027 | EMEA | London | Asset Management, Private Investing | Summer Analyst" in titles
    assert "2027 | EMEA | London | Operations | Summer Analyst" in titles
    assert "2027 | EMEA | London | Transaction Banking (TxB), Coverage | Summer Analyst" in titles
    assert all(item["canonical_employer"] == "Goldman Sachs" for item in roles)


@pytest.mark.asyncio
async def test_digest_rendering_idempotency_and_no_send(
    isolated_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await scan(isolated_root, fixture_mode=True)
    monkeypatch.setenv("SITE_URL", "https://radar.example")
    transport = InMemoryTransport()
    first = run_digest(
        isolated_root,
        dry_run=False,
        recipients=["reader@example.com"],
        transport=transport,
        now=datetime(2026, 8, 10, 14, tzinfo=UTC),
        fixture_mode=True,
    )
    second = run_digest(
        isolated_root,
        dry_run=False,
        recipients=["reader@example.com"],
        transport=transport,
        now=datetime(2026, 8, 10, 14, tzinfo=UTC),
        fixture_mode=True,
    )
    assert first.sent_count == 1
    assert second.no_send
    assert len(transport.deliveries) == 1
    assert "Unsubscribe" in transport.deliveries[0]["html"]
    assert "Privacy" in transport.deliveries[0]["html"]


@pytest.mark.asyncio
async def test_uncertain_roles_never_enter_digest(isolated_root: Path) -> None:
    await scan(isolated_root, fixture_mode=True)
    uncertain = [
        RoleRecord.model_validate(item)
        for item in json.loads(
            (isolated_root / "build" / "fixture-data" / "review_queue.json").read_text()
        )
        if item["eligibility_status"] == "uncertain"
    ]
    assert build_digest(uncertain, already_sent=set(), site_url="https://example.invalid") is None


def test_repository_configuration_valid(project_root: Path) -> None:
    assert validate_all_config(project_root)
    employers = load_employers(project_root)
    assert len(employers) >= 150
    assert any(item.id == "psc-unresolved" and not item.enabled for item in employers)
    assert all(item.endpoint for item in employers if item.enabled)
    assert sum(item.enabled and not item.monitor_only for item in employers) == 16
    assert sum(item.enabled and item.monitor_only for item in employers) == 18
    assert any(item.id == "w4mp" and item.enabled and item.ats_type == "w4mp" for item in employers)
    assert any(
        item.id == "higherin-london-internships"
        and item.enabled
        and item.source_authority.value == "discovery_only_source"
        for item in employers
    )
    assert any(
        item.id == "targetjobs-london-early-careers"
        and item.enabled
        and item.ats_type == "targetjobs"
        for item in employers
    )
    assert {
        item.id
        for item in employers
        if item.enabled
        and item.ats_type in {"work_hub", "prospects", "legalcheek", "adzuna", "reed"}
    } == {
        "work-hub-london",
        "prospects-london",
        "legalcheek-noticeboard",
        "adzuna-london",
        "reed-london",
    }
    assert next(item for item in employers if item.id == "adzuna-london").required_env == [
        "ADZUNA_APP_ID",
        "ADZUNA_APP_KEY",
    ]
    assert next(item for item in employers if item.id == "reed-london").required_env == [
        "REED_API_KEY"
    ]
    carlyle = next(item for item in employers if item.id == "carlyle")
    assert carlyle.enabled and carlyle.ats_type == "workday"
    assert carlyle.request_method == "POST"
    assert carlyle.endpoint and "/wday/cxs/carlyle/Carlyle/jobs" in carlyle.endpoint
    radar = load_radar(project_root)
    assert len(radar) == 22
    assert sum(item.evidence_type == "no_reliable_estimate" for item in radar) >= 9
    assert any(item.employer == "Bank of America" for item in radar)


def test_malformed_configuration_fails(isolated_root: Path) -> None:
    (isolated_root / "config" / "manual_overrides.yml").write_text("overrides: not-a-list\n")
    with pytest.raises(ConfigurationError):
        validate_all_config(isolated_root)


def test_duplicate_editable_job_filter_fails_validation(isolated_root: Path) -> None:
    path = isolated_root / "config" / "job_filters.yml"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace("  - graduates only\n", "  - graduates only\n  - Graduates Only\n", 1),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="duplicate phrases"):
        validate_all_config(isolated_root)


def test_subscription_security_artifacts(project_root: Path) -> None:
    migration = (
        project_root / "supabase" / "migrations" / "202608100001_subscribers.sql"
    ).read_text()
    subscribe = (project_root / "supabase" / "functions" / "subscribe" / "index.ts").read_text()
    confirm = (project_root / "supabase" / "functions" / "confirm" / "index.ts").read_text()
    unsubscribe = (project_root / "supabase" / "functions" / "unsubscribe" / "index.ts").read_text()
    assert "enable row level security" in migration.lower()
    assert "revoke all" in migration.lower()
    assert "confirmation_token_hash" in migration
    assert "TOKEN_SECRET" not in subscribe
    assert "If this address can be subscribed" in subscribe
    assert 'rpc("begin_subscription"' in subscribe
    assert '.select("status")' not in subscribe
    assert 'decision !== "confirm"' in confirm
    assert "unsubscribeDecision(data)" in unsubscribe
    assert "Temporarily unavailable" in unsubscribe
    assert "unsubscribe_token_hashes" in unsubscribe
    assert "prune_subscription_state" in migration


def test_no_subscriber_or_secret_data_committed(project_root: Path) -> None:
    allowed = {".env.example"}
    for path in project_root.iterdir():
        if path.name.startswith(".env") and path.name not in allowed:
            pytest.fail(f"Unexpected environment file: {path}")
    for directory in (project_root / "data", project_root / "site" / "generated"):
        for path in directory.rglob("*"):
            if path.is_file():
                assert "@example.com" not in path.read_text(encoding="utf-8", errors="ignore")

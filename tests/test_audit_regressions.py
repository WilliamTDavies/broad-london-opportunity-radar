from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

import opportunity_radar.email.digest as digest_module
from opportunity_radar.adapters.parsers import (
    GenericJsonAdapter,
    HtmlMonitorAdapter,
    WorkdayAdapter,
)
from opportunity_radar.classification import load_classification_rules
from opportunity_radar.classification.engine import classify_role, is_public_role
from opportunity_radar.email.digest import build_digest, eligible_for_digest, run_digest
from opportunity_radar.models import (
    CycleProvenance,
    DateProvenance,
    EligibilityStatus,
    EmployerConfig,
    GeographicScope,
    ProgrammeStatus,
    RawRole,
    RelevanceStatus,
    RoleRecord,
    SourceAuthority,
    SourceHealth,
    SourceHealthStatus,
)
from opportunity_radar.pipeline.deduplication import deduplicate
from opportunity_radar.pipeline.scanner import scan
from opportunity_radar.site import build_site
from opportunity_radar.validation import scan_repository_hygiene, validate_yaml_and_workflows

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)


def make_raw(**updates: object) -> RawRole:
    values: dict[str, object] = {
        "source_identifier": "audit-1",
        "employer": "Test Employer",
        "title": "Summer 2027 Policy Risk Internship",
        "source_url": "https://example.invalid/role?utm_source=audit",
        "application_url": "https://example.invalid/apply?ref=tracker",
        "source_type": "generic_json",
        "source_authority": SourceAuthority.OFFICIAL_ATS,
        "location": "London",
        "description": "Paid policy research, risk analysis and written briefings.",
        "eligibility_text": "Applicants must be in their penultimate year and may study any degree discipline.",
        "paid": True,
        "paid_evidence": "The internship pays £500 per week.",
        "cycle_hint": "Summer 2027",
    }
    values.update(updates)
    return RawRole.model_validate(values)


def classify(employer: EmployerConfig, **updates: object) -> RoleRecord:
    return classify_role(make_raw(**updates), employer, observed_at=NOW)


def test_eligibility_evidence_is_exact_source_text(employer: EmployerConfig) -> None:
    wording = "Applicants must be in their penultimate year and may study any degree discipline."
    role = classify(employer, eligibility_text=wording)
    assert {item.text for item in role.eligibility_evidence} == {wording}
    assert all(item.structured_field == "eligibility_text" for item in role.eligibility_evidence)
    assert role.degree_restrictions == [wording]
    assert role.study_year_restrictions == [wording]


def test_public_model_boundary_redacts_contact_email_addresses(
    employer: EmployerConfig,
) -> None:
    role = classify(
        employer,
        description="Paid policy work. Contact person@example.org for details.",
        eligibility_text=(
            "Penultimate-year applicants from any degree may contact person@example.org."
        ),
    )
    serialised = role.model_dump_json()
    assert "person@example.org" not in serialised
    assert "[contact email on source]" in serialised


def test_vacation_scheme_any_degree_without_non_law_stage_is_uncertain(
    employer: EmployerConfig,
) -> None:
    role = classify(
        employer,
        title="Summer Vacation Scheme 2027",
        description="Paid legal work.",
        eligibility_text="Applications are accepted from any degree discipline.",
    )
    assert role.eligibility_status == EligibilityStatus.UNCERTAIN
    assert not is_public_role(role)


def test_nationality_evidence_alone_does_not_establish_study_stage(
    employer: EmployerConfig,
) -> None:
    role = classify(
        employer,
        eligibility_text="",
        description="Paid national-security policy work.",
        nationality_requirements=["British citizens only"],
    )
    assert role.eligibility_status == EligibilityStatus.UNCERTAIN
    assert role.nationality_assessment and "element only" in role.nationality_assessment


def test_new_zealand_citizenship_handles_explicit_commonwealth_requirement(
    employer: EmployerConfig,
) -> None:
    role = classify(
        employer,
        nationality_requirements=["Applicants must be Commonwealth citizens"],
    )
    assert role.eligibility_status == EligibilityStatus.VERIFIED
    assert role.nationality_assessment and "New Zealand" in role.nationality_assessment


def test_uk_wide_without_london_is_not_assumed_london(employer: EmployerConfig) -> None:
    role = classify(employer, location="UK-wide programme")
    assert role.geographic_scope == GeographicScope.OUT_OF_SCOPE
    assert not is_public_role(role)


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("London (hybrid)", "hybrid"),
        ("Remote within the UK", "remote_uk"),
        ("Multiple locations including London", "multi_location"),
    ],
)
def test_location_type_normalisation(
    employer: EmployerConfig, location: str, expected: str
) -> None:
    assert classify(employer, location=location).location_type.value == expected


def test_source_manual_review_requirement_blocks_automatic_publication(
    employer: EmployerConfig,
) -> None:
    role = classify(employer.model_copy(update={"manual_review_required": True}))
    assert role.eligibility_status == EligibilityStatus.VERIFIED
    assert role.publication_review_required
    assert not is_public_role(role)


def test_quality_controlled_ngo_without_selectivity_needs_review(
    employer: EmployerConfig,
) -> None:
    role = classify(
        employer,
        organisation_type="ngo",
        description="Paid substantive humanitarian research and policy analysis.",
    )
    assert role.relevance_status == RelevanceStatus.BORDERLINE
    assert not is_public_role(role)


def test_match_score_has_every_named_component(employer: EmployerConfig) -> None:
    role = classify(employer, deadline=date(2026, 8, 18))
    assert set(role.match_components) == {
        "eligibility_strength",
        "substantive_relevance",
        "skill_alignment",
        "organisation_quality",
        "geographic_fit",
        "recency",
        "deadline_urgency",
        "evidence_quality",
    }
    assert role.match_score == sum(role.match_components.values())


def test_invalid_external_category_hint_is_ignored(
    employer: EmployerConfig, project_root: Path
) -> None:
    rules = load_classification_rules(project_root)
    role = classify_role(
        make_raw(category_hint="Prestigious Fabricated Category"),
        employer,
        observed_at=NOW,
        rules=rules,
    )
    assert role.primary_category != "Prestigious Fabricated Category"


def test_configured_category_keyword_changes_live_classification(
    employer: EmployerConfig, project_root: Path, tmp_path: Path
) -> None:
    import shutil

    shutil.copytree(project_root / "config", tmp_path / "config")
    path = tmp_path / "config" / "categories.yml"
    document = path.read_text(encoding="utf-8").replace(
        "Corporate Strategy: [corporate strategy, business strategy]",
        "Corporate Strategy: [corporate strategy, business strategy, orbital governance]",
    )
    path.write_text(document, encoding="utf-8")
    rules = load_classification_rules(tmp_path)
    role = classify_role(
        make_raw(title="Orbital Governance Internship", description="Orbital governance analysis."),
        employer,
        observed_at=NOW,
        rules=rules,
    )
    assert role.primary_category == "Corporate Strategy"


def test_date_and_cycle_provenance_follow_source_authority(employer: EmployerConfig) -> None:
    trusted = classify(
        employer,
        source_authority=SourceAuthority.TRUSTED_SECTOR_BOARD,
        published_date=date(2026, 8, 9),
        cycle_provenance=CycleProvenance.MANUAL_VERIFIED,
    )
    assert trusted.date_provenance == DateProvenance.TRUSTED_PRIMARY_LISTING
    assert trusted.cycle_provenance == CycleProvenance.MANUAL_VERIFIED


def test_explicitly_closed_role_records_auditable_closure_time(
    employer: EmployerConfig,
) -> None:
    role = classify(employer, explicitly_closed=True)
    assert role.status == ProgrammeStatus.CLOSED
    assert role.closed_at == NOW
    assert role.closure_reason == "Official listing states applications are closed"
    assert role.closure_evidence == "https://example.invalid/role?utm_source=audit"


def test_original_tracking_urls_are_preserved_as_provenance(employer: EmployerConfig) -> None:
    role = classify(employer)
    assert "https://example.invalid/role?utm_source=audit" in role.all_source_urls
    assert "https://example.invalid/apply?ref=tracker" in role.all_source_urls
    assert role.canonical_url == "https://example.invalid/role"


def test_same_url_with_materially_distinct_location_or_division_does_not_merge(
    employer: EmployerConfig,
) -> None:
    london = classify(employer, source_identifier="one", location="London", division="Policy")
    edinburgh = classify(
        employer,
        source_identifier="two",
        location="Edinburgh",
        division="Investment",
    )
    assert len(deduplicate([london, edinburgh])) == 2


@pytest.mark.asyncio
async def test_fixture_scan_cannot_contaminate_live_state(isolated_root: Path) -> None:
    live_before = (isolated_root / "data" / "open_roles.json").read_text()
    await scan(isolated_root, fixture_mode=True)
    assert (isolated_root / "data" / "open_roles.json").read_text() == live_before
    assert (isolated_root / "build" / "fixture-data" / "open_roles.json").exists()


@pytest.mark.asyncio
async def test_current_ineligible_wording_removes_stale_public_role(
    isolated_root: Path,
) -> None:
    await scan(isolated_root, fixture_mode=True)
    greenhouse = isolated_root / "fixtures" / "ats" / "greenhouse.json"
    payload = json.loads(greenhouse.read_text())
    payload["jobs"][0]["content"] = "<p>Final year students only.</p>"
    greenhouse.write_text(json.dumps(payload), encoding="utf-8")
    await scan(isolated_root, fixture_mode=True)
    data = isolated_root / "build" / "fixture-data"
    open_roles = json.loads((data / "open_roles.json").read_text())
    closed = json.loads((data / "closed_roles.json").read_text())
    assert not any("Corporate Finance" in item["title"] for item in open_roles)
    record = next(item for item in closed if "Corporate Finance" in item["title"])
    assert "publication boundary" in record["closure_reason"]


@pytest.mark.asyncio
async def test_filtered_fixture_scan_preserves_other_source_health(isolated_root: Path) -> None:
    await scan(isolated_root, fixture_mode=True)
    fixture_data = isolated_root / "build" / "fixture-data"
    review_before = json.loads((fixture_data / "review_queue.json").read_text())
    before = {
        item["id"]: item["consecutive_missing_count"]
        for item in json.loads(
            (isolated_root / "build" / "fixture-data" / "open_roles.json").read_text()
        )
    }
    await scan(isolated_root, fixture_mode=True, source_filter="fixture-greenhouse")
    health = json.loads(
        (isolated_root / "build" / "fixture-data" / "source_health.json").read_text()
    )
    assert {item["source_id"] for item in health} == {
        "fixture-greenhouse",
        "fixture-law",
        "fixture-w4mp",
        "fixture-sectors",
        "fixture-higherin",
        "fixture-charityjob",
        "fixture-nhs-jobs",
        "fixture-jobs-ac-uk",
    }
    after = {
        item["id"]: item["consecutive_missing_count"]
        for item in json.loads(
            (isolated_root / "build" / "fixture-data" / "open_roles.json").read_text()
        )
    }
    assert after == before
    assert json.loads((fixture_data / "review_queue.json").read_text()) == review_before


@pytest.mark.asyncio
async def test_http_request_errors_are_retried(employer: EmployerConfig) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("temporary network failure", request=request)
        return httpx.Response(
            200,
            json={
                "jobs": [{"id": "1", "title": "Policy Intern", "url": "https://example.invalid/1"}]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await GenericJsonAdapter(employer, client).fetch(check_robots=False)
    assert attempts == 3
    assert result.health.status == SourceHealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_workday_style_post_configuration_is_honoured(employer: EmployerConfig) -> None:
    seen_method = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_method
        seen_method = request.method
        return httpx.Response(200, json={"jobPostings": []})

    source = employer.model_copy(
        update={"request_method": "POST", "request_body": {"limit": 20, "offset": 0}}
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await WorkdayAdapter(source, client).fetch(check_robots=False)
    assert seen_method == "POST"


def test_html_monitor_preserves_closure_and_application_metadata(
    employer: EmployerConfig,
) -> None:
    payload = b'<article data-job-id="1" data-title="Policy Intern" data-url="/1" data-application-url="/apply" data-application-method="Email" data-location="London" data-eligibility="Penultimate year; any degree" data-paid="true" data-closed="true"></article>'
    role = HtmlMonitorAdapter(employer).parse(payload)[0]
    assert role.explicitly_closed
    assert role.application_url and role.application_url.endswith("/apply")
    assert role.application_method == "Email"


@pytest.mark.parametrize(
    "update",
    [
        {"relevance_status": RelevanceStatus.BORDERLINE, "manual_override": None},
        {"status": ProgrammeStatus.UPCOMING},
        {"status": ProgrammeStatus.CLOSED},
        {"source_authority": SourceAuthority.DISCOVERY_ONLY_SOURCE},
        {"publication_review_required": True},
    ],
)
def test_digest_rejects_non_sendable_boundaries(
    employer: EmployerConfig, update: dict[str, object]
) -> None:
    role = classify(employer).model_copy(update=update)
    assert not eligible_for_digest(role)


def test_digest_allows_only_manually_approved_borderline(employer: EmployerConfig) -> None:
    role = classify(employer).model_copy(
        update={
            "eligibility_status": EligibilityStatus.MANUAL,
            "relevance_status": RelevanceStatus.BORDERLINE,
            "manual_override": {"reason": "Official review"},
        }
    )
    assert eligible_for_digest(role)


@pytest.mark.asyncio
async def test_digest_dry_run_writes_local_html_and_text_previews(isolated_root: Path) -> None:
    await scan(isolated_root, fixture_mode=True)
    preview = isolated_root / "build" / "digest-preview"
    result = run_digest(
        isolated_root,
        dry_run=True,
        fixture_mode=True,
        preview_directory=preview,
        now=NOW,
    )
    assert result.role_count > 0
    assert (preview / "digest.html").read_text().startswith("<!doctype html>")
    assert "Unsubscribe:" in (preview / "digest.txt").read_text()


@pytest.mark.asyncio
async def test_zero_recipient_run_is_recorded_without_claiming_delivery(
    isolated_root: Path,
) -> None:
    await scan(isolated_root, fixture_mode=True)
    result = run_digest(
        isolated_root,
        dry_run=False,
        recipients=[],
        fixture_mode=True,
        now=NOW,
    )
    state = json.loads((isolated_root / "build" / "fixture-data" / "digest_state.json").read_text())
    assert result.no_send and result.sent_count == 0
    assert state["successful_runs"][-1]["outcome"] == "no_confirmed_recipients"


@pytest.mark.asyncio
async def test_production_retry_skips_recipient_already_delivered_same_digest(
    isolated_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await scan(isolated_root, fixture_mode=True)
    delivered_digest: dict[str, str] = {}
    deliveries: list[str] = []
    fail_second = True

    class PartialTransport:
        def send(self, *, recipient: str, **_: str) -> None:
            nonlocal fail_second
            if recipient == "second@example.com" and fail_second:
                fail_second = False
                raise RuntimeError("simulated delivery failure")
            deliveries.append(recipient)

    def subscribers(digest_id: str) -> list[str]:
        return [
            email
            for email in ("first@example.com", "second@example.com")
            if delivered_digest.get(email) != digest_id
        ]

    def mark(email: str, *, digest_id: str | None = None, failure: str | None = None) -> None:
        if digest_id:
            delivered_digest[email] = digest_id

    monkeypatch.setattr(digest_module, "_subscribers_from_supabase", subscribers)
    monkeypatch.setattr(digest_module, "_store_unsubscribe_hash", lambda *_: None)
    monkeypatch.setattr(digest_module, "_mark_subscriber_delivery", mark)
    monkeypatch.setattr(digest_module, "ResendTransport", lambda *_: PartialTransport())
    for name in (
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "RESEND_API_KEY",
        "RESEND_FROM_EMAIL",
        "TOKEN_SECRET",
    ):
        monkeypatch.setenv(name, "x" * 40)
    with pytest.raises(RuntimeError, match="simulated delivery failure"):
        run_digest(isolated_root, dry_run=False, fixture_mode=True, now=NOW)
    run_digest(isolated_root, dry_run=False, fixture_mode=True, now=NOW)
    assert deliveries == ["first@example.com", "second@example.com"]


def test_site_connects_configured_subscription_and_hides_internal_override(
    isolated_root: Path,
) -> None:
    data = isolated_root / "build" / "fixture-data"
    data.mkdir(parents=True)
    role = classify(
        EmployerConfig(
            id="site-test",
            canonical_name="Site Test",
            organisation_type="corporate",
            endpoint="https://example.invalid",
            priority_tier="major",
            manual_review_required=False,
        ),
        opening_date=date(2026, 8, 1),
        application_method="Online application",
    ).model_copy(update={"manual_override": {"private": "internal trace"}})
    for filename, value in {
        "open_roles.json": [role.model_dump(mode="json")],
        "recent_roles.json": [],
        "closed_roles.json": [],
        "review_queue.json": [],
        "source_health.json": [],
        "upcoming_roles.json": [],
        "observations.json": [],
        "metrics.json": {},
        "digest_state.json": {},
    }.items():
        (data / filename).write_text(json.dumps(value), encoding="utf-8")
    endpoint = "https://project.supabase.co/functions/v1/subscribe"
    output = build_site(
        isolated_root,
        fixture_mode=True,
        build_time=NOW,
        subscribe_endpoint=endpoint,
    )
    html = output.read_text()
    public = json.loads((output.parent / "roles.json").read_text())
    details = json.loads((output.parent / "role-details.json").read_text())
    assert "Employer type" in html
    assert role.id in details
    assert "Opening date" in details[role.id]
    assert "Application method" in details[role.id]
    assert f'data-open-card="{role.id}"' in html
    assert "role-details.json" in html
    assert f'data-endpoint="{endpoint}"' in html
    assert "Email subscriptions are not configured" not in html
    assert " disabled" not in html
    assert "manual_override" not in public[0]
    assert "internal trace" not in (output.parent / "roles.json").read_text()

    disabled_output = build_site(isolated_root, fixture_mode=True, build_time=NOW)
    disabled_html = disabled_output.read_text()
    assert "Email subscriptions are not configured" in disabled_html
    assert " disabled" in disabled_html


def test_workflow_validation_and_secret_scan_detect_failures(
    project_root: Path, tmp_path: Path
) -> None:
    assert validate_yaml_and_workflows(project_root)
    (tmp_path / "data").mkdir()
    (tmp_path / "site" / "generated").mkdir(parents=True)
    fake_token = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz1234567890"
    (tmp_path / "leak.txt").write_text(fake_token)
    with pytest.raises(ValueError, match="GitHub token"):
        scan_repository_hygiene(tmp_path)


def test_build_digest_escapes_untrusted_role_text(employer: EmployerConfig) -> None:
    role = classify(employer).model_copy(update={"title": "<script>alert(1)</script>"})
    message = build_digest([role], already_sent=set(), site_url="https://radar.example", now=NOW)
    assert message is not None
    assert "<script>" not in message.html
    assert "&lt;script&gt;" in message.html


def test_untrusted_adapter_cannot_emit_an_executable_link() -> None:
    with pytest.raises(ValidationError, match=r"absolute HTTP\(S\) URL"):
        make_raw(application_url="javascript:alert(1)")


def test_source_health_model_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        SourceHealth.model_validate(
            {"source_id": "x", "status": "pretend-healthy", "checked_at": NOW.isoformat()}
        )

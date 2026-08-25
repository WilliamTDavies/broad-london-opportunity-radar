from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import yaml

from opportunity_radar.adapters.base import AdapterError
from opportunity_radar.adapters.broad_sources import (
    AdzunaAdapter,
    LegalCheekAdapter,
    ProspectsAdapter,
    ReedAdapter,
    WorkHubAdapter,
)
from opportunity_radar.classification import classify_role, is_possible_role
from opportunity_radar.models import EmployerConfig, SourceAuthority, SourceHealthStatus
from opportunity_radar.pipeline.scanner import scan


def discovery_source(employer: EmployerConfig, adapter: str) -> EmployerConfig:
    return employer.model_copy(
        update={
            "id": f"fixture-{adapter}",
            "canonical_name": "Fixture listing board",
            "organisation_type": "trusted_board",
            "ats_type": adapter,
            "source_authority": SourceAuthority.DISCOVERY_ONLY_SOURCE,
            "manual_review_required": True,
            "priority_tier": "approved",
            "expected_min_items": 0,
        }
    )


@pytest.mark.parametrize(
    (
        "adapter",
        "adapter_name",
        "fixture",
        "expected_title",
        "expected_employer",
        "expected_possible",
    ),
    [
        (
            WorkHubAdapter,
            "work_hub",
            "work-hub.html",
            "Junior Commercial Analyst",
            "Fixture Advisory LLP",
            False,
        ),
        (
            ProspectsAdapter,
            "prospects",
            "prospects.html",
            "Summer Finance Internship 2027",
            "Fixture Markets Ltd",
            True,
        ),
        (
            LegalCheekAdapter,
            "legalcheek",
            "legalcheek.html",
            "London Winter Vacation Scheme 2026",
            "Fixture City Law LLP",
            True,
        ),
        (
            AdzunaAdapter,
            "adzuna",
            "adzuna.json",
            "Consulting Summer Intern",
            "Fixture Consulting Ltd",
            True,
        ),
        (
            ReedAdapter,
            "reed",
            "reed.json",
            "Legal Assistant",
            "Fixture Legal Services",
            False,
        ),
    ],
)
def test_new_broad_adapters_parse_structural_fixtures(
    adapter: type[WorkHubAdapter],
    adapter_name: str,
    fixture: str,
    expected_title: str,
    expected_employer: str,
    expected_possible: bool,
    project_root: Path,
    employer: EmployerConfig,
) -> None:
    source = discovery_source(employer, adapter_name)
    roles = adapter(source).parse((project_root / "fixtures" / "discovery" / fixture).read_bytes())
    assert roles
    assert roles[0].title == expected_title
    assert roles[0].employer == expected_employer
    assert roles[0].listing_publisher == "Fixture listing board"
    assert is_possible_role(classify_role(roles[0], source)) is expected_possible


def test_work_hub_infers_health_and_university_contexts(employer: EmployerConfig) -> None:
    source = discovery_source(employer, "work_hub")
    payload = b"""<html><body><p>Showing results 1 to 2 of <strong>2</strong></p>
    <div data-testid="searchResultCard-health-1"><a data-testid="jobTitle-health-1"
    href="/jobs/health-1">Locum Consultant Cardiologist</a>
    <p data-testid="searchResultCardEmployer"><span>Example NHS Trust</span><span> - London</span></p>
    <p class="govuk-body govuk-!-font-weight-bold">\xc2\xa3100,000 a year</p>
    <p data-testid="searchResultCardJobDescription">Specialist medical role.</p></div>
    <div data-testid="searchResultCard-university-1"><a data-testid="jobTitle-university-1"
    href="/jobs/university-1">Postdoctoral Research Associate</a>
    <p data-testid="searchResultCardEmployer"><span>Example University</span><span> - London</span></p>
    <p class="govuk-body govuk-!-font-weight-bold">\xc2\xa345,000 a year</p>
    <p data-testid="searchResultCardJobDescription">Advanced academic research.</p></div>
    </body></html>"""
    roles = WorkHubAdapter(source).parse(payload)
    assert [item.organisation_type for item in roles] == ["public_health", "higher_education"]
    assert all(not is_possible_role(classify_role(item, source)) for item in roles)


def test_api_and_work_hub_descriptions_redact_contact_email_addresses(
    employer: EmployerConfig,
) -> None:
    work_hub = b"""<html><body><p>Showing results 1 to 1 of <strong>1</strong></p>
    <div data-testid="searchResultCard-redact-1"><a data-testid="jobTitle-redact-1"
    href="/jobs/redact-1">Policy Assistant</a><p data-testid="searchResultCardEmployer">
    <span>Fixture Employer</span><span> - London</span></p><p
    data-testid="searchResultCardJobDescription">Email person@example.org to apply.</p></div>
    </body></html>"""
    assert (
        "person@example.org"
        not in WorkHubAdapter(discovery_source(employer, "work_hub")).parse(work_hub)[0].description
    )

    adzuna_payload = {
        "count": 1,
        "results": [
            {
                "id": "redact-2",
                "title": "Finance Intern",
                "description": "Contact recruiter@example.org",
                "redirect_url": "https://www.adzuna.co.uk/jobs/details/redact-2",
                "location": {"display_name": "London"},
                "company": {"display_name": "Fixture Employer"},
            }
        ],
    }
    assert (
        "recruiter@example.org"
        not in AdzunaAdapter(discovery_source(employer, "adzuna"))
        .parse(json.dumps(adzuna_payload).encode())[0]
        .description
    )


def test_new_broad_sources_keep_records_but_possible_filter_rejects_clear_mismatches(
    project_root: Path, employer: EmployerConfig
) -> None:
    cases = [
        (
            WorkHubAdapter,
            "work_hub",
            "work-hub.html",
            "Senior Finance Manager",
        ),
        (
            ProspectsAdapter,
            "prospects",
            "prospects.html",
            "Unpaid Marketing Internship",
        ),
        (AdzunaAdapter, "adzuna", "adzuna.json", "Director of Consulting"),
        (ReedAdapter, "reed", "reed.json", "Senior Solicitor"),
    ]
    for adapter, adapter_name, fixture, title in cases:
        source = discovery_source(employer, adapter_name)
        role = next(
            item
            for item in adapter(source).parse(
                (project_root / "fixtures" / "discovery" / fixture).read_bytes()
            )
            if item.title == title
        )
        assert not is_possible_role(classify_role(role, source)), title


@pytest.mark.asyncio
async def test_work_hub_scans_every_advertised_page_and_deduplicates_queries(
    project_root: Path, employer: EmployerConfig
) -> None:
    first = (project_root / "fixtures" / "discovery" / "work-hub.html").read_text()
    first = first.replace("of <strong>2</strong>", "of <strong>31</strong>")
    first = first.replace("</nav>", '<a aria-label="Page 2" href="?pageNumber=2">2</a></nav>')
    second = first.replace("dwp-fixture-101", "dwp-fixture-201").replace(
        "dwp-fixture-102", "dwp-fixture-202"
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = second if request.url.params.get("pageNumber") == "2" else first
        return httpx.Response(200, text=body)

    source = discovery_source(employer, "work_hub").model_copy(
        update={
            "endpoint": "https://work-hub.example/jobs/search",
            "source_authority": SourceAuthority.OFFICIAL_GOVERNMENT_PORTAL,
            "requests_per_minute": 6000,
            "expected_min_items": 4,
            "request_body": {
                "queries": ["finance internship"],
                "location": "London",
                "results_per_page": 30,
                "max_pages_per_query": 2,
            },
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await WorkHubAdapter(source, client).fetch(check_robots=False)
    assert len(result.roles) == 4
    assert result.health.status == SourceHealthStatus.HEALTHY
    assert result.health.pages_scanned == 2
    assert result.health.listing_count == 4
    assert len(requests) == 2
    assert requests[0].url.params["keywords"] == "finance internship"
    assert requests[1].url.params["pageNumber"] == "2"


@pytest.mark.asyncio
async def test_adzuna_api_paginates_and_never_exposes_credentials_in_health(
    project_root: Path,
    employer: EmployerConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADZUNA_APP_ID", "fixture-app-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "fixture-secret-key")
    payload = (project_root / "fixtures" / "discovery" / "adzuna.json").read_text()
    first = payload.replace('"count": 2', '"count": 51')
    second = first.replace("adz-fixture-1", "adz-fixture-101").replace(
        "adz-fixture-2", "adz-fixture-102"
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=second if request.url.path.endswith("/2") else first)

    source = discovery_source(employer, "adzuna").model_copy(
        update={
            "endpoint": "https://api.example/v1/jobs/gb/search",
            "requests_per_minute": 6000,
            "expected_min_items": 4,
            "request_body": {
                "queries": ["consulting intern"],
                "location": "London",
                "results_per_page": 50,
                "max_pages_per_query": 2,
                "max_age_days": 30,
            },
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await AdzunaAdapter(source, client).fetch()
    assert len(result.roles) == 4
    assert result.health.status == SourceHealthStatus.HEALTHY
    assert [request.url.path.rsplit("/", 1)[-1] for request in requests] == ["1", "2"]
    assert requests[0].url.params["app_id"] == "fixture-app-id"
    assert "fixture-app-id" not in (result.health.message or "")
    assert "fixture-secret-key" not in (result.health.message or "")


@pytest.mark.asyncio
async def test_reed_api_uses_basic_auth_and_offset_pagination(
    project_root: Path,
    employer: EmployerConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REED_API_KEY", "fixture-reed-key")
    payload = (project_root / "fixtures" / "discovery" / "reed.json").read_text()
    first = payload.replace('"totalResults": 2', '"totalResults": 101')
    second = first.replace("88001", "88101").replace("88002", "88102")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = second if request.url.params.get("resultsToSkip") == "100" else first
        return httpx.Response(200, text=body)

    source = discovery_source(employer, "reed").model_copy(
        update={
            "endpoint": "https://reed.example/api/1.0/search",
            "requests_per_minute": 6000,
            "expected_min_items": 4,
            "request_body": {
                "queries": ["legal assistant"],
                "location": "London",
                "results_per_page": 100,
                "max_pages_per_query": 2,
            },
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ReedAdapter(source, client).fetch()
    assert len(result.roles) == 4
    assert result.health.status == SourceHealthStatus.HEALTHY
    assert requests[0].headers["authorization"].startswith("Basic ")
    assert "fixture-reed-key" not in str(requests[0].url)
    assert requests[1].url.params["resultsToSkip"] == "100"


def test_reed_recovers_hiring_firm_from_efinancialcareers_title(
    employer: EmployerConfig,
) -> None:
    source = discovery_source(employer, "reed")
    payload = {
        "totalResults": 2,
        "results": [
            {
                "jobId": 1,
                "employerName": "eFinancialCareers",
                "jobTitle": "Investment Internship - Tikehau Capital",
                "locationName": "London",
                "jobDescription": "Paid investment internship.",
                "jobUrl": "https://www.reed.co.uk/jobs/1",
            },
            {
                "jobId": 2,
                "employerName": "eFinancialCareers",
                "jobTitle": "FRA - Business Development / Go-to-Market intern",
                "locationName": "London",
                "jobDescription": "Paid internship.",
                "jobUrl": "https://www.reed.co.uk/jobs/2",
            },
        ],
    }
    roles = ReedAdapter(source).parse(json.dumps(payload).encode())
    assert roles[0].employer == "Tikehau Capital"
    assert roles[0].title == "Investment Internship"
    assert roles[1].employer == "eFinancialCareers"


@pytest.mark.asyncio
async def test_missing_api_credentials_do_not_make_network_requests(
    employer: EmployerConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "REED_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("network request made without credentials")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adzuna = await AdzunaAdapter(discovery_source(employer, "adzuna"), client).fetch()
        reed = await ReedAdapter(discovery_source(employer, "reed"), client).fetch()
    assert adzuna.health.status == SourceHealthStatus.FAILED
    assert reed.health.status == SourceHealthStatus.FAILED
    assert "ADZUNA_APP_ID" in (adzuna.health.message or "")
    assert "REED_API_KEY" in (reed.health.message or "")


@pytest.mark.asyncio
async def test_scanner_labels_unconfigured_credentialed_source_inactive(
    isolated_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        monkeypatch.delenv(name, raising=False)

    def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("scanner made a network request for an inactive source")

    await scan(
        isolated_root,
        source_filter="adzuna-london",
        transport=httpx.MockTransport(handler),
    )
    health = json.loads((isolated_root / "data" / "source_health.json").read_text())
    record = next(item for item in health if item["source_id"] == "adzuna-london")
    assert record["status"] == "disabled"
    assert "ADZUNA_APP_ID" in record["message"]


@pytest.mark.asyncio
async def test_degraded_scan_removes_freshly_rejected_role_but_retains_unseen_role(
    isolated_root: Path,
) -> None:
    registry_path = isolated_root / "config" / "employers.yml"
    document = yaml.safe_load(registry_path.read_text())
    source = next(item for item in document["employers"] if item["id"] == "work-hub-london")
    source.update(
        {
            "endpoint": "https://work-hub.example/jobs/search",
            "requests_per_minute": 6000,
            "expected_min_items": 0,
            "request_body": {
                "queries": ["policy assistant"],
                "location": "London",
                "results_per_page": 30,
                "max_pages_per_query": 1,
            },
        }
    )
    registry_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    def page(*roles: tuple[str, str]) -> str:
        cards = "".join(
            f"""<div data-testid="searchResultCard-{identifier}">
            <a data-testid="jobTitle-{identifier}" href="/jobs/{identifier}">{title}</a>
            <p data-testid="searchResultCardEmployer"><span>Fixture Employer</span><span> - London</span></p>
            <p class="govuk-body govuk-!-font-weight-bold">£30,000 a year</p>
            <p data-testid="searchResultCardJobDescription">Paid junior research and policy work.</p>
            </div>"""
            for identifier, title in roles
        )
        return (
            "<html><body><p>Showing results 1 to 30 of <strong>60</strong></p>"
            + cards
            + '<nav><a aria-label="Page 1">1</a><a aria-label="Page 2">2</a></nav></body></html>'
        )

    first_page = page(("fresh-1", "Policy Internship"), ("missing-2", "Risk Internship"))
    second_page = page(("fresh-1", "Senior Policy Manager"))
    listing_requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal listing_requests
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        listing_requests += 1
        return httpx.Response(200, text=first_page if listing_requests == 1 else second_page)

    transport = httpx.MockTransport(handler)
    await scan(isolated_root, source_filter="work-hub-london", transport=transport)
    await scan(isolated_root, source_filter="work-hub-london", transport=transport)
    possible = json.loads((isolated_root / "data" / "possible_roles.json").read_text())
    assert not any(item["source_identifier"] == "fresh-1" for item in possible)
    assert any(item["source_identifier"] == "missing-2" for item in possible)
    health = json.loads((isolated_root / "data" / "source_health.json").read_text())
    record = next(item for item in health if item["source_id"] == "work-hub-london")
    assert record["status"] == "degraded" and record["capped"]


@pytest.mark.asyncio
async def test_rule_change_removes_stale_possible_role_even_when_source_is_not_scanned(
    isolated_root: Path,
) -> None:
    await scan(isolated_root, fixture_mode=True)
    possible_path = isolated_root / "build" / "fixture-data" / "possible_roles.json"
    possible = json.loads(possible_path.read_text())
    stale = possible[0]
    stale_id = stale["id"]
    stale["title"] = "Receptionist / Administrator"
    possible_path.write_text(json.dumps(possible), encoding="utf-8")

    await scan(isolated_root, fixture_mode=True, source_filter="fixture-greenhouse")
    refreshed = json.loads(possible_path.read_text())
    assert not any(item["id"] == stale_id for item in refreshed)


@pytest.mark.asyncio
async def test_rule_change_promotes_review_role_even_when_source_is_not_scanned(
    isolated_root: Path,
) -> None:
    await scan(isolated_root, fixture_mode=True)
    review_path = isolated_root / "build" / "fixture-data" / "review_queue.json"
    assert any(
        "Policy Research Internship" in item["title"]
        for item in json.loads(review_path.read_text())
    )

    filters_path = isolated_root / "config" / "job_filters.yml"
    filters_path.write_text(
        filters_path.read_text().replace(
            "  - forensic accounting\n",
            "  - forensic accounting\n  - policy\n",
            1,
        ),
        encoding="utf-8",
    )
    await scan(isolated_root, fixture_mode=True, source_filter="fixture-greenhouse")

    possible = json.loads(
        (isolated_root / "build" / "fixture-data" / "possible_roles.json").read_text()
    )
    review = json.loads(review_path.read_text())
    assert any("Policy Research Internship" in item["title"] for item in possible)
    assert not any("Policy Research Internship" in item["title"] for item in review)


@pytest.mark.parametrize(
    "adapter",
    [WorkHubAdapter, ProspectsAdapter, LegalCheekAdapter, AdzunaAdapter, ReedAdapter],
)
def test_new_adapters_fail_closed_on_unrecognised_payload(
    adapter: type[WorkHubAdapter], employer: EmployerConfig
) -> None:
    with pytest.raises(AdapterError):
        adapter(discovery_source(employer, adapter.adapter_name)).parse(
            b"<html><body>challenge page</body></html>"
        )


def test_legalcheek_refuses_to_claim_unverified_pagination(
    project_root: Path, employer: EmployerConfig
) -> None:
    payload = (project_root / "fixtures" / "discovery" / "legalcheek.html").read_text()
    with pytest.raises(AdapterError, match="pagination"):
        LegalCheekAdapter(discovery_source(employer, "legalcheek")).parse(
            payload.replace("Page 1 of 1", "Page 1 of 2").encode()
        )


@pytest.mark.asyncio
async def test_robots_check_fails_closed_on_network_error(employer: EmployerConfig) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            raise httpx.ConnectError("robots unavailable", request=request)
        pytest.fail("listing request made after robots check failed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ProspectsAdapter(discovery_source(employer, "prospects"), client).fetch()
    assert result.health.status == SourceHealthStatus.FAILED
    assert "robots.txt disallows" in (result.health.message or "")

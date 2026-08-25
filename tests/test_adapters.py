from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from opportunity_radar.adapters.parsers import (
    AshbyAdapter,
    CharityJobAdapter,
    CuratedYamlAdapter,
    FeedAdapter,
    GenericJsonAdapter,
    GovernmentPortalAdapter,
    GreenhouseAdapter,
    HigherinAdapter,
    HtmlMonitorAdapter,
    JobsAcUkAdapter,
    LeverAdapter,
    NHSJobsAdapter,
    SmartRecruitersAdapter,
    TargetJobsAdapter,
    TeamtailorAdapter,
    TrustedBoardAdapter,
    W4MPAdapter,
    WorkdayAdapter,
)
from opportunity_radar.classification import classify_role, is_possible_role, is_public_role
from opportunity_radar.models import (
    EligibilityStatus,
    EmployerConfig,
    LocationType,
    RelevanceStatus,
    SourceAuthority,
    SourceHealthStatus,
)


@pytest.mark.parametrize(
    ("adapter", "fixture", "expected_title"),
    [
        (GreenhouseAdapter, "greenhouse.json", "Summer 2027 Corporate Finance Internship"),
        (LeverAdapter, "lever.json", "Policy Research Intern"),
        (AshbyAdapter, "ashby.json", "Climate Risk Internship"),
        (SmartRecruitersAdapter, "smartrecruiters.json", "Commercial Analysis Intern"),
        (WorkdayAdapter, "workday.json", "Supply Chain Internship"),
        (TeamtailorAdapter, "teamtailor.json", "Health Policy Intern"),
        (GenericJsonAdapter, "generic.json", "Geospatial Analysis Internship"),
        (FeedAdapter, "feed.xml", "Public Policy Internship"),
        (HtmlMonitorAdapter, "html.html", "Risk Internship"),
    ],
)
def test_ats_adapters_parse_saved_fixtures(
    adapter: type[HtmlMonitorAdapter],
    fixture: str,
    expected_title: str,
    project_root: Path,
    employer: EmployerConfig,
) -> None:
    roles = adapter(employer).parse((project_root / "fixtures" / "ats" / fixture).read_bytes())
    assert roles
    assert roles[0].title == expected_title
    assert roles[0].source_identifier


def test_government_portal_sets_official_authority(
    project_root: Path, employer: EmployerConfig
) -> None:
    roles = GovernmentPortalAdapter(employer).parse(
        (project_root / "fixtures" / "government" / "portal.html").read_bytes()
    )
    assert roles[0].source_authority == SourceAuthority.OFFICIAL_GOVERNMENT_PORTAL
    assert roles[0].paid is True


def test_trusted_board_preserves_employer_and_publisher(
    project_root: Path, employer: EmployerConfig
) -> None:
    source = employer.model_copy(
        update={
            "canonical_name": "W4MP Jobs",
            "source_authority": SourceAuthority.TRUSTED_SECTOR_BOARD,
            "manual_review_required": True,
            "priority_tier": "approved",
        }
    )
    roles = TrustedBoardAdapter(source).parse(
        (project_root / "fixtures" / "parliament" / "w4mp.html").read_bytes()
    )
    assert roles[0].employer == "Alex Example MP"
    assert roles[0].listing_publisher == "W4MP Jobs"
    assert roles[0].named_office_or_mp == "Office of Alex Example MP"
    assert roles[0].political_affiliation == "Example Party"
    assert roles[0].application_method == "Email the office using the instructions in the listing"
    assert roles[0].published_date and roles[0].published_date.isoformat() == "2026-08-10"


def test_higherin_parses_real_employer_and_structured_stage(
    project_root: Path, employer: EmployerConfig
) -> None:
    source = employer.model_copy(
        update={
            "canonical_name": "Higherin",
            "source_authority": SourceAuthority.DISCOVERY_ONLY_SOURCE,
        }
    )
    roles = HigherinAdapter(source).parse(
        (project_root / "fixtures" / "discovery" / "higherin.html").read_bytes()
    )
    assert len(roles) == 3
    assert roles[0].employer == "Fixture Policy Employer"
    assert roles[0].eligibility_text == "Relevant for: 1st-year and 2nd-year"
    assert roles[0].deadline and roles[0].deadline.isoformat() == "2026-09-30"
    classified = classify_role(roles[0], source)
    assert classified.canonical_employer == "Fixture Policy Employer"
    assert classified.eligibility_status == EligibilityStatus.UNCERTAIN
    assert not is_possible_role(classified)
    assert not is_public_role(classified)


def test_w4mp_live_parser_preserves_all_records_for_central_classification(
    project_root: Path, employer: EmployerConfig
) -> None:
    source = employer.model_copy(
        update={
            "canonical_name": "W4MP Jobs",
            "source_authority": SourceAuthority.TRUSTED_SECTOR_BOARD,
            "manual_review_required": True,
            "priority_tier": "approved",
        }
    )
    roles = W4MPAdapter(source).parse(
        (project_root / "fixtures" / "parliament" / "w4mp-live.html").read_bytes()
    )
    assert [role.title for role in roles] == [
        "Temp to Perm Corporate Affairs Manager",
        "Caseworker",
    ]
    manager, caseworker = (classify_role(item, source) for item in roles)
    assert not is_possible_role(manager)
    assert not is_possible_role(caseworker)
    assert roles[1].employer == "Jessica Toale MP (Bournemouth West)"
    assert roles[1].listing_publisher == "W4MP Jobs"
    assert roles[1].organisation_type == "parliamentary_office"
    assert roles[1].deadline and roles[1].deadline.isoformat() == "2026-08-21"


def test_w4mp_deduplicates_responsive_pager_controls(employer: EmployerConfig) -> None:
    payload = b"""<html><body>
    <input type="hidden" name="__VIEWSTATE" value="state">
    <a href="javascript:__doPostBack(&#39;desktop$page2&#39;,&#39;&#39;)">2</a>
    <a href="javascript:__doPostBack(&#39;mobile$page2&#39;,&#39;&#39;)">2</a>
    <a href="javascript:__doPostBack(&#39;desktop$page3&#39;,&#39;&#39;)">3</a>
    </body></html>"""
    adapter = W4MPAdapter(employer)
    adapter.parse(payload)
    assert adapter._page_targets == ["desktop$page2", "desktop$page3"]


@pytest.mark.parametrize(
    ("adapter", "fixture", "expected_title", "expected_employer"),
    [
        (
            CharityJobAdapter,
            "charityjob.html",
            "Policy Administrator",
            "Example Policy Charity",
        ),
        (NHSJobsAdapter, "nhs-jobs.html", "Policy Support Officer", "Example NHS Trust"),
        (
            JobsAcUkAdapter,
            "jobs-ac-uk.html",
            "Research and Policy Assistant",
            "Example University of London",
        ),
    ],
)
def test_broad_discovery_adapters_preserve_real_employers_and_paid_status(
    adapter: type[CharityJobAdapter],
    fixture: str,
    expected_title: str,
    expected_employer: str,
    project_root: Path,
    employer: EmployerConfig,
) -> None:
    source = employer.model_copy(
        update={
            "canonical_name": "Discovery board",
            "source_authority": SourceAuthority.DISCOVERY_ONLY_SOURCE,
            "priority_tier": "approved",
            "manual_review_required": True,
        }
    )
    roles = adapter(source).parse((project_root / "fixtures" / "discovery" / fixture).read_bytes())
    assert len(roles) == 2
    assert roles[0].title == expected_title
    assert roles[0].employer == expected_employer
    assert roles[0].paid is True
    assert roles[0].listing_publisher == "Discovery board"
    classified = classify_role(roles[0], source)
    assert classified.eligibility_status == EligibilityStatus.UNCERTAIN
    assert not is_possible_role(classified)
    assert not is_public_role(classified)


def test_nhs_jobs_uses_official_portal_authority_and_preserves_trust(
    project_root: Path, employer: EmployerConfig
) -> None:
    source = employer.model_copy(
        update={
            "canonical_name": "NHS Jobs",
            "organisation_type": "public_health",
            "source_authority": SourceAuthority.OFFICIAL_GOVERNMENT_PORTAL,
            "priority_tier": "approved",
            "manual_review_required": True,
        }
    )
    role = NHSJobsAdapter(source).parse(
        (project_root / "fixtures" / "discovery" / "nhs-jobs.html").read_bytes()
    )[0]
    classified = classify_role(role, source)
    assert role.source_authority == SourceAuthority.OFFICIAL_GOVERNMENT_PORTAL
    assert classified.canonical_employer == "Example NHS Trust"
    assert classified.listing_publisher == "NHS Jobs"
    assert not is_possible_role(classified)


def test_targetjobs_preserves_employer_application_and_count(
    project_root: Path, employer: EmployerConfig
) -> None:
    source = employer.model_copy(
        update={
            "canonical_name": "targetjobs",
            "source_authority": SourceAuthority.DISCOVERY_ONLY_SOURCE,
            "priority_tier": "approved",
            "manual_review_required": True,
        }
    )
    adapter = TargetJobsAdapter(source)
    roles = adapter.parse(
        (project_root / "fixtures" / "discovery" / "targetjobs.json").read_bytes()
    )
    assert len(roles) == 2
    assert adapter._advertised_count == 2
    assert roles[0].title == "Policy Research Internship"
    assert roles[0].employer == "Fixture Policy Institute"
    assert roles[0].listing_publisher == "targetjobs"
    assert roles[0].application_url == "https://employer.example/apply/policy-intern"
    assert roles[0].deadline and roles[0].deadline.isoformat() == "2026-09-30"
    assert roles[0].paid is True
    assert not is_possible_role(classify_role(roles[0], source))
    assert (
        TargetJobsAdapter._employer(
            {
                "organisation": {"title": "Incorrect indexed employer"},
                "sourceOrganisationName": "Another incorrect name",
            },
            "https://jd.wd103.myworkdayjobs.com/Campus_Career_Site/job/London/Role_REQ1",
        )
        == "Jingdong Retail (UK) Limited"
    )


@pytest.mark.asyncio
async def test_targetjobs_fetches_every_advertised_page_and_sends_public_page_headers(
    project_root: Path, employer: EmployerConfig
) -> None:
    payload = (project_root / "fixtures" / "discovery" / "targetjobs.json").read_text()
    first = payload.replace('"result_count": 2', '"result_count": 101')
    second = (
        payload.replace('"result_count": 2', '"result_count": 101')
        .replace('"fixture-policy-1"', '"fixture-policy-101"')
        .replace('"fixture-senior-2"', '"fixture-senior-102"')
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = second if b'"offset":100' in request.content else first
        return httpx.Response(200, text=body)

    source = employer.model_copy(
        update={
            "id": "targetjobs-london-early-careers",
            "canonical_name": "targetjobs",
            "endpoint": "https://targetjobs.example/ext/svc/search",
            "careers_url": "https://targetjobs.co.uk/internships/london",
            "source_authority": SourceAuthority.DISCOVERY_ONLY_SOURCE,
            "requests_per_minute": 6000,
            "expected_min_items": 4,
            "result_cap": 200,
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await TargetJobsAdapter(source, client).fetch(check_robots=False)
    assert len(result.roles) == 4
    assert result.health.pages_scanned == 2
    assert result.health.status == SourceHealthStatus.DEGRADED
    assert not result.health.parser_ok
    assert requests[0].headers["origin"] == "https://targetjobs.co.uk"
    assert requests[0].headers["x-host"] == "users.targetjobs.co.uk"
    assert b'"offset":100' in requests[1].content


@pytest.mark.parametrize(
    ("adapter", "fixture", "excluded_title"),
    [
        (CharityJobAdapter, "charityjob.html", "Senior Director"),
        (NHSJobsAdapter, "nhs-jobs.html", "Registered Nurse"),
        (JobsAcUkAdapter, "jobs-ac-uk.html", "Assistant Professor of Finance"),
    ],
)
def test_broad_discovery_adapters_keep_but_possible_pool_excludes_obvious_mismatches(
    adapter: type[CharityJobAdapter],
    fixture: str,
    excluded_title: str,
    project_root: Path,
    employer: EmployerConfig,
) -> None:
    source = employer.model_copy(
        update={
            "source_authority": SourceAuthority.DISCOVERY_ONLY_SOURCE,
            "priority_tier": "approved",
            "manual_review_required": True,
        }
    )
    role = next(
        item
        for item in adapter(source).parse(
            (project_root / "fixtures" / "discovery" / fixture).read_bytes()
        )
        if item.title == excluded_title
    )
    assert not is_possible_role(classify_role(role, source))


@pytest.mark.asyncio
async def test_paginated_discovery_fetches_every_page_and_reports_coverage(
    project_root: Path, employer: EmployerConfig
) -> None:
    page_one = (project_root / "fixtures" / "discovery" / "charityjob.html").read_text()
    page_one = page_one.replace('"total_pages":1', '"total_pages":2')
    page_two = (
        page_one.replace("1079001", "1079011")
        .replace("1079002", "1079012")
        .replace('"total_count":2', '"total_count":99')
    )
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            200,
            text=page_two if request.url.params.get("page") == "2" else page_one,
        )

    source = employer.model_copy(
        update={
            "canonical_name": "CharityJob",
            "endpoint": "https://charity.example/jobs?location=London",
            "source_authority": SourceAuthority.DISCOVERY_ONLY_SOURCE,
            "requests_per_minute": 6000,
            "expected_min_items": 4,
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await CharityJobAdapter(source, client).fetch(check_robots=False)
    assert len(result.roles) == 4
    assert result.health.status == SourceHealthStatus.HEALTHY
    assert result.health.pages_scanned == 2
    assert result.health.listing_count == 4
    assert requests[-1].endswith("location=London&page=2")


@pytest.mark.asyncio
async def test_paginated_discovery_degrades_when_advertised_jobs_are_missing(
    project_root: Path, employer: EmployerConfig
) -> None:
    page = (project_root / "fixtures" / "discovery" / "charityjob.html").read_text()
    page = page.replace('"total_count":2', '"total_count":10')
    source = employer.model_copy(
        update={
            "canonical_name": "CharityJob",
            "endpoint": "https://charity.example/jobs?location=London",
            "source_authority": SourceAuthority.DISCOVERY_ONLY_SOURCE,
            "expected_min_items": 2,
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=page))
    ) as client:
        result = await CharityJobAdapter(source, client).fetch(check_robots=False)
    assert len(result.roles) == 2
    assert result.health.status == SourceHealthStatus.DEGRADED
    assert not result.health.parser_ok
    assert "of 10 advertised" in (result.health.message or "")


@pytest.mark.asyncio
async def test_higherin_fetches_every_declared_page(
    project_root: Path, employer: EmployerConfig
) -> None:
    first = (project_root / "fixtures" / "discovery" / "higherin.html").read_text()
    first = first.replace('"lastPage":1', '"lastPage":2')
    second = first.replace('"lastPage":2', '"lastPage":2').replace("9100", "9200")
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, text=second if request.url.params.get("page") == "2" else first)

    source = employer.model_copy(
        update={
            "canonical_name": "Higherin",
            "endpoint": "https://higherin.example/search-jobs/internships/london",
            "source_authority": SourceAuthority.DISCOVERY_ONLY_SOURCE,
            "expected_min_items": 6,
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await HigherinAdapter(source, client).fetch(check_robots=False)
    assert len(result.roles) == 6
    assert result.health.pages_scanned == 2
    assert result.health.listing_count == 6
    assert requests[-1].endswith("?page=2")


@pytest.mark.asyncio
async def test_w4mp_fetch_posts_every_pager_target(employer: EmployerConfig) -> None:
    page_one = """<html><body>
    <input type="hidden" name="__VIEWSTATE" value="state">
    <a href="javascript:__doPostBack(&#39;pager$page2&#39;,&#39;&#39;)">2</a>
    <article class="job-advert"><a href="JobDetails.aspx?jobid=100">100</a>
    <span itemprop="title">Policy Assistant</span><span itemprop="hiringOrganization">Office One MP</span>
    <div itemprop="jobLocation">Location: London</div><div itemprop="baseSalary">Salary: £30,000</div>
    <span itemprop="datePosted">11 August 2026</span>, closes on 30 August 2026</article>
    </body></html>""".encode()
    page_two = (
        page_one.replace(b"jobid=100", b"jobid=101")
        .replace(b"Office One MP", b"Office Two MP")
        .replace(b"pager$page2", b"pager$unused")
    )
    requests: list[tuple[str, bytes]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        requests.append((request.method, body))
        return httpx.Response(200, content=page_two if request.method == "POST" else page_one)

    source = employer.model_copy(
        update={
            "canonical_name": "W4MP Jobs",
            "endpoint": "https://w4mp.example/SearchJobs.aspx?search=alljobs",
            "source_authority": SourceAuthority.TRUSTED_SECTOR_BOARD,
            "expected_min_items": 2,
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await W4MPAdapter(source, client).fetch(check_robots=False)
    assert len(result.roles) == 2
    assert result.health.pages_scanned == 2
    assert result.health.listing_count == 2
    assert requests[0][0] == "GET" and requests[1][0] == "POST"
    assert b"pager%24page2" in requests[1][1]


def test_html_structure_change_raises(employer: EmployerConfig) -> None:
    with pytest.raises(Exception, match="structure changed"):
        HtmlMonitorAdapter(employer).parse(b'<div data-job="changed"></div>')


def test_monitor_only_html_source_tracks_page_without_claiming_roles(
    employer: EmployerConfig,
) -> None:
    source = employer.model_copy(update={"monitor_only": True})
    assert HtmlMonitorAdapter(source).parse(b"<main><h1>Official programme page</h1></main>") == []


def test_curated_official_records_parse(project_root: Path, employer: EmployerConfig) -> None:
    roles = CuratedYamlAdapter(employer).parse(
        (project_root / "fixtures" / "law" / "programmes.yml").read_bytes()
    )
    assert len(roles) == 2
    assert all(role.source_authority == SourceAuthority.OFFICIAL_PROGRAMME_PAGE for role in roles)


@pytest.mark.asyncio
async def test_workday_enriches_carlyle_detail_before_classification(
    project_root: Path, employer: EmployerConfig
) -> None:
    search_payload = (
        project_root / "fixtures" / "ats" / "workday-carlyle-search.json"
    ).read_bytes()
    detail_payload = (
        project_root / "fixtures" / "ats" / "workday-carlyle-detail.json"
    ).read_bytes()
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(200, content=search_payload)
        return httpx.Response(200, content=detail_payload)

    source = employer.model_copy(
        update={
            "id": "carlyle",
            "canonical_name": "The Carlyle Group",
            "organisation_type": "investment_manager",
            "careers_url": "https://carlyle.wd1.myworkdayjobs.com/Carlyle",
            "endpoint": "https://carlyle.wd1.myworkdayjobs.com/wday/cxs/carlyle/Carlyle/jobs",
            "request_method": "POST",
            "request_body": {"appliedFacets": {}, "limit": 20, "offset": 0},
            "priority_tier": "priority",
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await WorkdayAdapter(source, client).fetch(check_robots=False)

    assert requests == [
        ("POST", "/wday/cxs/carlyle/Carlyle/jobs"),
        ("GET", "/wday/cxs/carlyle/Carlyle/job/London-United-Kingdom/Intern_R-00234"),
    ]
    assert result.health.status == SourceHealthStatus.HEALTHY
    assert result.health.item_count == 1
    assert result.health.content_hash
    role = result.roles[0]
    assert role.source_identifier == "R-00234"
    assert role.title == "Private Credit Intern"
    assert role.location == "London, United Kingdom"
    assert role.location_type == LocationType.HYBRID
    assert role.published_date and role.published_date.isoformat() == "2026-08-11"
    assert "fundamental credit analysis" in role.description
    assert role.source_url == (
        "https://carlyle.wd1.myworkdayjobs.com/Carlyle/job/London-United-Kingdom/Intern_R-00234"
    )

    classified = classify_role(role, source)
    assert classified.eligibility_status == EligibilityStatus.UNCERTAIN
    assert classified.relevance_status == RelevanceStatus.STRONG
    assert not is_public_role(classified)
    assert is_possible_role(classified)


@pytest.mark.asyncio
async def test_workday_detail_failure_fails_closed(employer: EmployerConfig) -> None:
    search_payload = {
        "jobPostings": [
            {
                "title": "Private Credit Intern",
                "externalPath": "/job/London-United-Kingdom/Intern_R-00234",
                "locationsText": "London, United Kingdom",
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=search_payload)
        return httpx.Response(200, json={"unexpected": "shape"})

    source = employer.model_copy(
        update={
            "careers_url": "https://carlyle.wd1.myworkdayjobs.com/Carlyle",
            "endpoint": "https://carlyle.wd1.myworkdayjobs.com/wday/cxs/carlyle/Carlyle/jobs",
            "request_method": "POST",
            "request_body": {"limit": 20, "offset": 0},
        }
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await WorkdayAdapter(source, client).fetch(check_robots=False)
    assert result.roles == []
    assert result.health.status == SourceHealthStatus.FAILED
    assert result.health.parser_ok is False
    assert "detail enrichment failed" in (result.health.message or "").casefold()


@pytest.mark.asyncio
async def test_configured_source_cap_is_degraded(employer: EmployerConfig) -> None:
    payload = b'{"jobs":[{"id":"1","title":"Role","url":"https://example.invalid/1"}]}'
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=payload))
    source = employer.model_copy(
        update={"ats_type": "generic_json", "result_cap": 1, "expected_min_items": 1}
    )
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        result = await GenericJsonAdapter(source, client).fetch(check_robots=False)
    assert result.health.status == SourceHealthStatus.DEGRADED
    assert result.health.capped
    assert result.health.content_hash

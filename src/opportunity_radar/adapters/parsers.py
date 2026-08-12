from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
from datetime import UTC, date, datetime, timedelta
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx

from opportunity_radar.adapters.base import AdapterError, BaseAdapter, SourceFetchResult
from opportunity_radar.models import (
    LocationType,
    RawRole,
    SourceAuthority,
    SourceHealth,
    SourceHealthStatus,
)


def clean_html(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def parse_date(value: object) -> date | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, int | float):
        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, UTC).date()
    text = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", str(value).strip(), flags=re.I)
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text[:30], fmt).date()
        except ValueError:
            pass
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    return date.fromisoformat(match.group()) if match else None


def json_payload(payload: bytes) -> Any:
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"Invalid JSON: {exc}") from exc


class GreenhouseAdapter(BaseAdapter):
    adapter_name = "greenhouse"

    def parse(self, payload: bytes) -> list[RawRole]:
        data = json_payload(payload)
        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        return [
            self.role(
                identifier=str(job["id"]),
                title=job["title"],
                url=job["absolute_url"],
                location=job.get("location", {}).get("name", "Unknown"),
                description=clean_html(job.get("content")),
                # Greenhouse's updated_at is a modification time, not a posting date.
                published_date=parse_date(job.get("published_at") or job.get("first_published")),
            )
            for job in jobs
        ]


class LeverAdapter(BaseAdapter):
    adapter_name = "lever"

    def parse(self, payload: bytes) -> list[RawRole]:
        jobs = json_payload(payload)
        if not isinstance(jobs, list):
            raise AdapterError("Lever payload must be a list")
        return [
            self.role(
                identifier=str(job["id"]),
                title=job["text"],
                url=job.get("hostedUrl") or job.get("applyUrl"),
                location=job.get("categories", {}).get("location", "Unknown"),
                description=clean_html(job.get("descriptionPlain") or job.get("description")),
                published_date=parse_date(job.get("createdAt")),
            )
            for job in jobs
        ]


class AshbyAdapter(BaseAdapter):
    adapter_name = "ashby"

    def parse(self, payload: bytes) -> list[RawRole]:
        data = json_payload(payload)
        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        return [
            self.role(
                identifier=str(job.get("id") or job["jobUrl"]),
                title=job["title"],
                url=job["jobUrl"],
                location=job.get("location", "Unknown"),
                description=clean_html(job.get("descriptionHtml") or job.get("descriptionPlain")),
                published_date=parse_date(job.get("publishedAt")),
            )
            for job in jobs
        ]


class SmartRecruitersAdapter(BaseAdapter):
    adapter_name = "smartrecruiters"

    def parse(self, payload: bytes) -> list[RawRole]:
        data = json_payload(payload)
        jobs = data.get("content", []) if isinstance(data, dict) else []
        return [
            self.role(
                identifier=str(job["id"]),
                title=job["name"],
                url=job.get("ref") or job.get("applyUrl"),
                location=", ".join(
                    part
                    for part in (
                        job.get("location", {}).get("city"),
                        job.get("location", {}).get("country"),
                    )
                    if part
                ),
                description=clean_html(
                    job.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text")
                ),
                published_date=parse_date(job.get("releasedDate")),
            )
            for job in jobs
        ]


class WorkdayAdapter(BaseAdapter):
    adapter_name = "workday"

    def _listing_url(self, external_path: str) -> str:
        base = self.source.careers_url or self.source.endpoint or ""
        return urljoin(f"{base.rstrip('/')}/", external_path.lstrip("/"))

    def _detail_api_url(self, external_path: str) -> str:
        endpoint = self.source.endpoint or ""
        if not endpoint.endswith("/jobs") or not external_path.startswith("/job/"):
            raise AdapterError("Workday detail enrichment requires a CXS /jobs endpoint")
        return f"{endpoint.removesuffix('/jobs')}{external_path}"

    async def _get_detail(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        for attempt in range(3):
            try:
                response = await client.get(url, timeout=20.0)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        "retryable response", request=response.request, response=response
                    )
                response.raise_for_status()
                return response
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                if attempt == 2:
                    raise AdapterError(str(exc)) from exc
                await asyncio.sleep((2**attempt) + random.random() / 4)
        raise AdapterError("No Workday detail response received")

    def _parse_detail(self, payload: bytes, fallback: RawRole) -> RawRole:
        data = json_payload(payload)
        info = data.get("jobPostingInfo") if isinstance(data, dict) else None
        if not isinstance(info, dict):
            raise AdapterError("Workday detail response has no jobPostingInfo")
        external_url = str(info.get("externalUrl") or fallback.source_url)
        remote_type = str(info.get("remoteType") or "").casefold()
        location_type = {
            "hybrid": LocationType.HYBRID,
            "remote": LocationType.REMOTE_UK,
        }.get(remote_type, LocationType.UNKNOWN)
        return self.role(
            identifier=str(info.get("jobReqId") or fallback.source_identifier),
            title=str(info.get("title") or fallback.title),
            url=external_url,
            application_url=external_url,
            location=str(info.get("location") or fallback.location),
            location_type=location_type,
            description=clean_html(str(info.get("jobDescription") or fallback.description)),
            published_date=parse_date(info.get("startDate")) or fallback.published_date,
            explicitly_closed=not bool(info.get("canApply", True) and info.get("posted", True)),
        )

    async def fetch(self, *, check_robots: bool = True) -> SourceFetchResult:
        """Fetch Workday search results and enrich every returned role from its CXS detail API.

        Workday search responses omit the description that establishes relevance and eligibility.
        Publishing those summaries would create false positives, so any detail failure fails the
        source closed and prevents lifecycle removals.
        """
        summary = await super().fetch(check_robots=check_robots)
        if summary.health.status == SourceHealthStatus.FAILED or not summary.roles:
            return summary
        client = self._client or httpx.AsyncClient(
            headers={"User-Agent": "LondonOpportunityRadar/0.1 (+public research tracker)"},
            follow_redirects=True,
        )
        owns_client = self._client is None
        digest = hashlib.sha256((summary.health.content_hash or "").encode())
        try:
            enriched: list[RawRole] = []
            for role in summary.roles:
                detail_url = self._detail_api_url(role.source_identifier)
                response = await self._get_detail(client, detail_url)
                digest.update(response.content)
                enriched.append(self._parse_detail(response.content, role))
            return SourceFetchResult(
                roles=enriched,
                health=summary.health.model_copy(
                    update={
                        "item_count": len(enriched),
                        "content_hash": digest.hexdigest(),
                    }
                ),
            )
        except (httpx.HTTPError, AdapterError, ValueError) as exc:
            return SourceFetchResult(
                roles=[],
                health=SourceHealth(
                    source_id=self.source.id,
                    status=SourceHealthStatus.FAILED,
                    checked_at=datetime.now(UTC),
                    parser_ok=False,
                    message=f"Workday detail enrichment failed: {exc}",
                ),
            )
        finally:
            if owns_client:
                await client.aclose()

    def parse(self, payload: bytes) -> list[RawRole]:
        data = json_payload(payload)
        jobs = data.get("jobPostings", []) if isinstance(data, dict) else []
        return [
            self.role(
                identifier=str(job.get("externalPath") or job.get("id") or job["title"]),
                title=job["title"],
                url=self._listing_url(job["externalPath"]),
                location=job.get("locationsText", "Unknown"),
                description=clean_html(job.get("description")),
                published_date=parse_date(job.get("postedOn")),
            )
            for job in jobs
        ]


class TeamtailorAdapter(BaseAdapter):
    adapter_name = "teamtailor"

    def parse(self, payload: bytes) -> list[RawRole]:
        data = json_payload(payload)
        jobs = data.get("data", []) if isinstance(data, dict) else []
        roles: list[RawRole] = []
        for job in jobs:
            attrs = job.get("attributes", {})
            roles.append(
                self.role(
                    identifier=str(job["id"]),
                    title=attrs["title"],
                    url=attrs.get("url") or job.get("links", {}).get("self") or f"jobs/{job['id']}",
                    location=attrs.get("location", "Unknown"),
                    description=clean_html(attrs.get("body")),
                    published_date=parse_date(attrs.get("created-at")),
                )
            )
        return roles


class GenericJsonAdapter(BaseAdapter):
    adapter_name = "generic_json"

    def parse(self, payload: bytes) -> list[RawRole]:
        data = json_payload(payload)
        jobs = data.get("jobs", data) if isinstance(data, dict) else data
        if not isinstance(jobs, list):
            raise AdapterError("Generic JSON payload must be a list or contain jobs")
        return [
            self.role(
                identifier=str(job.get("id") or job.get("url")),
                title=str(job["title"]),
                url=str(job.get("url") or job.get("application_url")),
                application_url=(
                    str(job["application_url"]) if job.get("application_url") else None
                ),
                location=str(job.get("location", "Unknown")),
                description=clean_html(str(job.get("description", ""))),
                published_date=parse_date(job.get("published_date")),
                deadline=parse_date(job.get("deadline")),
                opening_date=parse_date(job.get("opening_date")),
                programme_start=parse_date(job.get("programme_start")),
                programme_end=parse_date(job.get("programme_end")),
                salary=job.get("salary"),
                paid=job.get("paid"),
                paid_evidence=job.get("paid_evidence"),
                eligibility_text=str(job.get("eligibility", "")),
                cycle_hint=job.get("cycle"),
                category_hint=job.get("category"),
                secondary_tags=job.get("secondary_tags", []),
                nationality_requirements=job.get("nationality_requirements", []),
                residency_requirements=job.get("residency_requirements", []),
                clearance_requirements=job.get("clearance_requirements", []),
                division=job.get("division"),
                application_method=job.get("application_method"),
                explicitly_closed=bool(job.get("explicitly_closed", False)),
                date_provenance=job.get("date_provenance"),
                cycle_provenance=job.get("cycle_provenance"),
            )
            for job in jobs
        ]


class FeedAdapter(BaseAdapter):
    adapter_name = "feed"

    def parse(self, payload: bytes) -> list[RawRole]:
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError as exc:
            raise AdapterError(f"Invalid XML feed: {exc}") from exc
        entries = root.findall(".//item") or root.findall("{*}entry")
        roles: list[RawRole] = []
        for entry in entries:

            def value(*names: str, current: ElementTree.Element = entry) -> str:
                for name in names:
                    node = current.find(name)
                    if node is None:
                        node = current.find(f"{{*}}{name}")
                    if node is not None:
                        if node.text:
                            return node.text
                        if node.attrib.get("href"):
                            return node.attrib["href"]
                return ""

            url = value("link")
            roles.append(
                self.role(
                    identifier=value("guid", "id") or url,
                    title=value("title"),
                    url=url,
                    location=value("location") or "Unknown",
                    description=clean_html(value("description", "summary", "content")),
                    published_date=parse_date(value("pubDate", "published", "updated")),
                )
            )
        return roles


class _DataJobParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.jobs: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if values.get("data-job-id"):
            self.jobs.append(values)


class HtmlMonitorAdapter(BaseAdapter):
    adapter_name = "html"

    def _job_attributes(self, payload: bytes) -> list[dict[str, str]]:
        parser = _DataJobParser()
        try:
            parser.feed(payload.decode())
        except UnicodeDecodeError as exc:
            raise AdapterError("HTML is not UTF-8") from exc
        if not parser.jobs and "data-job" in payload.decode(errors="ignore"):
            raise AdapterError("Page structure changed: job markers found but no records parsed")
        return parser.jobs

    @staticmethod
    def _requirements(value: str | None) -> list[str]:
        return [item.strip() for item in (value or "").split("|") if item.strip()]

    def parse(self, payload: bytes) -> list[RawRole]:
        # A monitor-only source deliberately tracks the official page bytes and
        # source health without pretending that a generic page is a role feed.
        # Role publication still requires a tested parser or curated record.
        if self.source.monitor_only:
            return []
        return [
            self.role(
                identifier=job["data-job-id"],
                title=job.get("data-title", "Untitled role"),
                url=job.get("data-url", self.source.endpoint or ""),
                location=job.get("data-location", "Unknown"),
                description=job.get("data-description", ""),
                eligibility_text=job.get("data-eligibility", ""),
                application_url=job.get("data-application-url") or None,
                application_method=job.get("data-application-method") or None,
                division=job.get("data-division") or None,
                political_affiliation=job.get("data-political-affiliation") or None,
                paid=job.get("data-paid", "").casefold() == "true"
                if job.get("data-paid")
                else None,
                published_date=parse_date(job.get("data-published-date")),
                deadline=parse_date(job.get("data-deadline")),
                opening_date=parse_date(job.get("data-opening-date")),
                programme_start=parse_date(job.get("data-programme-start")),
                programme_end=parse_date(job.get("data-programme-end")),
                salary=job.get("data-salary") or None,
                paid_evidence=job.get("data-paid-evidence") or None,
                cycle_hint=job.get("data-cycle"),
                nationality_requirements=self._requirements(
                    job.get("data-nationality-requirements")
                ),
                residency_requirements=self._requirements(job.get("data-residency-requirements")),
                clearance_requirements=self._requirements(job.get("data-clearance-requirements")),
                explicitly_closed=job.get("data-closed", "").casefold() == "true",
            )
            for job in self._job_attributes(payload)
        ]


class GovernmentPortalAdapter(HtmlMonitorAdapter):
    adapter_name = "government_portal"

    def role(self, **fields: Any) -> RawRole:
        role = super().role(**fields)
        return role.model_copy(
            update={"source_authority": SourceAuthority.OFFICIAL_GOVERNMENT_PORTAL}
        )


class TrustedBoardAdapter(HtmlMonitorAdapter):
    adapter_name = "trusted_board"

    def parse(self, payload: bytes) -> list[RawRole]:
        roles = super().parse(payload)
        attributes = {item["data-job-id"]: item for item in self._job_attributes(payload)}
        result: list[RawRole] = []
        for role in roles:
            job = attributes[role.source_identifier]
            employer = unescape(job.get("data-employer", role.employer))
            result.append(
                role.model_copy(
                    update={
                        "employer": employer,
                        "named_office_or_mp": unescape(job.get("data-office") or employer),
                        "listing_publisher": unescape(
                            job.get("data-publisher", self.source.canonical_name)
                        ),
                        "political_affiliation": unescape(job.get("data-political-affiliation", ""))
                        or None,
                        "application_method": unescape(job.get("data-application-method", ""))
                        or None,
                        "source_authority": SourceAuthority.TRUSTED_SECTOR_BOARD,
                    }
                )
            )
        return result


def _class_content(block: str, class_name: str) -> str:
    match = re.search(
        rf'<[^>]+class="[^"]*\b{re.escape(class_name)}\b[^"]*"[^>]*>(.*?)</[^>]+>',
        block,
        re.IGNORECASE | re.DOTALL,
    )
    return clean_html(match.group(1)) if match else ""


def _relative_posted_date(value: str, *, today: date | None = None) -> date | None:
    current = today or date.today()
    text = normalise_board_text(value)
    if text in {"today", "posted today"}:
        return current
    match = re.search(r"(?:posted )?(\d+) day(?:s)? ago", text)
    if match:
        return current - timedelta(days=int(match.group(1)))
    match = re.search(r"(?:posted )?(\d+) week(?:s)? ago", text)
    if match:
        return current - timedelta(days=7 * int(match.group(1)))
    return parse_date(value)


def _yearless_date(value: str, *, future: bool, today: date | None = None) -> date | None:
    """Resolve UK board dates such as ``31 Aug`` without inventing a distant cycle."""

    current = today or date.today()
    text = clean_html(value)
    for fmt in ("%d %b", "%d %B"):
        try:
            parsed = datetime.strptime(text, fmt).date().replace(year=current.year)
        except ValueError:
            continue
        if future and parsed < current - timedelta(days=2):
            parsed = parsed.replace(year=current.year + 1)
        if not future and parsed > current + timedelta(days=2):
            parsed = parsed.replace(year=current.year - 1)
        return parsed
    return parse_date(text)


class PaginatedDiscoveryAdapter(BaseAdapter):
    """Common bounded, rate-limited fetch loop for public HTML result boards."""

    adapter_name = "paginated_discovery"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._last_page = 1
        self._page_size = 1
        self._listing_count = 0
        self._advertised_count: int | None = None

    def _page_url(self, page: int) -> str:
        parts = urlsplit(self.source.endpoint or "")
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["page"] = str(page)
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

    async def _get_page(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        for attempt in range(3):
            try:
                response = await client.get(url, timeout=30.0)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        "retryable response", request=response.request, response=response
                    )
                response.raise_for_status()
                return response
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                if attempt == 2:
                    raise AdapterError(str(exc)) from exc
                await asyncio.sleep((2**attempt) + random.random() / 4)
        raise AdapterError("No paginated board response received")

    async def fetch(self, *, check_robots: bool = True) -> SourceFetchResult:
        first = await super().fetch(check_robots=check_robots)
        if first.health.status == SourceHealthStatus.FAILED:
            return first
        last_page = self._last_page
        maximum_pages = last_page
        if self.source.result_cap:
            maximum_pages = min(
                last_page,
                max(1, (self.source.result_cap + self._page_size - 1) // self._page_size),
            )
        roles = list(first.roles)
        digest = hashlib.sha256((first.health.content_hash or "").encode())
        pages_scanned = 1
        client = self._client or httpx.AsyncClient(
            headers={"User-Agent": "LondonOpportunityRadar/0.1 (+public research tracker)"},
            follow_redirects=True,
        )
        owns_client = self._client is None
        try:
            for page in range(2, maximum_pages + 1):
                await asyncio.sleep(60 / self.source.requests_per_minute)
                response = await self._get_page(client, self._page_url(page))
                digest.update(response.content)
                roles.extend(self.parse(response.content))
                pages_scanned += 1
            unique = {role.source_identifier: role for role in roles}
            roles = list(unique.values())
            capped = maximum_pages < last_page
            advertised_coverage_ok = self._advertised_count is None or len(roles) >= max(
                1, self._advertised_count - 1
            )
            parser_ok = len(roles) >= self.source.expected_min_items and advertised_coverage_ok
            return SourceFetchResult(
                roles=roles,
                health=first.health.model_copy(
                    update={
                        "status": (
                            SourceHealthStatus.HEALTHY
                            if parser_ok and not capped
                            else SourceHealthStatus.DEGRADED
                        ),
                        "item_count": len(roles),
                        "listing_count": len(roles),
                        "candidate_count": len(roles),
                        "pages_scanned": pages_scanned,
                        "capped": capped,
                        "parser_ok": parser_ok,
                        "content_hash": digest.hexdigest(),
                        "message": (
                            f"Scanned {len(roles)} live listings across {pages_scanned} "
                            f"page{'s' if pages_scanned != 1 else ''}"
                            + (
                                f" of {self._advertised_count} advertised"
                                + (
                                    " (one-result live pagination drift)."
                                    if len(roles) == self._advertised_count - 1
                                    else "."
                                )
                                if self._advertised_count is not None
                                else "."
                            )
                        ),
                    }
                ),
            )
        except (httpx.HTTPError, AdapterError, ValueError) as exc:
            return SourceFetchResult(
                roles=[],
                health=SourceHealth(
                    source_id=self.source.id,
                    status=SourceHealthStatus.FAILED,
                    checked_at=datetime.now(UTC),
                    parser_ok=False,
                    message=f"Paginated discovery scan failed: {exc}",
                ),
            )
        finally:
            if owns_client:
                await client.aclose()


class CharityJobAdapter(PaginatedDiscoveryAdapter):
    """Scan every current London paid-job result page on CharityJob."""

    adapter_name = "charityjob"
    _article_pattern = re.compile(
        r'<article[^>]+job-id="(\d+)"[^>]*>(.*?)</article>', re.IGNORECASE | re.DOTALL
    )

    def parse(self, payload: bytes) -> list[RawRole]:
        text = payload.decode(errors="replace")
        state = re.search(r"'search_parameters':\s*(\{.*?\})\s*\}\);", text, re.DOTALL)
        if state:
            try:
                metadata = json.loads(state.group(1))
                if self._advertised_count is None:
                    self._last_page = max(1, int(metadata.get("total_pages", 1)))
                    self._advertised_count = int(metadata.get("total_count", 0)) or None
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise AdapterError(f"CharityJob search metadata is invalid: {exc}") from exc
        else:
            page_match = re.search(r"Page\s+\d+\s+of\s+(\d+)", text, re.I)
            if not page_match:
                raise AdapterError("CharityJob pagination metadata was not found")
            if self._advertised_count is None:
                self._last_page = int(page_match.group(1))

        roles: list[RawRole] = []
        for identifier, block in self._article_pattern.findall(text):
            title_match = re.search(
                r'<div class="job-title[^\"]*">.*?<a href="([^"]+)"[^>]*>(.*?)</a>',
                block,
                re.IGNORECASE | re.DOTALL,
            )
            employer_match = re.search(
                r'<a[^>]+title="([^"]+)"[^>]+class="job-card-logo"',
                block,
                re.IGNORECASE,
            )
            if not title_match:
                continue
            organisation = _class_content(block, "organisation")
            path_parts = urlsplit(unescape(title_match.group(1))).path.strip("/").split("/")
            employer_slug = path_parts[1] if len(path_parts) > 1 else ""
            title = clean_html(title_match.group(2))
            if not title and len(path_parts) > 2:
                title = path_parts[2].replace("-", " ").title()
            employer = clean_html(employer_match.group(1)) if employer_match else ""
            if not employer and employer_slug:
                slug_text = normalise_board_text(employer_slug)
                comma_positions = [index for index, char in enumerate(organisation) if char == ","]
                employer = next(
                    (
                        organisation[:index].strip()
                        for index in comma_positions
                        if normalise_board_text(organisation[:index]) == slug_text
                    ),
                    employer_slug.replace("-", " ").title(),
                )
            if not employer:
                employer = (
                    path_parts[1].replace("-", " ").title()
                    if len(path_parts) > 1
                    else "Employer not stated"
                )
            location = organisation
            if organisation.casefold().startswith(f"{employer},".casefold()):
                location = organisation[len(employer) + 1 :].strip()
            elif normalise_board_text(organisation) == normalise_board_text(employer):
                location = "London (board search filter)"
            if normalise_board_text(location) == "remote":
                location = "Remote within the UK"
            salary = _class_content(block, "job-summary-item") or None
            if salary:
                salary = re.sub(r"^[•\s]+", "", salary).strip()
            posted = _class_content(block, "posted-item")
            roles.append(
                self.role(
                    identifier=identifier,
                    employer=employer,
                    title=title,
                    url=unescape(title_match.group(1)),
                    location=location or "London",
                    location_type=(
                        LocationType.REMOTE_UK
                        if "remote within" in location.casefold()
                        else LocationType.UNKNOWN
                    ),
                    description=(
                        "Paid CharityJob listing. Open the listing to verify experience, "
                        "study-stage and right-to-work requirements."
                    ),
                    published_date=_relative_posted_date(posted),
                    salary=salary,
                    paid=True if salary and "£" in salary else None,
                    paid_evidence=salary,
                    listing_publisher=self.source.canonical_name,
                    source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
                    organisation_type="charity",
                )
            )
        roles = list({role.source_identifier: role for role in roles}.values())
        self._page_size = max(1, len(roles))
        self._listing_count = len(roles)
        if not roles and "job-card-wrapper" in text:
            raise AdapterError("CharityJob cards were present but none could be parsed")
        return roles


class NHSJobsAdapter(PaginatedDiscoveryAdapter):
    """Scan the complete NHS Jobs London result set without opening every detail page."""

    adapter_name = "nhs_jobs"
    _item_pattern = re.compile(
        r'<li class="nhsuk-list-panel search-result[^>]*data-test="search-result"[^>]*>'
        r'(.*?)(?=<li class="nhsuk-list-panel search-result|</ul>\s*<nav)',
        re.IGNORECASE | re.DOTALL,
    )

    @staticmethod
    def _label(block: str, label: str) -> str:
        match = re.search(
            rf'data-test="{re.escape(label)}".*?<strong[^>]*>(.*?)</strong>',
            block,
            re.IGNORECASE | re.DOTALL,
        )
        return clean_html(match.group(1)) if match else ""

    def parse(self, payload: bytes) -> list[RawRole]:
        text = payload.decode(errors="replace")
        page_match = re.search(r"Page\s+\d+\s+of\s+(\d+)", text, re.I)
        count_match = re.search(r"([\d,]+)\s+jobs found in London", text, re.I)
        if self._advertised_count is None:
            self._last_page = int(page_match.group(1)) if page_match else 1
            self._advertised_count = (
                int(count_match.group(1).replace(",", "")) if count_match else None
            )
        roles: list[RawRole] = []
        for block in self._item_pattern.findall(text):
            title_match = re.search(
                r'<a href="([^"]*?/candidate/jobadvert/([^?\"]+)[^"]*)"[^>]*'
                r'data-test="search-result-job-title"[^>]*>(.*?)</a>',
                block,
                re.IGNORECASE | re.DOTALL,
            )
            location_match = re.search(
                r'data-test="search-result-location".*?<h3[^>]*>\s*(.*?)\s*'
                r'<div class="location-font-size">\s*(.*?)\s*</div>',
                block,
                re.IGNORECASE | re.DOTALL,
            )
            if not title_match or not location_match:
                continue
            employer = clean_html(location_match.group(1))
            location = clean_html(location_match.group(2))
            if "london" not in normalise_board_text(location):
                location = f"{location}, London" if location else "London"
            salary = self._label(block, "search-result-salary") or None
            contract = self._label(block, "search-result-jobType")
            working = self._label(block, "search-result-workingPattern")
            roles.append(
                self.role(
                    identifier=title_match.group(2),
                    employer=employer,
                    title=clean_html(title_match.group(3)),
                    url=unescape(title_match.group(1)),
                    location=location,
                    description=". ".join(
                        value
                        for value in (
                            f"Contract: {contract}" if contract else "",
                            f"Working pattern: {working}" if working else "",
                            "Open the NHS listing to verify professional and experience requirements.",
                        )
                        if value
                    ),
                    published_date=parse_date(self._label(block, "search-result-publicationDate")),
                    deadline=parse_date(self._label(block, "search-result-closingDate")),
                    salary=salary,
                    paid=True if salary else None,
                    paid_evidence=salary,
                    listing_publisher=self.source.canonical_name,
                    source_authority=self.source.source_authority,
                    organisation_type="public_health",
                )
            )
        roles = list({role.source_identifier: role for role in roles}.values())
        self._page_size = max(1, len(roles))
        self._listing_count = len(roles)
        if not roles and 'data-test="search-result"' in text:
            raise AdapterError("NHS Jobs result cards were present but none could be parsed")
        return roles


class JobsAcUkAdapter(PaginatedDiscoveryAdapter):
    """Scan every current London listing on the jobs.ac.uk public search."""

    adapter_name = "jobs_ac_uk"

    def _page_url(self, page: int) -> str:
        parts = urlsplit(self.source.endpoint or "")
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update({"sortOrder": "1", "pageSize": "25", "startIndex": str(1 + 25 * (page - 1))})
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment)
        )

    def parse(self, payload: bytes) -> list[RawRole]:
        text = payload.decode(errors="replace")
        count_match = re.search(r'<strong class="job-count">\s*([\d,]+)', text, re.I)
        if not count_match:
            raise AdapterError("jobs.ac.uk result count was not found")
        total = int(count_match.group(1).replace(",", ""))
        segments = re.split(r'(?=<div class="j-search-result__result\b)', text)
        roles: list[RawRole] = []
        for block in segments:
            identifier_match = re.search(r'data-advert-id="(\d+)"', block)
            title_match = re.search(
                r'<a href="(/job/[^\"]+)">\s*(.*?)\s*</a>',
                block,
                re.IGNORECASE | re.DOTALL,
            )
            employer_match = re.search(
                r'class="j-search-result__employer"[^>]*>\s*<b>(.*?)</b>',
                block,
                re.IGNORECASE | re.DOTALL,
            )
            location_match = re.search(
                r"</div>\s*<div>Location:\s*(.*?)\s*</div>",
                block,
                re.IGNORECASE | re.DOTALL,
            )
            if not identifier_match or not title_match or not employer_match or not location_match:
                continue
            department = _class_content(block, "j-search-result__department")
            salary_match = re.search(
                r'class="j-search-result__info"[^>]*>\s*<strong>Salary:\s*</strong>(.*?)</div>',
                block,
                re.IGNORECASE | re.DOTALL,
            )
            placed_match = re.search(
                r"<strong>Date Placed:\s*</strong>\s*([^<]+)", block, re.IGNORECASE
            )
            deadline_match = re.search(
                r'class="j-search-result__date--blue[^\"]*">\s*([^<]+)',
                block,
                re.IGNORECASE,
            )
            salary = clean_html(salary_match.group(1)) if salary_match else None
            roles.append(
                self.role(
                    identifier=identifier_match.group(1),
                    employer=clean_html(employer_match.group(1)),
                    title=clean_html(title_match.group(2)),
                    url=unescape(title_match.group(1)),
                    location=clean_html(location_match.group(1)),
                    description=". ".join(
                        value
                        for value in (
                            f"Department: {department}" if department else "",
                            "Open the jobs.ac.uk listing to verify qualifications and experience.",
                        )
                        if value
                    ),
                    published_date=(
                        _yearless_date(placed_match.group(1), future=False)
                        if placed_match
                        else None
                    ),
                    deadline=(
                        _yearless_date(deadline_match.group(1), future=True)
                        if deadline_match
                        else None
                    ),
                    salary=salary,
                    paid=True if salary else None,
                    paid_evidence=salary,
                    listing_publisher=self.source.canonical_name,
                    source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
                    organisation_type="higher_education",
                )
            )
        roles = list({role.source_identifier: role for role in roles}.values())
        self._page_size = max(1, len(roles))
        if self._advertised_count is None:
            self._advertised_count = total
            self._last_page = max(1, (total + self._page_size - 1) // self._page_size)
        self._listing_count = len(roles)
        if not roles and "j-search-result__result" in text:
            raise AdapterError("jobs.ac.uk cards were present but none could be parsed")
        return roles


class TargetJobsAdapter(BaseAdapter):
    """Scan targetjobs' public, robots-allowed London early-career search service.

    The targetjobs page loads results from this JSON service in the browser.  We use the same
    documented page filters (London, currently open and early-career opportunity types), retain
    the actual employer, and validate the complete result count before publishing possible leads.
    """

    adapter_name = "targetjobs"
    _page_size = 100
    _fields = (
        "nid",
        "uuid",
        "abstract",
        "title",
        "location",
        "parent_organisation_title",
        "type",
        "body",
        "url",
        "application_url",
        "application_deadline_date",
        "opportunity_start_date",
        "salary_range",
        "salary_upper",
        "salary_lower",
        "currency",
        "regions",
        "degree_requirements",
        "degree_subjects",
        "opportunity_type",
        "organisation_name",
        "source_organisation_name",
        "pre_register",
        "application_open",
        "free_job",
        "scraped_job",
        "external_id",
    )
    _opportunity_types = (
        "Internship",
        "Vacation scheme",
        "Insight programme",
        "Work experience",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._advertised_count: int | None = None

    def _request_body(self, offset: int) -> dict[str, object]:
        index_cutoff = datetime.now(UTC) - timedelta(minutes=10)
        return {
            "fields": self._fields,
            "keys": [""],
            "groupBy": None,
            "conditionGroup": {
                "conjunction": "AND",
                "groups": [
                    {
                        "conjunction": "OR",
                        "conditions": [
                            {
                                "name": "opportunity_type",
                                "value": value,
                                "operator": "=",
                            }
                            for value in self._opportunity_types
                        ],
                    },
                    {
                        "conjunction": "OR",
                        "conditions": [{"name": "city", "value": "London", "operator": "="}],
                    },
                    {
                        "conjunction": "OR",
                        "conditions": [{"name": "type", "value": "opportunity", "operator": "="}],
                    },
                    {
                        "conjunction": "OR",
                        "conditions": [
                            {
                                "name": "application_deadline_date",
                                "operator": "NOT BETWEEN",
                                "value": ["0", "NOW"],
                            }
                        ],
                    },
                ],
            },
            "facets": None,
            "sort": None,
            "conditions": [
                {
                    "name": "last_published",
                    "value": index_cutoff.isoformat().replace("+00:00", "Z"),
                    "operator": "<=",
                }
            ],
            "limit": self._page_size,
            "offset": offset,
            "includePromoted": False,
        }

    @staticmethod
    def _salary(document: dict[str, Any]) -> str | None:
        salary = document.get("salary")
        if not isinstance(salary, dict):
            return None
        currency = str(salary.get("currency") or "").strip()
        lower = str(salary.get("lower") or "").strip()
        upper = str(salary.get("upper") or "").strip()
        amount = (
            lower
            if lower and lower == upper
            else "-".join(value for value in (lower, upper) if value)
        )
        return " ".join(value for value in (currency, amount) if value) or None

    @staticmethod
    def _employer(document: dict[str, Any], application_url: str) -> str:
        application_host = urlsplit(application_url).netloc.casefold()
        verified_tenant_names = {
            "jd.wd103.myworkdayjobs.com": "Jingdong Retail (UK) Limited",
            "cc.wd3.myworkdayjobs.com": "CHANEL",
        }
        if application_host in verified_tenant_names:
            return verified_tenant_names[application_host]
        organisation = document.get("organisation")
        organisation_title = (
            str(organisation.get("title") or "") if isinstance(organisation, dict) else ""
        )
        candidate = next(
            (
                str(value).strip()
                for value in (
                    organisation_title,
                    document.get("parentOrganisationTitle"),
                    document.get("organisationName"),
                    document.get("sourceOrganisationName"),
                )
                if value and str(value).strip()
            ),
            "Employer not stated",
        )
        verified_brand_names = {
            "blackrock": "BlackRock",
            "gp bullhound": "GP Bullhound",
            "house of cb": "House of CB",
            "me em": "ME+EM",
            "onetrust": "OneTrust",
        }
        return verified_brand_names.get(normalise_board_text(candidate), candidate)

    def parse(self, payload: bytes) -> list[RawRole]:
        data = json_payload(payload)
        search = data.get("search") if isinstance(data, dict) else None
        if not isinstance(search, dict):
            raise AdapterError("targetjobs response has no search result")
        documents = search.get("documents")
        count = search.get("result_count")
        if not isinstance(documents, list) or not isinstance(count, int):
            raise AdapterError("targetjobs response is missing documents or result_count")
        if self._advertised_count is None:
            self._advertised_count = count

        roles: list[RawRole] = []
        for item in documents:
            if not isinstance(item, dict):
                continue
            title = clean_html(str(item.get("title") or ""))
            path = str(item.get("path") or item.get("url") or "")
            identifier = str(item.get("uuid") or item.get("nid") or item.get("externalId") or "")
            if not title or not path or not identifier:
                continue
            source_url = urljoin("https://targetjobs.co.uk", path)
            application_url = str(item.get("applicationUrl") or source_url)
            if urlsplit(application_url).scheme not in {"http", "https"}:
                application_url = source_url
            salary = self._salary(item)
            degree_requirements = item.get("degreeRequirements")
            if isinstance(degree_requirements, list):
                eligibility_text = "; ".join(
                    clean_html(str(value)) for value in degree_requirements
                )
            else:
                eligibility_text = clean_html(str(degree_requirements or ""))
            roles.append(
                self.role(
                    identifier=identifier,
                    employer=self._employer(item, application_url),
                    title=title,
                    url=source_url,
                    application_url=application_url,
                    location=clean_html(str(item.get("location") or "London")),
                    description=clean_html(str(item.get("body") or item.get("abstract") or "")),
                    deadline=parse_date(item.get("applicationDeadline")),
                    programme_start=parse_date(item.get("opportunityStartDate")),
                    eligibility_text=eligibility_text,
                    salary=salary,
                    paid=True if salary else None,
                    paid_evidence=salary,
                    explicitly_closed=not bool(item.get("applicationOpen", True)),
                    listing_publisher=self.source.canonical_name,
                    source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
                    organisation_type="corporate",
                    application_method=(
                        "Apply on the employer site linked from targetjobs"
                        if application_url != source_url
                        else "Open the targetjobs listing and follow its application instructions"
                    ),
                )
            )
        if documents and not roles:
            raise AdapterError("targetjobs documents were present but none could be parsed")
        return roles

    async def _post_page(self, client: httpx.AsyncClient, offset: int) -> httpx.Response:
        headers = {
            "Origin": "https://targetjobs.co.uk",
            "Referer": self.source.careers_url or "https://targetjobs.co.uk/internships/london",
            "X-Host": "users.targetjobs.co.uk",
        }
        for attempt in range(3):
            try:
                response = await client.post(
                    self.source.endpoint or "",
                    json=self._request_body(offset),
                    headers=headers,
                    timeout=30.0,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        "retryable response", request=response.request, response=response
                    )
                response.raise_for_status()
                return response
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                if attempt == 2:
                    raise AdapterError(str(exc)) from exc
                await asyncio.sleep((2**attempt) + random.random() / 4)
        raise AdapterError("No targetjobs response received")

    async def fetch(self, *, check_robots: bool = True) -> SourceFetchResult:
        if not self.source.endpoint:
            raise AdapterError(f"Source {self.source.id} has no endpoint")
        client = self._client or httpx.AsyncClient(
            headers={"User-Agent": "LondonOpportunityRadar/0.1 (+public research tracker)"},
            follow_redirects=True,
        )
        owns_client = self._client is None
        checked_at = datetime.now(UTC)
        digest = hashlib.sha256()
        pages_scanned = 0
        roles: list[RawRole] = []
        try:
            if check_robots and not await self._robots_allowed(client, self.source.endpoint):
                raise AdapterError(f"robots.txt disallows {self.source.endpoint}")
            offset = 0
            while True:
                if pages_scanned:
                    await asyncio.sleep(60 / self.source.requests_per_minute)
                response = await self._post_page(client, offset)
                digest.update(response.content)
                page_roles = self.parse(response.content)
                roles.extend(page_roles)
                pages_scanned += 1
                advertised = self._advertised_count or 0
                scan_limit = min(advertised, self.source.result_cap or advertised)
                offset += self._page_size
                if offset >= scan_limit:
                    break

            roles = list({role.source_identifier: role for role in roles}.values())
            advertised = self._advertised_count or 0
            cap = self.source.result_cap or advertised
            capped = advertised > cap
            expected = min(advertised, cap)
            parser_ok = len(roles) >= self.source.expected_min_items and len(roles) >= max(
                0, expected - 1
            )
            status = (
                SourceHealthStatus.HEALTHY
                if parser_ok and not capped
                else SourceHealthStatus.DEGRADED
            )
            return SourceFetchResult(
                roles=roles,
                health=SourceHealth(
                    source_id=self.source.id,
                    status=status,
                    checked_at=checked_at,
                    last_success_at=checked_at,
                    item_count=len(roles),
                    listing_count=len(roles),
                    candidate_count=len(roles),
                    pages_scanned=pages_scanned,
                    capped=capped,
                    parser_ok=parser_ok,
                    content_hash=digest.hexdigest(),
                    message=(
                        f"Scanned {len(roles)} open London early-career listings across "
                        f"{pages_scanned} page{'s' if pages_scanned != 1 else ''} of "
                        f"{advertised} advertised."
                    ),
                ),
            )
        except (httpx.HTTPError, AdapterError, ValueError) as exc:
            return SourceFetchResult(
                roles=[],
                health=SourceHealth(
                    source_id=self.source.id,
                    status=SourceHealthStatus.FAILED,
                    checked_at=checked_at,
                    parser_ok=False,
                    message=f"targetjobs scan failed: {exc}",
                ),
            )
        finally:
            if owns_client:
                await client.aclose()


class HigherinAdapter(BaseAdapter):
    """Parse Higherin's server-rendered London internship search state.

    Higherin is a discovery source rather than eligibility authority. Its records feed the
    possible-roles layer and retain the actual employer instead of being attributed to the board.
    """

    adapter_name = "higherin"
    _state_pattern = re.compile(
        r"window\.__RMP_SEARCH_RESULTS_INITIAL_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>",
        re.DOTALL,
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._last_page = 1

    def _state(self, payload: bytes) -> dict[str, Any]:
        try:
            text = payload.decode()
        except UnicodeDecodeError as exc:
            raise AdapterError("Higherin HTML is not UTF-8") from exc
        match = self._state_pattern.search(text)
        if not match:
            raise AdapterError(
                "Higherin search state was not found; page structure may have changed"
            )
        try:
            state = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise AdapterError(f"Higherin search state is invalid JSON: {exc}") from exc
        if not isinstance(state, dict) or not isinstance(state.get("data"), list):
            raise AdapterError("Higherin search state has no data list")
        pagination = state.get("meta", {}).get("pagination", {})
        self._last_page = max(1, int(pagination.get("lastPage", 1)))
        return state

    def parse(self, payload: bytes) -> list[RawRole]:
        state = self._state(payload)
        roles: list[RawRole] = []
        for job in state["data"]:
            if not isinstance(job, dict) or not job.get("jobTitle") or not job.get("url"):
                continue
            salary = str(job.get("salary") or "").strip() or None
            relevant_for = str(job.get("relevantFor") or "").strip()
            job_type = str(job.get("jobTypeName") or "").strip()
            description = ". ".join(item for item in (job_type, relevant_for) if item)
            employer = str(job.get("companyName") or "Employer not stated").strip()
            roles.append(
                self.role(
                    identifier=str(job.get("jobId") or job.get("id") or job["url"]),
                    employer=employer,
                    title=str(job["jobTitle"]),
                    url=str(job["url"]),
                    location=str(
                        job.get("jobLocationNamesTrimmed")
                        or job.get("jobLocationNames")
                        or "Unknown"
                    ),
                    description=description,
                    eligibility_text=(f"Relevant for: {relevant_for}" if relevant_for else ""),
                    deadline=parse_date(job.get("deadline")),
                    programme_start=parse_date(job.get("employmentStartDate")),
                    salary=salary,
                    paid=False if salary and "unpaid" in salary.casefold() else None,
                    paid_evidence=salary,
                    listing_publisher=self.source.canonical_name,
                    source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
                    organisation_type="corporate",
                )
            )
        return roles

    @staticmethod
    def _page_url(url: str, page: int) -> str:
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["page"] = str(page)
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )

    async def _get_page(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        for attempt in range(3):
            try:
                response = await client.get(url, timeout=25.0)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        "retryable response", request=response.request, response=response
                    )
                response.raise_for_status()
                return response
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                if attempt == 2:
                    raise AdapterError(str(exc)) from exc
                await asyncio.sleep((2**attempt) + random.random() / 4)
        raise AdapterError("No Higherin response received")

    async def fetch(self, *, check_robots: bool = True) -> SourceFetchResult:
        first = await super().fetch(check_robots=check_robots)
        if first.health.status == SourceHealthStatus.FAILED:
            return first
        client = self._client or httpx.AsyncClient(
            headers={"User-Agent": "LondonOpportunityRadar/0.1 (+public research tracker)"},
            follow_redirects=True,
        )
        owns_client = self._client is None
        roles = list(first.roles)
        digest = hashlib.sha256((first.health.content_hash or "").encode())
        pages_scanned = 1
        try:
            maximum_pages = self._last_page
            if self.source.result_cap:
                maximum_pages = min(
                    maximum_pages,
                    max(1, (self.source.result_cap + max(len(roles), 1) - 1) // max(len(roles), 1)),
                )
            for page in range(2, maximum_pages + 1):
                response = await self._get_page(
                    client, self._page_url(self.source.endpoint or "", page)
                )
                digest.update(response.content)
                page_roles = self.parse(response.content)
                roles.extend(page_roles)
                pages_scanned += 1
            unique = {role.source_identifier: role for role in roles}
            roles = list(unique.values())
            capped = maximum_pages < self._last_page
            parser_ok = len(roles) >= self.source.expected_min_items
            return SourceFetchResult(
                roles=roles,
                health=first.health.model_copy(
                    update={
                        "status": (
                            SourceHealthStatus.HEALTHY
                            if parser_ok and not capped
                            else SourceHealthStatus.DEGRADED
                        ),
                        "item_count": len(roles),
                        "listing_count": len(roles),
                        "candidate_count": len(roles),
                        "pages_scanned": pages_scanned,
                        "capped": capped,
                        "parser_ok": parser_ok,
                        "content_hash": digest.hexdigest(),
                        "message": (
                            f"Scanned {len(roles)} London internship listings across "
                            f"{pages_scanned} page{'s' if pages_scanned != 1 else ''}."
                        ),
                    }
                ),
            )
        except (httpx.HTTPError, AdapterError, ValueError) as exc:
            return SourceFetchResult(
                roles=[],
                health=SourceHealth(
                    source_id=self.source.id,
                    status=SourceHealthStatus.FAILED,
                    checked_at=datetime.now(UTC),
                    parser_ok=False,
                    message=f"Higherin pagination failed: {exc}",
                ),
            )
        finally:
            if owns_client:
                await client.aclose()


class _HiddenInputParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "input" and values.get("name") and values.get("type", "").casefold() == "hidden":
            self.values[values["name"]] = values.get("value", "")


class W4MPAdapter(BaseAdapter):
    """Scrape every page of W4MP's current-job search without inventing employer data."""

    adapter_name = "w4mp"
    _article_pattern = re.compile(
        r'<article[^>]*class="[^"]*job-advert[^"]*"[^>]*>(.*?)</article>',
        re.IGNORECASE | re.DOTALL,
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._page_targets: list[str] = []
        self._hidden_inputs: dict[str, str] = {}
        self._listing_count = 0

    @staticmethod
    def _property(block: str, name: str) -> str:
        match = re.search(
            rf'<[^>]+itemprop="{re.escape(name)}"[^>]*>(.*?)</[^>]+>',
            block,
            re.IGNORECASE | re.DOTALL,
        )
        return clean_html(match.group(1)) if match else ""

    def _pagination_state(self, payload: bytes) -> None:
        text = unescape(payload.decode(errors="replace"))
        targets: list[str] = []
        seen_labels: set[int] = set()
        for target, label in re.findall(
            r'href="javascript:__doPostBack\(\'([^\']+)\',\'\'\)">\s*(\d+)\s*</a>',
            text,
            re.IGNORECASE,
        ):
            page = int(label)
            if page > 1 and page not in seen_labels:
                targets.append(target)
                seen_labels.add(page)
        parser = _HiddenInputParser()
        parser.feed(payload.decode(errors="replace"))
        self._page_targets = targets
        self._hidden_inputs = parser.values

    def _all_listings(self, payload: bytes) -> list[RawRole]:
        try:
            text = payload.decode()
        except UnicodeDecodeError as exc:
            raise AdapterError("W4MP HTML is not UTF-8") from exc
        roles: list[RawRole] = []
        for block in self._article_pattern.findall(text):
            url_match = re.search(r'href="(JobDetails\.aspx\?jobid=(\d+))"', block, re.I)
            title = self._property(block, "title")
            employer = self._property(block, "hiringOrganization")
            if not url_match or not title or not employer:
                continue
            location = re.sub(
                r"^Location:\s*", "", self._property(block, "jobLocation"), flags=re.I
            )
            salary = re.sub(r"^Salary:\s*", "", self._property(block, "baseSalary"), flags=re.I)
            dates = clean_html(block)
            deadline_match = re.search(r"closes on\s+([0-9]{1,2}\s+[A-Za-z]+\s+\d{4})", dates, re.I)
            is_mp = bool(re.search(r"\bMP\b|parliament", employer, re.I))
            roles.append(
                self.role(
                    identifier=url_match.group(2),
                    employer=employer,
                    title=title,
                    url=url_match.group(1),
                    location=location or "Unknown",
                    description=(
                        f"Current W4MP listing for {title} at {employer}. "
                        "Open the listing to verify the full criteria before applying."
                    ),
                    published_date=parse_date(self._property(block, "datePosted")),
                    deadline=parse_date(deadline_match.group(1)) if deadline_match else None,
                    salary=salary or None,
                    paid=(
                        False
                        if salary and "unpaid" in salary.casefold()
                        else True
                        if salary
                        else None
                    ),
                    paid_evidence=salary or None,
                    listing_publisher=self.source.canonical_name,
                    named_office_or_mp=employer if is_mp else None,
                    application_method="Follow the application instructions on the W4MP listing",
                    source_authority=SourceAuthority.TRUSTED_SECTOR_BOARD,
                    organisation_type=(
                        "parliamentary_office" if is_mp else "politics_public_affairs"
                    ),
                )
            )
        return roles

    def parse(self, payload: bytes) -> list[RawRole]:
        self._pagination_state(payload)
        listings = self._all_listings(payload)
        self._listing_count = len(listings)
        return listings

    async def _post_page(
        self, client: httpx.AsyncClient, target: str, form: dict[str, str]
    ) -> httpx.Response:
        data = {**form, "__EVENTTARGET": target, "__EVENTARGUMENT": ""}
        for attempt in range(3):
            try:
                response = await client.post(self.source.endpoint or "", data=data, timeout=25.0)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        "retryable response", request=response.request, response=response
                    )
                response.raise_for_status()
                return response
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                if attempt == 2:
                    raise AdapterError(str(exc)) from exc
                await asyncio.sleep((2**attempt) + random.random() / 4)
        raise AdapterError("No W4MP response received")

    async def fetch(self, *, check_robots: bool = True) -> SourceFetchResult:
        first = await super().fetch(check_robots=check_robots)
        if first.health.status == SourceHealthStatus.FAILED:
            return first
        first_targets = list(self._page_targets)
        first_form = dict(self._hidden_inputs)
        candidate_roles = list(first.roles)
        listing_count = self._listing_count
        digest = hashlib.sha256((first.health.content_hash or "").encode())
        pages_scanned = 1
        client = self._client or httpx.AsyncClient(
            headers={"User-Agent": "LondonOpportunityRadar/0.1 (+public research tracker)"},
            follow_redirects=True,
        )
        owns_client = self._client is None
        try:
            maximum_targets = first_targets
            for target in maximum_targets:
                response = await self._post_page(client, target, first_form)
                digest.update(response.content)
                page_listings = self._all_listings(response.content)
                listing_count += len(page_listings)
                candidate_roles.extend(page_listings)
                pages_scanned += 1
            unique = {role.source_identifier: role for role in candidate_roles}
            roles = list(unique.values())
            listing_count = len(roles)
            capped = bool(self.source.result_cap and listing_count >= self.source.result_cap)
            parser_ok = listing_count >= self.source.expected_min_items
            return SourceFetchResult(
                roles=roles,
                health=first.health.model_copy(
                    update={
                        "status": (
                            SourceHealthStatus.HEALTHY
                            if parser_ok and not capped
                            else SourceHealthStatus.DEGRADED
                        ),
                        "item_count": len(roles),
                        "listing_count": listing_count,
                        "candidate_count": len(roles),
                        "pages_scanned": pages_scanned,
                        "capped": capped,
                        "parser_ok": parser_ok,
                        "content_hash": digest.hexdigest(),
                        "message": (
                            f"Scanned {listing_count} live listings across {pages_scanned} pages; "
                            f"passed {len(roles)} unique records to central classification."
                        ),
                    }
                ),
            )
        except (httpx.HTTPError, AdapterError, ValueError) as exc:
            return SourceFetchResult(
                roles=[],
                health=SourceHealth(
                    source_id=self.source.id,
                    status=SourceHealthStatus.FAILED,
                    checked_at=datetime.now(UTC),
                    parser_ok=False,
                    message=f"W4MP pagination failed: {exc}",
                ),
            )
        finally:
            if owns_client:
                await client.aclose()


def normalise_board_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


class CuratedYamlAdapter(BaseAdapter):
    adapter_name = "curated_yaml"

    def parse(self, payload: bytes) -> list[RawRole]:
        import yaml

        data = yaml.safe_load(payload)
        if not isinstance(data, dict) or not isinstance(data.get("roles"), list):
            raise AdapterError("Curated YAML must contain a roles list")
        return [RawRole.model_validate(item) for item in data["roles"]]

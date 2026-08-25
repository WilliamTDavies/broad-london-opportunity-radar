from __future__ import annotations

import asyncio
import base64
import hashlib
import math
import os
import random
import re
from contextlib import suppress
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from opportunity_radar.adapters.base import (
    USER_AGENT,
    AdapterError,
    BaseAdapter,
    SourceFetchResult,
)
from opportunity_radar.adapters.parsers import clean_html, json_payload, parse_date
from opportunity_radar.models import (
    LocationType,
    RawRole,
    SourceAuthority,
    SourceHealth,
    SourceHealthStatus,
)


def _configuration(source_body: dict[str, Any] | None) -> dict[str, Any]:
    return source_body or {}


EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def _public_description(value: str) -> str:
    """Do not republish personal contact addresses scraped from vacancy copy."""

    return re.sub(r"\s+", " ", EMAIL_PATTERN.sub("[contact email on source]", value)).strip()


def _reed_listing_identity(employer: str, title: str) -> tuple[str, str]:
    """Recover the hiring firm when a syndicator is supplied as Reed's employer."""

    if re.sub(r"[^a-z0-9]+", "", employer.casefold()) != "efinancialcareers":
        return employer, title
    parts = re.split(r"\s+[\u2013\u2014-]\s+", title)
    candidate = parts[-1].strip()
    folded = candidate.casefold()
    firm_signals = ("capital", "investments", "partners", "group", "& co", "bank")
    role_signals = ("intern", "analyst", "associate", "manager", "director", "officer")
    if (
        1 <= len(candidate.split()) <= 7
        and any(signal in folded for signal in firm_signals)
        and not any(signal in folded for signal in role_signals)
    ):
        return candidate, " - ".join(parts[:-1]).strip()
    return employer, title


def _positive_integer(configuration: dict[str, Any], key: str, default: int) -> int:
    value = configuration.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise AdapterError(f"Search configuration '{key}' must be a positive integer")
    return value


def _queries(configuration: dict[str, Any]) -> list[str]:
    value = configuration.get("queries")
    if not isinstance(value, list) or not value:
        raise AdapterError("Search configuration needs a non-empty queries list")
    queries = [str(item).strip() for item in value if str(item).strip()]
    if not queries:
        raise AdapterError("Search configuration has no usable query strings")
    return list(dict.fromkeys(queries))


async def _retry_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    source_id: str,
    params: dict[str, str | int] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """GET with bounded retries without putting credentials into an error message."""

    for attempt in range(3):
        try:
            response = await client.get(url, params=params, headers=headers, timeout=30.0)
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    "retryable response", request=response.request, response=response
                )
            if response.status_code >= 400:
                raise AdapterError(
                    f"{source_id} returned HTTP {response.status_code}; response body omitted"
                )
            return response
        except AdapterError:
            raise
        except (httpx.RequestError, httpx.HTTPStatusError) as exc:
            if attempt == 2:
                raise AdapterError(
                    f"{source_id} request failed after three attempts ({type(exc).__name__})"
                ) from exc
            await asyncio.sleep((2**attempt) + random.random() / 4)
    raise AdapterError(f"{source_id} returned no response")


def _location_type(*values: str) -> LocationType:
    text = " ".join(values).casefold()
    if "hybrid" in text:
        return LocationType.HYBRID
    if "remote" in text or "homeworking" in text or "home working" in text:
        return LocationType.REMOTE_UK
    if "on-site" in text or "onsite" in text or "office based" in text:
        return LocationType.ONSITE
    if "multiple locations" in text or "various locations" in text:
        return LocationType.MULTI_LOCATION
    return LocationType.UNKNOWN


def _advertised_organisation_type(employer: str, title: str, description: str) -> str:
    """Infer only broad safety contexts used by the possible-role exclusion rules."""

    text = " ".join((employer, title, description)).casefold()
    if any(
        signal in text
        for signal in (
            "nhs",
            "hospital",
            "healthcare trust",
            "health care trust",
            "medical centre",
            "medical center",
        )
    ):
        return "public_health"
    if any(signal in employer.casefold() for signal in ("university", "college", "school of")):
        return "higher_education"
    if any(
        signal in employer.casefold()
        for signal in (
            "ministry of",
            "department for",
            "city council",
            "borough council",
            "civil service",
        )
    ):
        return "government"
    return "corporate"


def _salary_range(
    minimum: object,
    maximum: object,
    *,
    currency: str = "GBP",
) -> str | None:
    values: list[float] = []
    for value in (minimum, maximum):
        if isinstance(value, int | float) and not isinstance(value, bool):
            values.append(float(value))
        elif isinstance(value, str):
            with suppress(ValueError):
                values.append(float(value.replace(",", "")))
    if not values:
        return None
    prefix = "£" if currency.upper() == "GBP" else f"{currency.upper()} "
    if len(values) == 1 or values[0] == values[-1]:
        return f"{prefix}{values[0]:,.0f}"
    return f"{prefix}{values[0]:,.0f}-{prefix}{values[-1]:,.0f}"


def _credential_failure(source_id: str, variable_names: tuple[str, ...]) -> SourceFetchResult:
    checked_at = datetime.now(UTC)
    names = ", ".join(variable_names)
    return SourceFetchResult(
        roles=[],
        health=SourceHealth(
            source_id=source_id,
            status=SourceHealthStatus.FAILED,
            checked_at=checked_at,
            pages_scanned=0,
            parser_ok=False,
            message=f"Credentialed source not scanned: set {names}",
        ),
    )


def _result_health(
    *,
    source_id: str,
    checked_at: datetime,
    roles: list[RawRole],
    listings_seen: int,
    pages_scanned: int,
    digest: hashlib._Hash,
    expected_minimum: int,
    query_count: int,
    failures: list[str],
    capped: bool,
) -> SourceFetchResult:
    parser_ok = pages_scanned > 0 and len(roles) >= expected_minimum
    if pages_scanned == 0:
        status = SourceHealthStatus.FAILED
    elif parser_ok and not failures and not capped:
        status = SourceHealthStatus.HEALTHY
    else:
        status = SourceHealthStatus.DEGRADED
    details = [
        f"Scanned {query_count} query shards across {pages_scanned} pages",
        f"found {len(roles)} unique roles from {listings_seen} result appearances",
    ]
    if capped:
        details.append("at least one query or the combined result set reached its safety cap")
    if failures:
        details.append(f"{len(failures)} query/page requests failed")
    if not parser_ok:
        details.append(f"fewer than the configured minimum of {expected_minimum} roles parsed")
    return SourceFetchResult(
        roles=roles,
        health=SourceHealth(
            source_id=source_id,
            status=status,
            checked_at=checked_at,
            last_success_at=checked_at if pages_scanned else None,
            item_count=len(roles),
            listing_count=listings_seen,
            candidate_count=len(roles),
            pages_scanned=pages_scanned,
            capped=capped,
            parser_ok=parser_ok,
            content_hash=digest.hexdigest() if pages_scanned else None,
            message="; ".join(details) + ".",
        ),
    )


class _WorkHubCardParser(HTMLParser):
    """Extract server-rendered cards without depending on Next.js flight data."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, Any]] = []
        self._card: dict[str, Any] | None = None
        self._card_div_depth = 0
        self._field: str | None = None
        self._field_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        test_id = values.get("data-testid", "")
        if tag == "div" and test_id.startswith("searchResultCard-"):
            self._card = {
                "id": test_id.removeprefix("searchResultCard-"),
                "title": [],
                "employer": [],
                "tags": [],
                "description": [],
                "salary": [],
                "all_text": [],
                "href": "",
            }
            self._card_div_depth = 1
            self._field = None
            self._field_depth = 0
            return
        if self._card is None:
            return
        if tag == "div":
            self._card_div_depth += 1
        if self._field is not None:
            self._field_depth += 1

        field: str | None = None
        if test_id.startswith("jobTitle-"):
            field = "title"
            self._card["href"] = values.get("href", "")
        elif test_id == "searchResultCardEmployer":
            field = "employer"
        elif test_id == "searchResultsCardTags":
            field = "tags"
        elif test_id == "searchResultCardJobDescription":
            field = "description"
        elif tag == "p" and "font-weight-bold" in values.get("class", ""):
            field = "salary"
        if field is not None:
            self._field = field
            self._field_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        if self._field is not None:
            self._field_depth -= 1
            if self._field_depth == 0:
                self._field = None
        if tag == "div":
            self._card_div_depth -= 1
            if self._card_div_depth == 0:
                self.cards.append(self._card)
                self._card = None
                self._field = None
                self._field_depth = 0

    def handle_data(self, data: str) -> None:
        if self._card is None:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        self._card["all_text"].append(text)
        if self._field is not None:
            self._card[self._field].append(text)


class WorkHubAdapter(BaseAdapter):
    """Search the official DWP Work Hub over a configurable early-career query matrix."""

    adapter_name = "work_hub"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._advertised_count = 0
        self._available_pages = 1

    def parse(self, payload: bytes) -> list[RawRole]:
        text = payload.decode(errors="replace")
        parser = _WorkHubCardParser()
        parser.feed(text)
        total_match = re.search(
            r"Showing results.*?\bof\s*<strong>([\d,]+)</strong>", text, re.I | re.S
        )
        self._advertised_count = int(total_match.group(1).replace(",", "")) if total_match else 0
        pages = [int(item) for item in re.findall(r'aria-label="Page\s+(\d+)"', text, re.I)]
        self._available_pages = max(pages, default=1)
        if not parser.cards and not re.search(
            r"Showing results|No jobs|0 jobs|did not match", text, re.I
        ):
            raise AdapterError("DWP Work Hub result-card structure changed")

        roles: list[RawRole] = []
        for card in parser.cards:
            identifier = str(card["id"])
            title = " ".join(card["title"]).strip()
            href = str(card["href"]).strip()
            employer_location = " ".join(card["employer"]).strip()
            if not identifier or not title or not href or not employer_location:
                continue
            employer = employer_location
            location = "Unknown"
            if " - " in employer_location:
                employer, location = employer_location.rsplit(" - ", 1)
            tags = " ".join(card["tags"]).strip()
            description = _public_description(" ".join(card["description"]))
            salary = " ".join(card["salary"]).strip() or None
            all_text = " ".join(card["all_text"])
            added = re.search(r"Added on\s+([0-9]{1,2}\s+[A-Za-z]+\s+\d{4})", all_text, re.I)
            roles.append(
                self.role(
                    identifier=identifier,
                    employer=employer.strip(),
                    title=title,
                    url=href,
                    location=location.strip() or "Unknown",
                    location_type=_location_type(location, tags),
                    description=". ".join(item for item in (description, tags) if item),
                    published_date=parse_date(added.group(1)) if added else None,
                    salary=salary,
                    paid=(
                        False
                        if salary and "unpaid" in salary.casefold()
                        else True
                        if salary and ("£" in salary or "salary" in salary.casefold())
                        else None
                    ),
                    paid_evidence=salary,
                    listing_publisher=self.source.canonical_name,
                    source_authority=SourceAuthority.OFFICIAL_GOVERNMENT_PORTAL,
                    organisation_type=_advertised_organisation_type(employer, title, description),
                )
            )
        if parser.cards and not roles:
            raise AdapterError("DWP Work Hub cards were present but no complete roles parsed")
        return roles

    async def fetch(self, *, check_robots: bool = True) -> SourceFetchResult:
        if not self.source.endpoint:
            raise AdapterError(f"Source {self.source.id} has no endpoint")
        configuration = _configuration(self.source.request_body)
        try:
            queries = _queries(configuration)
            page_size = _positive_integer(configuration, "results_per_page", 30)
            maximum_pages = _positive_integer(configuration, "max_pages_per_query", 10)
        except AdapterError as exc:
            return _result_health(
                source_id=self.source.id,
                checked_at=datetime.now(UTC),
                roles=[],
                listings_seen=0,
                pages_scanned=0,
                digest=hashlib.sha256(),
                expected_minimum=self.source.expected_min_items,
                query_count=0,
                failures=[str(exc)],
                capped=False,
            )
        location = str(configuration.get("location", "London"))
        client = self._client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        owns_client = self._client is None
        checked_at = datetime.now(UTC)
        digest = hashlib.sha256()
        failures: list[str] = []
        unique: dict[str, RawRole] = {}
        listings_seen = 0
        pages_scanned = 0
        capped = False
        try:
            if check_robots and not await self._robots_allowed(client, self.source.endpoint):
                raise AdapterError(f"robots.txt disallows {self.source.endpoint}")
            for query in queries:
                query_pages = 1
                for page in range(1, maximum_pages + 1):
                    if pages_scanned:
                        await asyncio.sleep(60 / self.source.requests_per_minute)
                    try:
                        response = await _retry_get(
                            client,
                            self.source.endpoint,
                            source_id=self.source.id,
                            params={
                                "keywords": query,
                                "location": location,
                                "pageNumber": page,
                                "resultsPerPage": page_size,
                                "sort": "DATE",
                            },
                        )
                    except AdapterError as exc:
                        failures.append(f"{query!r} page {page}: {exc}")
                        break
                    digest.update(response.content)
                    try:
                        page_roles = self.parse(response.content)
                    except (AdapterError, ValueError) as exc:
                        failures.append(f"{query!r} page {page}: {exc}")
                        break
                    pages_scanned += 1
                    listings_seen += len(page_roles)
                    for role in page_roles:
                        unique.setdefault(role.source_identifier, role)
                    if page == 1:
                        query_pages = self._available_pages
                        if query_pages > maximum_pages:
                            capped = True
                    if page >= query_pages:
                        break
                    if self.source.result_cap and len(unique) >= self.source.result_cap:
                        capped = True
                        break
                if self.source.result_cap and len(unique) >= self.source.result_cap:
                    break
            roles = list(unique.values())
            if self.source.result_cap and len(roles) > self.source.result_cap:
                roles = roles[: self.source.result_cap]
                capped = True
            return _result_health(
                source_id=self.source.id,
                checked_at=checked_at,
                roles=roles,
                listings_seen=listings_seen,
                pages_scanned=pages_scanned,
                digest=digest,
                expected_minimum=self.source.expected_min_items,
                query_count=len(queries),
                failures=failures,
                capped=capped,
            )
        except (httpx.HTTPError, AdapterError, ValueError) as exc:
            return _result_health(
                source_id=self.source.id,
                checked_at=checked_at,
                roles=list(unique.values()),
                listings_seen=listings_seen,
                pages_scanned=pages_scanned,
                digest=digest,
                expected_minimum=self.source.expected_min_items,
                query_count=len(queries),
                failures=[*failures, str(exc)],
                capped=capped,
            )
        finally:
            if owns_client:
                await client.aclose()


class ProspectsAdapter(BaseAdapter):
    """Parse the public Prospects London browse page into discovery-only records."""

    adapter_name = "prospects"
    _card_pattern = re.compile(r'<div class="card-secondary">(.*?)</div>\s*</li>', re.I | re.S)

    def parse(self, payload: bytes) -> list[RawRole]:
        text = payload.decode(errors="replace")
        blocks = self._card_pattern.findall(text)
        if not blocks:
            raise AdapterError("Prospects listing-card structure changed")
        roles: list[RawRole] = []
        for block in blocks:
            title_match = re.search(
                r'class="card-secondary-title"[^>]*>(.*?)</h3>', block, re.I | re.S
            )
            href_match = re.search(r'href="([^"]+)"[^>]*class="card-secondary-action"', block, re.I)
            kind_match = re.search(
                r'class="card-secondary-kicker"[^>]*>(.*?)</div>', block, re.I | re.S
            )
            meta_match = re.search(
                r'class="card-secondary-meta"[^>]*>(.*?)</ul>', block, re.I | re.S
            )
            if not title_match or not href_match or not meta_match:
                continue
            meta = [
                clean_html(item)
                for item in re.findall(r"<li[^>]*>(.*?)</li>", meta_match.group(1), re.I | re.S)
            ]
            if len(meta) < 2:
                continue
            employer = meta[0]
            location = meta[1]
            salary = meta[2] if len(meta) > 2 and meta[2] else None
            kind = clean_html(kind_match.group(1)) if kind_match else "opportunity"
            href = href_match.group(1)
            identifier_match = re.search(r"-(\d+)(?:[/?#]|$)", href)
            roles.append(
                self.role(
                    identifier=(identifier_match.group(1) if identifier_match else href),
                    employer=employer,
                    title=clean_html(title_match.group(1)),
                    url=href,
                    location=location,
                    location_type=_location_type(location),
                    description=f"Prospects listing type: {kind}.",
                    salary=salary,
                    paid=(
                        False
                        if salary and "unpaid" in salary.casefold()
                        else True
                        if salary and ("£" in salary or "competitive salary" in salary.casefold())
                        else None
                    ),
                    paid_evidence=salary,
                    listing_publisher=self.source.canonical_name,
                    source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
                    organisation_type="corporate",
                )
            )
        if not roles:
            raise AdapterError("Prospects cards were present but no complete roles parsed")
        return roles


class LegalCheekAdapter(BaseAdapter):
    """Parse Legal Cheek Hub's public jobs and work-experience noticeboard."""

    adapter_name = "legalcheek"
    _card_pattern = re.compile(
        r'<div class="card card-job">(.*?)</div>\s*</div>\s*</div>', re.I | re.S
    )

    def parse(self, payload: bytes) -> list[RawRole]:
        text = payload.decode(errors="replace")
        blocks = self._card_pattern.findall(text)
        if not blocks and not (
            "Noticeboard" in text and ("pagination" in text or "card-job" in text)
        ):
            raise AdapterError("Legal Cheek noticeboard structure changed")
        if not blocks and "card-job" in text:
            raise AdapterError("Legal Cheek listing-card structure changed")
        roles: list[RawRole] = []
        for block in blocks:
            href = re.search(r'class="card-job__link"[^>]*href="([^"]+)"', block, re.I)
            if href is None:
                href = re.search(r'href="([^"]+)"[^>]*class="card-job__link"', block, re.I)
            title = re.search(r'class="card-job__heading"[^>]*>(.*?)</h1>', block, re.I | re.S)
            employer = re.search(r'class="card-job__recruiter"[^>]*>(.*?)</h2>', block, re.I | re.S)
            location = re.search(r'class="card-job__location"[^>]*>(.*?)</p>', block, re.I | re.S)
            if not href or not title or not employer:
                continue
            target = href.group(1)
            identifier_match = re.search(r"/job/(\d+)", target)
            roles.append(
                self.role(
                    identifier=identifier_match.group(1) if identifier_match else target,
                    employer=clean_html(employer.group(1)),
                    title=clean_html(title.group(1)),
                    url=target,
                    location=clean_html(location.group(1)) if location else "Unknown",
                    description=(
                        "Legal Cheek Hub noticeboard lead. Verify programme dates, pay and "
                        "candidate criteria on the linked listing before applying."
                    ),
                    listing_publisher=self.source.canonical_name,
                    source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
                    organisation_type="law_firm",
                )
            )
        page_count = re.search(r"Page\s+\d+\s+of\s+(\d+)", clean_html(text), re.I)
        if page_count and int(page_count.group(1)) > 1:
            raise AdapterError(
                "Legal Cheek now has multiple noticeboard pages; pagination needs re-verification"
            )
        return roles


class AdzunaAdapter(BaseAdapter):
    """Use Adzuna's documented search API; credentials are never stored in source URLs."""

    adapter_name = "adzuna"
    credential_names = ("ADZUNA_APP_ID", "ADZUNA_APP_KEY")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._total_results = 0

    def parse(self, payload: bytes) -> list[RawRole]:
        data = json_payload(payload)
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise AdapterError("Adzuna payload must contain a results list")
        count = data.get("count", 0)
        self._total_results = int(count) if isinstance(count, int | float | str) else 0
        roles: list[RawRole] = []
        for job in data["results"]:
            if not isinstance(job, dict):
                continue
            title = str(job.get("title") or "").strip()
            target = str(job.get("redirect_url") or "").strip()
            identifier = str(job.get("id") or target).strip()
            if not title or not target or not identifier:
                continue
            company_value = job.get("company")
            location_value = job.get("location")
            company: dict[str, Any] = company_value if isinstance(company_value, dict) else {}
            location: dict[str, Any] = location_value if isinstance(location_value, dict) else {}
            salary = _salary_range(job.get("salary_min"), job.get("salary_max"))
            contract = " ".join(
                str(job.get(key) or "").strip()
                for key in ("contract_time", "contract_type")
                if job.get(key)
            )
            location_name = str(location.get("display_name") or "Unknown")
            roles.append(
                self.role(
                    identifier=identifier,
                    employer=str(company.get("display_name") or "Employer not stated"),
                    title=clean_html(title),
                    url=target,
                    location=location_name,
                    location_type=_location_type(location_name, contract),
                    description=_public_description(
                        ". ".join(
                            item
                            for item in (clean_html(str(job.get("description") or "")), contract)
                            if item
                        )
                    ),
                    published_date=parse_date(job.get("created")),
                    salary=salary,
                    paid=True if salary else None,
                    paid_evidence=salary,
                    listing_publisher=self.source.canonical_name,
                    source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
                    organisation_type="corporate",
                )
            )
        return roles

    async def fetch(self, *, check_robots: bool = True) -> SourceFetchResult:
        del check_robots  # This is an authenticated, documented API rather than an HTML crawler.
        credentials = tuple(os.getenv(name, "").strip() for name in self.credential_names)
        if not all(credentials):
            return _credential_failure(self.source.id, self.credential_names)
        if not self.source.endpoint:
            raise AdapterError(f"Source {self.source.id} has no endpoint")
        configuration = _configuration(self.source.request_body)
        try:
            queries = _queries(configuration)
            page_size = _positive_integer(configuration, "results_per_page", 50)
            maximum_pages = _positive_integer(configuration, "max_pages_per_query", 5)
            maximum_age = _positive_integer(configuration, "max_age_days", 30)
        except AdapterError as exc:
            return _result_health(
                source_id=self.source.id,
                checked_at=datetime.now(UTC),
                roles=[],
                listings_seen=0,
                pages_scanned=0,
                digest=hashlib.sha256(),
                expected_minimum=self.source.expected_min_items,
                query_count=0,
                failures=[str(exc)],
                capped=False,
            )
        location = str(configuration.get("location", "London"))
        client = self._client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        owns_client = self._client is None
        checked_at = datetime.now(UTC)
        digest = hashlib.sha256()
        failures: list[str] = []
        unique: dict[str, RawRole] = {}
        listings_seen = 0
        pages_scanned = 0
        capped = False
        try:
            for query in queries:
                query_pages = 1
                for page in range(1, maximum_pages + 1):
                    if pages_scanned:
                        await asyncio.sleep(60 / self.source.requests_per_minute)
                    try:
                        response = await _retry_get(
                            client,
                            f"{self.source.endpoint.rstrip('/')}/{page}",
                            source_id=self.source.id,
                            params={
                                "app_id": credentials[0],
                                "app_key": credentials[1],
                                "results_per_page": page_size,
                                "what": query,
                                "where": location,
                                "sort_by": "date",
                                "max_days_old": maximum_age,
                                "content-type": "application/json",
                            },
                        )
                        digest.update(response.content)
                        page_roles = self.parse(response.content)
                    except (AdapterError, ValueError) as exc:
                        failures.append(f"{query!r} page {page}: {exc}")
                        break
                    pages_scanned += 1
                    listings_seen += len(page_roles)
                    for role in page_roles:
                        unique.setdefault(role.source_identifier, role)
                    if page == 1:
                        query_pages = max(1, math.ceil(self._total_results / page_size))
                        if query_pages > maximum_pages:
                            capped = True
                    if page >= query_pages:
                        break
                    if self.source.result_cap and len(unique) >= self.source.result_cap:
                        capped = True
                        break
                if self.source.result_cap and len(unique) >= self.source.result_cap:
                    break
            roles = list(unique.values())
            if self.source.result_cap and len(roles) > self.source.result_cap:
                roles = roles[: self.source.result_cap]
                capped = True
            return _result_health(
                source_id=self.source.id,
                checked_at=checked_at,
                roles=roles,
                listings_seen=listings_seen,
                pages_scanned=pages_scanned,
                digest=digest,
                expected_minimum=self.source.expected_min_items,
                query_count=len(queries),
                failures=failures,
                capped=capped,
            )
        finally:
            if owns_client:
                await client.aclose()


class ReedAdapter(BaseAdapter):
    """Use Reed's documented jobseeker API over the same configurable query matrix."""

    adapter_name = "reed"
    credential_names = ("REED_API_KEY",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._total_results = 0

    def parse(self, payload: bytes) -> list[RawRole]:
        data = json_payload(payload)
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise AdapterError("Reed payload must contain a results list")
        total = data.get("totalResults", 0)
        self._total_results = int(total) if isinstance(total, int | float | str) else 0
        roles: list[RawRole] = []
        for job in data["results"]:
            if not isinstance(job, dict):
                continue
            identifier = str(job.get("jobId") or "").strip()
            title = str(job.get("jobTitle") or "").strip()
            target = str(job.get("jobUrl") or "").strip()
            if not target and identifier:
                target = f"https://www.reed.co.uk/jobs/{identifier}"
            elif target.startswith("/"):
                target = urljoin("https://www.reed.co.uk", target)
            if not identifier or not title or not target:
                continue
            currency = str(job.get("currency") or "GBP")
            salary = _salary_range(
                job.get("minimumSalary"), job.get("maximumSalary"), currency=currency
            )
            location = str(job.get("locationName") or "Unknown")
            advertised_employer, advertised_title = _reed_listing_identity(
                str(job.get("employerName") or "Employer not stated"), clean_html(title)
            )
            roles.append(
                self.role(
                    identifier=identifier,
                    employer=advertised_employer,
                    title=advertised_title,
                    url=target,
                    location=location,
                    location_type=_location_type(location),
                    description=_public_description(
                        clean_html(str(job.get("jobDescription") or ""))
                    ),
                    published_date=parse_date(job.get("date")),
                    deadline=parse_date(job.get("expirationDate")),
                    salary=salary,
                    paid=True if salary else None,
                    paid_evidence=salary,
                    listing_publisher=self.source.canonical_name,
                    source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
                    organisation_type="corporate",
                )
            )
        return roles

    async def fetch(self, *, check_robots: bool = True) -> SourceFetchResult:
        del check_robots  # This is an authenticated, documented API rather than an HTML crawler.
        api_key = os.getenv(self.credential_names[0], "").strip()
        if not api_key:
            return _credential_failure(self.source.id, self.credential_names)
        if not self.source.endpoint:
            raise AdapterError(f"Source {self.source.id} has no endpoint")
        configuration = _configuration(self.source.request_body)
        try:
            queries = _queries(configuration)
            page_size = min(100, _positive_integer(configuration, "results_per_page", 100))
            maximum_pages = _positive_integer(configuration, "max_pages_per_query", 3)
        except AdapterError as exc:
            return _result_health(
                source_id=self.source.id,
                checked_at=datetime.now(UTC),
                roles=[],
                listings_seen=0,
                pages_scanned=0,
                digest=hashlib.sha256(),
                expected_minimum=self.source.expected_min_items,
                query_count=0,
                failures=[str(exc)],
                capped=False,
            )
        location = str(configuration.get("location", "London"))
        distance = str(configuration.get("distance_miles", "10"))
        auth_token = base64.b64encode(f"{api_key}:".encode()).decode()
        headers = {"Authorization": f"Basic {auth_token}"}
        client = self._client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        owns_client = self._client is None
        checked_at = datetime.now(UTC)
        digest = hashlib.sha256()
        failures: list[str] = []
        unique: dict[str, RawRole] = {}
        listings_seen = 0
        pages_scanned = 0
        capped = False
        try:
            for query in queries:
                query_pages = 1
                for page in range(maximum_pages):
                    if pages_scanned:
                        await asyncio.sleep(60 / self.source.requests_per_minute)
                    try:
                        response = await _retry_get(
                            client,
                            self.source.endpoint,
                            source_id=self.source.id,
                            params={
                                "keywords": query,
                                "locationName": location,
                                "distanceFromLocation": distance,
                                "resultsToTake": page_size,
                                "resultsToSkip": page * page_size,
                            },
                            headers=headers,
                        )
                        digest.update(response.content)
                        page_roles = self.parse(response.content)
                    except (AdapterError, ValueError) as exc:
                        failures.append(f"{query!r} page {page + 1}: {exc}")
                        break
                    pages_scanned += 1
                    listings_seen += len(page_roles)
                    for role in page_roles:
                        unique.setdefault(role.source_identifier, role)
                    if page == 0:
                        query_pages = max(1, math.ceil(self._total_results / page_size))
                        if query_pages > maximum_pages:
                            capped = True
                    if page + 1 >= query_pages:
                        break
                    if self.source.result_cap and len(unique) >= self.source.result_cap:
                        capped = True
                        break
                if self.source.result_cap and len(unique) >= self.source.result_cap:
                    break
            roles = list(unique.values())
            if self.source.result_cap and len(roles) > self.source.result_cap:
                roles = roles[: self.source.result_cap]
                capped = True
            return _result_health(
                source_id=self.source.id,
                checked_at=checked_at,
                roles=roles,
                listings_seen=listings_seen,
                pages_scanned=pages_scanned,
                digest=digest,
                expected_minimum=self.source.expected_min_items,
                query_count=len(queries),
                failures=failures,
                capped=capped,
            )
        finally:
            if owns_client:
                await client.aclose()

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from opportunity_radar.models import EmployerConfig, RawRole, SourceHealth, SourceHealthStatus

LOGGER = logging.getLogger(__name__)
USER_AGENT = "LondonOpportunityRadar/0.1 (+public research tracker)"


class AdapterError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SourceFetchResult:
    roles: list[RawRole]
    health: SourceHealth


class BaseAdapter(ABC):
    adapter_name = "base"

    def __init__(self, source: EmployerConfig, client: httpx.AsyncClient | None = None) -> None:
        self.source = source
        self._client = client

    async def _robots_allowed(self, client: httpx.AsyncClient, url: str) -> bool:
        parts = urlsplit(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        try:
            response = await client.get(robots_url, timeout=5.0)
            if response.status_code >= 400:
                return True
            parser = RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(response.text.splitlines())
            return parser.can_fetch(USER_AGENT, url)
        except httpx.HTTPError:
            LOGGER.warning("robots_check_failed", extra={"source_id": self.source.id})
            return False

    async def fetch(self, *, check_robots: bool = True) -> SourceFetchResult:
        if not self.source.endpoint:
            raise AdapterError(f"Source {self.source.id} has no endpoint")
        client = self._client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        owns_client = self._client is None
        checked_at = datetime.now(UTC)
        try:
            if check_robots and not await self._robots_allowed(client, self.source.endpoint):
                raise AdapterError(f"robots.txt disallows {self.source.endpoint}")
            response: httpx.Response | None = None
            for attempt in range(3):
                try:
                    if self.source.request_method == "POST":
                        response = await client.post(
                            self.source.endpoint,
                            json=self.source.request_body or {},
                            timeout=20.0,
                        )
                    else:
                        response = await client.get(self.source.endpoint, timeout=20.0)
                    if response.status_code == 429 or response.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            "retryable response", request=response.request, response=response
                        )
                    response.raise_for_status()
                    break
                except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                    if attempt == 2:
                        raise AdapterError(str(exc)) from exc
                    await asyncio.sleep((2**attempt) + random.random() / 4)
            if response is None:
                raise AdapterError("No response received")
            roles = self.parse(response.content)
            capped = bool(self.source.result_cap and len(roles) >= self.source.result_cap)
            parser_ok = len(roles) >= self.source.expected_min_items
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
                    pages_scanned=1,
                    capped=capped,
                    parser_ok=parser_ok,
                    content_hash=hashlib.sha256(response.content).hexdigest(),
                    message=(
                        "Result set reached the configured cap"
                        if capped
                        else (
                            "Parsed fewer items than the configured minimum"
                            if not parser_ok
                            else None
                        )
                    ),
                ),
            )
        except (httpx.HTTPError, AdapterError, ValueError) as exc:
            LOGGER.warning("source_failed", extra={"source_id": self.source.id, "error": str(exc)})
            return SourceFetchResult(
                roles=[],
                health=SourceHealth(
                    source_id=self.source.id,
                    status=SourceHealthStatus.FAILED,
                    checked_at=checked_at,
                    parser_ok=not isinstance(exc, ValueError),
                    message=str(exc),
                ),
            )
        finally:
            if owns_client:
                await client.aclose()

    @abstractmethod
    def parse(self, payload: bytes) -> list[RawRole]:
        raise NotImplementedError

    def role(
        self,
        *,
        identifier: str,
        title: str,
        url: str,
        location: str = "Unknown",
        description: str = "",
        **fields: object,
    ) -> RawRole:
        base_url = self.source.endpoint or self.source.careers_url or ""
        canonical_url = urljoin(base_url, url)
        supplied_application = fields.get("application_url")
        if isinstance(supplied_application, str):
            fields["application_url"] = urljoin(base_url, supplied_application)
        data: dict[str, object] = {
            "source_identifier": str(identifier),
            "employer": self.source.canonical_name,
            "title": title,
            "source_url": canonical_url,
            "application_url": canonical_url,
            "source_type": self.adapter_name,
            "source_authority": self.source.source_authority,
            "organisation_type": self.source.organisation_type,
            "location": location,
            "description": description,
            "all_source_urls": [canonical_url],
            **fields,
        }
        return RawRole.model_validate(data)

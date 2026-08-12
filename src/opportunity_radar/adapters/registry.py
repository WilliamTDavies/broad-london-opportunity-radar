from __future__ import annotations

import httpx

from opportunity_radar.adapters.base import BaseAdapter
from opportunity_radar.adapters.broad_sources import (
    AdzunaAdapter,
    LegalCheekAdapter,
    ProspectsAdapter,
    ReedAdapter,
    WorkHubAdapter,
)
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
from opportunity_radar.models import EmployerConfig

ADAPTERS: dict[str, type[BaseAdapter]] = {
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
    "smartrecruiters": SmartRecruitersAdapter,
    "workday": WorkdayAdapter,
    "teamtailor": TeamtailorAdapter,
    "generic_json": GenericJsonAdapter,
    "rss": FeedAdapter,
    "atom": FeedAdapter,
    "html": HtmlMonitorAdapter,
    "government_portal": GovernmentPortalAdapter,
    "trusted_board": TrustedBoardAdapter,
    "w4mp": W4MPAdapter,
    "higherin": HigherinAdapter,
    "charityjob": CharityJobAdapter,
    "nhs_jobs": NHSJobsAdapter,
    "jobs_ac_uk": JobsAcUkAdapter,
    "targetjobs": TargetJobsAdapter,
    "work_hub": WorkHubAdapter,
    "prospects": ProspectsAdapter,
    "legalcheek": LegalCheekAdapter,
    "adzuna": AdzunaAdapter,
    "reed": ReedAdapter,
    "curated_yaml": CuratedYamlAdapter,
}


def create_adapter(source: EmployerConfig, client: httpx.AsyncClient | None = None) -> BaseAdapter:
    try:
        adapter_type = ADAPTERS[source.ats_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported adapter: {source.ats_type}") from exc
    return adapter_type(source, client)

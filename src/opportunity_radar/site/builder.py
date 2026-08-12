from __future__ import annotations

import html
import json
import os
import shutil
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from opportunity_radar.config import load_employers, load_radar
from opportunity_radar.models import (
    ProgrammeStatus,
    ProgrammeType,
    RadarEntry,
    RoleRecord,
    SourceHealth,
)
from opportunity_radar.storage import JsonStore

LABEL_OVERRIDES = {
    "official_ats": "Official ATS",
    "official_careers_page": "Official careers page",
    "official_programme_page": "Official programme page",
    "official_government_portal": "Official government portal",
    "trusted_sector_board": "Trusted sector board",
    "discovery_only_source": "Discovery-only source",
    "esg_and_responsible_investment": "ESG and responsible investment",
}


def _label(value: object) -> str:
    raw = str(getattr(value, "value", value))
    return LABEL_OVERRIDES.get(raw, raw.replace("_", " ").title())


def _identity(value: str) -> str:
    return value


ORGANISATION_LABELS = {
    "charity": "Major charity",
    "consultancy": "Consultancy",
    "corporate": "Company",
    "development_finance": "Development finance institution",
    "energy": "Energy company",
    "foundation": "Foundation",
    "geospatial": "Geospatial organisation",
    "government": "Government body",
    "healthcare": "Healthcare organisation",
    "insurance": "Insurer",
    "international_institution": "International institution",
    "investment_bank": "Investment bank",
    "investment_manager": "Investment manager",
    "law_firm": "Law firm",
    "logistics": "Logistics company",
    "ngo": "Major NGO",
    "nonprofit": "Non-profit organisation",
    "real_estate": "Real-estate company",
    "regulator": "Regulator",
    "think_tank": "Think tank",
    "trade_association": "Trade association",
    "trusted_board": "Trusted sector board",
    "parliamentary_office": "Parliamentary or political office",
    "politics_public_affairs": "Politics or public-affairs organisation",
    "public_health": "Public health or healthcare employer",
    "higher_education": "University or higher-education employer",
}


def _organisation_label(value: str) -> str:
    return ORGANISATION_LABELS.get(value, _label(value))


def _date(value: date | None) -> str:
    return value.strftime("%d %b %Y") if value else "Not stated"


def _options(
    roles: list[RoleRecord],
    attribute: str,
    *,
    labeler: Callable[[str], str] | None = None,
) -> str:
    values: set[str] = set()
    for role in roles:
        value = getattr(role, attribute)
        if isinstance(value, list):
            values.update(str(item) for item in value)
        else:
            values.add(str(getattr(value, "value", value)))
    display = labeler or _label
    return "".join(
        f'<option value="{html.escape(value.casefold())}">{html.escape(display(value))}</option>'
        for value in sorted(values)
        if value
    )


def _role_filter_data(role: RoleRecord, now: datetime, listing_tier: str) -> dict[str, str]:
    new = role.first_seen_at >= now - timedelta(hours=24)
    closing = bool(role.deadline and role.deadline <= now.date() + timedelta(days=7))
    return {
        "search": " ".join(
            value
            for value in (
                role.title,
                role.canonical_employer,
                role.division,
                role.description_excerpt,
                role.primary_category,
                *role.secondary_tags,
                role.programme_type.value,
                role.organisation_type,
                role.location,
            )
            if value
        ),
        "category": role.primary_category,
        "tags": "|".join(role.secondary_tags),
        "employer": role.canonical_employer,
        "organisation": role.organisation_type,
        "programme": role.programme_type.value,
        "eligibility": role.eligibility_status.value,
        "relevance": role.relevance_status.value,
        "location": role.location,
        "geography": role.geographic_scope.value,
        "paid": "paid" if role.paid else "unknown",
        "status": role.status.value,
        "cycle": role.cycle_provenance.value,
        "authority": role.source_authority.value,
        "nationality": "required" if role.nationality_requirements else "not-stated",
        "tier": role.employer_quality_tier,
        "listing": listing_tier,
        "new": str(new).lower(),
        "closing": str(closing).lower(),
        "score": str(role.match_score),
        "evidence": str(
            {
                "verified_eligible": 3,
                "manual_approved": 3,
                "likely_eligible": 2,
                "uncertain": 1,
                "ineligible": 0,
            }[role.eligibility_status.value]
        ),
        "deadline": role.deadline.isoformat() if role.deadline else "9999-12-31",
        "opening": role.opening_date.isoformat() if role.opening_date else "9999-12-31",
        "first-seen": role.first_seen_at.isoformat(),
    }


def _role_attributes(role: RoleRecord, now: datetime, listing_tier: str) -> str:
    return " ".join(
        f'data-{key}="{html.escape(value.casefold())}"'
        for key, value in _role_filter_data(role, now, listing_tier).items()
    )


def _role_card(role: RoleRecord, now: datetime, *, possible: bool = False) -> str:
    new = role.first_seen_at >= now - timedelta(hours=24)
    closing = bool(role.deadline and role.deadline <= now.date() + timedelta(days=7))
    published_label = "Published" if role.published_date else "First observed"
    published_value = role.published_date or role.first_seen_at.date()
    requirements = [
        *role.nationality_requirements,
        *role.residency_requirements,
        *role.clearance_requirements,
    ]
    evidence = "".join(
        f'<li>{html.escape(item.text)} <a href="{html.escape(item.source_url)}">evidence source</a></li>'
        for item in role.eligibility_evidence
    )
    reasons = " ".join(f"<li>{html.escape(reason)}</li>" for reason in role.relevance_reasons)
    requirement_text = "; ".join(requirements) or "None stated"
    organisation = _organisation_label(role.organisation_type)
    paid_label = "Paid — confirmed" if role.paid else "Pay not stated"
    source_label = _label(role.source_authority)
    match_summary = " · ".join(role.relevance_reasons[:2])
    badges = ('<span class="badge badge-new">New</span>' if new else "") + (
        '<span class="badge badge-urgent">Closing soon</span>' if closing else ""
    )
    office = (
        f'<p class="office">{html.escape(role.named_office_or_mp)}</p>'
        if role.named_office_or_mp
        else ""
    )
    division = f'<p class="division">{html.escape(role.division)}</p>' if role.division else ""
    exception = (
        f'<p class="exception">UK priority exception: {html.escape(role.geographic_exception_reason or "Approved national programme")}</p>'
        if role.geographic_scope.value == "uk_priority_exception"
        else ""
    )
    application_method = (
        f"<h4>Application method</h4><p>{html.escape(role.application_method)}</p>"
        if role.application_method
        else ""
    )
    nationality_assessment = (
        f"<p>{html.escape(role.nationality_assessment)}</p>" if role.nationality_assessment else ""
    )
    publisher = (
        f" · Publisher: {html.escape(role.listing_publisher)}" if role.listing_publisher else ""
    )
    same_application_and_source = role.application_url == role.canonical_url
    actions = (
        f'<a class="button" href="{html.escape(role.application_url)}" rel="noopener">'
        f"{'View listing and check criteria' if possible else 'Official listing &amp; application'}</a>"
        if same_application_and_source
        else (
            f'<a class="button" href="{html.escape(role.application_url)}" rel="noopener">'
            "Apply on official site</a>"
            f'<a class="source-link" href="{html.escape(role.canonical_url)}" rel="noopener">'
            "View source</a>"
        )
    )
    tags = (
        '<p class="tags"><strong>Related areas:</strong> '
        + html.escape(" · ".join(role.secondary_tags))
        + "</p>"
        if role.secondary_tags
        else ""
    )
    return f"""
<article class="role-card{" role-card-possible" if possible else ""}" id="role-{role.id}" tabindex="-1">
  <div class="card-context"><span>{"Possible lead — verify criteria" if possible else "Verified opportunity"}</span><span>{html.escape(organisation)}</span></div>
  <div class="role-top"><div><p class="employer-name">{html.escape(role.canonical_employer)}</p>{office}
  <h3>{html.escape(role.title)}</h3>{division}</div><button class="save" data-save="{role.id}" aria-pressed="false" aria-label="Save {html.escape(role.title)}">Save</button></div>
  <div class="badges">{badges}<span class="badge {"badge-possible" if possible else "badge-verified"}">{"Possible — check eligibility" if possible else "Verified criteria"}</span><span class="badge">{html.escape(role.primary_category)}</span><span class="badge badge-source">{html.escape(source_label)}</span></div>
  {exception}
  <p class="description">{html.escape(role.description_excerpt)}</p>
  <p class="match"><strong>{"Why it may fit" if possible else "Why it fits"}:</strong> {html.escape(match_summary)}</p>
  <dl class="facts"><div class="fact-wide"><dt>Location</dt><dd>{html.escape(role.location)}</dd></div><div><dt>Deadline</dt><dd>{_date(role.deadline)}</dd></div><div><dt>Programme</dt><dd>{html.escape(_label(role.programme_type))}</dd></div><div><dt>{published_label}</dt><dd>{_date(published_value)}</dd></div><div><dt>Pay</dt><dd>{paid_label}</dd></div></dl>
  <details><summary>Eligibility, dates and evidence</summary><div class="detail-body">{'<p class="possible-warning"><strong>Check before applying:</strong> this broad-discovery lead has no explicit conflicting criterion, but the source does not establish every requirement.</p>' if possible else ""}<h4>Eligibility evidence</h4><ul>{evidence}</ul><h4>All match reasons</h4><ul>{reasons}</ul>{tags}<h4>Opening date</h4><p>{_date(role.opening_date)}</p><h4>Nationality, residency or clearance</h4><p>{html.escape(requirement_text)}</p>{nationality_assessment}{application_method}<p class="provenance">Date: {_label(role.date_provenance)} · Cycle: {_label(role.cycle_provenance)} · Source: {source_label}{publisher}</p></div></details>
  <div class="actions">{actions}</div>
</article>"""


def _role_row(
    role: RoleRecord,
    now: datetime,
    *,
    possible: bool = False,
    include_filter_data: bool = True,
) -> str:
    new = role.first_seen_at >= now - timedelta(hours=24)
    closing = bool(role.deadline and role.deadline <= now.date() + timedelta(days=7))
    flags = ('<span class="badge badge-new">New</span>' if new else "") + (
        '<span class="badge badge-urgent">Closing soon</span>' if closing else ""
    )
    division = (
        f'<span class="row-division">{html.escape(role.division)}</span>' if role.division else ""
    )
    listing_tier = "possible" if possible else "verified"
    attrs = _role_attributes(role, now, listing_tier) if include_filter_data else ""
    return f"""
<tr class="role-row{" role-row-possible" if possible else ""}" data-role-id="{html.escape(role.id)}" {attrs}>
  <td class="role-cell"><span class="row-employer">{html.escape(role.canonical_employer)}</span>
    <button class="row-title" type="button" data-open-card="{html.escape(role.id)}" aria-haspopup="dialog"><span>{html.escape(role.title)}</span><small>View details and evidence</small></button>
    {division}<span class="row-flags">{flags}</span></td>
  <td><span class="mobile-label">Area</span>{html.escape(role.primary_category)}</td>
  <td><span class="mobile-label">Location</span>{html.escape(role.location)}</td>
  <td><span class="mobile-label">Deadline</span><strong>{_date(role.deadline)}</strong></td>
  <td><span class="mobile-label">Confidence</span><span class="badge {"badge-possible" if possible else "badge-verified"}">{"Possible — check" if possible else "Verified"}</span></td>
  <td class="row-actions"><button class="save" type="button" data-save="{html.escape(role.id)}" aria-pressed="false" aria-label="Save {html.escape(role.title)}">Save</button><a class="apply-link" href="{html.escape(role.application_url)}" rel="noopener">{"Check role" if possible else "Apply"} <span aria-hidden="true">↗</span></a></td>
</tr>"""


def build_site(
    root: Path,
    *,
    build_time: datetime | None = None,
    fixture_mode: bool = False,
    subscribe_endpoint: str | None = None,
) -> Path:
    now = build_time or datetime.now(UTC)
    data_directory = root / "build" / "fixture-data" if fixture_mode else root / "data"
    store = JsonStore(root, data_directory)
    verified_roles = [
        *store.read_models("open_roles.json", RoleRecord),
        *store.read_models("recent_roles.json", RoleRecord),
    ]
    possible_roles = store.read_models("possible_roles.json", RoleRecord)
    verified_ids = {role.id for role in verified_roles}
    possible_roles = [role for role in possible_roles if role.id not in verified_ids]
    roles = [*verified_roles, *possible_roles]
    active_ids = {role.id for role in roles}
    closed = [
        role
        for role in store.read_models("closed_roles.json", RoleRecord)
        if role.id not in active_ids
        and role.closed_at
        and role.closed_at >= now - timedelta(days=14)
    ]
    health = store.read_models("source_health.json", SourceHealth)
    metrics = store.read("metrics.json", {})
    radar_payload = store.read("upcoming_roles.json", [])
    radar = (
        [RadarEntry.model_validate(item) for item in radar_payload]
        if radar_payload
        else load_radar(root)
    )
    employers = load_employers(root)
    enabled_sources = [item for item in employers if item.enabled]
    publishing_sources = [item for item in enabled_sources if not item.monitor_only]
    watched_pages = [item for item in enabled_sources if item.monitor_only]
    generated = root / "build" / "fixture-site" if fixture_mode else root / "site" / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "site" / "static" / "styles.css", generated / "styles.css")
    shutil.copy2(root / "site" / "static" / "app.js", generated / "app.js")
    shutil.copy2(root / "METHODOLOGY.md", generated / "METHODOLOGY.md")
    shutil.copy2(root / "PRIVACY.md", generated / "PRIVACY.md")
    role_details = {
        **{role.id: _role_card(role, now) for role in verified_roles},
        **{role.id: _role_card(role, now, possible=True) for role in possible_roles},
    }
    role_pairs = [
        *((role, False) for role in verified_roles),
        *((role, True) for role in possible_roles),
    ]
    role_rows = "\n".join(
        _role_row(role, now, possible=possible) for role, possible in role_pairs[:100]
    )
    role_index: list[dict[str, object]] = []
    for role, possible in role_pairs:
        listing_tier = "possible" if possible else "verified"
        dataset = _role_filter_data(role, now, listing_tier)
        dataset["firstSeen"] = dataset.pop("first-seen")
        role_index.append(
            {
                "id": role.id,
                "dataset": dataset,
                "html": _role_row(
                    role,
                    now,
                    possible=possible,
                    include_filter_data=False,
                ),
            }
        )
    radar_rows_parts: list[str] = []
    for item in radar:
        live = next(
            (
                role
                for role in verified_roles
                if role.canonical_employer.casefold() == item.employer.casefold()
                and role.programme_type == item.expected_programme_type
                and role.status == ProgrammeStatus.OPEN
            ),
            None,
        )
        window = item.historical_opening_window
        evidence_type = item.evidence_type
        current_status = item.current_status
        source_url = item.source_url
        if live:
            window = _date(live.opening_date or live.first_seen_at.date())
            evidence_type = (
                "official_future_opening_date" if live.opening_date else "currently_open"
            )
            current_status = "currently open"
            source_url = live.canonical_url
        radar_rows_parts.append(
            "<tr>"
            f"<td>{html.escape(item.employer)}</td><td>{html.escape(_label(item.expected_programme_type))}</td>"
            f"<td>{html.escape(item.expected_location)}</td><td>{html.escape(window)}</td>"
            f"<td>{html.escape(_label(evidence_type))}</td><td>{html.escape(_label(current_status))}</td>"
            f'<td><a href="{html.escape(source_url)}">Evidence</a></td></tr>'
        )
    radar_rows = "".join(radar_rows_parts)
    closed_rows = (
        "".join(
            f'<li><strong>{html.escape(role.canonical_employer)} — {html.escape(role.title)}</strong>: {html.escape(role.closure_reason or "Closed")} <a href="{html.escape(role.closure_evidence or role.canonical_url)}">closure evidence</a></li>'
            for role in closed
        )
        or "<li>No recently closed roles.</li>"
    )
    health_by_id = {item.source_id: item for item in health}
    source_rows = "".join(
        "<tr>"
        f"<td>{html.escape(source.canonical_name)}</td>"
        f"<td>{html.escape('Verified snapshot' if source.ats_type == 'curated_yaml' else (_label(health_by_id[source.id].status) if source.id in health_by_id else 'Awaiting scheduled scan'))}</td>"
        f"<td>{health_by_id[source.id].listing_count if source.id in health_by_id else 0}</td>"
        f"<td>{html.escape(('Page watch only — no role publication. ' if source.monitor_only else '') + ((health_by_id[source.id].message or source.notes) if source.id in health_by_id else source.notes))}</td></tr>"
        for source in enabled_sources
    )
    counts = Counter(role.programme_type for role in roles)
    policy_count = sum(
        role.programme_type in {ProgrammeType.POLICY_RESEARCH, ProgrammeType.PARLIAMENTARY}
        for role in roles
    )
    environment_count = sum(
        any(term in role.primary_category.casefold() for term in ("climate", "environment", "esg"))
        for role in roles
    )
    development_count = sum(
        role.programme_type
        in {ProgrammeType.DEVELOPMENT_HUMANITARIAN, ProgrammeType.INTERNATIONAL_INSTITUTION}
        for role in roles
    )
    site_html = (root / "site" / "templates" / "index.html").read_text(encoding="utf-8")
    values = {
        "BUILD_TIME": now.isoformat(),
        "DATA_TIME": str(metrics.get("data_updated_at", "No successful scan yet")),
        "OPEN_COUNT": str(sum(role.status == ProgrammeStatus.OPEN for role in roles)),
        "VERIFIED_COUNT": str(len(verified_roles)),
        "POSSIBLE_COUNT": str(len(possible_roles)),
        "LISTINGS_SCANNED": str(metrics.get("listings_scanned", 0)),
        "NEW_DAY_COUNT": str(
            sum(role.first_seen_at >= now - timedelta(hours=24) for role in roles)
        ),
        "NEW_WEEK_COUNT": str(sum(role.first_seen_at >= now - timedelta(days=7) for role in roles)),
        "CLOSING_COUNT": str(
            sum(
                bool(
                    role.deadline and now.date() <= role.deadline <= now.date() + timedelta(days=7)
                )
                for role in roles
            )
        ),
        "SUMMER_COUNT": str(counts[ProgrammeType.SUMMER_INTERNSHIP]),
        "VACATION_COUNT": str(
            sum("vacation_scheme" in role.programme_type.value for role in roles)
        ),
        "POLICY_COUNT": str(policy_count),
        "ENVIRONMENT_COUNT": str(environment_count),
        "DEVELOPMENT_COUNT": str(development_count),
        "RADAR_COUNT": str(len(radar)),
        "EMPLOYER_COUNT": str(len(enabled_sources)),
        "PUBLISHING_SOURCE_COUNT": str(len(publishing_sources)),
        "WATCHED_PAGE_COUNT": str(len(watched_pages)),
        "HEALTHY_COUNT": str(sum(item.status.value == "healthy" for item in health)),
        "REVIEW_COUNT": str(metrics.get("review_queue", 0)),
        "DATA_MODE_BANNER": (
            '<div class="demo-banner" role="status"><strong>Test preview:</strong> '
            "these are synthetic fixtures used to verify the pipeline. They are never "
            "published as production opportunities.</div>"
            if fixture_mode
            else ""
        ),
        "COVERAGE_WARNING": html.escape(
            str(metrics.get("coverage_warning", "Fixture data only until a scan runs."))
        ),
        "ROLE_ROWS": role_rows,
        "RADAR_ROWS": radar_rows,
        "CLOSED_ROWS": closed_rows,
        "SOURCE_ROWS": source_rows,
        "CATEGORY_OPTIONS": _options(roles, "primary_category", labeler=_identity),
        "TAG_OPTIONS": _options(roles, "secondary_tags", labeler=_identity),
        "EMPLOYER_OPTIONS": _options(roles, "canonical_employer", labeler=_identity),
        "ORGANISATION_OPTIONS": _options(roles, "organisation_type", labeler=_organisation_label),
        "PROGRAMME_OPTIONS": _options(roles, "programme_type"),
        "ELIGIBILITY_OPTIONS": _options(roles, "eligibility_status"),
        "RELEVANCE_OPTIONS": _options(roles, "relevance_status"),
        "LOCATION_OPTIONS": _options(roles, "location", labeler=_identity),
        "AUTHORITY_OPTIONS": _options(roles, "source_authority"),
        "TIER_OPTIONS": _options(roles, "employer_quality_tier"),
        "INLINE_STYLES": (root / "site" / "static" / "styles.css").read_text(encoding="utf-8"),
        "INLINE_SCRIPT": (root / "site" / "static" / "app.js")
        .read_text(encoding="utf-8")
        .replace("</script", "<\\/script"),
        "SUBSCRIBE_ENDPOINT": html.escape(
            subscribe_endpoint
            or os.getenv("SUBSCRIBE_ENDPOINT", "")
            or (
                f"{os.environ['SUPABASE_URL'].rstrip('/')}/functions/v1/subscribe"
                if os.getenv("SUPABASE_URL")
                else ""
            )
        ),
    }
    subscription_configured = bool(values["SUBSCRIBE_ENDPOINT"])
    values["SUBSCRIBE_DISABLED"] = "" if subscription_configured else " disabled"
    values["SUBSCRIBE_STATUS"] = (
        ""
        if subscription_configured
        else "Email subscriptions are not configured on this deployment."
    )
    for key, value in values.items():
        site_html = site_html.replace(f"{{{{{key}}}}}", value)
    (generated / "index.html").write_text(site_html, encoding="utf-8")
    public_payload = [
        role.model_dump(mode="json", exclude={"manual_override"}) for role in verified_roles
    ]
    (generated / "roles.json").write_text(
        json.dumps(public_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    possible_payload = [
        role.model_dump(mode="json", exclude={"manual_override"}) for role in possible_roles
    ]
    (generated / "possible-roles.json").write_text(
        json.dumps(possible_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (generated / "role-index.json").write_text(
        json.dumps(role_index, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (generated / "role-details.json").write_text(
        json.dumps(role_details, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (generated / ".nojekyll").touch()
    return generated / "index.html"

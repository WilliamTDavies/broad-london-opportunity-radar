from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import parse_qs, urlsplit

from opportunity_radar.classification.engine import canonicalise_url, normalise_text
from opportunity_radar.models import LocationType, RoleRecord, SourceAuthority

AUTHORITY_RANK = {
    SourceAuthority.OFFICIAL_ATS: 6,
    SourceAuthority.OFFICIAL_PROGRAMME_PAGE: 5,
    SourceAuthority.OFFICIAL_GOVERNMENT_PORTAL: 5,
    SourceAuthority.OFFICIAL_CAREERS_PAGE: 4,
    SourceAuthority.TRUSTED_SECTOR_BOARD: 3,
    SourceAuthority.DISCOVERY_ONLY_SOURCE: 0,
}


def dedupe_keys(role: RoleRecord) -> set[str]:
    employer = normalise_text(role.canonical_employer)
    title = normalise_text(role.title)
    location = normalise_text(role.location)
    keys = {
        f"source:{employer}:{role.source_registry_id}:{role.source_identifier}",
        f"ats:{employer}:{role.source_identifier}",
        f"application:{canonicalise_url(role.application_url)}",
        f"official:{canonicalise_url(role.canonical_url)}",
        f"natural:{employer}:{title}:{location}:{normalise_text(role.division or '')}",
    }
    application_parts = urlsplit(role.application_url)
    application_host = application_parts.netloc.casefold().removeprefix("www.")
    ats_host = any(
        marker in application_host
        for marker in (
            "workdayjobs.com",
            "successfactors.",
            "greenhouse.io",
            "smartrecruiters.com",
            "teamtailor.com",
        )
    )
    path_parts = [part for part in application_parts.path.casefold().split("/") if part]
    if ats_host and path_parts:
        terminal_identifier = path_parts[-1]
        if len(terminal_identifier) >= 6 and terminal_identifier not in {"apply", "application"}:
            keys.add(f"external-ats:{application_host}:{terminal_identifier}")
    query = parse_qs(application_parts.query)
    for parameter in ("career_job_req_id", "jobid", "job_id", "gh_jid"):
        if query.get(parameter):
            keys.add(f"external-requisition:{application_host}:{parameter}:{query[parameter][0]}")
    if role.named_office_or_mp:
        keys.add(
            f"office:{normalise_text(role.named_office_or_mp)}:{title}:{role.deadline or 'none'}"
        )
    if role.programme_start:
        keys.add(f"programme:{employer}:{title}:{role.programme_start}:{role.programme_end}")
    return keys


def _merge(left: RoleRecord, right: RoleRecord) -> RoleRecord:
    preferred, other = (
        (left, right)
        if AUTHORITY_RANK[left.source_authority] >= AUTHORITY_RANK[right.source_authority]
        else (right, left)
    )
    data = preferred.model_dump()
    data["all_source_urls"] = list(
        dict.fromkeys([*preferred.all_source_urls, *other.all_source_urls])
    )
    data["first_seen_at"] = min(preferred.first_seen_at, other.first_seen_at)
    data["last_seen_at"] = max(preferred.last_seen_at, other.last_seen_at)
    data["eligibility_evidence"] = [
        *preferred.eligibility_evidence,
        *[
            item
            for item in other.eligibility_evidence
            if item.model_dump() not in [e.model_dump() for e in preferred.eligibility_evidence]
        ],
    ]
    data["secondary_tags"] = list(dict.fromkeys([*preferred.secondary_tags, *other.secondary_tags]))
    if not data.get("listing_publisher"):
        data["listing_publisher"] = other.listing_publisher
    for field in ("division", "application_method", "political_affiliation"):
        if not data.get(field):
            data[field] = getattr(other, field)
    return RoleRecord.model_validate(data)


def _materially_distinct(left: RoleRecord, right: RoleRecord) -> bool:
    if (
        left.source_registry_id == right.source_registry_id
        and left.source_identifier == right.source_identifier
    ):
        return False
    if (
        left.named_office_or_mp
        and right.named_office_or_mp
        and normalise_text(left.named_office_or_mp) != normalise_text(right.named_office_or_mp)
    ):
        return True
    if (
        left.division
        and right.division
        and normalise_text(left.division) != normalise_text(right.division)
    ):
        return True
    if (
        left.programme_start
        and right.programme_start
        and left.programme_start != right.programme_start
    ):
        return True
    left_location = normalise_text(left.location)
    right_location = normalise_text(right.location)
    if left_location == right_location:
        return False
    if LocationType.MULTI_LOCATION in {left.location_type, right.location_type}:
        return False
    both_london = all(
        any(term in location for term in ("london", "westminster"))
        for location in (left_location, right_location)
    )
    return not both_london


def deduplicate(roles: Iterable[RoleRecord]) -> list[RoleRecord]:
    groups: list[tuple[set[str], RoleRecord]] = []
    for role in roles:
        keys = dedupe_keys(role)
        matches = [
            index
            for index, (known, existing) in enumerate(groups)
            if known & keys and not _materially_distinct(existing, role)
        ]
        if not matches:
            groups.append((keys, role))
            continue
        base_index = matches[0]
        merged_keys, merged_role = groups[base_index]
        merged_keys |= keys
        merged_role = _merge(merged_role, role)
        for index in reversed(matches[1:]):
            extra_keys, extra_role = groups.pop(index)
            merged_keys |= extra_keys
            merged_role = _merge(merged_role, extra_role)
        groups[base_index] = (merged_keys, merged_role)
    return [role for _, role in groups]

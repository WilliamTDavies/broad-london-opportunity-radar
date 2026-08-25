from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

import httpx
import yaml

from opportunity_radar.adapters import create_adapter
from opportunity_radar.classification import (
    classify_role,
    is_possible_role,
    is_public_role,
    load_classification_rules,
    stable_role_id,
)
from opportunity_radar.config import load_employers, load_overrides, load_radar
from opportunity_radar.models import (
    EligibilityStatus,
    EmployerConfig,
    ProgrammeStatus,
    ProgrammeType,
    RawRole,
    RelevanceStatus,
    RoleRecord,
    SourceAuthority,
    SourceHealth,
    SourceHealthStatus,
)
from opportunity_radar.pipeline.changes import detect_role_changes
from opportunity_radar.pipeline.deduplication import dedupe_keys, deduplicate
from opportunity_radar.pipeline.lifecycle import apply_closure_safeguards
from opportunity_radar.storage import JsonStore

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScanSummary:
    sources_attempted: int
    sources_succeeded: int
    observations: int
    public_roles: int
    possible_roles: int
    review_items: int
    changed_files: int


class HostRateLimiter:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_request: dict[str, float] = {}

    async def wait(self, endpoint: str | None, requests_per_minute: int) -> None:
        if not endpoint:
            return
        host = urlsplit(endpoint).netloc.casefold()
        async with self._locks[host]:
            minimum_interval = 60 / requests_per_minute
            delay = minimum_interval - (monotonic() - self._last_request.get(host, 0.0))
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request[host] = monotonic()


def compare_source_health(current: SourceHealth, previous: SourceHealth | None) -> SourceHealth:
    changed = bool(
        current.content_hash
        and previous
        and previous.content_hash
        and current.content_hash != previous.content_hash
    )
    if not changed:
        return current
    return current.model_copy(
        update={
            "status": (
                SourceHealthStatus.DEGRADED
                if current.status == SourceHealthStatus.HEALTHY
                else current.status
            ),
            "changed_since_last_success": True,
            "message": "Official source content changed; review the source before closure decisions",
        }
    )


def reconcile_source_health(
    source: EmployerConfig, current: SourceHealth, previous: SourceHealth | None
) -> SourceHealth:
    """Flag opaque page-watch changes, while accepting expected live-feed inventory changes."""

    reconciled = compare_source_health(current, previous) if source.monitor_only else current
    if previous and reconciled.last_success_at is None:
        reconciled = reconciled.model_copy(
            update={
                "last_success_at": previous.last_success_at,
                "content_hash": reconciled.content_hash or previous.content_hash,
            }
        )
    return reconciled


def _fixture_path(root: Path, source: EmployerConfig) -> Path:
    if not source.fixture:
        raise ValueError(f"Fixture source {source.id} has no fixture path")
    return root / source.fixture


def _load_fixture_sources(root: Path) -> list[EmployerConfig]:
    path = root / "fixtures" / "sources.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [EmployerConfig.model_validate(item) for item in data.get("sources", [])]


def _poll_due(source: EmployerConfig, previous: SourceHealth | None, *, now: datetime) -> bool:
    if source.poll_interval_minutes == 0 or previous is None:
        return True
    if previous.status in {SourceHealthStatus.FAILED, SourceHealthStatus.DISABLED}:
        return True
    if not previous.parser_ok:
        return True
    return previous.checked_at + timedelta(minutes=source.poll_interval_minutes) <= now


def _policy_close_match(fresh: RoleRecord, existing_public: list[RoleRecord]) -> RoleRecord | None:
    """Match an ineligible refresh only to the same authoritative source record.

    A discovery board can carry a stale or incomplete copy of an official role. It must never
    close the stronger official record merely because application or natural-key dedupe overlaps.
    """

    if fresh.source_authority == SourceAuthority.DISCOVERY_ONLY_SOURCE:
        return None
    return next(
        (
            old
            for old in existing_public
            if old.source_registry_id == fresh.source_registry_id
            and (
                old.source_identifier == fresh.source_identifier
                or bool(dedupe_keys(old) & dedupe_keys(fresh))
            )
        ),
        None,
    )


def reconcile_stored_candidates(root: Path) -> dict[str, int]:
    """Reapply editable rules to stored candidates without contacting any source."""

    store = JsonStore(root)
    rules = load_classification_rules(root)
    open_public = [
        role
        for role in store.read_models("open_roles.json", RoleRecord)
        if is_public_role(role, rules)
    ]
    recent_public = [
        role
        for role in store.read_models("recent_roles.json", RoleRecord)
        if is_public_role(role, rules)
    ]
    public = [*open_public, *recent_public]
    public_ids = {role.id for role in public}
    candidates = deduplicate(
        [
            *store.read_models("possible_roles.json", RoleRecord),
            *store.read_models("review_queue.json", RoleRecord),
        ]
    )
    possible = [
        role
        for role in candidates
        if role.id not in public_ids
        and not any(dedupe_keys(role) & dedupe_keys(item) for item in public)
        and is_possible_role(role, rules)
    ]
    possible_ids = {role.id for role in possible}
    review = [
        role
        for role in candidates
        if role.id not in possible_ids
        and role.id not in public_ids
        and role.status != ProgrammeStatus.CLOSED
        and role.eligibility_status == EligibilityStatus.UNCERTAIN
        and role.programme_type != ProgrammeType.CYCLE_UNSTATED
        and role.relevance_status != RelevanceStatus.IRRELEVANT
    ]
    review.sort(
        key=lambda role: (role.published_date or role.first_seen_at.date(), role.last_seen_at),
        reverse=True,
    )
    review = review[: rules.review_queue_limit]
    changed = int(store.write("possible_roles.json", possible))
    changed += store.write("review_queue.json", review)
    metrics = store.read("metrics.json", {})
    if isinstance(metrics, dict):
        metrics["open_verified_roles"] = len(open_public)
        metrics["recent_cycle_unstated"] = len(recent_public)
        metrics["possible_roles"] = len(possible)
        metrics["review_queue"] = len(review)
        metrics["coverage_warning"] = (
            f"{len(public)} verified roles and {len(possible)} possible roles from "
            f"{metrics.get('publishing_sources', 0)} role-producing sources; "
            f"{metrics.get('monitor_only_sources', 0)} additional official pages are "
            "change-monitored but cannot publish roles by themselves. Coverage is selective, "
            "not comprehensive; curated records require scheduled official-page re-verification."
        )
        changed += store.write("metrics.json", metrics)
    return {"possible_roles": len(possible), "review_items": len(review), "changed_files": changed}


async def _retrieve_one(
    root: Path,
    source: EmployerConfig,
    fixture_mode: bool,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    host_limiter: HostRateLimiter,
) -> tuple[EmployerConfig, list[RawRole], SourceHealth]:
    async with semaphore:
        checked_at = datetime.now(UTC)
        try:
            missing_environment = [
                name for name in source.required_env if not os.getenv(name, "").strip()
            ]
            if missing_environment and not fixture_mode:
                return (
                    source,
                    [],
                    SourceHealth(
                        source_id=source.id,
                        status=SourceHealthStatus.DISABLED,
                        checked_at=checked_at,
                        pages_scanned=0,
                        parser_ok=True,
                        message=(
                            "Credentialed source is ready but inactive; set "
                            + ", ".join(missing_environment)
                        ),
                    ),
                )
            adapter = create_adapter(source, client)
            if fixture_mode or (source.ats_type == "curated_yaml" and source.curated_file):
                source_file = (
                    _fixture_path(root, source) if fixture_mode else root / str(source.curated_file)
                )
                payload = source_file.read_bytes()
                roles = adapter.parse(payload)
                return (
                    source,
                    roles,
                    SourceHealth(
                        source_id=source.id,
                        status=SourceHealthStatus.HEALTHY,
                        checked_at=checked_at,
                        last_success_at=checked_at,
                        item_count=len(roles),
                        listing_count=len(roles),
                        candidate_count=len(roles),
                        pages_scanned=1,
                        content_hash=hashlib.sha256(payload).hexdigest(),
                        message=(
                            "Verified official records stored as a curated snapshot; "
                            "scheduled official-page re-verification remains required"
                            if not fixture_mode
                            else "Saved test fixture; never published as production data"
                        ),
                    ),
                )
            await host_limiter.wait(source.endpoint, source.requests_per_minute)
            result = await adapter.fetch()
            health = result.health
            if source.monitor_only and health.last_success_at:
                health = health.model_copy(
                    update={
                        "status": SourceHealthStatus.DEGRADED,
                        "message": "Monitor-only source: retrieval works but no role-level parser is configured",
                    }
                )
            return source, result.roles, health
        except Exception as exc:
            LOGGER.exception("source_failed", extra={"source_id": source.id})
            return (
                source,
                [],
                SourceHealth(
                    source_id=source.id,
                    status=SourceHealthStatus.FAILED,
                    checked_at=checked_at,
                    parser_ok=False,
                    message=str(exc),
                ),
            )


async def scan(
    root: Path,
    *,
    fixture_mode: bool = False,
    source_filter: str | None = None,
    category_filter: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ScanSummary:
    data_directory = root / "build" / "fixture-data" if fixture_mode else root / "data"
    store = JsonStore(root, data_directory)
    previous_health = {
        item.source_id: item for item in store.read_models("source_health.json", SourceHealth)
    }
    employers = load_employers(root)
    selected = (
        _load_fixture_sources(root)
        if fixture_mode
        else [source for source in employers if source.enabled]
    )
    if source_filter:
        selected = [source for source in selected if source.id == source_filter]
        if not selected:
            raise ValueError(f"Unknown or disabled source filter: {source_filter}")
    elif not fixture_mode:
        cadence_now = datetime.now(UTC)
        selected = [
            source
            for source in selected
            if _poll_due(source, previous_health.get(source.id), now=cadence_now)
        ]
    overrides = load_overrides(root)
    rules = load_classification_rules(root)
    if category_filter:
        valid_categories = {normalise_slug(category) for category in rules.categories}
        if category_filter not in valid_categories:
            raise ValueError(f"Unknown category filter: {category_filter}")
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
    semaphore = asyncio.Semaphore(6)
    host_limiter = HostRateLimiter()
    async with httpx.AsyncClient(
        limits=limits,
        follow_redirects=True,
        trust_env=not fixture_mode,
        transport=transport,
    ) as client:
        results = await asyncio.gather(
            *[
                _retrieve_one(root, source, fixture_mode, client, semaphore, host_limiter)
                for source in selected
            ]
        )
    observed_at = datetime.now(UTC)
    classified: list[RoleRecord] = []
    health_records: list[SourceHealth] = []
    source_change_observations: list[dict[str, object]] = []
    for source, raw_roles, raw_health in results:
        health = reconcile_source_health(source, raw_health, previous_health.get(source.id))
        health_records.append(health)
        if health.changed_since_last_success:
            source_change_observations.append(
                {
                    "source_id": source.id,
                    "observed_at": observed_at.isoformat(),
                    "changes": ["official_source_page_changed"],
                    "source_url": source.endpoint,
                    "content_hash": health.content_hash,
                }
            )
        for raw in raw_roles:
            role = classify_role(
                raw,
                source,
                observed_at=observed_at,
                override=overrides.get(stable_role_id(raw)),
                rules=rules,
            ).model_copy(update={"source_health_at_last_check": health.status})
            if category_filter and normalise_slug(role.primary_category) != category_filter:
                continue
            classified.append(role)
    roles = deduplicate(classified)
    existing_possible = store.read_models("possible_roles.json", RoleRecord)
    existing_review = store.read_models("review_queue.json", RoleRecord)
    existing_candidates = [*existing_possible, *existing_review]
    existing_closed = store.read_models("closed_roles.json", RoleRecord)
    existing_public = [
        *store.read_models("open_roles.json", RoleRecord),
        *store.read_models("recent_roles.json", RoleRecord),
    ]
    existing_all = [*existing_public, *existing_closed]
    comparison_existing = [*existing_all, *existing_candidates]
    raw_observations: list[dict[str, object]] = []
    for role in roles:
        previous = next(
            (
                old
                for old in comparison_existing
                if (
                    (
                        old.source_registry_id == role.source_registry_id
                        and old.source_identifier == role.source_identifier
                    )
                    or bool(dedupe_keys(old) & dedupe_keys(role))
                )
            ),
            None,
        )
        raw_observations.append(
            {
                "role_id": role.id,
                "source_id": role.source_registry_id,
                "source_identifier": role.source_identifier,
                "observed_at": observed_at.isoformat(),
                "source_url": role.canonical_url,
                "changes": detect_role_changes(previous, role),
            }
        )
    lifecycle_candidates = [
        role
        for role in roles
        if is_public_role(role.model_copy(update={"status": ProgrammeStatus.OPEN}), rules)
    ]
    selected_source_ids = {source.id for source in selected}
    lifecycle_health = (
        {}
        if category_filter
        else {
            item.source_id: item for item in health_records if item.source_id in selected_source_ids
        }
    )
    processed, missing_closed = apply_closure_safeguards(
        existing_all,
        lifecycle_candidates,
        lifecycle_health,
        now=observed_at,
    )
    # A fetched role whose current evidence fails the publication boundary must disappear
    # immediately; it is not a missing-role case and must not retain stale eligible wording.
    non_public_fresh = [
        role
        for role in roles
        if role.status != ProgrammeStatus.CLOSED
        and not is_public_role(role.model_copy(update={"status": ProgrammeStatus.OPEN}), rules)
    ]
    policy_closed: list[RoleRecord] = []
    for fresh in non_public_fresh:
        matching = _policy_close_match(fresh, existing_public)
        if not matching:
            continue
        processed = [item for item in processed if item.id != matching.id]
        policy_closed.append(
            fresh.model_copy(
                update={
                    "id": matching.id,
                    "first_seen_at": matching.first_seen_at,
                    "status": ProgrammeStatus.CLOSED,
                    "closed_at": observed_at,
                    "closure_reason": "Current official evidence no longer meets the publication boundary",
                    "closure_evidence": fresh.canonical_url,
                    "consecutive_missing_count": 0,
                }
            )
        )
    processed.extend(policy_closed)
    public = [role for role in processed if role.status != ProgrammeStatus.CLOSED]
    newly_closed = [role for role in processed if role.status == ProgrammeStatus.CLOSED]
    for role in missing_closed:
        raw_observations.append(
            {
                "role_id": role.id,
                "source_id": role.source_registry_id,
                "source_identifier": role.source_identifier,
                "observed_at": observed_at.isoformat(),
                "source_url": role.canonical_url,
                "changes": ["confirmed_removal_after_three_scans"],
            }
        )
    closed_by_id = {role.id: role for role in [*existing_closed, *newly_closed]}
    recent = [role for role in public if role.programme_type == ProgrammeType.CYCLE_UNSTATED]
    open_roles = [role for role in public if role.programme_type != ProgrammeType.CYCLE_UNSTATED]
    current_possible: list[RoleRecord] = []
    for role in roles:
        if not is_possible_role(role, rules):
            continue
        previous = next(
            (
                old
                for old in existing_candidates
                if (
                    (
                        old.source_registry_id == role.source_registry_id
                        and old.source_identifier == role.source_identifier
                    )
                    or bool(dedupe_keys(old) & dedupe_keys(role))
                )
            ),
            None,
        )
        current_possible.append(
            role.model_copy(
                update={
                    "first_seen_at": previous.first_seen_at if previous else role.first_seen_at,
                    "last_seen_at": observed_at,
                }
            )
        )
    replaceable_source_ids = {
        health.source_id
        for health in health_records
        if health.source_id in selected_source_ids
        and health.status == SourceHealthStatus.HEALTHY
        and health.parser_ok
        and not health.capped
        and not health.changed_since_last_success
    }
    fresh_identifiers = {(role.source_registry_id, role.source_identifier) for role in roles}
    fresh_keys_by_source: dict[str, set[str]] = defaultdict(set)
    for role in roles:
        fresh_keys_by_source[role.source_registry_id].update(dedupe_keys(role))

    def was_fetched_now(existing: RoleRecord) -> bool:
        return (
            existing.source_registry_id,
            existing.source_identifier,
        ) in fresh_identifiers or bool(
            dedupe_keys(existing) & fresh_keys_by_source.get(existing.source_registry_id, set())
        )

    retained_possible = [
        role
        for role in existing_candidates
        if is_possible_role(role, rules)
        and role.source_registry_id not in replaceable_source_ids
        and not was_fetched_now(role)
    ]
    verified_ids = {role.id for role in public}
    possible = [
        role
        for role in deduplicate([*retained_possible, *current_possible])
        if role.id not in verified_ids
        and not any(dedupe_keys(role) & dedupe_keys(item) for item in public)
    ]
    current_review = [
        role
        for role in roles
        if role.status != ProgrammeStatus.CLOSED
        and role.eligibility_status == EligibilityStatus.UNCERTAIN
        and role.programme_type != ProgrammeType.CYCLE_UNSTATED
        and not is_possible_role(role, rules)
        and role.relevance_status.value != "irrelevant"
    ]
    retained_review = [
        role
        for role in existing_review
        if not is_possible_role(role, rules)
        and role.programme_type != ProgrammeType.CYCLE_UNSTATED
        and role.source_registry_id not in replaceable_source_ids
        and not was_fetched_now(role)
    ]
    review = deduplicate([*retained_review, *current_review])
    review.sort(
        key=lambda role: (role.published_date or role.first_seen_at.date(), role.last_seen_at),
        reverse=True,
    )
    review = review[: rules.review_queue_limit]
    changed = 0
    changed += store.write("open_roles.json", open_roles)
    changed += store.write("recent_roles.json", recent)
    changed += store.write("possible_roles.json", possible)
    changed += store.write("review_queue.json", review)
    changed += store.write("closed_roles.json", list(closed_by_id.values()))
    previous_observations = store.read("observations.json", [])
    retention_cutoff = observed_at.timestamp() - (90 * 24 * 60 * 60)
    retained_observations = []
    for item in previous_observations:
        try:
            timestamp = datetime.fromisoformat(str(item["observed_at"])).timestamp()
        except (KeyError, TypeError, ValueError):
            continue
        if timestamp >= retention_cutoff:
            retained_observations.append(item)
    changed += store.write(
        "observations.json",
        [
            *retained_observations,
            *source_change_observations,
            *raw_observations,
        ][-5000:],
    )
    selected_ids = {item.source_id for item in health_records}
    health_records = [
        *health_records,
        *[item for key, item in previous_health.items() if key not in selected_ids],
    ]
    changed += store.write("source_health.json", health_records)
    changed += store.write(
        "upcoming_roles.json", [item.model_dump(mode="json") for item in load_radar(root)]
    )
    if not (store.data / "digest_state.json").exists():
        changed += store.write(
            "digest_state.json",
            {
                "sent_role_ids": [],
                "successful_runs": [],
                "last_successful_digest_at": None,
            },
        )
    active_registry = (
        selected if fixture_mode else [source for source in employers if source.enabled]
    )
    publishing_sources = [source for source in active_registry if not source.monitor_only]
    watched_pages = [source for source in active_registry if source.monitor_only]
    coverage_warning = (
        "Synthetic fixture coverage for pipeline testing only; no fixture role is production data."
        if fixture_mode
        else (
            f"{len(public)} verified roles and {len(possible)} possible roles from "
            f"{len(publishing_sources)} role-producing sources; "
            f"{len(watched_pages)} additional official pages are change-monitored but cannot "
            "publish roles by themselves. Coverage is selective, not comprehensive; curated "
            "records require scheduled official-page re-verification."
        )
    )
    metrics = {
        "data_updated_at": observed_at.isoformat(),
        "open_verified_roles": len(open_roles),
        "recent_cycle_unstated": len(recent),
        "possible_roles": len(possible),
        "review_queue": len(review),
        "employers_monitored": len(active_registry),
        "publishing_sources": len(publishing_sources),
        "monitor_only_sources": len(watched_pages),
        "healthy_sources": sum(
            item.status == SourceHealthStatus.HEALTHY for item in health_records
        ),
        "failed_sources": sum(item.status == SourceHealthStatus.FAILED for item in health_records),
        "listings_scanned": sum(item.listing_count for item in health_records),
        "coverage_warning": coverage_warning,
    }
    changed += store.write("metrics.json", metrics)
    selected_ids = {source.id for source in selected}
    return ScanSummary(
        sources_attempted=len(selected),
        sources_succeeded=sum(
            item.status != SourceHealthStatus.FAILED
            and item.last_success_at is not None
            and item.source_id in selected_ids
            for item in health_records
        ),
        observations=len(classified),
        public_roles=len(public),
        possible_roles=len(possible),
        review_items=len(review),
        changed_files=changed,
    )


def normalise_slug(value: str) -> str:
    return "-".join(value.casefold().replace("&", "and").split())

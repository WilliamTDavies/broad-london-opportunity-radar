from __future__ import annotations

from datetime import UTC, datetime

from opportunity_radar.models import ProgrammeStatus, RoleRecord, SourceHealth, SourceHealthStatus
from opportunity_radar.pipeline.deduplication import dedupe_keys


def apply_closure_safeguards(
    existing: list[RoleRecord],
    observed: list[RoleRecord],
    health: dict[str, SourceHealth],
    *,
    now: datetime | None = None,
) -> tuple[list[RoleRecord], list[RoleRecord]]:
    checked_at = now or datetime.now(UTC)
    existing_keys = {role.id: dedupe_keys(role) for role in existing}
    seen_existing_ids: set[str] = set()
    retained: list[RoleRecord] = []
    newly_closed: list[RoleRecord] = []
    for fresh in observed:
        matching = next(
            (
                old
                for old in existing
                if old.id not in seen_existing_ids
                and (
                    (
                        old.source_registry_id == fresh.source_registry_id
                        and old.source_identifier == fresh.source_identifier
                    )
                    or bool(existing_keys[old.id] & dedupe_keys(fresh))
                )
            ),
            None,
        )
        if not matching:
            retained.append(fresh)
            continue
        seen_existing_ids.add(matching.id)
        retained.append(
            fresh.model_copy(
                update={
                    "id": matching.id,
                    "first_seen_at": min(matching.first_seen_at, fresh.first_seen_at),
                    "last_seen_at": max(matching.last_seen_at, fresh.last_seen_at),
                    "consecutive_missing_count": 0,
                    "all_source_urls": list(
                        dict.fromkeys([*matching.all_source_urls, *fresh.all_source_urls])
                    ),
                }
            )
        )
    for old in existing:
        if old.id in seen_existing_ids or old.status == ProgrammeStatus.CLOSED:
            continue
        source = health.get(old.source_registry_id) or health.get(old.source_type)
        safe_scan = bool(
            source
            and source.status == SourceHealthStatus.HEALTHY
            and not source.capped
            and source.parser_ok
        )
        if not safe_scan:
            retained.append(old)
            continue
        assert source is not None
        missing = old.consecutive_missing_count + 1
        update: dict[str, object] = {"consecutive_missing_count": missing}
        if missing >= 3:
            update.update(
                {
                    "status": ProgrammeStatus.CLOSED,
                    "closed_at": checked_at,
                    "closure_reason": "Absent from three consecutive successful uncapped scans",
                    "closure_evidence": source.source_id,
                }
            )
            closed = old.model_copy(update=update)
            newly_closed.append(closed)
            continue
        retained.append(old.model_copy(update=update))
    return retained, newly_closed


def should_increment_missing(health: SourceHealth) -> bool:
    return health.status == SourceHealthStatus.HEALTHY and not health.capped and health.parser_ok

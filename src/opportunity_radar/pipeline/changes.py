from __future__ import annotations

from opportunity_radar.models import ProgrammeStatus, RoleRecord


def detect_role_changes(previous: RoleRecord | None, current: RoleRecord) -> list[str]:
    if previous is None:
        return ["newly_published"]
    changes: list[str] = []
    if previous.application_url != current.application_url:
        changes.append("application_link_changed")
    if previous.opening_date != current.opening_date:
        changes.append("opening_date_changed")
    if previous.deadline != current.deadline:
        changes.append("closing_date_changed")
    if (previous.programme_start, previous.programme_end) != (
        current.programme_start,
        current.programme_end,
    ):
        changes.append("programme_dates_changed")
    if previous.eligibility_status != current.eligibility_status or [
        item.text for item in previous.eligibility_evidence
    ] != [item.text for item in current.eligibility_evidence]:
        changes.append("eligibility_wording_changed")
    if (previous.location, previous.geographic_scope) != (
        current.location,
        current.geographic_scope,
    ):
        changes.append("location_changed")
    if previous.programme_type != current.programme_type:
        changes.append("cycle_or_programme_type_changed")
    if previous.status != current.status:
        if current.status == ProgrammeStatus.OPEN:
            changes.append("applications_reopened")
        elif current.status == ProgrammeStatus.CLOSED:
            changes.append("confirmed_closure")
        elif current.status == ProgrammeStatus.UPCOMING:
            changes.append("future_opening_announced")
    return changes or ["observed_unchanged"]

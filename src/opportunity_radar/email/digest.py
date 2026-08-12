from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx

from opportunity_radar.models import (
    EligibilityStatus,
    GeographicScope,
    ProgrammeStatus,
    ProgrammeType,
    RelevanceStatus,
    RoleRecord,
    SourceAuthority,
)
from opportunity_radar.storage import JsonStore


@dataclass(frozen=True, slots=True)
class DigestMessage:
    subject: str
    html: str
    text: str
    role_ids: list[str]
    digest_id: str


@dataclass(frozen=True, slots=True)
class DigestResult:
    digest_id: str
    role_count: int
    recipient_count: int
    sent_count: int
    no_send: bool
    preview_html: str | None = None
    preview_text: str | None = None


class EmailTransport(Protocol):
    def send(
        self,
        *,
        recipient: str,
        subject: str,
        html_body: str,
        text_body: str,
        unsubscribe_url: str,
        idempotency_key: str,
    ) -> None: ...


class InMemoryTransport:
    def __init__(self) -> None:
        self.deliveries: list[dict[str, str]] = []
        self._keys: set[str] = set()

    def send(
        self,
        *,
        recipient: str,
        subject: str,
        html_body: str,
        text_body: str,
        unsubscribe_url: str,
        idempotency_key: str,
    ) -> None:
        if idempotency_key in self._keys:
            return
        self._keys.add(idempotency_key)
        self.deliveries.append(
            {
                "recipient": recipient,
                "subject": subject,
                "html": html_body,
                "text": text_body,
                "unsubscribe_url": unsubscribe_url,
                "idempotency_key": idempotency_key,
            }
        )


class ResendTransport:
    def __init__(self, api_key: str, from_email: str) -> None:
        self.api_key = api_key
        self.from_email = from_email

    def send(
        self,
        *,
        recipient: str,
        subject: str,
        html_body: str,
        text_body: str,
        unsubscribe_url: str,
        idempotency_key: str,
    ) -> None:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Idempotency-Key": idempotency_key,
            },
            json={
                "from": self.from_email,
                "to": [recipient],
                "subject": subject,
                "html": html_body,
                "text": text_body,
                "headers": {
                    "List-Unsubscribe": f"<{unsubscribe_url}>",
                    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                },
            },
            timeout=20.0,
        )
        response.raise_for_status()


def eligible_for_digest(role: RoleRecord) -> bool:
    status_ok = role.eligibility_status in {EligibilityStatus.VERIFIED, EligibilityStatus.MANUAL}
    if role.eligibility_status == EligibilityStatus.LIKELY:
        status_ok = role.email_approved
    relevance_ok = role.relevance_status in {RelevanceStatus.STRONG, RelevanceStatus.CREDIBLE}
    if role.relevance_status == RelevanceStatus.BORDERLINE:
        relevance_ok = bool(role.manual_override)
    return (
        status_ok
        and relevance_ok
        and role.status == ProgrammeStatus.OPEN
        and role.geographic_scope in {GeographicScope.LONDON, GeographicScope.UK_PRIORITY_EXCEPTION}
        and role.source_authority != SourceAuthority.DISCOVERY_ONLY_SOURCE
        and not role.publication_review_required
        and role.paid is not False
    )


def _digest_order(role: RoleRecord, current: datetime) -> tuple[int, str, str]:
    if role.eligibility_status == EligibilityStatus.VERIFIED:
        group = 0
    elif role.eligibility_status == EligibilityStatus.MANUAL:
        group = 1
    elif role.deadline and role.deadline <= current.date() + timedelta(days=7):
        group = 2
    elif "vacation_scheme" in role.programme_type.value:
        group = 3
    elif role.programme_type == ProgrammeType.SUMMER_INTERNSHIP:
        group = 4
    elif role.programme_type in {ProgrammeType.POLICY_RESEARCH, ProgrammeType.PARLIAMENTARY}:
        group = 5
    else:
        group = 6
    return group, role.canonical_employer.casefold(), role.title.casefold()


def build_digest(
    roles: list[RoleRecord],
    *,
    already_sent: set[str],
    site_url: str,
    now: datetime | None = None,
) -> DigestMessage | None:
    created_at = now or datetime.now(UTC)
    selected = [role for role in roles if role.id not in already_sent and eligible_for_digest(role)]
    if not selected:
        return None
    selected.sort(key=lambda role: _digest_order(role, created_at))
    role_ids = [role.id for role in selected]
    digest_id = hashlib.sha256("|".join(role_ids).encode()).hexdigest()[:20]
    html_items: list[str] = []
    text_items: list[str] = []
    for role in selected:
        reason = role.relevance_reasons[0] if role.relevance_reasons else "Relevant approved role"
        location = (
            "UK priority exception"
            if role.geographic_scope.value == "uk_priority_exception"
            else role.location
        )
        deadline = role.deadline.isoformat() if role.deadline else "Not stated"
        dashboard_url = f"{site_url.rstrip('/')}/#role-{role.id}"
        html_items.append(
            "<li><strong>"
            f"{html.escape(role.canonical_employer)} — {html.escape(role.title)}</strong><br>"
            f"{html.escape(role.primary_category)} · {html.escape(role.programme_type.value)} · "
            f"{html.escape(location)}<br>Deadline: {deadline} · "
            f"{html.escape(role.eligibility_status.value)}<br>{html.escape(reason)}<br>"
            f'<a href="{html.escape(role.application_url)}">Apply</a> · '
            f'<a href="{html.escape(dashboard_url)}">Dashboard record</a></li>'
        )
        text_items.append(
            f"{role.canonical_employer} — {role.title}\n"
            f"{role.primary_category} | {role.programme_type.value} | {location}\n"
            f"Deadline: {deadline} | {role.eligibility_status.value}\n{reason}\n"
            f"Apply: {role.application_url}\nRecord: {dashboard_url}"
        )
    subject = (
        f"London Opportunity Radar: {len(selected)} new role{'s' if len(selected) != 1 else ''}"
    )
    html_body = (
        '<!doctype html><html lang="en-GB"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<style>body{margin:0;background:#f4f6f5;color:#16242c;font:16px/1.5 Arial,sans-serif}"
        ".wrap{max-width:680px;margin:auto;background:#fff;padding:24px}li{margin:0 0 24px}"
        "a{color:#075a78}strong{font-size:18px}@media(max-width:560px){.wrap{padding:16px}}</style>"
        '</head><body><div class="wrap"><h1>London Opportunity Radar</h1>'
        "<p>You are receiving this because you confirmed a daily opportunity alert subscription.</p>"
        f"<ol>{''.join(html_items)}</ol>"
        f'<p><a href="{html.escape(site_url)}">View the dashboard</a> · '
        f'<a href="{html.escape(site_url.rstrip("/"))}/#privacy">Privacy</a></p>'
        '<p><a href="{{UNSUBSCRIBE_URL}}">Unsubscribe</a></p></div></body></html>'
    )
    text_body = (
        "London Opportunity Radar\n\n"
        "You are receiving this because you confirmed a daily opportunity alert subscription.\n\n"
        + "\n\n".join(text_items)
        + f"\n\nDashboard: {site_url}\nPrivacy: {site_url.rstrip('/')}/#privacy"
        + "\nUnsubscribe: {{UNSUBSCRIBE_URL}}\n"
    )
    return DigestMessage(subject, html_body, text_body, role_ids, digest_id)


def _load_roles(store: JsonStore) -> list[RoleRecord]:
    return [
        *store.read_models("open_roles.json", RoleRecord),
        *store.read_models("recent_roles.json", RoleRecord),
    ]


def run_digest(
    root: Path,
    *,
    dry_run: bool,
    recipients: list[str] | None = None,
    transport: EmailTransport | None = None,
    now: datetime | None = None,
    fixture_mode: bool = False,
    preview_directory: Path | None = None,
) -> DigestResult:
    data_directory = root / "build" / "fixture-data" if fixture_mode else root / "data"
    store = JsonStore(root, data_directory)
    state = store.read(
        "digest_state.json",
        {"sent_role_ids": [], "successful_runs": [], "last_successful_digest_at": None},
    )
    previous_success = state.get("last_successful_digest_at")
    last_success = datetime.fromisoformat(previous_success) if previous_success else None
    candidate_roles = [
        role
        for role in _load_roles(store)
        if last_success is None or role.last_seen_at > last_success
    ]
    message = build_digest(
        candidate_roles,
        already_sent=set(state.get("sent_role_ids", [])),
        site_url=os.getenv("SITE_URL", "https://example.github.io/london-opportunity-radar"),
        now=now,
    )
    run_at = now or datetime.now(UTC)
    if message is None:
        state["successful_runs"] = [
            *state.get("successful_runs", []),
            {"at": run_at.isoformat(), "outcome": "no_new_roles"},
        ][-100:]
        state["last_successful_digest_at"] = run_at.isoformat()
        if not dry_run:
            store.write("digest_state.json", state)
        return DigestResult("no-send", 0, len(recipients or []), 0, True)
    preview_html: str | None = None
    preview_text: str | None = None
    if dry_run and preview_directory:
        preview_directory.mkdir(parents=True, exist_ok=True)
        preview_unsubscribe = "https://example.invalid/unsubscribe-preview"
        html_path = preview_directory / "digest.html"
        text_path = preview_directory / "digest.txt"
        html_path.write_text(
            message.html.replace("{{UNSUBSCRIBE_URL}}", preview_unsubscribe), encoding="utf-8"
        )
        text_path.write_text(
            message.text.replace("{{UNSUBSCRIBE_URL}}", preview_unsubscribe), encoding="utf-8"
        )
        preview_html = str(html_path)
        preview_text = str(text_path)
    if recipients is None:
        recipients = [] if dry_run else _subscribers_from_supabase(message.digest_id)
    if not recipients and not dry_run:
        state["sent_role_ids"] = list(
            dict.fromkeys([*state.get("sent_role_ids", []), *message.role_ids])
        )
        state["successful_runs"] = [
            *state.get("successful_runs", []),
            {"at": run_at.isoformat(), "outcome": "no_confirmed_recipients"},
        ][-100:]
        state["last_successful_digest_at"] = run_at.isoformat()
        store.write("digest_state.json", state)
        return DigestResult(
            message.digest_id,
            len(message.role_ids),
            0,
            0,
            True,
            preview_html,
            preview_text,
        )
    production_transport = transport is None and not dry_run
    if transport is None:
        if dry_run:
            transport = InMemoryTransport()
        else:
            transport = ResendTransport(
                required_env("RESEND_API_KEY"), required_env("RESEND_FROM_EMAIL")
            )
    sent = 0
    for recipient in recipients:
        token = secrets.token_urlsafe(32)
        unsubscribe = (
            f"{required_env('SUPABASE_URL')}/functions/v1/unsubscribe?token={token}"
            if production_transport
            else f"https://example.invalid/unsubscribe?token={token}"
        )
        if production_transport:
            _store_unsubscribe_hash(recipient, token)
        try:
            transport.send(
                recipient=recipient,
                subject=message.subject,
                html_body=message.html.replace("{{UNSUBSCRIBE_URL}}", unsubscribe),
                text_body=message.text.replace("{{UNSUBSCRIBE_URL}}", unsubscribe),
                unsubscribe_url=unsubscribe,
                idempotency_key=(
                    f"{message.digest_id}:{hashlib.sha256(recipient.encode()).hexdigest()[:16]}"
                ),
            )
        except Exception:
            if production_transport:
                _mark_subscriber_delivery(recipient, failure="delivery_failed")
            raise
        if production_transport:
            _mark_subscriber_delivery(recipient, digest_id=message.digest_id)
        sent += 1
    if not dry_run:
        state["sent_role_ids"] = list(
            dict.fromkeys([*state.get("sent_role_ids", []), *message.role_ids])
        )
        state["successful_runs"] = [
            *state.get("successful_runs", []),
            {"at": run_at.isoformat(), "outcome": "sent", "digest_id": message.digest_id},
        ][-100:]
        state["last_successful_digest_at"] = run_at.isoformat()
        store.write("digest_state.json", state)
    return DigestResult(
        message.digest_id,
        len(message.role_ids),
        len(recipients),
        sent,
        False,
        preview_html,
        preview_text,
    )


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _supabase_headers() -> dict[str, str]:
    key = required_env("SUPABASE_SERVICE_ROLE_KEY")
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _subscribers_from_supabase(digest_id: str) -> list[str]:
    prune = httpx.post(
        f"{required_env('SUPABASE_URL')}/rest/v1/rpc/prune_subscription_state",
        headers=_supabase_headers(),
        content="{}",
        timeout=20.0,
    )
    prune.raise_for_status()
    response = httpx.get(
        f"{required_env('SUPABASE_URL')}/rest/v1/subscribers"
        "?status=eq.confirmed&select=email,last_digest_sent",
        headers=_supabase_headers(),
        timeout=20.0,
    )
    response.raise_for_status()
    return [item["email"] for item in response.json() if item.get("last_digest_sent") != digest_id]


def _store_unsubscribe_hash(email: str, token: str) -> None:
    token_hash = hmac.new(
        required_env("TOKEN_SECRET").encode(), token.encode(), hashlib.sha256
    ).hexdigest()
    response = httpx.post(
        f"{required_env('SUPABASE_URL')}/rest/v1/rpc/add_unsubscribe_token",
        headers=_supabase_headers(),
        content=json.dumps({"subscriber_email": email, "new_token_hash": token_hash}),
        timeout=20.0,
    )
    response.raise_for_status()


def _mark_subscriber_delivery(
    email: str, *, digest_id: str | None = None, failure: str | None = None
) -> None:
    update = {
        "last_digest_sent": digest_id,
        "delivery_failure_status": failure,
    }
    response = httpx.patch(
        f"{required_env('SUPABASE_URL')}/rest/v1/subscribers",
        params={"email": f"eq.{email}"},
        headers={**_supabase_headers(), "Prefer": "return=minimal"},
        json=update,
        timeout=20.0,
    )
    response.raise_for_status()

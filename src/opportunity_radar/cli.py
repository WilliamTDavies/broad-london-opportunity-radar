from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

from opportunity_radar.adapters.curl_transport import CurlTransport
from opportunity_radar.classification import is_public_role
from opportunity_radar.config import validate_all_config
from opportunity_radar.email import run_digest
from opportunity_radar.models import EligibilityStatus, ManualOverride, RelevanceStatus, RoleRecord
from opportunity_radar.pipeline import scan
from opportunity_radar.site import build_site
from opportunity_radar.storage import JsonStore
from opportunity_radar.validation import validate_repository


def repository_root() -> Path:
    configured = os.getenv("RADAR_ROOT")
    if configured:
        return Path(configured).resolve()
    working_directory = Path.cwd()
    if (working_directory / "config" / "employers.yml").exists():
        return working_directory
    return Path(__file__).resolve().parents[2]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="opportunity-radar")
    sub = result.add_subparsers(dest="command", required=True)
    scan_parser = sub.add_parser("scan")
    scan_parser.add_argument("--source")
    scan_parser.add_argument("--category")
    scan_parser.add_argument("--fixtures", action="store_true")
    scan_parser.add_argument(
        "--curl-transport",
        action="store_true",
        help="Use the no-shell curl fallback in a Python-network-restricted local sandbox",
    )
    role_commands = ("classify", "explain")
    for command in role_commands:
        command_parser = sub.add_parser(command)
        command_parser.add_argument("--role-id", required=True)
    approve = sub.add_parser("approve")
    approve.add_argument("--role-id", required=True)
    approve.add_argument("--reason")
    approve.add_argument("--evidence-url")
    approve.add_argument(
        "--relevance-status",
        choices=[
            RelevanceStatus.STRONG.value,
            RelevanceStatus.CREDIBLE.value,
            RelevanceStatus.BORDERLINE.value,
        ],
    )
    approve.add_argument("--email-approved", action="store_true")
    sub.add_parser("review-queue")
    build = sub.add_parser("build-site")
    build.add_argument("--fixtures", action="store_true")
    digest = sub.add_parser("digest")
    digest.add_argument("--dry-run", action="store_true")
    digest.add_argument("--fixtures", action="store_true")
    validate = sub.add_parser("validate")
    validate.add_argument("--fixtures", action="store_true")
    sub.add_parser("source-health")
    return result


def _all_roles(store: JsonStore) -> list[RoleRecord]:
    result: list[RoleRecord] = []
    for name in (
        "open_roles.json",
        "recent_roles.json",
        "possible_roles.json",
        "review_queue.json",
        "closed_roles.json",
    ):
        result.extend(store.read_models(name, RoleRecord))
    return list({role.id: role for role in result}.values())


def _find_role(store: JsonStore, role_id: str) -> RoleRecord:
    role = next((item for item in _all_roles(store) if item.id == role_id), None)
    if not role:
        raise ValueError(f"Unknown role ID: {role_id}")
    return role


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = parser().parse_args(argv)
    root = repository_root()
    store = JsonStore(root)
    try:
        if args.command == "scan":
            summary = asyncio.run(
                scan(
                    root,
                    fixture_mode=args.fixtures,
                    source_filter=args.source,
                    category_filter=args.category,
                    transport=CurlTransport() if args.curl_transport else None,
                )
            )
            print(json.dumps(asdict(summary), indent=2))
        elif args.command == "classify":
            role = _find_role(store, args.role_id)
            print(json.dumps(role.model_dump(mode="json"), indent=2))
        elif args.command == "explain":
            role = _find_role(store, args.role_id)
            print(f"{role.canonical_employer} — {role.title}")
            print(f"Eligibility: {role.eligibility_status.value}")
            for item in role.eligibility_evidence:
                print(f"  {item.rule_id}: {item.text} ({item.source_url})")
            print(f"Relevance: {role.relevance_status.value}")
            for reason in role.relevance_reasons:
                print(f"  {reason}")
            print(f"Match score: {role.match_score}/100 (not an acceptance probability)")
            for component, points in role.match_components.items():
                print(f"  {component}: {points}")
        elif args.command == "review-queue":
            for role in store.read_models("review_queue.json", RoleRecord):
                print(
                    f"{role.id}\t{role.eligibility_status}\t{role.canonical_employer}\t{role.title}"
                )
        elif args.command == "approve":
            role = _find_role(store, args.role_id)
            if not args.reason or not args.evidence_url:
                raise ValueError("approve requires --reason and --evidence-url")
            relevance = RelevanceStatus(args.relevance_status) if args.relevance_status else None
            override = ManualOverride(
                role_id=role.id,
                eligibility_status=EligibilityStatus.MANUAL,
                relevance_status=relevance,
                email_approved=args.email_approved,
                reason=args.reason,
                evidence_url=args.evidence_url,
                reviewed_at=datetime.now(UTC),
            )
            approved = role.model_copy(
                update={
                    "eligibility_status": EligibilityStatus.MANUAL,
                    "relevance_status": relevance or role.relevance_status,
                    "publication_review_required": False,
                    "manual_override": override.model_dump(mode="json"),
                    "email_approved": args.email_approved,
                }
            )
            if not is_public_role(approved):
                raise ValueError("The documented override does not make this role safe to publish")
            override_path = root / "config" / "manual_overrides.yml"
            document = yaml.safe_load(override_path.read_text(encoding="utf-8")) or {}
            existing = document.get("overrides", [])
            document["overrides"] = [
                *[item for item in existing if item.get("role_id") != role.id],
                override.model_dump(mode="json"),
            ]
            override_path.write_text(
                yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
            )
            print(f"Recorded documented override for {role.id}")
        elif args.command == "build-site":
            print(build_site(root, fixture_mode=args.fixtures))
        elif args.command == "digest":
            result = run_digest(
                root,
                dry_run=args.dry_run,
                fixture_mode=args.fixtures,
                preview_directory=(root / "build" / "digest-preview") if args.dry_run else None,
            )
            print(json.dumps(asdict(result), indent=2))
        elif args.command == "validate":
            messages = validate_all_config(root)
            build_site(root, fixture_mode=args.fixtures)
            repository_messages = validate_repository(root, fixture_mode=args.fixtures)
            print("\n".join([*messages, *repository_messages, "site build valid"]))
        elif args.command == "source-health":
            print(json.dumps(store.read("source_health.json", []), indent=2))
        else:
            return 2
    except (ValueError, RuntimeError, OSError) as exc:
        logging.error("%s", exc)
        return 1
    return 0

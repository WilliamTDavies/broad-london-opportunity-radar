from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from opportunity_radar.classification import is_possible_role, is_public_role
from opportunity_radar.models import RadarEntry, RoleRecord, SourceHealth

SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Resend API key": re.compile(r"\bre_[A-Za-z0-9_-]{24,}\b"),
    "JWT-like credential": re.compile(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
    ),
}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON {path}: {exc}") from exc


def validate_structured_state(root: Path, *, fixture_mode: bool = False) -> list[str]:
    data = root / "build" / "fixture-data" if fixture_mode else root / "data"
    role_files = (
        "open_roles.json",
        "recent_roles.json",
        "possible_roles.json",
        "closed_roles.json",
        "review_queue.json",
    )
    try:
        for filename in role_files:
            values = _load_json(data / filename)
            if not isinstance(values, list):
                raise ValueError(f"{data / filename} must contain a list")
            [RoleRecord.model_validate(item) for item in values]
        health = _load_json(data / "source_health.json")
        if not isinstance(health, list):
            raise ValueError("source_health.json must contain a list")
        [SourceHealth.model_validate(item) for item in health]
        radar = _load_json(data / "upcoming_roles.json")
        if not isinstance(radar, list):
            raise ValueError("upcoming_roles.json must contain a list")
        [RadarEntry.model_validate(item) for item in radar]
        for filename in ("observations.json", "metrics.json", "digest_state.json"):
            _load_json(data / filename)
    except ValidationError as exc:
        raise ValueError(f"Invalid structured state: {exc}") from exc
    return ["structured state valid"]


def validate_yaml_and_workflows(root: Path) -> list[str]:
    for path in sorted([*root.glob("config/*.yml"), *root.glob("fixtures/**/*.yml")]):
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f"Invalid YAML {path}: {exc}") from exc
    workflow_directory = root / ".github" / "workflows"
    required = {"ci.yml", "scan.yml", "deploy-pages.yml", "daily-digest.yml"}
    if {path.name for path in workflow_directory.glob("*.yml")} != required:
        raise ValueError("Workflow set does not match the four required workflow files")
    for path in workflow_directory.glob("*.yml"):
        try:
            value = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid workflow YAML {path}: {exc}") from exc
        if not isinstance(value, dict) or not {"name", "on", "permissions", "jobs"}.issubset(value):
            raise ValueError(f"Workflow {path} lacks a required top-level key")
        if not isinstance(value["permissions"], dict):
            raise ValueError(f"Workflow {path} must declare explicit permissions")
    return ["YAML and workflow structure valid"]


def scan_repository_hygiene(root: Path, *, fixture_mode: bool = False) -> list[str]:
    ignored_parts = {".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__", ".git"}
    findings: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in ignored_parts for part in path.parts):
            continue
        if path.name == ".env.example":
            if any(line.partition("=")[2] for line in path.read_text().splitlines() if "=" in line):
                findings.append(".env.example contains a value")
            continue
        if path.name == ".env" or path.name.startswith("subscribers."):
            findings.append(f"forbidden file: {path.relative_to(root)}")
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{label}: {path.relative_to(root)}")
    public_directories = [root / "data", root / "site" / "generated"]
    if fixture_mode:
        public_directories.extend(
            [root / "build" / "fixture-data", root / "build" / "fixture-site"]
        )
    email_pattern = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
    for directory in public_directories:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and email_pattern.search(
                path.read_text(encoding="utf-8", errors="ignore")
            ):
                findings.append(f"email address in public state: {path.relative_to(root)}")
    if findings:
        raise ValueError("Repository hygiene failed: " + "; ".join(sorted(set(findings))))
    return ["repository secret and subscriber-data scan valid"]


class _SurfaceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.links: list[str] = []
        self.has_main = False
        self.has_h1 = False
        self.language: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "html":
            self.language = values.get("lang")
        if tag == "main":
            self.has_main = True
        if tag == "h1":
            self.has_h1 = True
        if values.get("id"):
            self.ids.append(str(values["id"]))
        if tag == "a":
            self.links.append(str(values.get("href") or ""))


def validate_generated_site(root: Path, *, fixture_mode: bool = False) -> list[str]:
    generated = root / "build" / "fixture-site" if fixture_mode else root / "site" / "generated"
    html_path = generated / "index.html"
    markup = html_path.read_text(encoding="utf-8")
    if "{{" in markup or "YOUR_PROJECT" in markup:
        raise ValueError("Generated dashboard contains an unresolved template placeholder")
    parser = _SurfaceParser()
    parser.feed(markup)
    if parser.language != "en-GB" or not parser.has_main or not parser.has_h1:
        raise ValueError("Generated dashboard lacks required semantic document landmarks")
    if len(parser.ids) != len(set(parser.ids)):
        raise ValueError("Generated dashboard contains duplicate element IDs")
    if any(not link for link in parser.links):
        raise ValueError("Generated dashboard contains an empty link")
    for filename in (
        "styles.css",
        "app.js",
        "roles.json",
        "possible-roles.json",
        "role-index.json",
        "role-details.json",
        "METHODOLOGY.md",
        "PRIVACY.md",
    ):
        if not (generated / filename).is_file():
            raise ValueError(f"Generated dashboard is missing {filename}")
    css = (generated / "styles.css").read_text(encoding="utf-8")
    javascript = (generated / "app.js").read_text(encoding="utf-8")
    if "prefers-reduced-motion" not in css or ":focus-visible" not in css:
        raise ValueError("Generated dashboard lacks reduced-motion or keyboard-focus CSS")
    if "localStorage" not in javascript or "readSaved" not in javascript:
        raise ValueError("Generated dashboard lacks safe local saved-role behaviour")
    public_roles = _load_json(generated / "roles.json")
    for item in public_roles:
        role = RoleRecord.model_validate(item)
        if item.get("eligibility_status") in {"uncertain", "ineligible"}:
            raise ValueError("Uncertain or ineligible role leaked into public dashboard data")
        if "manual_override" in item:
            raise ValueError("Internal manual-override data leaked into public dashboard data")
        if not is_public_role(role):
            raise ValueError(
                "Role outside the verified publication boundary leaked into roles.json"
            )
    possible_roles = _load_json(generated / "possible-roles.json")
    for item in possible_roles:
        role = RoleRecord.model_validate(item)
        if item.get("eligibility_status") == "ineligible":
            raise ValueError("Ineligible role leaked into possible-opportunities data")
        if "manual_override" in item:
            raise ValueError(
                "Internal manual-override data leaked into possible-opportunities data"
            )
        if not is_possible_role(role):
            raise ValueError("Role outside the possible publication boundary leaked into data")
    if {item["id"] for item in public_roles} & {item["id"] for item in possible_roles}:
        raise ValueError("A role is duplicated across verified and possible public datasets")
    role_details = _load_json(generated / "role-details.json")
    expected_detail_ids = {item["id"] for item in [*public_roles, *possible_roles]}
    if not isinstance(role_details, dict) or set(role_details) != expected_detail_ids:
        raise ValueError("Lazy role details do not exactly cover the public role datasets")
    if any(
        not isinstance(value, str) or 'class="role-card' not in value or "{{" in value
        for value in role_details.values()
    ):
        raise ValueError("Lazy role details contain invalid role-card markup")
    role_index = _load_json(generated / "role-index.json")
    if (
        not isinstance(role_index, list)
        or {item.get("id") for item in role_index if isinstance(item, dict)} != expected_detail_ids
        or len(role_index) != len(expected_detail_ids)
    ):
        raise ValueError("Lazy role index does not exactly cover the public role datasets")
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("dataset"), dict)
        or not isinstance(item.get("html"), str)
        or 'class="role-row' not in item["html"]
        or "{{" in item["html"]
        for item in role_index
    ):
        raise ValueError("Lazy role index contains invalid row data")
    return ["generated dashboard structure and public boundary valid"]


def validate_repository(root: Path, *, fixture_mode: bool = False) -> list[str]:
    return [
        *validate_structured_state(root, fixture_mode=fixture_mode),
        *validate_yaml_and_workflows(root),
        *scan_repository_hygiene(root, fixture_mode=fixture_mode),
        *validate_generated_site(root, fixture_mode=fixture_mode),
    ]

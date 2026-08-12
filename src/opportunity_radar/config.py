from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ValidationError

from opportunity_radar.models import (
    EmployerConfig,
    ManualOverride,
    ProgrammeType,
    RadarEntry,
    SourceAuthority,
)


class ConfigurationError(ValueError):
    pass


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"{path} must contain a YAML mapping")
    return value


def _validated_list[T: BaseModel](path: Path, key: str, model: type[T]) -> list[T]:
    document = load_yaml(path)
    items = document.get(key)
    if not isinstance(items, list):
        raise ConfigurationError(f"{path}: '{key}' must be a list")
    try:
        return [model.model_validate(item) for item in items]
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid {path}: {exc}") from exc


def load_employers(root: Path) -> list[EmployerConfig]:
    employers = _validated_list(root / "config" / "employers.yml", "employers", EmployerConfig)
    ids = [item.id for item in employers]
    if len(ids) != len(set(ids)):
        raise ConfigurationError("Employer IDs must be unique")
    for employer in employers:
        if employer.enabled and not employer.endpoint:
            raise ConfigurationError(f"Enabled employer {employer.id} has no verified endpoint")
        if employer.uk_priority_exception and not employer.exception_reason:
            raise ConfigurationError(f"UK priority exception {employer.id} needs a reason")
        if (
            employer.enabled
            and employer.source_authority == SourceAuthority.DISCOVERY_ONLY_SOURCE
            and not employer.manual_review_required
        ):
            raise ConfigurationError(
                f"Discovery-only source {employer.id} must require review and can only feed "
                "the clearly labelled possible-roles layer"
            )
        if employer.request_method == "POST" and employer.request_body is None:
            raise ConfigurationError(f"POST source {employer.id} needs a request_body")
        for label, value in (
            ("careers_url", employer.careers_url),
            ("endpoint", employer.endpoint),
        ):
            if value and urlsplit(value).scheme not in {"http", "https"}:
                raise ConfigurationError(f"{employer.id} {label} must use HTTP(S)")
        if employer.curated_file:
            if employer.ats_type != "curated_yaml":
                raise ConfigurationError(
                    f"Curated file for {employer.id} requires the curated_yaml adapter"
                )
            curated = (root / employer.curated_file).resolve()
            if root.resolve() not in curated.parents or curated.suffix not in {".yml", ".yaml"}:
                raise ConfigurationError(
                    f"Curated file for {employer.id} must be a YAML file inside the repository"
                )
            if not curated.exists():
                raise ConfigurationError(f"Curated file for {employer.id} does not exist")
    return employers


def load_overrides(root: Path) -> dict[str, ManualOverride]:
    overrides = _validated_list(
        root / "config" / "manual_overrides.yml", "overrides", ManualOverride
    )
    return {item.role_id: item for item in overrides}


def load_radar(root: Path) -> list[RadarEntry]:
    return _validated_list(root / "config" / "radar.yml", "radar", RadarEntry)


def validate_all_config(root: Path) -> list[str]:
    load_employers(root)
    load_overrides(root)
    load_radar(root)
    required = [
        "trusted_sources.yml",
        "organisation_tiers.yml",
        "categories.yml",
        "programmes.yml",
        "eligibility_rules.yml",
        "relevance_rules.yml",
    ]
    for filename in required:
        load_yaml(root / "config" / filename)
    try:
        from opportunity_radar.adapters import ADAPTERS
        from opportunity_radar.classification import load_classification_rules

        load_classification_rules(root)
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc
    unsupported = sorted({item.ats_type for item in load_employers(root)} - set(ADAPTERS))
    if unsupported:
        raise ConfigurationError(f"Unsupported adapters in employer registry: {unsupported}")
    programmes = load_yaml(root / "config" / "programmes.yml").get("programme_types")
    expected_programmes = {item.value for item in ProgrammeType}
    if not isinstance(programmes, list) or set(programmes) != expected_programmes:
        raise ConfigurationError("programmes.yml must contain every ProgrammeType exactly once")
    trusted_document = load_yaml(root / "config" / "trusted_sources.yml")
    trusted = trusted_document.get("trusted_sources")
    if not isinstance(trusted, list) or not trusted:
        raise ConfigurationError(
            "trusted_sources.yml must contain a non-empty trusted_sources list"
        )
    for item in trusted:
        if not isinstance(item, dict) or item.get("authority") not in {
            SourceAuthority.TRUSTED_SECTOR_BOARD.value,
            SourceAuthority.OFFICIAL_GOVERNMENT_PORTAL.value,
        }:
            raise ConfigurationError("Trusted source entries need an approved primary authority")
        if urlsplit(str(item.get("url", ""))).scheme != "https":
            raise ConfigurationError("Trusted source URLs must use HTTPS")
    discovery = trusted_document.get("discovery_only_sources")
    if not isinstance(discovery, list):
        raise ConfigurationError("trusted_sources.yml needs a discovery_only_sources list")
    for item in discovery:
        if (
            not isinstance(item, dict)
            or item.get("authority") != SourceAuthority.DISCOVERY_ONLY_SOURCE.value
        ):
            raise ConfigurationError(
                "Discovery source entries need discovery_only_source authority"
            )
        if urlsplit(str(item.get("url", ""))).scheme != "https":
            raise ConfigurationError("Discovery source URLs must use HTTPS")
    return ["configuration valid"]

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class ClassificationRules:
    category_keywords: dict[str, tuple[str, ...]]
    verified_eligibility: dict[str, tuple[str, ...]]
    likely_eligibility: dict[str, tuple[str, ...]]
    hard_exclusions: tuple[str, ...]
    relevance_positive: dict[str, tuple[str, ...]]
    skill_alignment: dict[str, tuple[str, ...]]
    relevance_negative: tuple[str, ...]
    score_weights: dict[str, int]
    quality_controlled_types: frozenset[str]
    require_paid_types: frozenset[str]
    require_selectivity_types: frozenset[str]
    approved_quality_tiers: frozenset[str]

    @property
    def categories(self) -> frozenset[str]:
        return frozenset(self.category_keywords)


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return {str(key): item for key, item in value.items()}


def _term_mapping(value: object, *, label: str) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for key, terms in _mapping(value, label=label).items():
        if not isinstance(terms, list) or not all(isinstance(term, str) for term in terms):
            raise ValueError(f"{label}.{key} must be a list of strings")
        result[key] = tuple(terms)
    return result


def _string_list(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return tuple(value)


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Cannot load {path}: {exc}") from exc
    return _mapping(value, label=str(path))


def load_classification_rules(root: Path) -> ClassificationRules:
    categories = _read_mapping(root / "config" / "categories.yml")
    eligibility = _read_mapping(root / "config" / "eligibility_rules.yml")
    relevance = _read_mapping(root / "config" / "relevance_rules.yml")
    tiers = _read_mapping(root / "config" / "organisation_tiers.yml")

    taxonomy = _mapping(categories.get("categories"), label="categories.categories")
    taxonomy_categories: set[str] = set()
    for group, values in taxonomy.items():
        taxonomy_categories.update(_string_list(values, label=f"categories.categories.{group}"))
    category_keywords = _term_mapping(
        categories.get("category_keywords"), label="categories.category_keywords"
    )
    if set(category_keywords) != taxonomy_categories:
        missing = sorted(taxonomy_categories - set(category_keywords))
        extra = sorted(set(category_keywords) - taxonomy_categories)
        raise ValueError(f"Category keyword coverage mismatch; missing={missing}, extra={extra}")

    rules = _mapping(eligibility.get("rules"), label="eligibility_rules.rules")
    tier_values = _mapping(tiers.get("tiers"), label="organisation_tiers.tiers")
    quality_rules = _mapping(tiers.get("rules"), label="organisation_tiers.rules")
    score_weights_raw = _mapping(
        relevance.get("score_components"), label="relevance_rules.score_components"
    )
    score_weights: dict[str, int] = {}
    for key, value in score_weights_raw.items():
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"relevance_rules.score_components.{key} must be a non-negative int")
        score_weights[key] = value
    expected_components = {
        "eligibility_strength",
        "substantive_relevance",
        "skill_alignment",
        "organisation_quality",
        "geographic_fit",
        "recency",
        "deadline_urgency",
        "evidence_quality",
    }
    if set(score_weights) != expected_components or sum(score_weights.values()) != 100:
        raise ValueError("Score components must contain the eight required keys and total 100")

    controlled_types: set[str] = set()
    require_paid_types: set[str] = set()
    require_selectivity_types: set[str] = set()
    for organisation_type, raw_rule in quality_rules.items():
        rule = _mapping(raw_rule, label=f"organisation_tiers.rules.{organisation_type}")
        controlled_types.add(organisation_type)
        if rule.get("require_paid") is True:
            require_paid_types.add(organisation_type)
        if rule.get("require_selective") is True:
            require_selectivity_types.add(organisation_type)
    return ClassificationRules(
        category_keywords=category_keywords,
        verified_eligibility=_term_mapping(
            rules.get("verified_positive"), label="eligibility_rules.rules.verified_positive"
        ),
        likely_eligibility=_term_mapping(
            rules.get("likely_positive"), label="eligibility_rules.rules.likely_positive"
        ),
        hard_exclusions=_string_list(
            rules.get("hard_exclusions"), label="eligibility_rules.rules.hard_exclusions"
        ),
        relevance_positive=_term_mapping(
            relevance.get("positive"), label="relevance_rules.positive"
        ),
        skill_alignment=_term_mapping(
            relevance.get("skill_alignment"), label="relevance_rules.skill_alignment"
        ),
        relevance_negative=_string_list(
            relevance.get("negative"), label="relevance_rules.negative"
        ),
        score_weights=score_weights,
        quality_controlled_types=frozenset(controlled_types),
        require_paid_types=frozenset(require_paid_types),
        require_selectivity_types=frozenset(require_selectivity_types),
        approved_quality_tiers=frozenset(key for key in tier_values if key != "review"),
    )

from __future__ import annotations

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_web_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("URL must be an absolute HTTP(S) URL")
    return value


CONTACT_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)


def _redact_contact_email(value: str) -> str:
    return CONTACT_EMAIL_PATTERN.sub("[contact email on source]", value)


class SourceAuthority(StrEnum):
    OFFICIAL_ATS = "official_ats"
    OFFICIAL_CAREERS_PAGE = "official_careers_page"
    OFFICIAL_PROGRAMME_PAGE = "official_programme_page"
    OFFICIAL_GOVERNMENT_PORTAL = "official_government_portal"
    TRUSTED_SECTOR_BOARD = "trusted_sector_board"
    DISCOVERY_ONLY_SOURCE = "discovery_only_source"


class EligibilityStatus(StrEnum):
    VERIFIED = "verified_eligible"
    LIKELY = "likely_eligible"
    MANUAL = "manual_approved"
    UNCERTAIN = "uncertain"
    INELIGIBLE = "ineligible"


class RelevanceStatus(StrEnum):
    STRONG = "strong_match"
    CREDIBLE = "credible_match"
    BORDERLINE = "borderline_relevance"
    IRRELEVANT = "irrelevant"


class GeographicScope(StrEnum):
    LONDON = "london"
    UK_PRIORITY_EXCEPTION = "uk_priority_exception"
    OUT_OF_SCOPE = "out_of_scope"
    UNCERTAIN = "uncertain"


class LocationType(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE_UK = "remote_uk"
    MULTI_LOCATION = "multi_location"
    UNKNOWN = "unknown"


class ProgrammeType(StrEnum):
    SUMMER_INTERNSHIP = "summer_internship_2027"
    WINTER_VACATION = "winter_vacation_scheme_2026"
    SPRING_VACATION = "spring_vacation_scheme_2027"
    SUMMER_VACATION = "summer_vacation_scheme_2027"
    SELECTIVE_INSIGHT = "selective_insight_programme"
    SHORT_PROFESSIONAL = "short_professional_internship"
    POLICY_RESEARCH = "policy_research_internship"
    PARLIAMENTARY = "parliamentary_office_internship"
    INTERNATIONAL_INSTITUTION = "international_institution_internship"
    DEVELOPMENT_HUMANITARIAN = "development_humanitarian_internship"
    ENVIRONMENTAL_ESG = "environmental_esg_internship"
    HEALTHCARE_POLICY = "healthcare_health_policy_internship"
    COMMERCIAL_OPERATIONS = "commercial_operations_internship"
    CYCLE_UNSTATED = "cycle_unstated_recent_role"
    UPCOMING = "upcoming_announced_programme"


class DateProvenance(StrEnum):
    EMPLOYER_STATED = "employer_stated"
    OFFICIAL_PROGRAMME_PAGE = "official_programme_page"
    TRUSTED_PRIMARY_LISTING = "trusted_primary_listing"
    OBSERVED_FIRST_SEEN = "observed_first_seen"
    HISTORICAL_ESTIMATE = "historical_estimate"
    THIRD_PARTY_ESTIMATE = "third_party_estimate"
    UNKNOWN = "unknown"


class CycleProvenance(StrEnum):
    EMPLOYER_STATED = "employer_stated"
    PROGRAMME_DATES = "programme_dates"
    OFFICIAL_RECRUITMENT_PAGE = "official_recruitment_page"
    MANUAL_VERIFIED = "manual_verified"
    CYCLE_UNSTATED = "cycle_unstated"
    UNKNOWN = "unknown"


class ProgrammeStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    UPCOMING = "upcoming"


class SourceHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    DISABLED = "disabled"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    text: str
    source_url: str
    structured_field: str | None = None

    @field_validator("source_url")
    @classmethod
    def web_source_url(cls, value: str) -> str:
        return _validate_web_url(value)

    @field_validator("text")
    @classmethod
    def no_contact_email(cls, value: str) -> str:
        return _redact_contact_email(value)


class RawRole(BaseModel):
    """Source-neutral record emitted by adapters before policy decisions."""

    model_config = ConfigDict(extra="allow")

    source_identifier: str
    employer: str
    employer_alias: str | None = None
    title: str
    source_url: str
    application_url: str | None = None
    source_type: str
    source_authority: SourceAuthority
    listing_publisher: str | None = None
    organisation_type: str = "corporate"
    named_office_or_mp: str | None = None
    political_affiliation: str | None = None
    division: str | None = None
    application_method: str | None = None
    location: str = "Unknown"
    location_type: LocationType = LocationType.UNKNOWN
    description: str = ""
    published_date: date | None = None
    opening_date: date | None = None
    deadline: date | None = None
    programme_start: date | None = None
    programme_end: date | None = None
    salary: str | None = None
    paid: bool | None = None
    paid_evidence: str | None = None
    eligibility_text: str = ""
    nationality_requirements: list[str] = Field(default_factory=list)
    residency_requirements: list[str] = Field(default_factory=list)
    clearance_requirements: list[str] = Field(default_factory=list)
    all_source_urls: list[str] = Field(default_factory=list)
    explicitly_closed: bool = False
    cycle_hint: str | None = None
    date_provenance: DateProvenance | None = None
    cycle_provenance: CycleProvenance | None = None
    category_hint: str | None = None
    secondary_tags: list[str] = Field(default_factory=list)

    @field_validator("source_url", "application_url")
    @classmethod
    def web_role_url(cls, value: str | None) -> str | None:
        return _validate_web_url(value) if value is not None else value

    @field_validator("all_source_urls", mode="after")
    @classmethod
    def unique_urls(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(_validate_web_url(item) for item in value))

    @field_validator(
        "description",
        "eligibility_text",
        "application_method",
        "paid_evidence",
        mode="after",
    )
    @classmethod
    def redact_contact_email(cls, value: str | None) -> str | None:
        return _redact_contact_email(value) if value is not None else None


class RoleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    canonical_employer: str
    employer_alias: str | None = None
    organisation_type: str
    named_office_or_mp: str | None = None
    political_affiliation: str | None = None
    division: str | None = None
    application_method: str | None = None
    listing_publisher: str | None = None
    source_authority: SourceAuthority
    title: str
    canonical_url: str
    application_url: str
    all_source_urls: list[str]
    source_registry_id: str
    source_type: str
    source_identifier: str
    location: str
    location_type: LocationType
    geographic_scope: GeographicScope
    geographic_exception_reason: str | None = None
    programme_type: ProgrammeType
    primary_category: str
    secondary_tags: list[str]
    description_excerpt: str
    published_date: date | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    opening_date: date | None = None
    deadline: date | None = None
    programme_start: date | None = None
    programme_end: date | None = None
    salary: str | None = None
    paid: bool | None = None
    paid_status_evidence: str | None = None
    eligibility_status: EligibilityStatus
    eligibility_evidence: list[Evidence]
    eligibility_rule_ids: list[str]
    relevance_status: RelevanceStatus
    relevance_reasons: list[str]
    match_score: int = Field(ge=0, le=100)
    match_components: dict[str, int]
    degree_restrictions: list[str] = Field(default_factory=list)
    study_year_restrictions: list[str] = Field(default_factory=list)
    graduation_year_restrictions: list[str] = Field(default_factory=list)
    nationality_requirements: list[str] = Field(default_factory=list)
    residency_requirements: list[str] = Field(default_factory=list)
    clearance_requirements: list[str] = Field(default_factory=list)
    nationality_assessment: str | None = None
    employer_quality_tier: str
    approved_organisation: bool
    publication_review_required: bool = False
    date_provenance: DateProvenance
    cycle_provenance: CycleProvenance
    status: ProgrammeStatus
    closure_reason: str | None = None
    closure_evidence: str | None = None
    closed_at: datetime | None = None
    consecutive_missing_count: int = Field(default=0, ge=0)
    source_health_at_last_check: SourceHealthStatus
    manual_override: dict[str, Any] | None = None
    email_approved: bool = False

    @field_validator("canonical_url", "application_url")
    @classmethod
    def web_public_url(cls, value: str) -> str:
        return _validate_web_url(value)

    @field_validator("all_source_urls")
    @classmethod
    def web_public_source_urls(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(_validate_web_url(item) for item in value))

    @field_validator(
        "description_excerpt",
        "application_method",
        "paid_status_evidence",
        "nationality_assessment",
        "closure_reason",
        mode="after",
    )
    @classmethod
    def redact_contact_email(cls, value: str | None) -> str | None:
        return _redact_contact_email(value) if value is not None else None


class SourceHealth(BaseModel):
    source_id: str
    status: SourceHealthStatus
    checked_at: datetime
    last_success_at: datetime | None = None
    item_count: int = 0
    listing_count: int = 0
    candidate_count: int = 0
    pages_scanned: int = Field(default=1, ge=0)
    capped: bool = False
    parser_ok: bool = True
    content_hash: str | None = None
    changed_since_last_success: bool = False
    message: str | None = None


class EmployerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    organisation_type: str
    careers_url: str | None = None
    ats_type: str = "html"
    endpoint: str | None = None
    source_authority: SourceAuthority = SourceAuthority.OFFICIAL_CAREERS_PAGE
    country_scope: str = "United Kingdom"
    location_scope: str = "london"
    enabled: bool = False
    priority_tier: str = "standard"
    relevant_categories: list[str] = Field(default_factory=list)
    expected_window: str | None = None
    window_evidence_url: str | None = None
    last_successful_poll: datetime | None = None
    source_health: SourceHealthStatus = SourceHealthStatus.DISABLED
    notes: str = ""
    uk_priority_exception: bool = False
    exception_reason: str | None = None
    requests_per_minute: int = Field(default=10, ge=1)
    poll_interval_minutes: int = Field(default=0, ge=0)
    result_cap: int | None = Field(default=None, ge=1)
    expected_min_items: int = Field(default=0, ge=0)
    request_method: Literal["GET", "POST"] = "GET"
    request_body: dict[str, Any] | None = None
    required_env: list[str] = Field(default_factory=list)
    monitor_only: bool = False
    manual_review_required: bool = True
    fixture: str | None = None
    curated_file: str | None = None

    @field_validator("required_env")
    @classmethod
    def safe_environment_names(cls, value: list[str]) -> list[str]:
        names = list(dict.fromkeys(value))
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", name) for name in names):
            raise ValueError("required_env entries must be uppercase environment variable names")
        return names


class ManualOverride(BaseModel):
    role_id: str
    eligibility_status: EligibilityStatus | None = None
    relevance_status: RelevanceStatus | None = None
    email_approved: bool = False
    geographic_scope: GeographicScope | None = None
    reason: str
    evidence_url: str
    reviewed_at: datetime

    @field_validator("evidence_url")
    @classmethod
    def web_override_url(cls, value: str) -> str:
        return _validate_web_url(value)


class RadarEntry(BaseModel):
    id: str
    employer: str
    expected_programme_type: ProgrammeType
    expected_location: str
    historical_opening_window: str
    evidence_type: Literal[
        "official_future_opening_date",
        "employer_stated_opening_month",
        "historically_observed_typical_month",
        "trusted_third_party_estimate",
        "no_reliable_estimate",
        "currently_open",
        "recently_closed",
    ]
    source_url: str
    last_verified: date
    current_status: str
    official_opening_date: date | None = None

    @field_validator("source_url")
    @classmethod
    def web_evidence_url(cls, value: str) -> str:
        return _validate_web_url(value)

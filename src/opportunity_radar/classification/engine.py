from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from opportunity_radar.classification.rules import ClassificationRules
from opportunity_radar.models import (
    CycleProvenance,
    DateProvenance,
    EligibilityStatus,
    EmployerConfig,
    Evidence,
    GeographicScope,
    LocationType,
    ManualOverride,
    ProgrammeStatus,
    ProgrammeType,
    RawRole,
    RelevanceStatus,
    RoleRecord,
    SourceAuthority,
    SourceHealthStatus,
)

TRACKING_PARAMETERS = {"gclid", "fbclid", "ref", "source"}

DEFAULT_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Law-Firm Vacation Schemes": ("vacation scheme",),
    "Investment Banking": ("investment banking", "mergers and acquisitions", "m&a"),
    "Corporate Finance and Transactions": ("corporate finance", "transaction advisory"),
    "Markets, Sales and Trading": ("sales and trading", "global markets", "trading"),
    "Asset and Investment Management": ("asset management", "investment management"),
    "Development Finance and Impact Investment": ("development finance", "impact investment"),
    "Real Estate Investment and Advisory": ("real estate", "property investment"),
    "Financial Regulation and Central Banking": ("central bank", "financial regulation"),
    "Compliance and Financial Crime": ("compliance", "financial crime", "anti money laundering"),
    "Legal and Regulatory": ("legal", "regulatory", "litigation"),
    "Insurance and Reinsurance": ("insurance", "reinsurance", "underwriting"),
    "Climate and Catastrophe Risk": ("catastrophe risk", "climate risk"),
    "Management and Strategy Consulting": ("strategy consulting", "management consulting"),
    "Economic Consulting": ("economic consulting", "economist"),
    "Healthcare Consulting": ("healthcare consulting",),
    "Corporate Strategy": ("corporate strategy", "business strategy"),
    "Business Operations and Commercial Analysis": ("commercial analysis", "business operations"),
    "Public Policy and Policy Research": ("public policy", "policy research"),
    "Parliament and MP Offices": ("parliament", "member of parliament", "mp office", "westminster"),
    "Intelligence and National Security": ("national security", "intelligence analyst"),
    "Political and Geopolitical Risk": ("geopolitical", "political risk"),
    "Think Tanks and Research Institutes": ("think tank", "research institute"),
    "International Institutions and Multilateral Organisations": (
        "multilateral",
        "international institution",
        "world bank",
        "united nations",
    ),
    "International Development": ("international development", "development programme"),
    "Humanitarian Affairs and Emergency Response": ("humanitarian", "emergency response"),
    "Monitoring, Evaluation, Research and Learning": ("monitoring and evaluation", "mel"),
    "Energy and Commodities": ("energy trading", "commodities"),
    "Oil and Gas": ("oil and gas",),
    "Environmental Risk Management": ("environmental risk", "environmental assessment"),
    "Climate Strategy": ("climate strategy", "decarbonisation", "energy transition"),
    "ESG and Responsible Investment": ("esg", "responsible investment", "sustainability"),
    "Geospatial Analysis and GIS": ("geospatial", "qgis", "gis", "location intelligence"),
    "Public and Global Health": ("global health", "public health"),
    "Health Policy and Health Economics": ("health policy", "health economics"),
    "Pharmaceutical and Healthcare": ("pharmaceutical", "market access", "healthcare"),
    "Supply Chain and Procurement": ("supply chain", "procurement"),
    "Logistics and Emergency Operations": ("logistics", "emergency operations"),
    "Communications and Stakeholder Engagement": (
        "stakeholder engagement",
        "strategic communications",
    ),
    "Corporate Responsibility and Social Impact": ("corporate responsibility", "social impact"),
    "Other Relevant": (),
}

DEFAULT_RULES = ClassificationRules(
    category_keywords=DEFAULT_CATEGORY_KEYWORDS,
    verified_eligibility={
        "graduation_2028": (
            "graduate in 2028",
            "graduating in 2028",
            "graduation year 2028",
            "anticipated graduation date summer 2028",
            "completion time frame between june 2027 and july 2028",
            "completion timeframe between june 2027 and july 2028",
        ),
        "penultimate_year": ("penultimate year", "penultimate or final year"),
        "second_year": ("second year",),
        "any_degree": ("any degree", "all degree disciplines", "any discipline"),
        "non_law": ("non law",),
    },
    likely_eligibility={
        "broad_undergraduate": ("undergraduate students", "current undergraduate", "undergraduates")
    },
    hard_exclusions=(
        "graduates only",
        "completed degree required",
        "final year only",
        "final year university students and recent graduates",
        "designed for final year university students",
        "law degree only",
        "llb required",
        "software engineer",
        "quantitative researcher",
        "quantitative research internship",
        "quant researcher",
        "quant research internship",
        "quantitative trader",
        "quantitative trading internship",
        "quant trader",
        "quant trading internship",
        "quantitative developer",
        "quant developer",
        "machine learning engineer",
        "computer science degree required",
        "engineering degree required",
        "mathematics degree required",
        "medical degree required",
        "laboratory scientist",
        "campus ambassador",
        "retail assistant",
        "hospitality assistant",
        "fundraising volunteer",
        "social media volunteer",
        "election campaign volunteer",
        "unpaid",
        "c++ required",
        "c++ is required",
        "must have c++",
        "proficiency in c++",
        "proficient in c++",
        "strong c++ skills",
        "strong c++ programming skills",
        "advanced c++",
        "commercial c++ experience",
        "professional c++ experience",
        "c++ programming experience",
        "experience programming in c++",
        "experience with c++ required",
        "experienced compliance professional",
    ),
    relevance_positive={
        "legal_risk": ("legal", "compliance", "regulatory", "risk"),
        "investment_diligence": (
            "due diligence",
            "financial analysis",
            "valuation",
            "financial modelling",
        ),
        "research_policy": ("research", "analysis", "policy", "parliament", "briefing"),
        "climate_development": ("climate", "environmental risk", "humanitarian", "development"),
        "health": ("public health", "health policy", "health economics", "healthcare consulting"),
        "commercial": ("investment", "banking", "insurance", "real estate", "commercial analysis"),
        "operations": ("stakeholder", "programme management", "project management", "supply chain"),
        "geospatial": ("geospatial", "gis", "qgis", "location intelligence"),
    },
    skill_alignment={
        "analytical_tools": ("excel", "python", "spss"),
        "research_communication": ("research", "writing", "briefing", "evidence review"),
    },
    relevance_negative=(
        "advanced software engineering",
        "computer science only",
        "advanced quantitative finance",
        "specialist machine learning",
        "engineering only",
        "clinical",
        "laboratory",
        "generic fundraising",
        "generic social media",
        "generic office administration",
        "election campaigning",
    ),
    score_weights={
        "eligibility_strength": 20,
        "substantive_relevance": 35,
        "skill_alignment": 10,
        "organisation_quality": 10,
        "geographic_fit": 10,
        "recency": 5,
        "deadline_urgency": 5,
        "evidence_quality": 5,
    },
    quality_controlled_types=frozenset({"charity", "ngo", "foundation", "nonprofit", "think_tank"}),
    require_paid_types=frozenset({"charity", "ngo", "foundation", "nonprofit", "think_tank"}),
    require_selectivity_types=frozenset({"charity", "ngo", "foundation", "nonprofit"}),
    approved_quality_tiers=frozenset({"priority", "major", "approved"}),
)

ELIGIBILITY_RULE_IDS = {
    "graduation_2028": "graduation.2028",
    "penultimate_year": "study.penultimate",
    "second_year": "study.second_year",
    "any_degree": "degree.any",
    "non_law": "degree.non_law",
    "broad_undergraduate": "study.broad_undergraduate",
}

RELEVANCE_REASONS = {
    "legal_risk": "Legal, compliance, regulatory or risk work aligns with prior experience",
    "investment_diligence": "Uses investment due diligence, valuation or financial-analysis skills",
    "research_policy": "Uses research, analysis and written briefing skills",
    "climate_development": "Relevant to climate, resilience, humanitarian or development study",
    "health": "Relevant to health policy, global health or healthcare consulting",
    "commercial": "Provides substantive financial or commercial analysis",
    "operations": "Uses stakeholder, programme or operational coordination skills",
    "geospatial": "Matches geospatial and location-analysis experience",
    "communications": "Involves substantive strategic communications or public affairs",
}


def canonicalise_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
    ]
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def stable_role_id(raw: RawRole) -> str:
    key = f"{normalise_text(raw.employer)}|{raw.source_type}|{raw.source_identifier}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def normalise_text(value: str) -> str:
    folded = value.casefold()
    # Preserve language names that punctuation stripping would otherwise reduce
    # to the dangerously broad single-letter terms "c" and "c".
    folded = re.sub(r"\bc\s*\+\s*\+", " cplusplus ", folded)
    folded = re.sub(r"\bc\s*#", " csharp ", folded)
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


EMPLOYER_DISPLAY_OVERRIDES = {
    "transport for london": "Transport for London",
}

EMPLOYER_TOKEN_CASING = {
    "amrc": "AMRC",
    "asu": "ASU",
    "cclc": "CCLC",
    "ciee": "CIEE",
    "cic": "CIC",
    "cio": "CIO",
    "fc": "FC",
    "ft": "FT",
    "gp": "GP",
    "mp": "MP",
    "nhs": "NHS",
    "tpp": "TPP",
    "tssa": "TSSA",
    "ucl": "UCL",
    "uk": "UK",
    "uk100": "UK100",
    "uspg": "USPG",
    "wwf": "WWF",
    "ygam": "YGAM",
    "ymca": "YMCA",
}


def clean_employer_name(value: str) -> str:
    """Return a stable display name without altering substantive employer identity."""

    collapsed = re.sub(r"\s+", " ", value).strip()
    override = EMPLOYER_DISPLAY_OVERRIDES.get(normalise_text(collapsed))
    if override:
        return override
    return re.sub(
        r"\b[A-Za-z0-9]+\b",
        lambda match: EMPLOYER_TOKEN_CASING.get(match.group().casefold(), match.group()),
        collapsed,
    )


def _matches(text: str, term: str) -> bool:
    normalised_term = normalise_text(term)
    if not normalised_term:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(normalised_term)}(?![a-z0-9])", text) is not None


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    return any(_matches(text, term) for term in terms)


def _fragments(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[.!?;])\s+|\n+", value) if item.strip()]


def _evidence_fragment(raw: RawRole, terms: tuple[str, ...]) -> tuple[str, str]:
    for field in ("eligibility_text", "description", "title"):
        value = str(getattr(raw, field) or "").strip()
        for fragment in _fragments(value):
            text = normalise_text(fragment)
            if _contains(text, terms):
                return fragment, field
    fallback = raw.eligibility_text.strip() or raw.description.strip() or raw.title.strip()
    return fallback, "eligibility_text" if raw.eligibility_text.strip() else "description"


def _exact_restrictions(raw: RawRole) -> tuple[list[str], list[str], list[str]]:
    degree_terms = (
        "any degree",
        "all degree disciplines",
        "any discipline",
        "non law",
        "law degree",
        "llb",
        "computer science degree",
        "engineering degree",
        "mathematics degree",
        "medical degree",
    )
    study_terms = ("penultimate year", "second year", "final year", "undergraduate")
    graduation_terms = (
        "graduate in 2028",
        "graduating in 2028",
        "graduation year 2028",
        "anticipated graduation date summer 2028",
        "completion time frame between june 2027 and july 2028",
        "completion timeframe between june 2027 and july 2028",
    )
    source = raw.eligibility_text.strip() or raw.description.strip()

    def select(terms: tuple[str, ...]) -> list[str]:
        return list(
            dict.fromkeys(
                fragment
                for fragment in _fragments(source)
                if _contains(normalise_text(fragment), terms)
            )
        )

    return select(degree_terms), select(study_terms), select(graduation_terms)


def classify_location_type(raw: RawRole) -> LocationType:
    if raw.location_type != LocationType.UNKNOWN:
        return raw.location_type
    text = normalise_text(raw.location)
    if "hybrid" in text:
        return LocationType.HYBRID
    if _contains(text, ("remote uk", "united kingdom remote", "remote within the uk")):
        return LocationType.REMOTE_UK
    if (
        _contains(text, ("multiple locations", "various locations", "uk wide"))
        or ";" in raw.location
    ):
        return LocationType.MULTI_LOCATION
    if text not in {"", "unknown"}:
        return LocationType.ONSITE
    return LocationType.UNKNOWN


def classify_geography(
    raw: RawRole, employer: EmployerConfig
) -> tuple[GeographicScope, str | None]:
    text = normalise_text(raw.location)
    if _contains(text, ("london", "greater london", "westminster")):
        return GeographicScope.LONDON, None
    if _contains(text, ("remote uk", "united kingdom remote", "remote within the uk")):
        return GeographicScope.LONDON, None
    if _matches(text, "uk wide") and _matches(text, "london"):
        return GeographicScope.LONDON, None
    if employer.uk_priority_exception:
        return GeographicScope.UK_PRIORITY_EXCEPTION, employer.exception_reason
    if text in {"", "unknown", "uk", "united kingdom"}:
        return GeographicScope.UNCERTAIN, None
    return GeographicScope.OUT_OF_SCOPE, None


def _stated_cycle_provenance(raw: RawRole) -> CycleProvenance:
    if raw.cycle_provenance:
        return raw.cycle_provenance
    if raw.source_type == "curated_yaml":
        return CycleProvenance.MANUAL_VERIFIED
    if raw.source_authority in {
        SourceAuthority.OFFICIAL_ATS,
        SourceAuthority.OFFICIAL_CAREERS_PAGE,
        SourceAuthority.OFFICIAL_PROGRAMME_PAGE,
        SourceAuthority.OFFICIAL_GOVERNMENT_PORTAL,
    }:
        return CycleProvenance.EMPLOYER_STATED
    return CycleProvenance.UNKNOWN


def classify_programme(raw: RawRole) -> tuple[ProgrammeType, CycleProvenance]:
    text = normalise_text(f"{raw.title} {raw.description} {raw.cycle_hint or ''}")
    stated = _stated_cycle_provenance(raw)
    if _matches(text, "vacation scheme"):
        if _matches(text, "winter 2026"):
            return ProgrammeType.WINTER_VACATION, stated
        if _matches(text, "spring 2027"):
            return ProgrammeType.SPRING_VACATION, stated
        if _matches(text, "summer 2027"):
            return ProgrammeType.SUMMER_VACATION, stated
        return ProgrammeType.CYCLE_UNSTATED, CycleProvenance.CYCLE_UNSTATED
    if _contains(text, ("summer 2027", "2027 summer")):
        return ProgrammeType.SUMMER_INTERNSHIP, stated
    if (
        raw.programme_start
        and raw.programme_start.year == 2027
        and raw.programme_start.month in {6, 7, 8}
    ):
        return ProgrammeType.SUMMER_INTERNSHIP, CycleProvenance.PROGRAMME_DATES
    if not raw.cycle_hint or not _contains(normalise_text(raw.cycle_hint), ("2026 27", "2027")):
        return ProgrammeType.CYCLE_UNSTATED, CycleProvenance.CYCLE_UNSTATED
    cycle_provenance = raw.cycle_provenance or (
        CycleProvenance.OFFICIAL_RECRUITMENT_PAGE
        if raw.source_authority != SourceAuthority.TRUSTED_SECTOR_BOARD
        else CycleProvenance.UNKNOWN
    )
    if _contains(text, ("parliament", "member of parliament", "mp office")):
        return ProgrammeType.PARLIAMENTARY, cycle_provenance
    if _contains(text, ("policy", "think tank")):
        return ProgrammeType.POLICY_RESEARCH, cycle_provenance
    if _contains(text, ("humanitarian", "international development")):
        return ProgrammeType.DEVELOPMENT_HUMANITARIAN, cycle_provenance
    if _contains(text, ("world bank", "united nations", "multilateral")):
        return ProgrammeType.INTERNATIONAL_INSTITUTION, cycle_provenance
    if _contains(text, ("environment", "climate", "esg", "sustainability")):
        return ProgrammeType.ENVIRONMENTAL_ESG, cycle_provenance
    if _contains(text, ("health policy", "health economics", "healthcare consulting")):
        return ProgrammeType.HEALTHCARE_POLICY, cycle_provenance
    if _contains(text, ("supply chain", "procurement", "commercial analysis")):
        return ProgrammeType.COMMERCIAL_OPERATIONS, cycle_provenance
    if _contains(text, ("insight programme", "insight program")):
        return ProgrammeType.SELECTIVE_INSIGHT, cycle_provenance
    if _contains(text, ("short internship", "professional internship")):
        return ProgrammeType.SHORT_PROFESSIONAL, cycle_provenance
    return ProgrammeType.CYCLE_UNSTATED, CycleProvenance.CYCLE_UNSTATED


def classify_category(
    raw: RawRole, rules: ClassificationRules = DEFAULT_RULES
) -> tuple[str, list[str]]:
    text = normalise_text(f"{raw.title} {raw.description}")
    title = normalise_text(raw.title)
    primary = raw.category_hint if raw.category_hint in rules.categories else None
    if not primary:
        scored = [
            (
                sum(3 for term in terms if _matches(title, term))
                + sum(1 for term in terms if _matches(text, term)),
                category,
            )
            for category, terms in rules.category_keywords.items()
        ]
        score, primary = max(scored, default=(0, "Other Relevant"))
        if score == 0:
            primary = "Other Relevant"
    tags = [tag for tag in raw.secondary_tags if tag in rules.categories]
    tags.extend(
        category
        for category, terms in rules.category_keywords.items()
        if category != primary and _contains(text, terms)
    )
    return primary, list(dict.fromkeys(tags))


def assess_eligibility(
    raw: RawRole,
    programme_type: ProgrammeType,
    geographic_scope: GeographicScope,
    rules: ClassificationRules = DEFAULT_RULES,
) -> tuple[EligibilityStatus, list[Evidence], list[str], str | None]:
    source = raw.source_url
    evidence: list[Evidence] = []
    rule_ids: list[str] = []
    text = normalise_text(f"{raw.title} {raw.description} {raw.eligibility_text}")
    eligibility_source = raw.eligibility_text.strip() or raw.description.strip()
    eligibility_text = normalise_text(eligibility_source)

    def add(rule_id: str, fragment: str, structured_field: str | None = None) -> None:
        rule_ids.append(rule_id)
        evidence.append(
            Evidence(
                rule_id=rule_id,
                text=fragment,
                source_url=source,
                structured_field=structured_field,
            )
        )

    if geographic_scope in {GeographicScope.OUT_OF_SCOPE, GeographicScope.UNCERTAIN}:
        add("location.not_verified", raw.location, "location")
        status = (
            EligibilityStatus.INELIGIBLE
            if geographic_scope == GeographicScope.OUT_OF_SCOPE
            else EligibilityStatus.UNCERTAIN
        )
        return status, evidence, rule_ids, None
    if raw.paid is False:
        add("pay.unpaid", raw.paid_evidence or "paid=false", "paid_evidence")
        return EligibilityStatus.INELIGIBLE, evidence, rule_ids, None
    if re.search(r"(?<![a-z0-9])final year(?: students?)? only(?![a-z0-9])", text):
        fragment, field = _evidence_fragment(raw, ("final year",))
        add("study.final_year_only", fragment, field)
        return EligibilityStatus.INELIGIBLE, evidence, rule_ids, None
    if _matches(text, "unpaid"):
        fragment, field = _evidence_fragment(raw, ("unpaid",))
        add("pay.unpaid", fragment, field)
        return EligibilityStatus.INELIGIBLE, evidence, rule_ids, None
    if _contains(text, rules.hard_exclusions):
        matched = next(term for term in rules.hard_exclusions if _matches(text, term))
        fragment, field = _evidence_fragment(raw, (matched,))
        add(f"exclusion.{normalise_text(matched).replace(' ', '_')}", fragment, field)
        return EligibilityStatus.INELIGIBLE, evidence, rule_ids, None
    relevant_for = normalise_text(raw.eligibility_text)
    if _matches(relevant_for, "relevant for 3rd year") and not _contains(
        relevant_for, ("2nd year", "second year")
    ):
        add("study.third_year_only", raw.eligibility_text, "eligibility_text")
        return EligibilityStatus.INELIGIBLE, evidence, rule_ids, None
    if _matches(relevant_for, "relevant for 1st year") and not _contains(
        relevant_for, ("2nd year", "second year")
    ):
        add("study.first_year_only", raw.eligibility_text, "eligibility_text")
        return EligibilityStatus.INELIGIBLE, evidence, rule_ids, None
    if programme_type == ProgrammeType.PARLIAMENTARY and raw.paid is not True:
        add("pay.parliament_requires_paid", raw.paid_evidence or "Paid status is not stated")
        return EligibilityStatus.UNCERTAIN, evidence, rule_ids, None
    if raw.organisation_type in rules.require_paid_types and raw.paid is not True:
        add("pay.quality_controlled_organisation", raw.paid_evidence or "Paid status is not stated")
        return EligibilityStatus.UNCERTAIN, evidence, rule_ids, None

    vacation_types = {
        ProgrammeType.WINTER_VACATION,
        ProgrammeType.SPRING_VACATION,
        ProgrammeType.SUMMER_VACATION,
    }
    if programme_type in vacation_types:
        if _contains(eligibility_text, ("final year non law", "final year non-law")):
            fragment, field = _evidence_fragment(raw, ("final year non law",))
            add("law.final_year_non_law_only", fragment, field)
            return EligibilityStatus.INELIGIBLE, evidence, rule_ids, None
        law_stage_ok = (
            _matches(eligibility_text, "penultimate year")
            and _contains(
                eligibility_text,
                (
                    "non law",
                    "any degree",
                    "all degree disciplines",
                    "all penultimate year undergraduates",
                ),
            )
        ) or (
            _matches(eligibility_text, "second year")
            and _contains(
                eligibility_text,
                ("non law", "any degree", "any discipline", "all degree disciplines"),
            )
        )
        if not law_stage_ok:
            add(
                "law.explicit_non_law_stage_missing",
                eligibility_source or "No explicit eligible non-law study stage was found",
                "eligibility_text" if raw.eligibility_text.strip() else "description",
            )
            return EligibilityStatus.UNCERTAIN, evidence, rule_ids, None
        add(
            "law.non_law_stage_verified",
            eligibility_source,
            "eligibility_text" if raw.eligibility_text.strip() else "description",
        )

    if raw.source_authority == SourceAuthority.DISCOVERY_ONLY_SOURCE:
        add(
            "source.discovery_only",
            "Eligibility is plausible but must be verified on the employer's application page",
        )
        return EligibilityStatus.UNCERTAIN, evidence, rule_ids, None

    nationality_assessments: list[str] = []
    if raw.nationality_requirements:
        joined = normalise_text(" ".join(raw.nationality_requirements))
        if _contains(joined, ("british", "uk national")):
            nationality_assessments.append(
                "Known British citizenship meets the stated nationality element only."
            )
            add("nationality.british", raw.nationality_requirements[0], "nationality_requirements")
        elif _contains(joined, ("new zealand", "commonwealth citizen", "commonwealth citizens")):
            nationality_assessments.append(
                "Known New Zealand citizenship meets the stated nationality element only."
            )
            add(
                "nationality.new_zealand",
                raw.nationality_requirements[0],
                "nationality_requirements",
            )
        else:
            add(
                "nationality.not_established",
                raw.nationality_requirements[0],
                "nationality_requirements",
            )
            return EligibilityStatus.UNCERTAIN, evidence, rule_ids, None
    nationality_assessment = " ".join(nationality_assessments) or None

    if raw.residency_requirements or raw.clearance_requirements:
        requirement = (raw.residency_requirements + raw.clearance_requirements)[0]
        field = "residency_requirements" if raw.residency_requirements else "clearance_requirements"
        add("security.additional_requirement", requirement, field)
        return EligibilityStatus.UNCERTAIN, evidence, rule_ids, nationality_assessment

    explicit_matches = 0
    for config_id, terms in rules.verified_eligibility.items():
        if _contains(eligibility_text, terms):
            fragment, field = _evidence_fragment(raw, terms)
            add(ELIGIBILITY_RULE_IDS.get(config_id, f"eligibility.{config_id}"), fragment, field)
            explicit_matches += 1
    if programme_type in vacation_types:
        explicit_matches += 1
    if explicit_matches:
        return EligibilityStatus.VERIFIED, evidence, rule_ids, nationality_assessment
    for config_id, terms in rules.likely_eligibility.items():
        if _contains(eligibility_text, terms):
            fragment, field = _evidence_fragment(raw, terms)
            add(ELIGIBILITY_RULE_IDS.get(config_id, f"eligibility.{config_id}"), fragment, field)
            return EligibilityStatus.LIKELY, evidence, rule_ids, nationality_assessment
    add(
        "eligibility.material_evidence_missing",
        eligibility_source or "Material study-stage eligibility is not stated",
        "eligibility_text" if raw.eligibility_text.strip() else "description",
    )
    return EligibilityStatus.UNCERTAIN, evidence, rule_ids, nationality_assessment


def assess_relevance(
    raw: RawRole,
    primary_category: str,
    employer: EmployerConfig,
    rules: ClassificationRules = DEFAULT_RULES,
) -> tuple[RelevanceStatus, list[str], int, int]:
    text = normalise_text(f"{raw.title} {raw.description}")
    negative_terms = (*rules.relevance_negative, *rules.hard_exclusions)
    if _contains(text, negative_terms):
        matched = next(term for term in negative_terms if _matches(text, term))
        return RelevanceStatus.IRRELEVANT, [f"Excluded work: {matched}"], 0, 0
    if (
        raw.organisation_type in rules.quality_controlled_types
        and employer.priority_tier not in rules.approved_quality_tiers
    ):
        return (
            RelevanceStatus.IRRELEVANT,
            ["Organisation scale or selectivity has not been approved"],
            0,
            0,
        )
    reasons: list[str] = []
    substantive_hits = 0
    for rule_id, terms in rules.relevance_positive.items():
        if _contains(text, terms):
            substantive_hits += 1
            reasons.append(
                RELEVANCE_REASONS.get(rule_id, f"Matches {rule_id.replace('_', ' ')} evidence")
            )
    skill_hits = sum(_contains(text, terms) for terms in rules.skill_alignment.values())
    if skill_hits:
        reasons.append("Uses relevant analytical, research or communication skills")
    if primary_category != "Other Relevant":
        substantive_hits += 1
        reasons.append(f"Falls within the approved {primary_category} category")

    controlled_needs_selectivity = raw.organisation_type in rules.require_selectivity_types
    selectivity_stated = _contains(
        text, ("selective", "competitive", "structured internship programme")
    )
    if controlled_needs_selectivity and not selectivity_stated:
        reasons.append("Selectivity is not established for this charity, NGO or foundation role")
        return (
            RelevanceStatus.BORDERLINE,
            list(dict.fromkeys(reasons)),
            substantive_hits,
            skill_hits,
        )
    if substantive_hits >= 3:
        status = RelevanceStatus.STRONG
    elif substantive_hits >= 1:
        status = RelevanceStatus.CREDIBLE
    elif employer.manual_review_required:
        status = RelevanceStatus.BORDERLINE
        reasons.append("Substantive relevance requires manual review")
    else:
        status = RelevanceStatus.IRRELEVANT
        reasons.append("No substantive approved-category evidence found")
    return status, list(dict.fromkeys(reasons)), substantive_hits, skill_hits


def _date_provenance(raw: RawRole) -> DateProvenance:
    if raw.date_provenance:
        return raw.date_provenance
    if not raw.published_date:
        return DateProvenance.OBSERVED_FIRST_SEEN
    if raw.source_authority == SourceAuthority.TRUSTED_SECTOR_BOARD:
        return DateProvenance.TRUSTED_PRIMARY_LISTING
    if raw.source_authority == SourceAuthority.OFFICIAL_PROGRAMME_PAGE:
        return DateProvenance.OFFICIAL_PROGRAMME_PAGE
    return DateProvenance.EMPLOYER_STATED


def _weighted_score(
    *,
    rules: ClassificationRules,
    eligibility: EligibilityStatus,
    geography: GeographicScope,
    authority: SourceAuthority,
    quality_approved: bool,
    substantive_hits: int,
    skill_hits: int,
    published_date: date | None,
    deadline: date | None,
    now: datetime,
) -> tuple[int, dict[str, int]]:
    weights = rules.score_weights
    eligibility_ratio = {
        EligibilityStatus.VERIFIED: 1.0,
        EligibilityStatus.MANUAL: 1.0,
        EligibilityStatus.LIKELY: 0.6,
        EligibilityStatus.UNCERTAIN: 0.0,
        EligibilityStatus.INELIGIBLE: 0.0,
    }[eligibility]
    geography_ratio = {
        GeographicScope.LONDON: 1.0,
        GeographicScope.UK_PRIORITY_EXCEPTION: 0.6,
        GeographicScope.UNCERTAIN: 0.0,
        GeographicScope.OUT_OF_SCOPE: 0.0,
    }[geography]
    authority_ratio = {
        SourceAuthority.OFFICIAL_ATS: 1.0,
        SourceAuthority.OFFICIAL_CAREERS_PAGE: 0.9,
        SourceAuthority.OFFICIAL_PROGRAMME_PAGE: 1.0,
        SourceAuthority.OFFICIAL_GOVERNMENT_PORTAL: 1.0,
        SourceAuthority.TRUSTED_SECTOR_BOARD: 0.8,
        SourceAuthority.DISCOVERY_ONLY_SOURCE: 0.0,
    }[authority]
    observed_date = published_date or now.date()
    age_days = max(0, (now.date() - observed_date).days)
    recency_ratio = 1.0 if age_days <= 7 else 0.5 if age_days <= 30 else 0.0
    days_to_deadline = (deadline - now.date()).days if deadline else None
    urgency_ratio = (
        1.0
        if days_to_deadline is not None and 0 <= days_to_deadline <= 14
        else 0.5
        if days_to_deadline is not None and 15 <= days_to_deadline <= 30
        else 0.0
    )
    ratios = {
        "eligibility_strength": eligibility_ratio,
        "substantive_relevance": min(1.0, substantive_hits / 3),
        "skill_alignment": min(1.0, skill_hits / 2),
        "organisation_quality": 1.0 if quality_approved else 0.0,
        "geographic_fit": geography_ratio,
        "recency": recency_ratio,
        "deadline_urgency": urgency_ratio,
        "evidence_quality": authority_ratio,
    }
    components = {key: round(weights[key] * ratio) for key, ratio in ratios.items()}
    score = sum(components.values())
    if eligibility in {EligibilityStatus.INELIGIBLE, EligibilityStatus.UNCERTAIN}:
        score = min(score, 49)
    return score, components


def classify_role(
    raw: RawRole,
    employer: EmployerConfig,
    *,
    observed_at: datetime | None = None,
    override: ManualOverride | None = None,
    rules: ClassificationRules = DEFAULT_RULES,
) -> RoleRecord:
    now = observed_at or datetime.now(UTC)
    geography, exception_reason = classify_geography(raw, employer)
    location_type = classify_location_type(raw)
    programme, cycle_provenance = classify_programme(raw)
    primary, tags = classify_category(raw, rules)
    eligibility, eligibility_evidence, eligibility_rule_ids, nationality_assessment = (
        assess_eligibility(raw, programme, geography, rules)
    )
    relevance, reasons, substantive_hits, skill_hits = assess_relevance(
        raw, primary, employer, rules
    )
    manual_data = None
    email_approved = False
    if override:
        if override.eligibility_status:
            eligibility = override.eligibility_status
        if override.relevance_status:
            relevance = override.relevance_status
        if override.geographic_scope:
            geography = override.geographic_scope
        email_approved = override.email_approved
        manual_data = override.model_dump(mode="json")
        eligibility_evidence.append(
            Evidence(
                rule_id="manual.override",
                text=override.reason,
                source_url=override.evidence_url,
                structured_field="manual_override",
            )
        )
        eligibility_rule_ids.append("manual.override")
    quality_approved = employer.priority_tier in rules.approved_quality_tiers
    score, components = _weighted_score(
        rules=rules,
        eligibility=eligibility,
        geography=geography,
        authority=raw.source_authority,
        quality_approved=quality_approved,
        substantive_hits=substantive_hits,
        skill_hits=skill_hits,
        published_date=raw.published_date,
        deadline=raw.deadline,
        now=now,
    )
    status = ProgrammeStatus.CLOSED if raw.explicitly_closed else ProgrammeStatus.OPEN
    if raw.opening_date and raw.opening_date > now.date() and not raw.explicitly_closed:
        status = ProgrammeStatus.UPCOMING
    canonical_url = canonicalise_url(raw.source_url)
    application_url = canonicalise_url(raw.application_url or raw.source_url)
    source_urls = [
        raw.source_url,
        *(item for item in [raw.application_url, *raw.all_source_urls] if item),
        canonical_url,
        application_url,
    ]
    degree_restrictions, study_restrictions, graduation_restrictions = _exact_restrictions(raw)
    return RoleRecord(
        id=stable_role_id(raw),
        canonical_employer=clean_employer_name(
            raw.employer
            if raw.source_authority
            in {
                SourceAuthority.OFFICIAL_GOVERNMENT_PORTAL,
                SourceAuthority.TRUSTED_SECTOR_BOARD,
                SourceAuthority.DISCOVERY_ONLY_SOURCE,
            }
            else employer.canonical_name
        ),
        employer_alias=raw.employer_alias,
        organisation_type=raw.organisation_type or employer.organisation_type,
        named_office_or_mp=raw.named_office_or_mp,
        political_affiliation=raw.political_affiliation,
        division=raw.division,
        application_method=raw.application_method,
        listing_publisher=raw.listing_publisher,
        source_authority=raw.source_authority,
        title=raw.title.strip(),
        canonical_url=canonical_url,
        application_url=application_url,
        all_source_urls=list(dict.fromkeys(source_urls)),
        source_registry_id=employer.id,
        source_type=raw.source_type,
        source_identifier=raw.source_identifier,
        location=raw.location,
        location_type=location_type,
        geographic_scope=geography,
        geographic_exception_reason=exception_reason,
        programme_type=programme,
        primary_category=primary,
        secondary_tags=tags,
        description_excerpt=raw.description.strip()[:500],
        published_date=raw.published_date,
        first_seen_at=now,
        last_seen_at=now,
        opening_date=raw.opening_date,
        deadline=raw.deadline,
        programme_start=raw.programme_start,
        programme_end=raw.programme_end,
        salary=raw.salary,
        paid=raw.paid,
        paid_status_evidence=raw.paid_evidence,
        eligibility_status=eligibility,
        eligibility_evidence=eligibility_evidence,
        eligibility_rule_ids=eligibility_rule_ids,
        relevance_status=relevance,
        relevance_reasons=reasons,
        match_score=score,
        match_components=components,
        degree_restrictions=degree_restrictions,
        study_year_restrictions=study_restrictions,
        graduation_year_restrictions=graduation_restrictions,
        nationality_requirements=raw.nationality_requirements,
        residency_requirements=raw.residency_requirements,
        clearance_requirements=raw.clearance_requirements,
        nationality_assessment=nationality_assessment,
        employer_quality_tier=employer.priority_tier,
        approved_organisation=quality_approved,
        publication_review_required=employer.manual_review_required and override is None,
        date_provenance=_date_provenance(raw),
        cycle_provenance=cycle_provenance,
        status=status,
        closure_reason=(
            "Official listing states applications are closed" if raw.explicitly_closed else None
        ),
        closure_evidence=raw.source_url if raw.explicitly_closed else None,
        closed_at=now if raw.explicitly_closed else None,
        source_health_at_last_check=SourceHealthStatus.HEALTHY,
        manual_override=manual_data,
        email_approved=email_approved,
    )


def _fits_candidate_availability(
    role: RoleRecord, rules: ClassificationRules = DEFAULT_RULES
) -> bool:
    title = normalise_text(role.title)
    raw_text = f"{role.title} {role.description_excerpt}".casefold()
    full_text = normalise_text(f"{role.title} {role.description_excerpt}")
    programme_role = _contains(title, rules.programme_role_signals or PROGRAMME_ROLE_SIGNALS)
    availability_evidence = _contains(
        full_text,
        rules.term_time_availability_signals or TERM_TIME_AVAILABILITY_SIGNALS,
    ) or _has_term_time_hours(raw_text)
    term_time_role = (
        _contains(title, rules.term_time_role_signals or TERM_TIME_ROLE_SIGNALS)
        and availability_evidence
    )
    research_context_ok = (
        not _contains(title, rules.research_role_signals or RESEARCH_ROLE_SIGNALS)
        or _contains(title, rules.allowed_research_contexts or ALLOWED_RESEARCH_CONTEXTS)
        or normalise_text(role.canonical_employer)
        in {
            normalise_text(name)
            for name in (rules.allowed_research_employers or ALLOWED_RESEARCH_EMPLOYERS)
        }
    )
    contextual_exclusions = rules.contextual_role_exclusions.get(role.organisation_type, ())
    if not contextual_exclusions and role.organisation_type == "public_health":
        contextual_exclusions = PUBLIC_HEALTH_ROLE_EXCLUSIONS
    elif not contextual_exclusions and role.organisation_type == "higher_education":
        contextual_exclusions = HIGHER_EDUCATION_ROLE_EXCLUSIONS
    return (
        (programme_role or term_time_role)
        and not _contains(title, rules.possible_role_exclusions or POSSIBLE_ROLE_EXCLUSIONS)
        and not _contains(full_text, rules.hard_exclusions)
        and not _has_long_duration(full_text, rules.long_duration_signals or LONG_DURATION_SIGNALS)
        and (
            programme_role
            or availability_evidence
            or not _contains(full_text, rules.ordinary_job_signals or ORDINARY_JOB_SIGNALS)
        )
        and research_context_ok
        and not _contains(title, contextual_exclusions)
    )


def is_public_role(role: RoleRecord, rules: ClassificationRules = DEFAULT_RULES) -> bool:
    eligibility_ok = role.eligibility_status in {
        EligibilityStatus.VERIFIED,
        EligibilityStatus.LIKELY,
        EligibilityStatus.MANUAL,
    }
    relevance_ok = role.relevance_status in {RelevanceStatus.STRONG, RelevanceStatus.CREDIBLE}
    if role.relevance_status == RelevanceStatus.BORDERLINE and role.manual_override:
        relevance_ok = True
    return (
        eligibility_ok
        and relevance_ok
        and not role.publication_review_required
        and role.status != ProgrammeStatus.CLOSED
        and role.geographic_scope in {GeographicScope.LONDON, GeographicScope.UK_PRIORITY_EXCEPTION}
        and role.source_authority != SourceAuthority.DISCOVERY_ONLY_SOURCE
        and role.paid is not False
        and _fits_candidate_availability(role, rules)
    )


PROGRAMME_ROLE_SIGNALS = (
    "intern",
    "internship",
    "vacation scheme",
    "spring week",
    "spring insight",
    "insight week",
    "insight programme",
    "insight program",
    "insight day",
    "work experience",
    "summer analyst",
    "summer associate",
    "summer placement",
    "winter internship",
    "winter project",
    "winter programme",
    "winter program",
    "micro internship",
)

TERM_TIME_ROLE_SIGNALS = (
    "compliance",
    "anti money laundering",
    "aml",
    "know your customer",
    "kyc",
    "financial crime",
    "risk",
    "regulatory",
    "internal audit",
    "governance",
    "finance",
    "financial",
    "accounting",
    "investment",
    "asset management",
    "wealth management",
    "banking",
    "credit",
    "legal",
    "paralegal",
    "law",
    "consulting",
    "consultancy",
    "strategy",
    "policy",
    "public affairs",
    "government affairs",
    "corporate affairs",
    "economics",
    "economic",
    "due diligence",
    "commercial analysis",
    "research",
)

TERM_TIME_AVAILABILITY_SIGNALS = (
    "part time",
    "term time",
    "weekend only",
    "weekends only",
    "evenings only",
    "casual contract",
    "zero hours",
    "flexible part time",
    "part time considered",
    "job share",
    "0.5 fte",
    "0.4 fte",
    "0.3 fte",
    "0.2 fte",
)

LONG_DURATION_SIGNALS = (
    "4 month internship",
    "intern for 4 months",
    "4 months ftc",
    "5 month internship",
    "intern for 5 months",
    "5 months ftc",
    "6 month internship",
    "intern for 6 months",
    "6 months ftc",
    "9 month internship",
    "intern for 9 months",
    "9 months ftc",
    "12 month internship",
    "intern for 12 months",
    "12 months ftc",
    "one year internship",
    "6 month contract",
    "12 month contract",
    "one year contract",
    "12 month placement",
    "one year placement",
    "one year work placement",
    "industrial placement",
    "year in industry",
    "off cycle",
    "offcycle",
)

ORDINARY_JOB_SIGNALS = ("full time", "permanent")
RESEARCH_ROLE_SIGNALS = ("research", "researcher")
ALLOWED_RESEARCH_CONTEXTS = (
    "finance",
    "financial",
    "investment",
    "credit",
    "risk",
    "compliance",
    "regulatory",
    "economics",
    "economic",
    "market",
    "markets",
    "equity",
    "debt",
    "banking",
    "insurance",
    "capital",
    "forensic accounting",
)
ALLOWED_RESEARCH_EMPLOYERS = frozenset(
    {
        "Bank of America",
        "Barclays",
        "BlackRock",
        "Bloomberg",
        "BNP Paribas",
        "Citi",
        "Deutsche Bank",
        "Financial Conduct Authority",
        "Fitch Ratings",
        "Goldman Sachs",
        "HSBC",
        "JPMorgan Chase",
        "JPMorganChase",
        "Lazard",
        "London Stock Exchange Group",
        "LSEG",
        "Morgan Stanley",
        "Moody's",
        "Morningstar",
        "MSCI",
        "Nomura",
        "Rothschild & Co",
        "S&P Global",
        "Standard Chartered",
        "UBS",
        "Bank of England",
    }
)

POSSIBLE_ROLE_EXCLUSIONS = (
    "graduate",
    "graduate scheme",
    "graduate programme",
    "graduate program",
    "graduate job",
    "manager",
    "senior",
    "head of",
    "director",
    "chief",
    "principal",
    "supervisor",
    "lead",
    "leader",
    "apprentice",
    "school leaver",
    "campus ambassador",
    "reception",
    "receptionist",
    "front of house",
    "front desk",
    "switchboard",
    "nursery",
    "early years",
    "childcare",
    "child care",
    "preschool",
    "pre school",
    "room leader",
    "nanny",
    "babysitter",
    "playworker",
    "play worker",
    "teaching assistant",
    "learning support assistant",
    "classroom assistant",
    "kitchen assistant",
    "catering assistant",
    "assistant chef",
    "sales assistant",
    "customer service",
    "tutor",
    "gas engineer",
    "java developer",
    "locum",
    "business studies teacher",
    "pharmacy assistant",
    "therapy assistant",
    "machine learning",
    "natural language processing",
    "software engineer",
    "software developer",
    "data science",
    "quant research",
    "quantitative research",
    "quant researcher",
    "quantitative researcher",
    "quantitative analyst",
    "quantitative finance",
    "quantitative strategies",
    "quantitative trading",
    "quant trading",
    "quant trader",
    "quantitative developer",
    "quant developer",
    "systematic researcher",
    "systematic trading",
    "algorithmic trading",
    "quants",
    "engineering internship",
    "engineering summer internship",
    "solutions engineer",
    "architecture intern",
    "actuarial",
    "professor",
    "lecturer",
    "lecturers",
    "research fellow",
    "research fellows",
    "clinical fellow",
    "clinical research",
    "medical research",
    "medical communications",
    "health research",
    "biomedical research",
    "neuroscience research",
    "laboratory research",
    "research technician",
    "research scientist",
    "doctor",
    "nurse",
    "midwife",
    "radiographer",
    "psychologist",
    "psychotherapist",
    "therapist",
    "pharmacist",
    "physiotherapist",
    "occupational therapist",
    "dentist",
    "medical prescriber",
    "healthcare assistant",
    "care assistant",
    "solicitor",
    "volunteer",
    "palliative care",
    "clinical advisor",
    "clinical adviser",
    "12 month placement",
    "industrial placement",
    "year in industry",
    "summer 2026",
    "start date march april 2026",
    "social media",
    "social creative",
    "systems analyst",
    "expert",
    "construction ambassador",
    "financial controller",
    "legal counsel",
    "legal secretary",
    "legal cashier",
    "personal assistant",
    "pa to",
    "internship program coordinator",
    "internship programme coordinator",
    "careers coordinator work experience",
    "work experience coordinator",
)

NON_JOB_DISCOVERY_PROVIDERS = {
    "beyond academy",
    "the intern group",
}

PUBLIC_HEALTH_ROLE_EXCLUSIONS = (
    "consultant",
    "locum",
    "general practitioner",
    "psychiatrist",
    "surgeon",
    "anaesthetist",
    "pathologist",
    "cardiologist",
    "ophthalmologist",
    "neurologist",
    "dermatologist",
    "paediatric",
    "gynaecologist",
    "orthopaedic",
    "nursing",
    "physiotherapy",
    "radiograph",
    "pharmacy",
    "kitchen assistant",
    "housekeeping assistant",
    "catering assistant",
    "activities assistant",
    "care support assistant",
    "allied health professional",
    "practitioner",
    "psychological",
    "therapy",
    "radiographic",
    "support worker",
    "catering",
    "engineer",
    "surgical",
    "physician",
    "medical officer",
)

HIGHER_EDUCATION_ROLE_EXCLUSIONS = (
    "postdoctoral",
    "post doctoral",
    "research associate",
    "dean",
    "reader",
    "programme leader",
    "program leader",
    "subject lead",
)


def _has_term_time_hours(text: str) -> bool:
    """Recognise an explicit weekly schedule that can fit alongside university."""

    patterns = (
        r"(?<![a-z0-9.])(\d{1,2}(?:\.\d+)?)\s*(?:hours?|hrs?)\s*(?:per|a|/)\s*week(?![a-z0-9])",
        r"(?<![a-z0-9.])(\d{1,2}(?:\.\d+)?)\s*(?:hour|hr)\s*week(?![a-z0-9])",
        r"(?<![a-z0-9.])up to\s+(\d{1,2}(?:\.\d+)?)\s*(?:hours?|hrs?)\s*(?:weekly|(?:per|a|/)\s*week)(?![a-z0-9])",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            if 1 <= float(match.group(1)) <= 24:
                return True
    return False


_DURATION_MONTHS = {
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


def _has_long_duration(text: str, configured_signals: tuple[str, ...]) -> bool:
    """Catch numeric and written long durations even when word order varies."""

    if _contains(text, configured_signals):
        return True
    for match in re.finditer(
        r"(?<![a-z0-9])(?P<duration>[4-9]|[1-9][0-9]|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+months?(?![a-z0-9])",
        text,
    ):
        raw_duration = match.group("duration")
        months = int(raw_duration) if raw_duration.isdigit() else _DURATION_MONTHS[raw_duration]
        if months > 60:
            continue
        window = text[max(0, match.start() - 60) : match.end() + 60]
        if months >= 4 and _contains(window, ("intern", "internship", "placement")):
            return True
        if months >= 6 and _contains(window, ("contract", "fixed term", "ftc")):
            return True
    for match in re.finditer(r"(?<![a-z0-9])(?:one|1)\s+year(?![a-z0-9])", text):
        window = text[max(0, match.start() - 60) : match.end() + 60]
        if _contains(
            window, ("intern", "internship", "placement", "contract", "fixed term", "ftc")
        ):
            return True
    return False


def is_possible_role(role: RoleRecord, rules: ClassificationRules | None = None) -> bool:
    """Select break-based programmes and genuinely term-compatible professional work."""

    active_rules = rules or DEFAULT_RULES
    if is_public_role(role, active_rules):
        return False
    excluded_employers = active_rules.excluded_discovery_employers or frozenset(
        NON_JOB_DISCOVERY_PROVIDERS
    )
    title = normalise_text(role.title)
    relevance_ok = role.relevance_status in {
        RelevanceStatus.STRONG,
        RelevanceStatus.CREDIBLE,
        RelevanceStatus.BORDERLINE,
    }
    gp_clinician = (
        role.organisation_type == "public_health"
        and _matches(title, "gp")
        and not _contains(
            title,
            ("reception", "receptionist", "admin", "administrator", "assistant"),
        )
    )
    fee_bearing_placement_provider = (
        role.source_authority == SourceAuthority.DISCOVERY_ONLY_SOURCE
        and normalise_text(role.canonical_employer)
        in {normalise_text(name) for name in excluded_employers}
    )
    return (
        role.status == ProgrammeStatus.OPEN
        and role.eligibility_status != EligibilityStatus.INELIGIBLE
        and relevance_ok
        and _fits_candidate_availability(role, active_rules)
        and not gp_clinician
        and not fee_bearing_placement_provider
        and role.geographic_scope in {GeographicScope.LONDON, GeographicScope.UK_PRIORITY_EXCEPTION}
        and role.paid is not False
    )

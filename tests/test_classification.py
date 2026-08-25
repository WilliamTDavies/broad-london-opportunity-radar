from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opportunity_radar.classification import load_classification_rules
from opportunity_radar.classification.engine import (
    canonicalise_url,
    classify_role,
    clean_employer_name,
    is_possible_role,
    is_public_role,
)
from opportunity_radar.models import (
    EligibilityStatus,
    EmployerConfig,
    GeographicScope,
    ManualOverride,
    ProgrammeType,
    RawRole,
    RelevanceStatus,
    RoleRecord,
    SourceAuthority,
)

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)


def raw(**updates: object) -> RawRole:
    data: dict[str, object] = {
        "source_identifier": "role-1",
        "employer": "Test Employer",
        "title": "Summer 2027 Policy and Risk Internship",
        "source_url": "https://example.invalid/jobs/1?utm_source=test",
        "source_type": "fixture",
        "source_authority": SourceAuthority.OFFICIAL_PROGRAMME_PAGE,
        "location": "London",
        "description": "Paid policy research, risk analysis and written briefings.",
        "eligibility_text": "Open to penultimate-year students from any degree discipline.",
        "paid": True,
        "paid_evidence": "Official listing states £500 per week",
        "cycle_hint": "Summer 2027",
    }
    data.update(updates)
    return RawRole.model_validate(data)


def classify(employer: EmployerConfig, **updates: object) -> RoleRecord:
    return classify_role(raw(**updates), employer, observed_at=NOW)


def test_verified_penultimate_any_degree_role_is_public(employer: EmployerConfig) -> None:
    role = classify(employer)
    assert role.eligibility_status == EligibilityStatus.VERIFIED
    assert role.relevance_status in {RelevanceStatus.STRONG, RelevanceStatus.CREDIBLE}
    assert role.programme_type == ProgrammeType.SUMMER_INTERNSHIP
    assert is_public_role(role)
    assert role.eligibility_evidence


@pytest.mark.parametrize(
    ("source_name", "expected"),
    [
        ("  Transport   For London ", "Transport for London"),
        ("Age Uk Richmond ", "Age UK Richmond"),
        (
            "University College London NHS Foundation Trust",
            "University College London NHS Foundation Trust",
        ),
    ],
)
def test_employer_display_names_are_clean_and_stable(source_name: str, expected: str) -> None:
    assert clean_employer_name(source_name) == expected


def test_discovery_role_uses_clean_employer_display_name(employer: EmployerConfig) -> None:
    role = classify_role(
        raw(
            employer=" Transport  For London ",
            source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
        ),
        employer,
        observed_at=NOW,
    )
    assert role.canonical_employer == "Transport for London"


def test_official_anticipated_summer_2028_wording_is_verified(
    employer: EmployerConfig,
) -> None:
    role = classify(
        employer,
        eligibility_text=(
            "Currently enrolled as an undergraduate or masters student. "
            "Anticipated graduation date: Summer 2028."
        ),
    )
    assert role.eligibility_status == EligibilityStatus.VERIFIED
    assert role.graduation_year_restrictions == ["Anticipated graduation date: Summer 2028."]
    assert is_public_role(role)


def test_official_completion_window_covering_june_2028_is_verified(
    employer: EmployerConfig,
) -> None:
    wording = (
        "Candidates must be pursuing a Bachelor's or Master's degree with a completion "
        "time frame between June 2027 and July 2028."
    )
    role = classify(employer, eligibility_text=wording)
    assert role.eligibility_status == EligibilityStatus.VERIFIED
    assert role.graduation_year_restrictions == [wording]
    assert is_public_role(role)


def test_investment_due_diligence_has_an_accurate_explanation(
    employer: EmployerConfig,
) -> None:
    role = classify(
        employer,
        title="Summer 2027 Private Equity Internship",
        description="Investment research, due diligence and financial analysis.",
    )
    assert any("investment due diligence" in reason.casefold() for reason in role.relevance_reasons)
    assert not any("legal, compliance" in reason.casefold() for reason in role.relevance_reasons)


@pytest.mark.parametrize(
    "updates",
    [
        {"eligibility_text": "Final year students only."},
        {"eligibility_text": "Law degree only; LLB required."},
        {
            "title": "Summer 2027 Software Engineering Internship",
            "description": "Computer science degree required.",
        },
        {"paid": False, "paid_evidence": "Unpaid"},
        {"description": "Completed degree required for this graduate role."},
    ],
)
def test_hard_exclusions_cannot_be_overridden_by_priority(
    employer: EmployerConfig, updates: dict[str, object]
) -> None:
    role = classify(employer.model_copy(update={"priority_tier": "priority"}), **updates)
    assert role.eligibility_status == EligibilityStatus.INELIGIBLE
    assert not is_public_role(role)


def test_eligible_non_law_vacation_scheme(employer: EmployerConfig) -> None:
    role = classify(
        employer,
        title="Summer Vacation Scheme 2027",
        description="Paid legal and regulatory work.",
        eligibility_text="Open to penultimate-year non-law students from any degree.",
    )
    assert role.programme_type == ProgrammeType.SUMMER_VACATION
    assert role.eligibility_status == EligibilityStatus.VERIFIED
    assert is_public_role(role)


def test_final_year_non_law_vacation_scheme_rejected(employer: EmployerConfig) -> None:
    role = classify(
        employer,
        title="Spring Vacation Scheme 2027",
        eligibility_text="Penultimate-year law students; final-year non-law students only.",
    )
    assert role.eligibility_status == EligibilityStatus.INELIGIBLE


def test_parliamentary_research_outside_current_research_scope(
    employer: EmployerConfig,
) -> None:
    role = classify(
        employer,
        title="Paid Parliamentary Research Intern",
        description="Paid Westminster parliamentary policy research for an MP office.",
        eligibility_text="Current undergraduates from any degree.",
        cycle_hint="2026-27",
    )
    assert role.programme_type == ProgrammeType.PARLIAMENTARY
    assert not is_public_role(role)


def test_unpaid_political_campaign_rejected(employer: EmployerConfig) -> None:
    role = classify(
        employer,
        title="Election Campaign Volunteer",
        description="Unpaid election campaign volunteering.",
        paid=False,
        paid_evidence="Unpaid",
    )
    assert role.eligibility_status == EligibilityStatus.INELIGIBLE


@pytest.mark.parametrize(
    ("title", "description", "category"),
    [
        (
            "Environmental Risk Internship",
            "Paid climate risk and environmental assessment.",
            "Environmental Risk Management",
        ),
        (
            "Development Finance Intern",
            "Paid development finance, impact investment and due diligence.",
            "Development Finance and Impact Investment",
        ),
        (
            "Health Policy Internship",
            "Paid health policy and health economics research.",
            "Health Policy and Health Economics",
        ),
        (
            "Geospatial Analysis Internship",
            "Paid QGIS and GIS location intelligence analysis.",
            "Geospatial Analysis and GIS",
        ),
        (
            "Supply Chain Internship",
            "Paid procurement, logistics and supply chain analysis.",
            "Supply Chain and Procurement",
        ),
    ],
)
def test_priority_sector_roles_are_accepted(
    employer: EmployerConfig, title: str, description: str, category: str
) -> None:
    role = classify(employer, title=title, description=description)
    assert role.primary_category == category
    assert is_public_role(role)


def test_substantive_communications_distinguished_from_social_media(
    employer: EmployerConfig,
) -> None:
    substantive = classify(
        employer,
        title="Strategic Stakeholder Engagement Internship",
        description="Paid policy research, strategic communications and stakeholder engagement.",
    )
    generic = classify(
        employer,
        source_identifier="role-2",
        title="Social Media Volunteer",
        description="Unpaid generic social media volunteer.",
        paid=False,
    )
    assert is_public_role(substantive)
    assert not is_public_role(generic)


def test_british_citizenship_only_satisfies_nationality_element(employer: EmployerConfig) -> None:
    role = classify(
        employer.model_copy(
            update={
                "uk_priority_exception": True,
                "exception_reason": "Approved national programme",
            }
        ),
        location="Cheltenham",
        nationality_requirements=["British citizen"],
        residency_requirements=["Must meet an unstated residency period"],
        clearance_requirements=["Developed Vetting may be required"],
    )
    assert role.geographic_scope == GeographicScope.UK_PRIORITY_EXCEPTION
    assert role.eligibility_status == EligibilityStatus.UNCERTAIN
    assert "nationality element only" in (role.nationality_assessment or "")
    assert not is_public_role(role)


def test_department_and_basic_coding_do_not_create_stem_eligibility(
    employer: EmployerConfig,
) -> None:
    role = classify(
        employer,
        title="Machine Learning Engineer Internship",
        description="Python and HTML. Mathematics degree required. Department of Mathematical and Physical Sciences accepted.",
    )
    assert role.eligibility_status == EligibilityStatus.INELIGIBLE


def test_cycle_unstated_remains_separate(employer: EmployerConfig) -> None:
    role = classify(
        employer,
        title="Commercial Research Intern",
        description="Paid commercial analysis and market research.",
        cycle_hint=None,
    )
    assert role.programme_type == ProgrammeType.CYCLE_UNSTATED
    assert role.cycle_provenance.value == "cycle_unstated"


def test_priority_employer_monitoring_does_not_automatically_include(
    employer: EmployerConfig,
) -> None:
    role = classify(
        employer.model_copy(update={"priority_tier": "priority"}),
        title="Generic Administrative Assistant",
        description="Routine office administration.",
    )
    assert not is_public_role(role)


@pytest.mark.parametrize(
    "title",
    [
        "Business Support Admin",
        "Research Regulatory Facilitator",
        "Customer Service Officer",
        "Programme Specialist",
    ],
)
def test_possible_pool_rejects_generic_titles_without_availability_evidence(
    employer: EmployerConfig, title: str
) -> None:
    source = employer.model_copy(
        update={"manual_review_required": True, "priority_tier": "approved"}
    )
    role = classify(
        source,
        title=title,
        source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
        eligibility_text="",
    )
    assert not is_possible_role(role)


def test_possible_pool_keeps_full_time_summer_compliance_internship(
    employer: EmployerConfig,
) -> None:
    source = employer.model_copy(
        update={"manual_review_required": True, "priority_tier": "approved"}
    )
    role = classify(
        source,
        title="2027 EMEA London Compliance Summer Analyst",
        description="Full-time nine-week summer internship in compliance and financial crime.",
        eligibility_text="",
        source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
    )
    assert role.eligibility_status != EligibilityStatus.INELIGIBLE
    assert is_possible_role(role)


def test_possible_pool_requires_part_time_evidence_for_ordinary_compliance_role(
    employer: EmployerConfig,
) -> None:
    source = employer.model_copy(
        update={"manual_review_required": True, "priority_tier": "approved"}
    )
    full_time = classify(
        source,
        title="Compliance Analyst",
        description="Permanent full-time compliance and regulatory role.",
        eligibility_text="",
        source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
    )
    part_time = classify(
        source,
        source_identifier="part-time-compliance",
        title="Compliance Analyst",
        description="Part-time role for 16 hours per week in compliance and regulatory risk.",
        eligibility_text="",
        source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
    )
    assert not is_possible_role(full_time)
    assert is_possible_role(part_time)


@pytest.mark.parametrize(
    ("schedule", "expected"),
    [
        ("Contracted hours: 42.5 hours per week.", False),
        ("Part-time schedule of 20 hrs/week.", True),
        ("Work up to 24 hours weekly.", True),
        ("This is a 25 hour week.", False),
    ],
)
def test_term_time_hour_parser_does_not_truncate_decimal_hours(
    employer: EmployerConfig, schedule: str, expected: bool
) -> None:
    source = employer.model_copy(
        update={"manual_review_required": True, "priority_tier": "approved"}
    )
    role = classify(
        source,
        title="Financial Reporting Assistant",
        description=f"{schedule} Finance and regulatory reporting work.",
        eligibility_text="",
        source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
    )
    assert is_possible_role(role) is expected


@pytest.mark.parametrize(
    "title",
    [
        "Compliance Internship - 12 Month Contract",
        "Risk Off-Cycle Internship",
        "Policy Research Internship",
        "Clinical Research Internship",
        "Winter Vacation Scheme for Final-Year University Students and Recent Graduates",
    ],
)
def test_possible_pool_rejects_long_or_out_of_scope_internships(
    employer: EmployerConfig, title: str
) -> None:
    source = employer.model_copy(
        update={"manual_review_required": True, "priority_tier": "approved"}
    )
    role = classify(
        source,
        title=title,
        description="Paid internship with analytical and research work.",
        eligibility_text="",
        source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
    )
    assert not is_possible_role(role)


def test_possible_pool_keeps_financial_research_internship(
    employer: EmployerConfig,
) -> None:
    source = employer.model_copy(
        update={"manual_review_required": True, "priority_tier": "approved"}
    )
    role = classify(
        source,
        title="Credit Research Internship",
        description="Paid internship in financial credit and risk research.",
        eligibility_text="",
        source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
    )
    assert is_possible_role(role)


def test_finance_employer_context_keeps_global_research_internship(
    project_root: Path, employer: EmployerConfig
) -> None:
    rules = load_classification_rules(project_root)
    source = employer.model_copy(
        update={"manual_review_required": True, "priority_tier": "approved"}
    )
    finance = classify_role(
        raw(
            employer="UBS",
            title="Global Research (HOLT) Summer Internship 2027",
            description="Paid analytical summer internship.",
            eligibility_text="",
            source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
        ),
        source,
        observed_at=NOW,
        rules=rules,
    )
    science = classify_role(
        raw(
            source_identifier="science-research",
            employer="Example Biotech",
            title="Global Research Summer Internship 2027",
            description="Paid scientific summer internship.",
            eligibility_text="",
            source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
        ),
        source,
        observed_at=NOW,
        rules=rules,
    )
    assert is_possible_role(finance, rules)
    assert not is_possible_role(science, rules)


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("Group Financial Controller", "Contracted hours: 42.5 hours per week."),
        ("PA to Internal Audit Directors", "Part-time role for 21 hours per week."),
        ("Legal Counsel", "Part-time role for three days per week."),
        ("Commercial Property Legal Secretary", "Flexible part-time hours."),
        ("Legal Cashier", "Part-time role for 21 hours per week."),
        ("Internship Program Coordinator", "Part-time university programme administration."),
        ("Careers Coordinator Work Experience", "Part-time education role."),
        ("Student Construction Ambassador & Industry Insight Programme", "Paid programme."),
        ("Quantitative Strategies and Data Group Internship", "Paid summer internship."),
        ("Global Markets Digital Office Internship (Quants & Strats)", "Paid internship."),
        ("Compliance Officer", "Seeking an experienced compliance professional."),
    ],
)
def test_semantically_misleading_titles_are_rejected(
    employer: EmployerConfig, title: str, description: str
) -> None:
    source = employer.model_copy(
        update={"manual_review_required": True, "priority_tier": "approved"}
    )
    role = classify(
        source,
        title=title,
        description=f"{description} Includes financial analysis and compliance work.",
        eligibility_text="",
        source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
    )
    assert not is_possible_role(role)


@pytest.mark.parametrize(
    "description",
    [
        "Paid compliance internship lasting four months.",
        "Paid risk internship on a five-month placement.",
        "Part-time compliance role on a nine month fixed-term contract.",
        "Part-time finance role; contract duration is twelve months.",
        "HR internship on a 13 months graduate contract.",
    ],
)
def test_written_and_reordered_long_durations_are_rejected(
    employer: EmployerConfig, description: str
) -> None:
    source = employer.model_copy(
        update={"manual_review_required": True, "priority_tier": "approved"}
    )
    role = classify(
        source,
        title="Compliance Internship",
        description=description,
        eligibility_text="",
        source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
    )
    assert not is_possible_role(role)


@pytest.mark.parametrize(
    ("title", "organisation_type"),
    [
        ("Locum Consultant Cardiologist", "public_health"),
        ("Community Nursing Associate", "public_health"),
        ("Kitchen Assistant - Care Home", "public_health"),
        ("First Aid and Welfare Volunteer", "public_health"),
        ("Pod Leader Wellbeing Support Worker", "charity"),
        ("Consultant in Specialist Palliative Care", "charity"),
        ("Clinical Research Practitioner", "public_health"),
        ("Fixed term salaried GP with permanent placement", "public_health"),
        ("Postdoctoral Research Associate", "higher_education"),
        ("Storytelling Research Fellows", "higher_education"),
        ("Lecturers of Business", "higher_education"),
        ("Executive Dean", "higher_education"),
        ("Immigration Solicitor", "charity"),
        ("Marketing Intern - 12 Month Placement", "corporate"),
        ("Graduate Intern, Portfolio Valuations", "corporate"),
        ("Quant Trading Internship", "corporate"),
        ("Actuarial Summer Internship", "corporate"),
        ("Architecture Intern (Paid Internship)", "corporate"),
        ("Marketing and Sales Internship - Summer 2026", "corporate"),
        ("Customer Service Receptionist", "corporate"),
        ("Front of House Assistant", "corporate"),
        ("Nursery Assistant", "corporate"),
        ("Early Years Assistant", "corporate"),
        ("Teaching Assistant", "corporate"),
        ("Quantitative Research Analyst", "corporate"),
        ("Quantitative Analyst", "corporate"),
        ("Kitchen Assistant", "corporate"),
        ("Sales Assistant", "corporate"),
        ("Locum Consultant Cardiologist", "corporate"),
    ],
)
def test_possible_pool_rejects_obviously_credentialed_or_senior_titles(
    employer: EmployerConfig, title: str, organisation_type: str
) -> None:
    source = employer.model_copy(
        update={"manual_review_required": True, "priority_tier": "approved"}
    )
    role = classify(
        source,
        title=title,
        organisation_type=organisation_type,
        source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
        eligibility_text="",
    )
    assert not is_possible_role(role)


@pytest.mark.parametrize("provider", ["Beyond Academy", "The Intern Group"])
def test_possible_pool_rejects_fee_bearing_placement_provider_products(
    employer: EmployerConfig, provider: str
) -> None:
    source = employer.model_copy(
        update={"manual_review_required": True, "priority_tier": "approved"}
    )
    role = classify_role(
        raw(
            employer=provider,
            title="Global Immersive Internship Programme",
            source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
            eligibility_text="",
        ),
        source,
        observed_at=NOW,
    )
    assert not is_possible_role(role)


def test_possible_pool_rejects_gp_reception_and_ordinary_admin(
    employer: EmployerConfig,
) -> None:
    source = employer.model_copy(
        update={"manual_review_required": True, "priority_tier": "approved"}
    )
    reception = classify(
        source,
        title="GP Receptionist / Administrator",
        organisation_type="public_health",
        source_authority=SourceAuthority.OFFICIAL_GOVERNMENT_PORTAL,
        eligibility_text="",
    )
    admin = classify(
        source,
        title="GP Practice Administrator",
        organisation_type="public_health",
        source_authority=SourceAuthority.OFFICIAL_GOVERNMENT_PORTAL,
        eligibility_text="",
    )
    assert not is_possible_role(reception)
    assert not is_possible_role(admin)


def test_editable_job_filters_reject_required_cpp_but_not_optional_mention(
    project_root: Path, employer: EmployerConfig
) -> None:
    rules = load_classification_rules(project_root)
    source = employer.model_copy(
        update={"manual_review_required": True, "priority_tier": "approved"}
    )
    required = classify_role(
        raw(
            title="Investment Research Intern",
            description="Applicants must have strong C++ programming skills.",
            eligibility_text="",
            source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
        ),
        source,
        observed_at=NOW,
        rules=rules,
    )
    optional = classify_role(
        raw(
            source_identifier="role-optional-cpp",
            title="Investment Research Intern",
            description="Python is used; exposure to C++ is useful but optional.",
            eligibility_text="",
            source_authority=SourceAuthority.DISCOVERY_ONLY_SOURCE,
        ),
        source,
        observed_at=NOW,
        rules=rules,
    )
    assert required.eligibility_status == EligibilityStatus.INELIGIBLE
    assert not is_possible_role(required, rules)
    assert optional.eligibility_status != EligibilityStatus.INELIGIBLE
    assert is_possible_role(optional, rules)


def test_government_board_preserves_the_actual_listing_employer(
    employer: EmployerConfig,
) -> None:
    role = classify_role(
        raw(
            employer="Example NHS Foundation Trust",
            source_authority=SourceAuthority.OFFICIAL_GOVERNMENT_PORTAL,
        ),
        employer,
        observed_at=NOW,
    )
    assert role.canonical_employer == "Example NHS Foundation Trust"


def test_minor_ngo_is_rejected_even_when_role_is_paid(employer: EmployerConfig) -> None:
    role = classify(
        employer.model_copy(update={"priority_tier": "review"}),
        title="Humanitarian Research Internship",
        description="Paid humanitarian research and monitoring work.",
        organisation_type="ngo",
    )
    assert role.relevance_status == RelevanceStatus.IRRELEVANT
    assert not is_public_role(role)


def test_documented_manual_override_can_publish_borderline_role(
    employer: EmployerConfig,
) -> None:
    source = raw(
        title="Selective Professional Internship",
        description="Substantive paid professional experience.",
        eligibility_text="Eligibility reviewed against the official programme page.",
    )
    override = ManualOverride(
        role_id="placeholder",
        eligibility_status=EligibilityStatus.MANUAL,
        relevance_status=RelevanceStatus.BORDERLINE,
        email_approved=True,
        reason="Maintainer verified undergraduate eligibility and substantive responsibilities",
        evidence_url="https://example.invalid/official-evidence",
        reviewed_at=NOW,
    )
    role = classify_role(source, employer, observed_at=NOW, override=override)
    assert role.eligibility_status == EligibilityStatus.MANUAL
    assert is_public_role(role)
    assert role.email_approved


def test_url_canonicalisation_removes_tracking() -> None:
    assert (
        canonicalise_url("HTTPS://Example.COM/jobs/1/?utm_source=x&gclid=2")
        == "https://example.com/jobs/1"
    )

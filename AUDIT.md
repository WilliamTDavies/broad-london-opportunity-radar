# Independent specification audit

Original audit date: 11 August 2026 (America/Chicago). Broad-source remediation updated 12 August 2026.

Specification audited: `Pasted markdown(20260811-002308).md`, 1,838 lines, SHA-256 `e37c236ffb82e86b5b058465f7f760596fcf1934858a520b32ffb1d4f9e7876e`.

This is an evidence record, not a completeness claim. The 22 August remediation narrows publication to short internships, vacation/insight/winter programmes and relevant professional roles with explicit term-compatible hours. The checked-in snapshot now contains 25 verified roles and 82 possible roles across 47 employers after reclassifying the stored broad-board results. A focused 37-query matrix replaces generic assistant/analyst queries; long placements, ordinary full-time work, clinical/scientific research and hard technical conflicts are excluded. Adzuna and Reed are implemented but require their API secrets for future live scans. Supabase, Resend, GitHub Actions and Pages have not been deployed from this environment. Counts and conclusions elsewhere in this document dated 11 August are historical unless this addendum supersedes them.

## Breadth-remediation addendum (current)

This addendum supersedes older counts and “uncertain roles stay off the public dashboard” statements retained later in the historical requirement audit.

- `classification/engine.py` now has independent `is_public_role` (verified) and `is_possible_role` (recall-oriented) boundaries. Explicitly ineligible, closed, unpaid, out-of-scope, senior and specialist technical roles fail both.
- `adapters/parsers.py` includes tested, count-validating retrieval for CharityJob, NHS Jobs, jobs.ac.uk and targetjobs plus complete Higherin and W4MP adapters. `adapters/broad_sources.py` adds tested DWP Work Hub, Prospects, Legal Cheek, Adzuna and Reed adapters. The actual employer is preserved; the board is recorded separately as publisher.
- `pipeline/scanner.py` persists `possible_roles.json` separately. Failed/capped sources retain unseen records, while fetched records and stale records invalidated by current rules are removed immediately.
- `site/builder.py` combines both tiers in the default open-jobs view while generating separate `roles.json` and `possible-roles.json`. Filtering by confidence, saving, search and sorting work across both tiers. The table renders at most 100 matches at a time and fetches escaped detail cards from `role-details.json` on demand.
- The verified-only email boundary is unchanged. Possible records never enter the digest.
- Live DWP, Prospects and Legal Cheek source-filtered scans ran through HTTPX in this workspace. No scheduled GitHub scan or deployment success is claimed.

## Status vocabulary

- **implemented and verified** — code/configuration exists and the cited local test or command passed.
- **partially implemented** — meaningful implementation exists, but part of the stated requirement is absent or not fully verified.
- **missing** — no adequate implementation exists.
- **blocked by unavailable credentials or external access** — the local implementation exists, but the required live system could not be exercised honestly.
- **intentionally excluded with a valid reason** — omission is required for safety or evidence quality and is documented.

## Final local verification evidence

The release gate is rerun after every audit correction. The final authoritative counts and command output are recorded in the “Final verification” section at the end of this document. Principal evidence locations are:

- validated models: `src/opportunity_radar/models/records.py`;
- configuration loaders and cross-validation: `src/opportunity_radar/config.py`, `src/opportunity_radar/classification/rules.py`;
- classification/publication boundary: `src/opportunity_radar/classification/engine.py`;
- adapters: `src/opportunity_radar/adapters/` and `fixtures/`;
- scan, lifecycle, dedupe and storage: `src/opportunity_radar/pipeline/`, `src/opportunity_radar/storage/json_store.py`;
- dashboard: `src/opportunity_radar/site/builder.py`, `site/templates/index.html`, `site/static/`;
- subscription infrastructure: `supabase/migrations/`, `supabase/functions/`;
- digest: `src/opportunity_radar/email/digest.py`;
- workflows: `.github/workflows/`;
- executable evidence: `tests/` and `tests/js/`.

## Requirement traceability

### 1. Product objective and boundaries

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Track the stated London Summer 2027, law vacation-scheme, paid policy/parliamentary and exceptional programme scope | partially implemented | Production contains 16 verified records and 789 possible records; `config/radar.yml` tracks 22 evidence-labelled programmes. A currently open, verified non-law vacation scheme is not present. |
| Poll sources, detect new roles, classify, deduplicate, close cautiously, build a site/radar and select a daily digest | implemented and verified | `pipeline/scanner.py`, `pipeline/changes.py`, `pipeline/deduplication.py`, `pipeline/lifecycle.py`, `site/builder.py`, and `email/digest.py`; fixture E2E `test_complete_fixture_pipeline`; command `python run.py scan --fixtures` produced 28 observations, 9 public roles, 1 possible role and 1 review item under the stricter rules. |
| Do not become a technology/prestige-only tracker | implemented and verified | Hard exclusions and organisation rules in `config/eligibility_rules.yml` and `organisation_tiers.yml`; tests `test_hard_exclusions_cannot_be_overridden_by_priority`, `test_priority_employer_monitoring_does_not_automatically_include`, and `test_department_and_basic_coding_do_not_create_stem_eligibility`. |
| Distinguish verified facts from inference and preserve exact evidence | implemented and verified | `Evidence` and provenance enums in `models/records.py`; exact fragments are built in `classification/engine.py`; `test_eligibility_evidence_is_exact_source_text` and `test_date_and_cycle_provenance_follow_source_authority`. |

### 2. Target candidate and eligibility profile

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Use the stated stage, non-law degree and graduation year without publishing identity/CV | implemented and verified | Candidate-safe public wording is in `site/templates/index.html`; repository hygiene validation scans public output; no résumé or identity file exists. Graduation/study-stage rules are in `classification/engine.py`. |
| Do not treat department, Python or HTML as specialist STEM eligibility | implemented and verified | `test_department_and_basic_coding_do_not_create_stem_eligibility`; negative rules in `config/eligibility_rules.yml`. |
| Use British/New Zealand citizenship only for an explicit nationality requirement, never as proof of residency/clearance | implemented and verified | `classification/engine.py`; `test_british_citizenship_only_satisfies_nationality_element`, `test_new_zealand_citizenship_handles_explicit_commonwealth_requirement`, `test_nationality_evidence_alone_does_not_establish_study_stage`. |
| No visa/sponsorship ranking or badges | implemented and verified | No sponsorship field, score component, template badge or rule exists; `RoleRecord.match_components` is constrained to the eight documented factors by classification tests. |

### 3. Eligibility, quality, evidence and relevance rules

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Include explicit 2028, penultimate/second-year, any-degree and applicable undergraduate evidence | implemented and verified | Config-driven patterns in `eligibility_rules.yml`, evaluation in `classification/engine.py`; `test_verified_penultimate_any_degree_role_is_public`. |
| Non-law vacation schemes require an unambiguous applicable study stage | implemented and verified | `test_eligible_non_law_vacation_scheme`, `test_final_year_non_law_vacation_scheme_rejected`, and `test_vacation_scheme_any_degree_without_non_law_stage_is_uncertain`. |
| Hard-exclude graduate, law-only, specialist technical, clinical, placement-year, unpaid and other listed unsuitable work | implemented and verified | `config/eligibility_rules.yml`, `classification/engine.py`; parameterised hard-exclusion and priority tests in `tests/test_classification.py`. |
| Apply stricter major/paid/selective/substantive rules to charities, NGOs, foundations and think tanks | implemented and verified | `config/organisation_tiers.yml`, `classification/rules.py`, `classification/engine.py`; `test_minor_ngo_is_rejected_even_when_role_is_paid` and `test_quality_controlled_ngo_without_selectivity_needs_review`. |
| Keep eligibility and relevance separate; publish only allowed combinations | implemented and verified | Separate enums/fields and `is_public_role` in `classification/engine.py`; `test_priority_employer_monitoring_does_not_automatically_include`, manual override and digest-boundary tests. |
| Allow only verified/manual email by default and explicitly approved likely roles | implemented and verified | `eligible_for_digest` in `email/digest.py`; `test_digest_rejects_non_sendable_boundaries`, `test_uncertain_roles_never_enter_digest`. |
| Store precise evidence and avoid unexplained confidence | implemented and verified | Evidence includes rule, exact text, source URL and structured field; score components are explicit. Tests: exact evidence and `test_match_score_has_every_named_component`. |

### 4. Geography

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| London, Greater London, London-hybrid, remote UK and multi-location London handling | implemented and verified | `classify_location_type`/`classify_geography`; location parameter tests and `test_uk_wide_without_london_is_not_assumed_london`. |
| UK-wide counts only when London is selectable | implemented and verified | `test_uk_wide_without_london_is_not_assumed_london`; the classifier requires London wording rather than assuming it. |
| Named, reasoned UK priority exceptions only | implemented and verified | `EmployerConfig` validation and `config/employers.yml`; `test_priority_employer_monitoring_does_not_automatically_include`; exception text is visible in dashboard cards. |

### 5. Programme types and cycle separation

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| All 15 required programme values | implemented and verified | `ProgrammeType` in `models/records.py`, `config/programmes.yml`, config validation. |
| Summer 2027 requires explicit evidence; unstated cycle remains separate and labelled | implemented and verified | `classify_programme`, cycle provenance, separate JSON/site section; `test_cycle_unstated_remains_separate`; fixture output contains one separate cycle-unstated role. |

### 6. Category taxonomy

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Required finance, risk/law, consulting, public affairs, climate, health, operations and communications categories | implemented and verified | Complete taxonomy and configured keyword mapping in `config/categories.yml`; cross-validation in `classification/rules.py`; sector acceptance tests in `tests/test_classification.py`. |
| Explainable primary/secondary classification controlled by config | implemented and verified | `classify_category`; `test_configured_category_keyword_changes_live_classification` proves YAML changes alter classification; invalid hints are rejected by `test_invalid_external_category_hint_is_ignored`. |

### 7. Employer and source registry

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Seed the specified employer groups and resolve aliases/metadata | implemented and verified | `config/employers.yml` validates 231 unique entries: 28 enabled and 203 disabled. The enabled set has three curated official snapshots, Carlyle Workday, six broad London feeds and eighteen official page-change monitors. |
| Verify URLs/endpoints before enabling and do not invent PSC/Winston Taylor identities | implemented and verified | `SOURCES.md` and disabled `psc-unresolved`; `test_repository_configuration_valid`. Official BoE, GCHQ, W4MP and Civil Service pages were checked independently on 10 August 2026. |
| Provide broad live coverage beyond the registry | partially implemented | CharityJob, NHS Jobs, jobs.ac.uk, W4MP, Higherin, targetjobs, DWP Work Hub, Prospects, Legal Cheek, Adzuna and Reed can discover employers independently of the seeded list. Stored results are now filtered to 82 possible roles rather than publishing ordinary jobs. Some major boards and proprietary ATSs remain inaccessible or disabled, so web-wide completeness cannot be claimed. |

### 8. Data acquisition and adapters

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Teamtailor, generic JSON, RSS/Atom, HTML, government, trusted board, broad-board pagination and curated YAML | implemented and verified | 19 registry keys in `adapters/registry.py`; saved fixtures in `fixtures/`; adapter tests cover the four advertised-count feeds, Higherin, W4MP, government and curated sources. |
| Employer-specific POST bodies and role-detail enrichment for Workday APIs | implemented and verified | `request_method`/`request_body` on `EmployerConfig`, request code in `adapters/base.py`, and fail-closed detail enrichment in `adapters/parsers.py`; `test_workday_style_post_configuration_is_honoured`, `test_workday_enriches_carlyle_detail_before_classification`, and `test_workday_detail_failure_fails_closed`. |
| Detect material application/date/eligibility/location/programme/status changes | implemented and verified | `pipeline/changes.py`; `test_material_changes_are_explicitly_recorded`, `test_reopening_is_detected`. |
| Preserve MP/office, affiliation, paid/location, publisher, application method and deadline | implemented and verified | `TrustedBoardAdapter`, `fixtures/parliament/w4mp.html`; `test_trusted_board_preserves_employer_and_publisher`. Affiliation is metadata only. |
| Async bounded concurrency, host throttling, retries/backoff, timeouts, robots and source-health isolation | implemented and verified | `adapters/base.py` and `pipeline/scanner.py`; `test_http_request_errors_are_retried`, source failure/cap/parser-change tests. |
| Official page monitoring without pretending a page is a job feed | implemented and verified | `monitor_only` config and `HtmlMonitorAdapter`; `test_monitor_only_html_source_tracks_page_without_claiming_roles`. |
| Oracle HCM, SuccessFactors and iCIMS adapters | intentionally excluded with a valid reason | No verified priority endpoint required them. `SOURCES.md` explicitly declines to claim support until a safe employer-specific fixture exists. |
| Live role-level retrieval from enabled sources | implemented and verified | Four curated sources publish 25 verified records, including nine official Goldman Sachs London Summer Analyst roles. Previous complete source-filtered scans exercised CharityJob, NHS Jobs, jobs.ac.uk, W4MP, Higherin, targetjobs and Carlyle (`R-00234`). The current environment reverified the local/fixture paths; the next GitHub run is required to refresh every live source. |

### 9. Job record and provenance

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Required identifiers, organisation/office/publisher, URLs, location, dates, pay, decisions, restrictions, score, health, lifecycle and override fields | implemented and verified | `RawRole` and `RoleRecord` in `models/records.py`; Pydantic state validation in `validation.py`; generated fixture records validate. |
| Date/cycle provenance enums and correct first-seen labelling | implemented and verified | Required enums in `models/records.py`; builder selects “Published” only for a source date, otherwise “First observed”; provenance regression test. |
| Preserve original tracking URLs while canonicalising primary URLs | implemented and verified | `test_original_tracking_urls_are_preserved_as_provenance`. |

### 10. Deduplication

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| ATS ID, application/source URL, natural key, MP/office and programme fallbacks | implemented and verified | `pipeline/deduplication.py`; `test_deduplication_collapses_tracking_and_alias_sources`. |
| Preserve distinct division, office, programme and material location | implemented and verified | `_materially_distinct`; tests for distinct location/division and same-London dedupe. |
| Merge authority/provenance without losing original URLs | implemented and verified | `_merge`; dedupe and URL provenance tests. |

### 11. Closure safeguards

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Explicit closure or three healthy, uncapped, parser-valid misses | implemented and verified | `pipeline/lifecycle.py`; `test_three_healthy_uncapped_absences_close_role`. |
| Failure, cap, degraded health or parser change cannot increment missing | implemented and verified | `test_failed_or_capped_source_cannot_increment_missing`, `test_source_page_change_degrades_health_and_blocks_closure`. |
| Newly ineligible evidence removes stale public copy immediately | implemented and verified | `pipeline/scanner.py`; `test_current_ineligible_wording_removes_stale_public_role`. |
| Recently closed remains public for 14 days with reasons | implemented and verified | Site builder filters closed records by 14 days and renders closure evidence; lifecycle stores reason/evidence; site/closure tests and validation. |

### 12. Drop radar

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Evidence-labelled official/month/history/third-party/no-estimate/open/closed states | implemented and verified | constrained `RadarEntry` model, `config/radar.yml`, `data/upcoming_roles.json`, radar table in builder. |
| Replace estimate when matching live role appears | implemented and verified | reconciliation in `site/builder.py`; fixture/static build and structured-state validation. |
| Do not guess when evidence is absent | implemented and verified | BoE is explicitly `no_reliable_estimate`/“No verified window”; GCHQ has an official date and URL. |

### 13. Matching, ranking and explainability

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Rule-based positive/negative evidence across specified domains and skills | implemented and verified | `config/relevance_rules.yml`, `classification/rules.py`, `classification/engine.py`; priority-sector and communications tests. |
| Eight separately weighted components totalling 100; never an acceptance probability | implemented and verified | score config and cross-validation; `test_match_score_has_every_named_component`; CLI `explain` prints the disclaimer and components. |
| Ineligibility cannot be rescued by prestige | implemented and verified | publication boundary and `test_hard_exclusions_cannot_be_overridden_by_priority`. |

### 14. Public dashboard

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Required metrics, coverage warning, sections, radar, closed, source health, methodology, privacy and subscribe | implemented and verified | `site/templates/index.html`, `site/builder.py`; fixture `index.html`; `test_static_site_generation_and_filter_assets`; `validate_generated_site`. |
| Required role fields, exact evidence, official/first-seen labels and provenance | implemented and verified | `_role_card` in `site/builder.py`; generated fixture HTML; `test_site_connects_configured_subscription_and_hides_internal_override`. |
| Search, all requested filters, sorting and saved roles | implemented and verified | template data attributes and `site/static/app.js`; 4 executable JS tests cover corrupted storage, round-trip save, numeric evidence sorting and category matching. |
| Public boundary excludes uncertain/ineligible/internal override/subscriber data | implemented and verified | builder excludes `manual_override`; `validation.py`; site/audit/hygiene tests. |
| Responsive semantics, keyboard focus, reduced motion and intended AA palette | partially implemented | Semantic landmarks, unique IDs, focus and reduced-motion rules are validated. Computed key text contrast pairs are all at least 4.94:1. No Chromium/axe executable was available, so responsive visual behaviour and every interactive state were not independently browser-tested. |
| Open/upcoming filter spans both role cards and radar entries | partially implemented | Role-card filter exists, but radar is a separate evidence table rather than part of the card filter set. The distinction is visible and honest, but the single control does not filter radar rows. |

### 15. Public email subscription

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Form, normalisation, honeypot, restricted CORS and generic anti-enumeration response | implemented and verified | template/app JS, `_shared/security.ts`/`state.mjs`; configured and disabled-site tests; Node normalisation test; static security assertions. |
| Double opt-in, random confirmation/unsubscribe tokens, HMAC hashes and expiry | implemented and verified | migration and Edge Functions; pure confirmation state is exercised by Node tests. |
| Atomic/idempotent subscription and safe repeat confirmation/unsubscribe | implemented and verified | SQL `begin_subscription`, `confirmationDecision`, `unsubscribeDecision`; Node tests cover pending/confirmed/unsubscribed/expired/unknown decisions. Database race behaviour is defined atomically in SQL but not run against a live Postgres instance. |
| One-click unsubscribe and List-Unsubscribe headers | implemented and verified | `unsubscribe/index.ts`, `ResendTransport` in `email/digest.py`, digest tests. |
| Minimal schema, RLS and no anon/authenticated table privilege | implemented and verified | `supabase/migrations/202608100001_subscribers.sql`; `test_subscription_security_artifacts`. |
| Live migration, Edge deployment, Resend confirmation and end-to-end browser flow | blocked by unavailable credentials or external access | No Supabase project, service-role key, Resend domain/key or deployed endpoint was available. No live subscriber or email was fabricated. |

### 16. Daily digest

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Select only unsent qualifying roles since the previous success and exclude uncertain/ineligible/irrelevant/unpaid/discovery/review-required records | implemented and verified | `eligible_for_digest`/`run_digest`; digest boundary, uncertain and retry tests. |
| Required ordering and role fields; responsive HTML plus plain text | implemented and verified | `_digest_order` and `build_digest`; `build/digest-preview/digest.html` and `.txt`; dry-run test. |
| No empty email and successful no-send state | implemented and verified | `test_digest_rendering_idempotency_and_no_send`, `test_zero_recipient_run_is_recorded_without_claiming_delivery`. |
| Per-recipient/provider idempotency and partial-delivery retry | implemented and verified | deterministic digest/recipient keys and Supabase last marker; `test_production_retry_skips_recipient_already_delivered_same_digest`. |
| Real delivery and live unsubscribe links | blocked by unavailable credentials or external access | Dry-run only; no real email was sent. |

### 17. GitHub Actions and deployment

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Four named workflows, schedules/manual dispatch, locks, caching, diagnostics and least-privilege permissions | implemented and verified | `.github/workflows/*.yml`; `validation.validate_yaml_and_workflows`; CI assertions. Whole-registry scan is every three hours, while large sources respect six- or twelve-hour per-source cadence; scan and digest share a write lock and retry rebased pushes. |
| Pages supported artifact/deployment and separate data/code timestamps | implemented and verified | `deploy-pages.yml`, builder metrics/template. |
| CI format/lint/type/test/JS/config/state/workflow/hygiene/fixture E2E | implemented and verified | `ci.yml` command list; every local equivalent passed. |
| Actual hosted workflow execution and Pages deployment | blocked by unavailable credentials or external access | No GitHub repository/Actions run/Pages environment was available. Workflow YAML was structurally parsed, not run by GitHub; `actionlint` was unavailable. |

### 18. Transparent storage and retention

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Required JSON state files and atomic no-op writes | implemented and verified | `data/`, `JsonStore.write`; fixture checksum test and live-data checksum command. |
| Fixture runs cannot contaminate production data | implemented and verified | fixture data lives in `build/fixture-data`; `test_fixture_scan_cannot_contaminate_live_state`; all nine live JSON checksums passed after fixture scan. |
| Observation/digest/token/rate-limit growth is bounded | implemented and verified | 90-day/5,000 observation cap in scanner, 100 digest runs, 20 unsubscribe hashes, SQL pruning. |
| Subscriber records never enter repository/public JSON | implemented and verified | Supabase-only architecture, `.gitignore`, hygiene validation and CI checks. |

### 19–20. Repository structure and CLI

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Separation of config/data/fixtures/site/source/Supabase/tests/docs | implemented and verified | Repository tree follows the specified structure; adapter/classification/pipeline/site/email/storage responsibilities are separate. |
| Required CLI operations, clear non-zero failures and secret-safe logs | implemented and verified | `src/opportunity_radar/cli.py`; three negative commands returned exit 1 for invalid source, category and role. `approve` requires reason and official evidence URL. |

### 21. Tests

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| Adapter, government, trusted-board, authority separation, classification, geography, quality, provenance, dedupe, source failure/cap/closure/change, override/review and E2E coverage | implemented and verified | 148 collected Python tests across `tests/test_adapters.py`, `test_classification.py`, `test_pipeline.py`, `test_site_email_config.py`, `test_audit_regressions.py`. |
| Static-site/search/sort/save and subscription state behaviour | implemented and verified | 9 Node tests in `tests/js/`; Python generated-site tests and validators. |
| No live employer contact or real email from tests | implemented and verified | HTTP uses `httpx.MockTransport`/saved fixtures; digest uses in-memory/monkeypatched transports. |
| Full Edge Function database integration and real browser accessibility test | blocked by unavailable credentials or external access | Pure state and static artifacts are tested, but Deno/Supabase/Postgres and Chromium/axe were unavailable. |

### 22–24. Documentation, environment and quality

| Requirement | Status | Concrete evidence and qualification |
|---|---|---|
| README, methodology, architecture, privacy, security and sources contain required topics without false deployment claims | implemented and verified | The six documents plus this audit are present. Audit corrections removed a stale `YOUR_PROJECT` instruction and corrected workflow permission and retention claims. |
| `.env.example` names only and fixture mode requires no secrets | implemented and verified | `.env.example`; hygiene validator; fixture scan/build/digest ran without credentials. |
| Python 3.12, Pydantic, async httpx, pytest, Ruff, mypy, structured logs, deterministic/pinned dependencies | implemented and verified | `pyproject.toml`; Ruff/mypy/pytest gates pass; `socksio==1.0.0` was restored after a real proxy-path failure. |
| Fresh editable dependency install in this sandbox | implemented and verified | `.venv/bin/pip install -e ".[dev]"` completed successfully and `.venv/bin/pip check` reported no broken requirements. A separate operating-system Python 3.12 installation was not needed because the project environment already uses Python 3.12. |
| No TODO/FIXME/stub/credential/fabricated production data | implemented and verified | Focused `rg` search found only the intentional abstract adapter `NotImplementedError`, exception declarations/date fallback `pass`, the required README screenshot placeholder and HTML input placeholders. Fixture employers/URLs are explicitly labelled fixtures and isolated from production state. Repository hygiene validation passed. |
| No authentication bypass, tracking, application submission, political ranking, STEM assumption or uncertain publication | implemented and verified | Adapter/publication boundaries and tests; no application automation or tracking code exists; affiliation is display metadata only. |

## Acceptance criteria 1–34

| # | Status | Evidence |
|---:|---|---|
| 1 | implemented and verified | Fixture scan: 4 sources, 19 observations, 12 public roles, multiple sectors and a closed-role lifecycle record. |
| 2 | implemented and verified | `Meridian Capital (fixture)` corporate-finance role in fixture open list; finance classification test. |
| 3 | implemented and verified | Eligible non-law law fixture and `test_eligible_non_law_vacation_scheme`. |
| 4 | implemented and verified | `test_final_year_non_law_vacation_scheme_rejected`. |
| 5 | implemented and verified | Specialist software hard-exclusion parameter test. |
| 6 | implemented and verified | Environmental-risk fixture plus priority-sector acceptance test. |
| 7 | implemented and verified | W4MP paid parliamentary fixture and board/employer separation tests. |
| 8 | implemented and verified | `test_unpaid_political_campaign_rejected`. |
| 9 | implemented and verified | Policy fixture and priority-sector test. |
| 10 | implemented and verified | `test_minor_ngo_is_rejected_even_when_role_is_paid`. |
| 11 | implemented and verified | Humanitarian M&E fixture and international/development test case. |
| 12 | implemented and verified | Development-finance fixture and sector test. |
| 13 | implemented and verified | Health policy/economics fixture and sector test. |
| 14 | implemented and verified | Geospatial fixture and sector test. |
| 15 | implemented and verified | Supply-chain/commercial fixture and sector test. |
| 16 | implemented and verified | `test_substantive_communications_distinguished_from_social_media`. |
| 17 | implemented and verified | British nationality tests. |
| 18 | implemented and verified | Residency/clearance uncertainty test. |
| 19 | implemented and verified | Separate `recent_roles.json` and cycle-unstated test. |
| 20 | implemented and verified | Uncertain digest rejection tests. |
| 21 | implemented and verified | Dedupe tests. |
| 22 | implemented and verified | W4MP employer/publisher test. |
| 23 | implemented and verified | Failure/cap/parser-change closure tests. |
| 24 | implemented and verified | Fixture and production static builds plus validation passed. |
| 25 | implemented and verified | Category controls/data and JS category matching test; every configured category is cross-validated. Full browser clicking was unavailable. |
| 26 | implemented and verified | Search/sort/save code and executable JS tests; generated HTML contains required controls. Full browser DOM automation was unavailable. |
| 27 | implemented and verified | Builder injects `SUBSCRIBE_ENDPOINT`; configured/disabled regression test. Live endpoint deployment is separately blocked. |
| 28 | partially implemented | Confirmation/unsubscribe code and pure state tests pass; live Supabase integration is blocked. |
| 29 | implemented and verified | Dry-run HTML/plain previews generated and inspected. |
| 30 | implemented and verified | Whole-run and partial-recipient retry tests. |
| 31 | implemented and verified | Four YAML workflows parse and pass structural/permission validation; no GitHub execution. |
| 32 | implemented and verified | Final Python and Node suites pass; counts below. |
| 33 | implemented and verified | Repository secret/subscriber hygiene validation passed. |
| 34 | implemented and verified | README contains exact Supabase, Resend, GitHub secret/variable and Pages steps; external execution remains for the deployer. |

## Defects found and remediated

Substantive audit corrections include:

1. replaced synthesised “evidence” summaries with exact source fragments and structured-field provenance;
2. made category, eligibility, relevance, quality and scoring YAML drive actual decisions;
3. hardened non-law vacation-stage, citizenship/residency/clearance, London/UK-wide and manual-review publication boundaries;
4. added every specified score component and corrected date/cycle provenance;
5. preserved tracking URLs as evidence while canonicalising primary links;
6. stopped dedupe from merging distinct divisions/offices/material locations;
7. isolated fixture state from production state and prevented filtered scans from corrupting other source health/closure counts;
8. immediately removed stale public records when fresh official wording becomes ineligible;
9. added HTTP request retries, configurable POST bodies and richer application/closure/requirement parsing;
10. made monitor-only official pages health-check without falsely claiming role parsing;
11. excluded uncertain, discovery, upcoming, closed, review-required and unapproved borderline records from digest selection;
12. added dry-run previews, zero-recipient/no-role state, per-recipient retry protection and pruning;
13. made subscription start atomic, protected reconfirmation after unsubscribe, honoured rate-limit windows and handled database failures generically;
14. replaced the dense organisation grid with readable employer-type labels, a responsive card hierarchy, compact metrics, clearer evidence details and an unmistakable fixture-data banner;
15. expanded CI validation and corrected inaccurate README/architecture/privacy claims; and
16. restored the pinned SOCKS transport dependency after a real live-scan startup failure exposed it; and
17. rejected non-HTTP(S) source/application/evidence links at the Pydantic boundary to prevent executable feed links; and
18. timestamped roles first observed as explicitly closed so the 14-day recently-closed view can display them.
19. added 13 verified official-ATS production roles from BlackRock and Blackstone, plus evidence-labelled Goldman Sachs, Freshfields and Slaughter and May radar entries;
20. recognised official “anticipated graduation date: Summer 2028” wording and corrected investment due-diligence explanations that previously implied legal work; and
21. prevented source-filtered scans from incrementing missing counts or misreporting aggregate enabled-source coverage; and
22. added three missing official Bank of America London 2027 roles, expanded the radar to 22 programmes and the official-page pool to 21 enabled sources, separated role producers from page watches, and made the dashboard self-contained with a compact open-jobs list; and
23. enabled Carlyle's official London-intern Workday source and added fail-closed role-detail enrichment; and
24. implemented the later breadth-first requirement with paginated W4MP/Higherin discovery, a separate possible-role lifecycle/public dataset, confidence filtering, broader employer preservation and explicit technical/seniority exclusions. Carlyle `R-00234` is now correctly visible as possible rather than silently withheld; and
25. added complete advertised-count CharityJob, NHS Jobs and jobs.ac.uk pagination, six-hour responsible polling, source-scoped review retention, broader junior-title acceptance, clinical/academic exclusions and a lazy 100-row dashboard that keeps every possible role usable without duplicating every detail card in the initial page; and
26. added the robots-allowed public targetjobs London early-career service, complete result-count validation, external-ATS requisition dedupe, discovery-copy protection for stronger official records, placement-provider exclusions and verified employer-name repair for erroneous indexed tenants; and
27. normalised source-provided employer display names by collapsing stray whitespace, repairing common UK/acronym casing and merging the duplicate `Transport For London`/`Transport for London` filter entries without changing employer identity.
28. added a shared focused finance/consulting/law/policy/research query matrix, official DWP Work Hub pagination, Prospects and Legal Cheek public parsers, and optional credential-safe Adzuna/Reed APIs; and
29. corrected capped-source retention so freshly rejected and rule-invalid stale records disappear without sacrificing unseen-role protection, removed repeated receptionist/service/specialist false positives, failed robots checks closed, and redacted vacancy contact emails from committed public state.

## Residual gaps and blockers

- **Live source coverage:** 25 roles are verified and 82 wider leads remain visible across 47 employers. Source health retains 17,317 historical listing appearances, most of which are correctly filtered out. Web-wide completeness is impossible to guarantee; 203 registry entries remain disabled and curated snapshots still require official re-verification.
- **Credentialed aggregators:** Adzuna and Reed are fully configured, fixture-tested and secret-safe, but no live API success is claimed because `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` and `REED_API_KEY` were unavailable.
- **Live services:** Supabase migration/functions, Resend delivery, GitHub Actions and Pages require accounts, secrets and deployment authority that were unavailable.
- **Browser/Deno integration:** the Playwright package exists but its Chromium binary is unavailable; Deno/Supabase local runtime is also unavailable. Static semantics, inline CSS presence, responsive rules, duplicate IDs, public boundaries, JavaScript logic and pure subscription state were tested instead.
- **Scheduled live-network execution:** source-filtered HTTPX scans succeeded locally for DWP Work Hub, Prospects and Legal Cheek. GitHub's scheduled path still needs its first external workflow run; no scheduled success is fabricated.
- **Unsupported proprietary ATSs:** Oracle HCM, SuccessFactors and iCIMS remain deliberately unclaimed until a real priority source and saved fixture justify them.

There are no known safely fixable local defects left undisclosed. The correct conclusion is **locally complete for the breadth-first verified/possible design and populated with a materially broader snapshot, but not provably comprehensive and not externally deployed**.

## Exact manual deployment steps

1. In a clean Python 3.12 environment run `python -m pip install -e ".[dev]"`, then the complete final verification commands below.
2. Create a Supabase project in a suitable UK/EU region; apply `supabase/migrations/202608100001_subscribers.sql`.
3. Confirm RLS is enabled and anon/authenticated have no privileges on `subscribers` or `endpoint_rate_limits`.
4. Set Edge Function secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `ALLOWED_ORIGIN`, `TOKEN_SECRET` (at least 32 random characters).
5. Deploy `subscribe`, `confirm` and `unsubscribe` with `supabase functions deploy FUNCTION --no-verify-jwt`.
6. Verify the Resend sending domain and exercise subscribe → confirm → digest dry-run/test recipient → one-click unsubscribe. Inspect Supabase state and confirm generic responses do not enumerate addresses.
7. Create a GitHub repository. Add Actions secrets `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `TOKEN_SECRET`.
8. Add Actions variables `SITE_URL`, `ALLOWED_ORIGIN`, `SUBSCRIBE_ENDPOINT`; the latter is `https://PROJECT_REF.supabase.co/functions/v1/subscribe`.
   Optionally add `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` and `REED_API_KEY` as Actions secrets to activate the two credentialed aggregators; job scanning otherwise remains functional.
9. Enable GitHub Pages with GitHub Actions as source. Run CI, deploy Pages, then re-check `SITE_URL`/`ALLOWED_ORIGIN` against the final HTTPS origin.
10. Run the source workflow manually. Confirm 16 strict records remain in `roles.json`; confirm Carlyle `R-00234` and eligible-looking CharityJob/NHS/jobs.ac.uk/W4MP/Higherin/targetjobs/DWP/Prospects records enter `possible-roles.json`; inspect advertised totals, query counts, page counts, caps, inactive credentialed sources and all eighteen monitor-only watches separately.
11. For each disabled priority employer, verify an official public endpoint, add a saved fixture and regression test, then enable it. Never enable a guessed endpoint.
12. Enable non-dry-run digest only after an end-to-end test address confirms delivery, idempotent retry and unsubscribe behaviour.

## Final verification

This section must match the final release run and should be updated if code changes after audit:

```text
editable build/install + pip check    -> pass; package installed; no broken requirements
ruff format --check .                 -> pass (34 files)
ruff check .                          -> pass
mypy                                  -> pass (26 source files)
pytest                                -> pass (220 tests)
node --test tests/js/*.test.*         -> pass (11 tests)
key CSS contrast calculation          -> pass (minimum checked pair 5.46:1)
python run.py scan --fixtures         -> 8 attempted, 8 succeeded, 28 observations, 9 verified, 1 possible, 1 review
python run.py build-site --fixtures   -> pass
python run.py validate --fixtures     -> pass
python run.py digest --dry-run --fixtures -> 9 roles, HTML and text previews, 0 real sends
python run.py build-site              -> pass
python run.py validate                -> pass
captured live Higherin validation     -> 69 listings across 4 pages
captured live W4MP validation         -> 151 listings across 8 pages; 56 possible
captured live CharityJob validation   -> 1,235 listings across 83 pages; 452 possible
captured live NHS Jobs validation     -> 1,106 listings across 12 pages; 112 possible
captured live jobs.ac.uk validation   -> 433 listings across 18 pages; 110 possible
captured live targetjobs validation   -> 79 listings across 1 page; 19 possible
captured Carlyle validation           -> R-00234 visible as possible
captured live DWP Work Hub validation -> 30 query shards, 150 pages, 4,182 appearances, 1,475 unique records; cap exposed
captured live Prospects validation    -> 86 cards; 2 possible after policy filtering
captured live Legal Cheek validation  -> 1 current noticeboard card; 0 possible after policy filtering
Adzuna/Reed credential checks         -> inactive with exact missing-secret names; 0 network requests or false success
generated HTML static inspection      -> 333,820 bytes, 100 initial rows, 998 indexed/detail roles, 22 radar rows, 33 source rows, inline CSS, 0 duplicate IDs, 0 external stylesheets
```

The new live pages were retrieved through HTTPX and passed through the production parsers/classifiers. A whole-registry GitHub scheduled scan is not claimed. Missing API credentials and existing failed monitor health remain visible rather than being rewritten as success.

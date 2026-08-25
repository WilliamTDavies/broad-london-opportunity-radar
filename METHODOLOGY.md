# Methodology

## Publication boundary

“Open” means an official employer source or approved trusted primary listing currently exposes an application route and does not state that applications are closed. A missing record does not become closed after one scan. Explicit closure, a terminal endpoint response, or three consecutive successful uncapped absences is required. A passed deadline alone is insufficient unless the application is also unavailable. Recently closed records remain public for 14 days.

`verified_eligible` means official wording explicitly establishes graduation year 2028, penultimate/second year, any-degree eligibility, or another unambiguous condition that includes the target audience. `likely_eligible` is used for broad undergraduate wording without a contradictory restriction. `manual_approved` requires a dated maintainer decision and official evidence.

The dashboard has two publication tiers. **Verified** requires acceptable evidence on eligibility, relevance, location, source and status. **Possible - check criteria** accepts uncertainty only when the listing is an internship/break programme or a relevant professional role with explicit part-time/term-time evidence. Generic junior-sounding titles are insufficient. Long placements, off-cycle internships, ordinary permanent/full-time work and incompatible specialist fields are excluded. Possible records live in a separate JSON file and never enter the verified digest.

Eligibility is not relevance. Relevance separately classifies strong, credible, borderline or irrelevant alignment. Borderline relevance can appear only in the possible layer when a junior-access signal exists. Only verified or manually approved roles enter email by default.

## Organisation quality

Organisation tier is configured, not inferred from a prestige keyword. Major professional employers, recognised regulators/institutions and specifically approved specialists receive a quality component. A tier never rescues an unpaid, geographically invalid, explicitly ineligible or technically unsuitable role. Charities, foundations and NGOs must be paid, selective, substantive, suitable for an undergraduate and operated by a major/approved organisation. Think-tank scope is similarly restricted to paid, substantive roles at recognised institutions.

## Cycle and dates

Summer 2027 classification requires employer wording, programme dates or a verified official recruitment page. Roles lacking cycle evidence stay in “Recent relevant opportunities — cycle not stated” and are never renamed Summer 2027. Dates carry provenance: employer stated, official programme page, trusted primary listing, observed first seen, historical estimate, third-party estimate or unknown. `first_seen_at` is always labelled as observation, never posting date.

The drop radar labels official dates, employer-stated months, historical windows, third-party estimates and “No verified window” distinctly. A live official role replaces an estimate.

## Nationality, residency and vetting

Known British or New Zealand citizenship is used only where official wording imposes a corresponding requirement. British citizenship can satisfy the nationality element of a UK government or security role. It does not establish residency, Developed Vetting, security clearance or background eligibility. An unresolved additional requirement makes eligibility uncertain; a role can appear only as possible when every other broad-publication condition passes.

## Relevance

Deterministic positive rules identify substantive legal/risk work, investment/commercial analysis, consulting, compliance, regulation and related professional work. Research titles must also state a finance, markets, economics, compliance or risk context; medical and scientific research is outside the current tracker scope. Negative rules exclude specialist software, heavy quantitative/ML, clinical/lab work, generic administration, fundraising, social media and campaigning. Components are displayed as reasons, not acceptance probabilities.

The candidate’s degree is Global Humanitarian Studies. Its department does not turn it into mathematics, physics, engineering or computer science. Python and HTML are ordinary analytical/presentation skills and do not establish specialist technical eligibility.

## Authority and provenance

Official ATS, careers, programme and government sources are preferred. W4MP is an approved trusted primary board for MP/parliamentary-office and public-affairs roles; the named organisation or office remains the employer and W4MP remains publisher. Higherin, CharityJob, jobs.ac.uk, targetjobs, Prospects, Legal Cheek, Adzuna and Reed are discovery-only. NHS Jobs and DWP Find a Job are official government portals, but incomplete study-stage wording still leaves their records in the possible tier. Every aggregator preserves the advertised employer and identifies the board separately as publisher. Discovery evidence can publish a clearly labelled possible lead but cannot establish verified eligibility or enter email without official evidence.

Deduplication prefers employer plus ATS ID, then canonical application/source URL, employer-title-location, office-title-deadline and programme dates/division. Tracking parameters are removed while every original source URL is retained. Distinct divisions, offices or locations remain separate.

## Automation limits

Rules can miss novel wording, dynamic pages can change, and an employer can close early. Source failures are isolated and visible. Unexpected caps, rate limits and parser changes suppress missing-count updates. The possible layer favours useful recall within the university-availability boundary and can still include roles the candidate later rejects. Applicants must verify every requirement and deadline on the linked source.

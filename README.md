# London 2027 Opportunity Radar

A static job-tracking dashboard for London internships, vacation schemes, spring weeks and other early-career roles relevant to a penultimate-year undergraduate graduating in 2028.

The project scans public job boards and employer career pages, normalises listings into one format, applies transparent eligibility and relevance rules, removes duplicates, and publishes an automatically updated GitHub Pages dashboard.

Live site: https://williamtdavies.github.io/broad-london-opportunity-radar/

## What It Does

The tracker searches beyond a fixed employer list, but publication is deliberately limited to work that can fit around university: short internships and break programmes, or relevant roles with explicit part-time/term-time evidence.

Listings are split into two layers:

- `Verified`: enough source evidence exists to support the role, location and eligibility match.
- `Possible - check criteria`: the role looks plausibly relevant, but the candidate should manually check the listing before applying.

The system favours finding more possible opportunities over making perfect recommendations.

## How Jobs Are Found

Jobs come from a configured source registry in `config/employers.yml` and `config/trusted_sources.yml`.

The scanner collects listings from:

- official employer ATS pages, including Workday-style career pages;
- public sector and government job boards;
- early-careers and internship boards;
- law, charity, university and general job boards;
- optional API-backed sources such as Adzuna and Reed, if credentials are added.

Each source uses an adapter that converts that website's HTML, JSON, XML or API response into the same internal role format. Broad job boards can discover employers that are not individually listed in the config.

The project does not scrape behind logins, bypass CAPTCHAs, or claim coverage of restricted platforms such as LinkedIn, Indeed, Glassdoor or Google Jobs.

## Filtering and Matching

Classification is deterministic. The project does not use an LLM to decide whether a job is suitable.

Rules check:

- London, remote-UK and approved UK-wide locations;
- internship, spring week, vacation scheme and winter-project wording;
- explicit part-time/term-time availability for ordinary professional roles;
- long placements, fixed-term contracts and permanent/full-time job wording;
- graduation-year and study-stage requirements;
- degree restrictions;
- citizenship, nationality, residency and security-clearance wording;
- role relevance and exclusion rules;
- source quality and evidence strength.

Hard inclusions and exclusions are editable in:

```text
config/job_filters.yml
```

This is the main file to edit. It separates break-programme titles, part-time professional areas, availability evidence, long-duration exclusions, research contexts and hard exclusions. Generic words such as `assistant`, `analyst` and `officer` do not qualify a role by themselves.

## Dashboard

The generated dashboard is a plain static site using HTML, CSS and vanilla JavaScript.

It supports:

- title and keyword search;
- company search;
- filters by role type, source, status and confidence;
- sorting;
- saved roles in the browser;
- separate verified and possible-opportunity views.

Saved roles stay in local browser storage and are not uploaded anywhere.

## Automation

GitHub Actions starts a scan every three hours. Expensive boards still respect their six- or twelve-hour per-source cadence. When role data changes, the workflow commits the JSON files and GitHub Pages rebuilds at the same URL.

The main workflow is:

```text
scan public sources
validate data
deduplicate roles
classify eligibility and relevance
generate static dashboard
deploy to GitHub Pages
```

## Tech Stack

- Python 3.12
- HTTPX and asyncio for concurrent public-source scanning
- Pydantic for validated role models
- PyYAML for editable rules and source configuration
- HTML, CSS and vanilla JavaScript for the dashboard
- Pytest, Ruff and mypy for testing and quality checks
- GitHub Actions and GitHub Pages for automation and hosting

## Repository Structure

```text
config/                         Source lists and filtering rules
data/                           Checked-in role data and source health
fixtures/                       Test responses
site/templates/                 Dashboard HTML
site/static/                    Dashboard CSS and JavaScript
src/opportunity_radar/adapters/ Source-specific parsers
src/opportunity_radar/classification/ Eligibility and relevance rules
src/opportunity_radar/pipeline/ Scanning and deduplication
src/opportunity_radar/site/     Static-site generation
tests/                          Python and JavaScript tests
.github/workflows/              CI, scheduled scans and deployment
```

## Local Setup

Use Python 3.12. Python 3.14 is not currently supported by the pinned dependency set.

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run the fixture pipeline:

```bash
python run.py scan --fixtures
python run.py validate --fixtures
python run.py build-site --fixtures
python -m http.server 8000 --directory build/fixture-site
```

Run a live local scan:

```bash
python run.py scan
python run.py validate
python run.py build-site
python -m http.server 8000 --directory site/generated
```

After changing only `config/job_filters.yml`, you can reapply the rules without making network requests:

```bash
python run.py prune-candidates
python run.py validate
```

Then open:

```text
http://localhost:8000
```

Live scans can take several minutes because sources are rate-limited.

## Optional Email System

The repository includes optional Supabase and Resend support for confirmed email subscriptions and verified-role digests.

This is not required for the public dashboard. The tracker can scan jobs, build the site and deploy to GitHub Pages without Supabase or email credentials.

## Limitations

No scraper can guarantee every job on the internet. Some platforms restrict automated access, some sources change layout, and API-backed sources require credentials.

The project makes those limits visible through source-health tracking rather than pretending coverage is complete.

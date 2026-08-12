# Broad job-board setup

This repository is already configured to scan every source that can run safely without a login.
Two additional aggregators use their documented APIs and switch on automatically when you add
their keys. Supabase and Resend are not required for job scanning or the dashboard.

## Sources included

| Source | Coverage | Setup |
| --- | --- | --- |
| DWP Find a Job / Work Hub | Broad London search over 30 finance, consulting, law, policy, research and junior-role queries | None |
| Prospects London | Work experience, internships, schemes, graduate roles and apprenticeships across all sectors | None |
| Legal Cheek Hub | Legal work experience, vacation schemes, open days, paralegal roles and related opportunities | None |
| targetjobs | London internships, vacation schemes, insight programmes and work experience | None |
| Higherin | London internships | None |
| CharityJob | Paid London charity and non-profit vacancies | None |
| NHS Jobs | London vacancies, with clinical and specialist roles filtered out | None |
| jobs.ac.uk | London university, research and professional-services vacancies | None |
| W4MP | Parliamentary and political-office vacancies | None |
| Adzuna | Broad London aggregator search over the same 30-query matrix | Free API credentials |
| Reed | Broad London aggregator search over the same 30-query matrix | Free API key |
| Employer ATS and official pages | Workday plus existing employer-specific ATS records and page watches | None for configured sources |

## Add the optional Adzuna and Reed APIs

The rest of the scanner works without these keys. If a key is missing, source health says
`inactive` and no request is made.

### Adzuna

1. Open <https://developer.adzuna.com/> and create a developer account.
2. Create an application and copy its **Application ID** and **Application key**.
3. In the GitHub repository, open **Settings > Secrets and variables > Actions**.
4. Select **New repository secret** and create:
   - `ADZUNA_APP_ID` containing the Application ID;
   - `ADZUNA_APP_KEY` containing the Application key.

### Reed

1. Open <https://www.reed.co.uk/developers/jobseeker> and request a Jobseeker API key.
2. In **Settings > Secrets and variables > Actions**, create `REED_API_KEY` containing that key.

Do not paste real keys into `.env.example`, `config/employers.yml`, a commit, an issue or a chat
message. The scan workflow already maps the three GitHub secrets into the scanner.

## Run it on Windows

Use Python 3.12, not Python 3.14.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python run.py scan
python run.py validate
python run.py build-site
python -m http.server 8000 --directory site/generated
```

Open <http://localhost:8000>. A full first scan can take several minutes because large boards are
paginated and rate-limited. To test one source:

```powershell
python run.py scan --source work-hub-london
python run.py scan --source prospects-london
python run.py scan --source legalcheek-noticeboard
python run.py scan --source adzuna-london
python run.py scan --source reed-london
```

## Change the breadth

Open `config/employers.yml` and find `broad_search_queries`. That one YAML list is shared by DWP,
Adzuna and Reed. Add a phrase on its own line, for example:

```yaml
  - restructuring intern
  - tax internship
  - competition law assistant
```

The current list already covers internships, summer analysts, vacation schemes, insight and work
experience, research, policy, legal and paralegal work, finance, investment, risk, consulting,
strategy, commercial, business, operations, projects, public affairs, sustainability, ESG,
communications and fundraising.

Each matrix source also has `max_pages_per_query`, `result_cap`, `requests_per_minute` and
`poll_interval_minutes` settings in the same file. Raising page caps increases coverage, runtime
and load on the source. A cap is never hidden: source health becomes degraded and prior unseen
records are retained rather than silently declared closed.

## What is deliberately not scraped

The scanner does not automate LinkedIn, Indeed, Glassdoor, Google Jobs or other sites that prohibit
the access pattern, require authentication, present CAPTCHAs, or do not expose a stable public
listing interface. Bright Network and eFinancialCareers presented automated-access challenges at
the time of verification, so they are not falsely labelled as working sources. Direct scraping is
not needed to benefit from some of their employer listings because Adzuna, Reed, targetjobs,
Prospects and official employer ATS feeds provide overlapping discovery routes.

No collection system can guarantee every vacancy on the web. This project maximises lawful,
repeatable coverage, exposes failures and caps, and treats aggregator records as possible leads
that must be checked on the linked application page.

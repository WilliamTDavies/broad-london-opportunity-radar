# Source registry and coverage

Verified 22 August 2026. A configured employer is a monitoring target, not a role whitelist. Thirty-four sources are enabled: four curated official-ATS snapshots, one live official Workday search/detail feed, eleven employer-agnostic London discovery/government feeds and eighteen official page-change monitors. After the stricter university-availability filter is applied, the checked-in snapshot contains 25 verified roles and 82 possible roles across 47 employers. The current source-health history contains 17,317 listing appearances, but most of those records are deliberately not published because they are ordinary full-time jobs, long placements, irrelevant research or otherwise incompatible with study. The remaining 203 registry entries are disabled until a safe endpoint or curated official record is verified. Coverage is broad, but it is not a guarantee of every job on the web.

## Role-producing official sources

| Employer | Authority | Adapter | Official URL | Current coverage |
|---|---|---|---|---|
| Bank of America | Official ATS | Curated official-record snapshot | <https://careers.bankofamerica.com/en-us/students/job-search> | Three official London 2027 Summer Analyst listings verified 11 August 2026. Each accepts degree completion between June 2027 and July 2028 and closes 11 October 2026. |
| BlackRock | Official ATS | Curated official-record snapshot | <https://careers.blackrock.com/employment/london-england-united-kingdom-students-and-graduates-jobs/45831/9022304/2635167-6269131-2648110-2643743/4> | Two official London 2027 programme listings verified 10 August 2026. Both explicitly require penultimate-year study and 2028 graduation; the main programme also states any degree subject. |
| Blackstone | Official ATS | Curated official-record snapshot | <https://blackstone.wd1.myworkdayjobs.com/Blackstone_Campus_Careers> | Eleven distinct London 2027 Summer Analyst listings verified 10 August 2026, each requiring anticipated Summer 2028 graduation. The specialist Quant & Portfolio Analytics listing remains excluded because its mathematical-modelling and programming requirements do not establish candidate fit. |
| Goldman Sachs | Official ATS | Curated official-record snapshot | <https://higher.gs.com/> | Nine London 2027 Summer Analyst listings verified 22 August 2026, including Compliance, Regulatory Relations, Internal Audit, Risk, Investment Banking, Private Investing and Transaction Banking. The official EMEA programme describes a nine-to-ten-week internship for penultimate- or final-year students. Quantitative-strats and engineering listings are intentionally excluded. |
| The Carlyle Group | Official ATS | Live Workday search + detail enrichment | <https://carlyle.wd1.myworkdayjobs.com/Carlyle> | The London Intern facet and official CXS detail endpoint were verified 11 August 2026. `R-00234`, Private Credit Intern, is detected and visible as a possible role because its wording gives no study/graduation stage. |

The four curated files are production records, not fixtures, and retain direct official URLs and exact eligibility fragments. They require scheduled page re-verification because local curated ingestion does not itself detect an ATS closure. Carlyle is polled live and fails closed if its role-detail response cannot be parsed.

## Official pages watched for changes

These eighteen sources fetch an official page and record source health/content changes. They are deliberately labelled as page watches: a successful fetch is not evidence that a suitable role is open, and the monitor emits no public role without a role-level listing or curated official record.

| Employers or programmes | State |
|---|---|
| Millennium Management; IISS; Rothschild & Co; HSBC; Houlihan Lokey; Lazard; Barclays | Official careers/internship pages watched; no verified London 2027 role is currently published. |
| GCHQ; Bank of England; Goldman Sachs | Official programme pages watched; verified dates or status are shown in the evidence-labelled radar. |
| A&O Shearman; Latham & Watkins; Covington & Burling; Hogan Lovells Cadwalader; Linklaters; Freshfields; Slaughter and May; Herbert Smith Freehills Kramer | Official London vacation-scheme pages watched; publication requires the live application and explicit eligible non-law study stage. |

## Broad discovery and government sources

| Source | Authority | URL | State |
|---|---|---|---|
| W4MP Jobs | Trusted sector board | <https://www.w4mpjobs.org/searchjobs.aspx?search=alljobs> | Enabled. The ASP.NET pager adapter scans every result page, preserves the named organisation/office as employer and W4MP as publisher, and passes listings to central classification. Only internships or professional roles with explicit term-compatible hours are published. |
| Higherin London Internships | Discovery-only board | <https://higherin.com/search-jobs/internships/london> | Enabled. The structured search-state adapter scans every page and preserves employer, title, location, deadline, salary wording and stated relevant study years. The 11 August capture contained 69 listings; eligible-looking records remain possible until checked on the employer page. |
| CharityJob London | Discovery-only board | <https://www.charityjob.co.uk/jobs/in-london> | Enabled. The rate-limited adapter paginates the advertised results, deduplicates responsive copies and handles cards without logos. Ordinary full-time charity jobs are no longer published merely because they use a broad relevant keyword. |
| NHS Jobs London | Official government portal | <https://www.jobs.nhs.uk/candidate/search/results?location=London> | Enabled. The date-sorted adapter requests 100 results per page and validates the advertised result count. Clinical, medical-research, full-time and long-contract results are excluded unless the record is a genuinely compatible internship or term-time professional role. |
| jobs.ac.uk London | Discovery-only board | <https://www.jobs.ac.uk/search/location/london> | Enabled. The facet adapter scans London results and validates the advertised result count. Senior academic, scientific, clinical and non-finance research roles are excluded; finance, risk and economics research internships remain eligible for review. |
| targetjobs London Early Careers | Discovery-only board | <https://targetjobs.co.uk/internships/london> | Enabled. Robots allows crawling and the adapter uses the page's public JSON search service. It verifies all 79 advertised open London internship, vacation-scheme, insight and work-experience records; 19 remain possible after official-copy dedupe and obvious graduate, technical, placement-provider and stale-cycle exclusions. |
| DWP Find a Job / Work Hub | Official government portal | <https://www.jobs.service.gov.uk/jobs/search> | Enabled. The current replacement for the retired Find a Job site is searched over 37 focused London query shards. The adapter paginates, preserves the actual employer, deduplicates by DWP job ID and exposes caps. Robots explicitly allows `/jobs`, and the service terms permit reasonable automated copying with DWP attribution. |
| Prospects London | Discovery-only board | <https://www.prospects.ac.uk/browse-graduate-jobs/all-sectors/london-53> | Enabled. Parses every public London browse card and retains listing type, employer, location and pay wording. Graduate-only, apprenticeship, unpaid and specialist records remain excluded by central policy. |
| Legal Cheek Hub | Discovery-only board | <https://hub.legalcheek.com/jobs> | Enabled. Parses the current public law noticeboard for vacation schemes, work experience, open days, paralegal roles and other legal opportunities. The adapter fails closed if unverified pagination appears. |
| Adzuna London | Discovery-only API | <https://developer.adzuna.com/docs/search> | Configured and enabled when `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` are supplied. The documented API uses the same 37-query matrix, a 30-day window, pagination and ID deduplication. |
| Reed London | Discovery-only API | <https://www.reed.co.uk/developers/jobseeker> | Configured and enabled, but locally inactive until `REED_API_KEY` is supplied. The documented Jobseeker API uses Basic authentication, query shards, offset pagination and ID deduplication. |
| Civil Service Jobs | Official government portal | <https://www.civilservicejobs.service.gov.uk/> | The legacy portal may present bot checks and remains disabled; broad public/private vacancies are now covered through the current official DWP Work Hub service. |

The large public feeds have a six-hour per-source poll interval and the credentialed aggregators a twelve-hour interval during scheduled whole-registry scans; explicit `--source` scans bypass that cadence. Every pagination/query adapter records pages scanned, result appearances, unique records, caps and parser-health evidence. A source failure, structural change or cap retains prior records that were not seen; a record that was fetched and now fails the filter is removed immediately.

## Disabled employers and sources (203)

These remain disabled because a safe public ATS/official role endpoint has not yet been verified and tested. Entries with unresolved names are explicitly marked; none has an invented board identifier.

- PwC; Deloitte; EY; MI5; Pfizer; Macfarlanes; Gowling WLG; Jane Street; Hines; Cadwalader, Wickersham & Taft (legacy alias); Mayer Brown; SEFE Marketing & Trading; Equinor; Simpson Thacher & Bartlett; Allianz; PSC — Politics/consulting (unresolved); Morgan Stanley; JPMorganChase; Citi; UBS; Deutsche Bank; BNP Paribas; Standard Chartered; NatWest Group.
- Lloyds Banking Group; Schroders; Fidelity International; Legal & General; Aviva; Apollo Global Management; KKR; Brookfield; Ares Management; Man Group; Brevan Howard; Point72; Bloomberg; S&P Global; Moody’s; Morningstar; MSCI; Morningstar Sustainalytics; Institutional Shareholder Services; British International Investment; European Bank for Reconstruction and Development; International Finance Corporation; Bridges Fund Management; Aon; Marsh McLennan; Willis Towers Watson; Lloyd’s; Swiss Re; Munich Re; Zurich Insurance; Control Risks; FTI Consulting; Kroll; Teneo; Brunswick Group; Eurasia Group; FGS Global; APCO Worldwide; Edelman.
- Portland Communications; FleishmanHillard; Burson; McKinsey & Company; Boston Consulting Group; Bain & Company; Oliver Wyman; Kearney; Accenture; KPMG; Strategy&; AlixPartners; Grant Thornton; Baringa; ZS; IQVIA; Frontier Economics; Compass Lexecon; NERA Economic Consulting; Oxera; London Economics; bp; Shell; TotalEnergies; Centrica; National Grid; Vitol; Trafigura; Gunvor; Glencore; SEFE; RWE; EDF Energy; SSE; Ørsted; Vattenfall; Octopus Energy; Drax; ERM; Anthesis.
- Arup; WSP; AECOM; Ricardo; Ramboll; Mott MacDonald; SLR Consulting; South Pole; Carbon Trust; Principles for Responsible Investment; CDP; S&P Global Sustainable1; BloombergNEF; Travers Smith; White & Case; Baker McKenzie; Gibson Dunn; Kirkland & Ellis; Sidley Austin; Weil, Gotshal & Manges; Milbank; Sullivan & Cromwell; Davis Polk & Wardwell; Paul, Weiss, Rifkind, Wharton & Garrison; Vinson & Elkins; Winston Taylor (unresolved); UK Parliament; House of Commons; House of Lords; Financial Conduct Authority; Competition and Markets Authority; UK Civil Service; HM Treasury; Cabinet Office.
- Foreign, Commonwealth & Development Office; Department for Business and Trade; Department for Energy Security and Net Zero; Department for Environment, Food & Rural Affairs; UK Health Security Agency; Greater London Authority; London Assembly; City of London Corporation; Chatham House; Royal United Services Institute; Institute for Government; RAND Europe; Tony Blair Institute for Global Change; Centre for European Reform; Resolution Foundation; Institute for Public Policy Research; Policy Exchange; Centre for Policy Studies; ODI Global; British Chambers of Commerce; London Chamber of Commerce and Industry; Confederation of British Industry; TheCityUK; UK Finance; Institute of Directors; BritishAmerican Business; United Nations agencies; World Bank Group; International Monetary Fund; OECD; NATO; International Committee of the Red Cross; International Federation of Red Cross and Red Crescent Societies; British Red Cross; Save the Children International; International Rescue Committee; Mercy Corps; Wellcome; Gates Foundation; Médecins Sans Frontières UK.
- Oxfam GB; GSK; AstraZeneca; Johnson & Johnson; NHS England; National Institute for Health and Care Excellence; Department of Health and Social Care; CBRE; JLL; Savills; Knight Frank; Cushman & Wakefield; Esri UK; Ordnance Survey; Mapbox; Maxar; Google; Microsoft; Amazon; Meta; Uber; Unilever; Procter & Gamble; Diageo; DHL; Maersk.

The authoritative machine-readable list, notes, geography exceptions and rates are in `config/employers.yml`.

## Adapter types

- Greenhouse
- Lever
- Ashby
- SmartRecruiters
- Workday
- Teamtailor
- Generic JSON
- RSS and Atom
- Monitored official HTML
- Official government portal
- Approved trusted sector board
- Paginated W4MP current-jobs search
- Paginated Higherin London-internship search
- Paginated CharityJob London search
- Paginated NHS Jobs London search
- Paginated jobs.ac.uk London search
- Count-validated targetjobs London early-career search service
- Query-matrix DWP Work Hub search
- Prospects London browse-page parser
- Legal Cheek Hub noticeboard parser
- Adzuna documented search API
- Reed documented Jobseeker API
- Curated YAML backed by an official programme page or ATS record

Workday search parsing is generic, while the tested Carlyle configuration supplies tenant-specific London/intern facets and uses official CXS detail enrichment before classification. Generic HTML still requires employer-specific selectors or curated evidence. Oracle HCM, SuccessFactors and iCIMS are not claimed as supported until a real priority endpoint justifies and tests an adapter.

## Expected-window evidence

- Bank of England: official programme page; no verified opening window, so the radar says “No verified window”.
- GCHQ: official programme page; opening date 24 August 2026, labelled official rather than historical.
- Goldman Sachs: official 2027 EMEA Summer Analyst page; applications open 15 August 2026, but London must be confirmed when application locations appear.
- Freshfields: official vacation-scheme page; Summer 2027 applications reopen in Autumn 2026.
- Slaughter and May: official application timetable; 2027 Summer Work Experience opens 1 September 2026 and closes 4 December 2026.
- All other programmes: no radar date until an official month/date, observed historical window or clearly labelled trusted estimate is recorded with a URL and verification date.

## Coverage limitations

Dynamic proprietary ATS pages, employer-specific Workday tenants, CAPTCHAs, authentication, robots restrictions and site terms can prevent safe automation. Such sources fail closed and remain disabled; the scanner does not bypass access controls. LinkedIn, Indeed, Glassdoor and Google Jobs are not directly scraped. Bright Network and eFinancialCareers presented automated-access challenges during verification. ReliefWeb's current API requires a pre-approved application name, and SmartRecruiters' Posting API requires credentials for reliable broad access. Discovery-only listings are clearly labelled possible and cannot enter verified data or email. Even healthy sources do not guarantee every division or website is covered; users must verify the linked application page.

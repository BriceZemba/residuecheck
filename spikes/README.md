# Spikes

Time-boxed checks that decide the architecture. Each script writes its raw findings to `results/`; decisions are recorded here because result files are regenerated on every run.

| Spike | Script | Status | Run on |
|---|---|---|---|
| S1 Token Factory models, prices, tool calling, vision | `s1_models.py` | ready, waiting for API key | |
| S2 Tavily on Moroccan trade names | not written | waiting for API key | |
| S3 ONSSA index phytosanitaire | `s3_onssa.py` | **pass** | 2026-09-13 |
| S4 RASFF pesticide notifications | `s4_rasff.py` | **pass** | 2026-09-13 |
| S5 Hosting on Nebius | not written | todo | |
| S6 Official registers, Türkiye and Egypt | manual probes with Tavily CLI + curl (below) | **pass, with caveats** | 2026-09-16 |

## S3 decision (2026-09-13)

- The ONSSA index can be read by script: GET home, postback "Nom commercial" (1,472 linked trade names; index last updated 11/09/2026 12:24), postback the product link. About 2 s per product with a 1.5 s politeness delay.
- Parsed per product: holder, supplier, registration number, validity date, category, formulation, active substances with content, and usages (crop, pest, dose, stage, max applications, interval, mode, DAR in days).
- The usages table has different columns per product, so it is parsed by header name. Non-numeric DAR values exist (e.g. "NA" for stored products) and are kept as text.
- Detail pages are ~3 MB (viewstate). No bulk crawl: lookups are on demand and cached in `data/onssa_cache/`. For eval set G2 we cache the ~60 products we need.
- Guard confirmed: exact normalised name match only. "AKTARA 25 WG" returns not_found with suggestion "ACTARA 25 WG"; "ZORBEX 300 SC" returns not_found with no suggestion. Neither is auto-resolved.
- Data quality: the ABAMEC page's free-text classification section names another product ("CONAN"). Only structured tables are trusted.
- The Excel/PDF export buttons on the list page did not return a file (page re-rendered). Not pursued.
- Demo lead, to verify in W1 with MRL data: ACTARA 25 WG (thiamethoxam 25%) is registered in Morocco for citrus with DAR 28 days; the EU Pesticides Database lists thiamethoxam as "Not approved" (approval expired 30/04/2019). The EU MRL for oranges still needs checking before any claim.

## S4 decision (2026-09-13)

- RASFF data comes from the DG SANTE open data API "API - iRASFF" (`/rasff/irasff-general-info-view`, v1.1), found through RASFF Window's public configuration. No subscription key was needed.
- The server-side date filter (`NOTIF_DATE_FROM`) fails with HTTP 400 for every format tried; we page through each origin country and filter dates locally. Data starts in 2020.
- Origin names must match the API's spelling ("Türkiye", not "Turkey"; the wrong name silently returns 0 rows).
- The hazard field gives the substance directly (`<substance> - {pesticide residues}`), sometimes suffixed "unauthorised substance"; normalised into `substance` + `unauthorised_flag`.
- Since 2024-01-01, fruits and vegetables, 5 origins: 717 distinct notifications, 1,250 substance rows (`data/rasff_pesticides_fv.csv`). 508 of the 717 notifications (792 substance rows) have basis "border control - consignment detained".
- By origin (substance rows): Türkiye 512, Egypt 419, India 166, Kenya 124, Morocco 29. Morocco is a small share, so the impact story is framed around exporters to the EU in general, with Morocco as the first origin register supported.
- G4 back-test will sample from this file with a fixed seed; 30% held out.

## S6 decision (2026-09-16)

Tavily CLI 0.1.8 (OAuth login) was used for discovery; direct HTTP requests for comparison.

**Türkiye: BKÜ, Bitki Koruma Ürünleri Veri Tabanı (Ministry of Agriculture and Forestry), https://bku.tarimorman.gov.tr**

- Product pages have stable URLs: `/BKURuhsat/Details/{id}`. Each gives the trade name, formulation, active substance(s) with content, licence number and date, validity date, licence holder. Example: `Details/3530` = BETHRİN 2.5 EC, 25 g/l Deltamethrin, licence 3366, valid until 18.03.2033.
- Crops and pre-harvest intervals are not on the detail page (usage search is a separate page); Türkiye stays resolver-only, as planned.
- The site's own search (`/Arama/Index`) is a POST form that needs an ID from an autocomplete endpoint; a plain name search returned "no record". Not reverse-engineered.
- Tavily Search with `--include-domains bku.tarimorman.gov.tr` returns detail pages, but ranking is poor: a search for "ACTARA 25 WG thiamethoxam ruhsat" returned 8 unrelated products. A resolver that trusts the top result would be wrong. The verifier (product name must appear on the cited page) is required, and the resolver needs query reformulation.
- Tavily Extract reads detail pages cleanly (~1 KB of markdown).

**Egypt: APC, لجنة مبيدات الآفات الزراعية (Agricultural Pesticide Committee), http://www.apc.gov.eg**

- Product pages: `/ar/PesticideDetails.aspx?id={id}` (also `www1.apc.gov.eg/ar/products/{id}/details.aspx` and `/m/qr.aspx?p={id}`). Each gives registration number, CAS, trade name **in Arabic** (e.g. "اب جريد 46% SL"), active substances **in English** (Bentazone + MCPA), concentration, registration status, producer, use class, and per-crop recommendations with dose and pre-harvest interval ("فترة ما قبل الحصاد": 100 days on rice, 90 on maize for that product).
- The site search (`/ar/AdvancedSearch.aspx`) is an ASP.NET form (356 KB page with the full common-name list).
- Direct access: first attempts timed out (HTTPS and redirects), then 12 of 12 plain-HTTP requests succeeded (0.3-1.2 s). So the site is reachable; the earlier failure was transient. Tavily's value here is discovery (trade name -> product page), not access.
- Tavily Search with `--include-domains apc.gov.eg` returned 6 product pages for a generic Arabic query; Extract returns the full page including recommendations.

**Consequences for the plan**

- G2b truth: sample product IDs directly from both registers (not through Tavily, to avoid a circular gold set), fetch pages directly, record trade name, substances and URL. Questions use the trade name as written on the page (Latin for Türkiye, Arabic for Egypt) plus a few transliterations and fakes.
- Egypt has crop-level pre-harvest intervals, so registration and DAR checks for Egypt are possible later; not in scope for v2.
- Claim to avoid: "only Tavily can reach these registers". True claim: "the registers have no usable name search API; Tavily finds the product page, the verifier confirms it".

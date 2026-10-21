# AI & Digital Health Professor Finder

A small Python data pipeline that cleans, validates, merges, scores and ranks a **hand-compiled list of 11 CSV rows** about Canadian professors whose research relates to AI, digital health and health data. It is a portfolio project that demonstrates data-pipeline skills (ingestion, schema mapping, cleaning, validation, de-duplication, transparent scoring, tested CSV output).

It is **not** a production system, not a web scraper, and not an AI agent. It uses only Python and pandas, and it never opens a web page.

## What it does (pipeline stages)

1. **Ingest**: read `data/researchers.csv` (read-only; the program never changes it).
2. **Map**: rename source columns to the target schema (`name` -> `full_name`, `institution` -> `university`, `dept` -> `department`, `title` -> `academic_title`, `interests` -> `research_interests`, `profile_url` -> `university_profile_url`; `source_url`, `profile_type`, and the optional `evidence_note` / `human_verified` keep their names). A missing required column stops the run with a clear message.
3. **Clean**: normalize text and names, standardize university names.
4. **Validate**: reject records with errors (see below).
5. **Merge duplicates**: keep one record per person.
6. **Score**: transparent keyword matching on the research interests.
7. **Check sources**: add warnings that ask a person to review some records.
8. **Rank and export**: write the CSV files and a row-count summary.

## Cleaning rules

- Accents are **preserved** (`Vallières` stays `Vallières`); text is composed to one consistent Unicode form and repeated spaces are collapsed.
- Names: `Vallières, Martin` and `Dr. Martin  Vallières` become `Martin Vallières`.
- University names: unambiguous short forms (`UBC`, `McGill`, `UVic`, `U of T`) become full names; matching ignores case and accents. Unknown names are left unchanged (and then rejected, see below).
- Placeholders such as `N/A`, `none`, `-` count as empty. Nothing is ever filled in or guessed.
- Research interests are separated by `; ` and repeated items are dropped.

## Three separate things: errors, warnings, verification

| | Meaning | Effect |
|---|---|---|
| **Validation error** | A rule is broken (see list below). | Record goes to `rejected_records.csv` with a plain-English reason. |
| **Source warning** | Record is usable but a person should look at it. | Record stays in the ranking; `Source Review Status` = `Review recommended`. |
| **Human verification** | A person actually checked the sources. | `Human Verification` = `Done` **only** if the input CSV has `human_verified = yes`. Currently `Not done` for every record. |

**Rejection reasons:** missing full name / university / academic title / research interests / profile URL / research source URL; a URL that is not a valid `http(s)` link; academic title without "professor"; university not in the built-in list of 20 Canadian universities; profile type other than `university` or `institutional`; no research keyword matched.

**Source warnings:** the profile is an *institutional* page (for example Vector Institute or VCH Research Institute) rather than a university page. This is accepted as a possible source, and a reviewer should confirm that the page states the university appointment. Warnings are also raised for a "university" profile on a non-matching domain, and for titles containing *adjunct*, *teaching stream*, *emeritus* or *visiting*. URLs containing words like "news" are **not** treated as invalid.

The program only reads the text of the CSV. It does not check that links are live, official or current.

## Duplicate handling

Records with the same name and university (accent- and case-insensitive) are treated as the same person and merged into **one** record, regardless of row order. The kept record is chosen by fixed rules (university-hosted profile first, then the one with more interests). Interests that appear only in another row are added; nothing is invented. The other rows and URLs are listed in `CSV Row(s)` and `Other Source URLs`, so every source stays traceable. This assumes same name + same university means same person; a reviewer should confirm.

## Scoring method

Matching is case-insensitive, whole-word, and uses only `research_interests`. Keywords belong to six areas (AI in healthcare and medicine, digital health and informatics, biomedical AI, computational medicine and biology, clinical decision support, health technology). Each distinct matched keyword adds its weight: **2** for specific health-AI phrases (for example `digital health`), **1** for generic terms (for example `machine learning`). The score is the sum. Overlapping phrases can both count (`machine learning for health` and `machine learning`), so specific wording ranks higher. All keywords and weights are in `RESEARCH_AREAS` in `main.py`.

The score measures **research-topic relevance only**, not prestige, seniority, or whether someone accepts students. Ties share a rank and are ordered by name.

## Output files (`output/`)

| File | Content |
|---|---|
| `ranked_professors.csv` | One row per person: rank, name, university, department, title, score, matched areas and keywords, interests, profile and source URLs, other sources, CSV rows, source review status and warnings, human verification, evidence note. |
| `rejected_records.csv` | Rejected rows with `Rejection Reasons`, sorted by CSV row. |
| `run_summary.txt` | Row counts: input = ranked + merged duplicates + rejected. The run stops if they do not add up. |

Sample result from the shipped dataset (9 ranked, 1 merged duplicate row, 1 rejected):

| Rank | Name | University | Score | Source review |
|---|---|---|---|---|
| 1 | Kendall Ho | University of British Columbia | 5 | No warnings |
| 1 | Martin Vallières | McGill University | 5 | No warnings |
| 1 | Rahul G. Krishnan | University of Toronto | 5 | Review recommended |
| 4 | Morgan Price | University of Victoria | 4 | Review recommended (adjunct) |
| 4 | Pascal Tyrrell | University of Toronto | 4 | No warnings |
| 4 | Purang Abolmaesumi | University of British Columbia | 4 | Review recommended |
| 7 | Michael Guerzhoy | University of Toronto | 3 | Review recommended (teaching stream) |
| 7 | Muhammad Mamdani | University of Toronto | 3 | Review recommended |
| 9 | Ilker Hacihaliloglu | University of British Columbia | 2 | Review recommended |

Rejected: Samina Abidi (no profile URL; profile type "unverified").

## Install, run, test

Requires Python 3.9 or newer and pandas. In a VS Code terminal (PowerShell on Windows), from the project folder:

```powershell
python --version
python -c "import pandas; print(pandas.__version__)"
python -m pip install -r requirements.txt   # only if pandas is missing
python main.py
python -m unittest discover -s tests -v
```

If `python` is not found on Windows, use `py` instead. On macOS/Linux use `python3`. Results are written to the `output/` folder next to `main.py` (created automatically).

## Data provenance and verification status

`data/researchers.csv` was compiled by hand (it is **not** scraped). The T-CAIREM directory (https://directory.tcairem.ai/members) was checked first, but its member list is rendered by JavaScript and returned no readable data, so it is not used.

Each row has an `evidence_note` explaining what was looked at on **2026-10-21**. These checks were made by an AI assistant reading the pages, and they are **not human verification**:

- **Page opened and appointment text read:** Tyrrell, Krishnan, Mamdani, Vallières (McGill), Abolmaesumi, Hacihaliloglu, Price.
- **Only search-result text read (page not opened directly):** Guerzhoy (U of T Engineering profile) and Ho (UBC and VCH Research Institute pages).
- **Not re-checked:** the second Vallières source (Lady Davis Institute page), kept only as an additional source.
- **Excluded:** Abidi. No official Dalhousie profile was found; the only source is a third-party site.

Some raw values deliberately keep short forms (`UBC`, `McGill`, `UVic`) or an extra space so the cleaning stage has real input. Please re-open every profile before relying on a record, then set `human_verified` to `yes` for the rows you have personally checked.

## Limitations

- Tiny sample (11 rows), compiled manually; appointments and interests change over time.
- No link checking, no web access, no verification of titles or affiliations by the program itself.
- Keyword matching is literal: it misses synonyms and does not understand context. Interests are copied or condensed from the cited pages, so a record can score low if a page words its interests differently.
- The Canadian university list is short and non-exhaustive; unlisted universities are rejected.
- Same name + same university is assumed to be the same person.
- Some profiles are institutional (Vector Institute, VCH Research Institute) rather than university pages; they confirm an appointment only if the page says so.

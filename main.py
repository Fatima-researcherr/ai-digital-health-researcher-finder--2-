"""AI & Digital Health Professor Finder: a small, transparent data pipeline.

Stages: read CSV -> map columns -> clean -> validate (errors reject a record)
        -> merge duplicates -> match keywords -> score -> source warnings
        -> rank -> export CSV files.

Three different things are kept apart on purpose:
  1. Validation errors   : the record is rejected (see rejected_records.csv).
  2. Source warnings     : the record is kept, but a person should review it.
  3. Human verification  : only "Done" if the input CSV says a person checked it.
The program never opens a web page, so it cannot tell whether a link is live,
official or current.
"""

import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
INPUT_CSV = BASE_DIR / "data" / "researchers.csv"
OUTPUT_DIR = BASE_DIR / "output"

# ---------------------------------------------------------------------------
# Target schema (internal column name -> basic type), in output order
# ---------------------------------------------------------------------------
TARGET_SCHEMA = {
    "rank": "int",
    "full_name": "str",
    "university": "str",
    "department": "str",
    "academic_title": "str",
    "relevance_score": "int",
    "matched_areas": "str",
    "matched_keywords": "str",
    "research_interests": "str",
    "profile_type": "str",  # "university" or "institutional"
    "university_profile_url": "str",
    "source_url": "str",
    "other_source_urls": "str",  # extra sources from merged duplicate rows
    "csv_rows": "str",  # input CSV row number(s) this record came from
    "source_review_status": "str",  # "No warnings" or "Review recommended"
    "source_warnings": "str",
    "human_verification": "str",  # "Not done" or "Done"
    "evidence_note": "str",
}

REJECTED_COLUMNS = [
    "csv_rows", "full_name", "university", "rejection_reasons", "department",
    "academic_title", "research_interests", "profile_type",
    "university_profile_url", "source_url", "evidence_note",
]

# Readable headers used in the exported CSV files
OUTPUT_LABELS = {
    "rank": "Rank",
    "full_name": "Full Name",
    "university": "University",
    "department": "Department",
    "academic_title": "Academic Title",
    "relevance_score": "Relevance Score",
    "matched_areas": "Matched Research Areas",
    "matched_keywords": "Matched Keywords",
    "research_interests": "Research Interests",
    "profile_type": "Profile Type",
    "university_profile_url": "Profile URL",
    "source_url": "Research Source URL",
    "other_source_urls": "Other Source URLs",
    "csv_rows": "CSV Row(s)",
    "source_review_status": "Source Review Status",
    "source_warnings": "Source Warnings (need manual review)",
    "human_verification": "Human Verification",
    "evidence_note": "Evidence Note",
    "rejection_reasons": "Rejection Reasons",
}

# ---------------------------------------------------------------------------
# Schema mapping: source CSV column -> target column
# ---------------------------------------------------------------------------
SOURCE_TO_TARGET = {
    "name": "full_name",
    "institution": "university",
    "dept": "department",
    "title": "academic_title",
    "interests": "research_interests",
    "profile_url": "university_profile_url",
    "source_url": "source_url",
    "profile_type": "profile_type",
}
# Optional source columns: filled with "" when the CSV does not have them.
OPTIONAL_SOURCE_TO_TARGET = {
    "evidence_note": "evidence_note",
    "human_verified": "human_verified",  # "yes" only if a person checked the sources
}

REQUIRED_FIELDS = [
    "full_name", "university", "academic_title", "research_interests",
    "university_profile_url", "source_url",
]
FIELD_LABELS = {
    "full_name": "full name",
    "university": "university",
    "academic_title": "academic title",
    "research_interests": "research interests",
    "university_profile_url": "profile URL",
    "source_url": "research source URL",
}
URL_FIELDS = ["university_profile_url", "source_url"]
ALLOWED_PROFILE_TYPES = {"university", "institutional"}

# Text that means "no value" in a cell.
PLACEHOLDERS = {"", "n/a", "na", "none", "null", "unknown", "tbd", "-", "--"}

# ---------------------------------------------------------------------------
# Canadian universities (small, non-exhaustive) and their web domains
# ---------------------------------------------------------------------------
UNIVERSITY_DOMAINS = {
    "University of Toronto": "utoronto.ca",
    "McGill University": "mcgill.ca",
    "University of British Columbia": "ubc.ca",
    "University of Victoria": "uvic.ca",
    "Dalhousie University": "dal.ca",
    "University of Waterloo": "uwaterloo.ca",
    "University of Alberta": "ualberta.ca",
    "University of Calgary": "ucalgary.ca",
    "McMaster University": "mcmaster.ca",
    "Queen's University": "queensu.ca",
    "Western University": "uwo.ca",
    "University of Ottawa": "uottawa.ca",
    "Université de Montréal": "umontreal.ca",
    "Université de Sherbrooke": "usherbrooke.ca",
    "Université Laval": "ulaval.ca",
    "Simon Fraser University": "sfu.ca",
    "York University": "yorku.ca",
    "Toronto Metropolitan University": "torontomu.ca",
    "University of Manitoba": "umanitoba.ca",
    "University of Saskatchewan": "usask.ca",
}
CANADIAN_UNIVERSITIES = set(UNIVERSITY_DOMAINS)

# Only unambiguous short forms are corrected.
_EXTRA_ALIASES = {
    "u of t": "University of Toronto",
    "uoft": "University of Toronto",
    "mcgill": "McGill University",
    "ubc": "University of British Columbia",
    "uvic": "University of Victoria",
    "dal": "Dalhousie University",
}

# Title words that are still professor titles but deserve a human look.
UNUSUAL_TITLE_TERMS = ("adjunct", "teaching stream", "emeritus", "visiting")

# ---------------------------------------------------------------------------
# Research keywords with weights (points). Specific health-AI phrases score 2;
# generic terms score 1 because they are not health-specific on their own.
# ---------------------------------------------------------------------------
RESEARCH_AREAS = {
    "AI in healthcare and medicine": {
        "artificial intelligence": 1,
        "machine learning": 1,
        "deep learning": 1,
        "ai in medicine": 2,
        "ai and healthcare": 2,
        "ai for health": 2,
        "ai in mental health": 2,
        "machine learning for health": 2,
        "data science for healthcare": 2,
        "precision medicine": 2,
    },
    "Digital health and health informatics": {
        "digital health": 2,
        "health informatics": 2,
        "clinical information systems": 2,
        "electronic health records": 2,
        "telehealth": 2,
        "virtual care": 2,
        "remote patient monitoring": 2,
        "wearables": 1,
    },
    "Biomedical AI and medical machine learning": {
        "medical image analysis": 2,
        "medical machine learning": 2,
        "medical imaging": 2,
        "biomedical": 2,
        "ultrasound imaging": 1,
    },
    "Computational medicine and biology": {
        "computational medicine": 2,
        "computational biology": 2,
        "bioinformatics": 1,
    },
    "Clinical decision support": {
        "clinical decision support": 2,
    },
    "Health technology and biomedical engineering": {
        "health technology": 2,
        "biomedical engineering": 2,
        "medical devices": 1,
    },
}


# ---------------------------------------------------------------------------
# Ingestion and schema mapping
# ---------------------------------------------------------------------------
def load_csv(path):
    """Read a CSV as text. Empty cells stay empty strings (not NaN)."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def map_schema(df):
    """Rename source columns to target names; fail clearly if one is missing."""
    missing = [col for col in SOURCE_TO_TARGET if col not in df.columns]
    if missing:
        raise ValueError(f"Input CSV is missing required columns: {missing}")
    mapped = df[list(SOURCE_TO_TARGET)].rename(columns=SOURCE_TO_TARGET)
    for source, target in OPTIONAL_SOURCE_TO_TARGET.items():
        mapped[target] = df[source] if source in df.columns else ""
    return mapped


# ---------------------------------------------------------------------------
# Cleaning (accents are preserved everywhere)
# ---------------------------------------------------------------------------
def fold(text):
    """Lowercase, accent-free text, used only for comparing (never for output)."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip().lower()


def clean_text(value):
    """Compose accents (NFC), collapse whitespace, turn placeholders into ''."""
    text = unicodedata.normalize("NFC", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return "" if text.lower() in PLACEHOLDERS else text


def clean_name(value):
    """'Dr. Martin  Vallières' and 'Vallières, Martin' -> 'Martin Vallières'."""
    name = re.sub(r"^(dr|prof|professor)\.?\s+", "", clean_text(value), flags=re.IGNORECASE)
    if name.count(",") == 1:
        last, first = (part.strip() for part in name.split(","))
        if last and first:
            name = f"{first} {last}"
    return name


_UNIVERSITY_LOOKUP = {fold(name): name for name in CANADIAN_UNIVERSITIES}
_UNIVERSITY_LOOKUP.update(_EXTRA_ALIASES)


def clean_university(value):
    """Standardize a university name (accent- and case-insensitive lookup)."""
    text = clean_text(value)
    key = re.sub(r"^the ", "", fold(text).rstrip("."))
    return _UNIVERSITY_LOOKUP.get(key, text)


def split_interests(text):
    """Split on ';' or '|' and drop repeated items (case-insensitive)."""
    items, seen = [], set()
    for item in re.split(r"[;|]", text):
        item = item.strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            items.append(item)
    return items


def clean_record(record):
    """Return a cleaned copy of one record (a dict)."""
    cleaned = {key: clean_text(value) for key, value in record.items()}
    cleaned["full_name"] = clean_name(record["full_name"])
    cleaned["university"] = clean_university(record["university"])
    cleaned["research_interests"] = "; ".join(split_interests(cleaned["research_interests"]))
    cleaned["profile_type"] = cleaned["profile_type"].lower()
    cleaned["human_verified"] = cleaned["human_verified"].lower()
    return cleaned


# ---------------------------------------------------------------------------
# Validation: errors that REJECT a record
# ---------------------------------------------------------------------------
def is_valid_url(url):
    """Accept only http(s) links with a host name that contains a dot."""
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and "." in parsed.netloc and " " not in url


def validate_record(record):
    """Return plain-English error messages. An empty list means valid."""
    errors = []
    for field in REQUIRED_FIELDS:
        if not record.get(field):
            errors.append(f"Missing required field: {FIELD_LABELS[field]}")
    for field in URL_FIELDS:
        value = record.get(field)
        if value and not is_valid_url(value):
            errors.append(f"The {FIELD_LABELS[field]} is not a valid http(s) link: {value}")
    title = record.get("academic_title")
    if title and "professor" not in title.lower():
        errors.append(f"Academic title does not contain 'professor' (found: {title})")
    university = record.get("university")
    if university and university not in CANADIAN_UNIVERSITIES:
        errors.append(
            f"University is not in the built-in list of Canadian universities (found: {university})"
        )
    if record.get("profile_type") not in ALLOWED_PROFILE_TYPES:
        errors.append(
            "Profile type must be 'university' or 'institutional' "
            f"(found: '{record.get('profile_type', '')}')"
        )
    return errors


# ---------------------------------------------------------------------------
# Source warnings: the record is KEPT, but a person should review it.
# These look only at the text of the record. No web page is ever opened.
# ---------------------------------------------------------------------------
def get_host(url):
    """Host name of a URL without 'www.' (for example 'vchri.ca')."""
    return urlparse(url).netloc.lower().split(":")[0].removeprefix("www.")


def source_warnings(record):
    """Return warnings (list of strings). An empty list is NOT verification."""
    warnings = []
    host = get_host(record["university_profile_url"])
    expected = UNIVERSITY_DOMAINS.get(record["university"])
    on_university_site = bool(expected) and (host == expected or host.endswith("." + expected))

    if record["profile_type"] == "institutional":
        warnings.append(
            f"Institutional profile hosted by {host}, not by the university. It is accepted as a "
            "possible source; a reviewer should confirm the page states the university appointment"
        )
    elif expected and not on_university_site:
        warnings.append(f"Marked as a university profile, but {host} is not a {expected} address")

    title = record["academic_title"].lower()
    for term in UNUSUAL_TITLE_TERMS:
        if term in title:
            warnings.append(
                f"Title contains '{term}': confirm this counts as a faculty role for your purposes"
            )
    return warnings


# ---------------------------------------------------------------------------
# Duplicates: the same person (same name + university) is merged, in any order
# ---------------------------------------------------------------------------
def make_duplicate_key(record):
    return (fold(record["full_name"]), fold(record["university"]))


def _row_numbers(record):
    return [int(n) for n in record["csv_rows"].split(";") if n.strip()]


def merge_duplicates(records):
    """Keep one record per person. The result does not depend on row order.

    The kept ("primary") record is chosen by fixed rules (university-hosted
    profile first, then more interests, then URL). Interests that only appear
    in other rows are added; nothing is invented. All other rows and URLs are
    listed in csv_rows / other_source_urls so every source stays traceable.
    """
    groups = {}
    for record in records:
        groups.setdefault(make_duplicate_key(record), []).append(record)

    merged = []
    for group in groups.values():
        group.sort(
            key=lambda r: (
                r["profile_type"] != "university",
                -len(split_interests(r["research_interests"])),
                r["university_profile_url"],
            )
        )
        primary = dict(group[0])
        interests = split_interests(primary["research_interests"])
        known = {item.lower() for item in interests}
        extra_interests, extra_urls = [], set()
        for other in group[1:]:
            for item in split_interests(other["research_interests"]):
                if item.lower() not in known:
                    known.add(item.lower())
                    extra_interests.append(item)
            for url in (other["university_profile_url"], other["source_url"]):
                if url not in (primary["university_profile_url"], primary["source_url"]):
                    extra_urls.add(url)
        primary["research_interests"] = "; ".join(
            interests + sorted(extra_interests, key=str.lower)
        )
        primary["other_source_urls"] = "; ".join(sorted(extra_urls))
        rows = sorted(n for r in group for n in _row_numbers(r))
        primary["csv_rows"] = "; ".join(str(n) for n in rows)
        merged.append(primary)
    return merged


# ---------------------------------------------------------------------------
# Keyword matching, scoring and ranking
# ---------------------------------------------------------------------------
def match_keywords(text):
    """Return (keywords, areas, score). Score = sum of distinct keyword weights."""
    keywords, areas, score = [], [], 0
    for area, area_keywords in RESEARCH_AREAS.items():
        for keyword, weight in area_keywords.items():
            pattern = r"(?<!\w)" + re.escape(keyword) + r"(?!\w)"
            if re.search(pattern, text, flags=re.IGNORECASE):
                keywords.append(keyword)
                score += weight
                if area not in areas:
                    areas.append(area)
    return keywords, areas, score


def rank_records(records):
    """Sort by score (high to low), then name (accent-insensitive). Ties share a rank."""
    if not records:
        return pd.DataFrame(columns=list(TARGET_SCHEMA))
    df = pd.DataFrame(records)
    columns = [col for col in TARGET_SCHEMA if col in df.columns or col == "rank"]
    df["_name_key"] = df["full_name"].map(fold)
    df = df.sort_values(["relevance_score", "_name_key"], ascending=[False, True])
    df["rank"] = df["relevance_score"].rank(method="min", ascending=False).astype(int)
    return df[columns].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def count_rows(csv_rows):
    return len([n for n in str(csv_rows).split(";") if n.strip()])


def build_summary(input_rows, ranked, rejected):
    """Count rows so the run can prove that nothing was lost or duplicated."""
    ranked_rows = sum(count_rows(v) for v in ranked["csv_rows"]) if len(ranked) else 0
    rejected_rows = sum(count_rows(v) for v in rejected["csv_rows"]) if len(rejected) else 0
    return {
        "input_rows": input_rows,
        "ranked_records": len(ranked),
        "merged_duplicate_rows": ranked_rows - len(ranked),
        "rejected_records": len(rejected),
        "consistent": input_rows == ranked_rows + rejected_rows,
    }


def run_pipeline(input_csv=INPUT_CSV, output_dir=OUTPUT_DIR):
    """Run all stages and write the output files. Returns (ranked, rejected).

    The input file is only read, never changed.
    """
    mapped = map_schema(load_csv(input_csv))

    valid, rejected = [], []
    for row_number, raw in enumerate(mapped.to_dict("records"), start=2):
        record = clean_record(raw)
        record["csv_rows"] = str(row_number)
        record["other_source_urls"] = ""
        errors = validate_record(record)
        if errors:
            rejected.append({**record, "rejection_reasons": "; ".join(errors)})
        else:
            valid.append(record)

    accepted = []
    for record in merge_duplicates(valid):
        keywords, areas, score = match_keywords(record["research_interests"])
        if score == 0:
            reason = "No research keywords matched the listed research interests"
            rejected.append({**record, "rejection_reasons": reason})
            continue
        warnings = source_warnings(record)
        record["matched_keywords"] = "; ".join(keywords)
        record["matched_areas"] = "; ".join(areas)
        record["relevance_score"] = score
        record["source_review_status"] = "Review recommended" if warnings else "No warnings"
        record["source_warnings"] = "; ".join(warnings)
        record["human_verification"] = "Done" if record["human_verified"] == "yes" else "Not done"
        accepted.append(record)

    ranked = rank_records(accepted)
    rejected.sort(key=lambda r: min(_row_numbers(r)))
    rejected_df = pd.DataFrame(rejected, columns=REJECTED_COLUMNS)

    summary = build_summary(len(mapped), ranked, rejected_df)
    if not summary["consistent"]:
        raise RuntimeError(f"Row counts do not add up: {summary}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for df, filename in ((ranked, "ranked_professors.csv"), (rejected_df, "rejected_records.csv")):
        df.rename(columns=OUTPUT_LABELS).to_csv(
            output_dir / filename, index=False, encoding="utf-8-sig"
        )
    (output_dir / "run_summary.txt").write_text(format_summary(summary), encoding="utf-8")
    return ranked, rejected_df


def format_summary(summary):
    lines = [
        f"Input rows read           : {summary['input_rows']}",
        f"Ranked records            : {summary['ranked_records']}",
        f"Duplicate rows merged     : {summary['merged_duplicate_rows']}",
        f"Rejected records          : {summary['rejected_records']}",
        "Row count check           : "
        + ("OK (input = ranked + merged + rejected)" if summary["consistent"] else "MISMATCH"),
        "Note: no web page is opened by this program; links are not checked and "
        "no record is marked as verified by a human unless the input CSV says so.",
    ]
    return "\n".join(lines) + "\n"


def main():
    ranked, rejected = run_pipeline()
    summary = build_summary(len(load_csv(INPUT_CSV)), ranked, rejected)
    print(format_summary(summary))
    print(f"Results saved in: {OUTPUT_DIR}")
    print("  - ranked_professors.csv\n  - rejected_records.csv\n  - run_summary.txt")
    if not ranked.empty:
        print("\nRanked records:")
        print(ranked[["rank", "full_name", "university", "relevance_score",
                      "source_review_status"]].to_string(index=False))
    if not rejected.empty:
        print("\nRejected records:")
        for _, row in rejected.iterrows():
            print(f"  - row {row['csv_rows']}: {row['full_name']}: {row['rejection_reasons']}")


if __name__ == "__main__":
    main()

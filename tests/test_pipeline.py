"""Automated tests for the pipeline. Run from the project folder:

    python -m unittest discover -s tests -v
"""

import random
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402


def good_record(**overrides):
    """A cleaned, valid record (internal column names)."""
    record = {
        "full_name": "Ada Example",
        "university": "University of Toronto",
        "department": "Department of Medicine",
        "academic_title": "Assistant Professor",
        "research_interests": "AI in medicine; machine learning",
        "university_profile_url": "https://example.utoronto.ca/ada",
        "source_url": "https://example.utoronto.ca/ada",
        "profile_type": "university",
        "evidence_note": "",
        "human_verified": "",
        "csv_rows": "2",
        "other_source_urls": "",
    }
    record.update(overrides)
    return record


def source_row(**overrides):
    """A raw input row (source column names)."""
    row = {"name": "Kendall Ho", "institution": "UBC", "dept": "Emergency Medicine",
           "title": "Professor", "interests": "Digital health; Virtual care",
           "profile_url": "https://vision.ubc.ca/people/kendall-ho",
           "source_url": "https://www.vchri.ca/researchers/kendall-ho",
           "profile_type": "university"}
    row.update(overrides)
    return row


def run_on_rows(rows):
    """Run the pipeline on a temporary CSV. Returns (ranked, rejected, out_dir)."""
    tmp = tempfile.TemporaryDirectory()
    csv_path = Path(tmp.name) / "in.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    out = Path(tmp.name) / "out"
    ranked, rejected = main.run_pipeline(csv_path, out)
    return ranked, rejected, out, tmp


class TestSchemaMapping(unittest.TestCase):
    def test_columns_are_renamed(self):
        source = pd.DataFrame([{col: "x" for col in main.SOURCE_TO_TARGET}])
        mapped = main.map_schema(source)
        for target in main.SOURCE_TO_TARGET.values():
            self.assertIn(target, mapped.columns)

    def test_missing_source_column_raises(self):
        with self.assertRaises(ValueError):
            main.map_schema(pd.DataFrame([{"name": "x"}]))

    def test_optional_columns_default_to_empty(self):
        source = pd.DataFrame([{col: "x" for col in main.SOURCE_TO_TARGET}])
        mapped = main.map_schema(source)
        self.assertEqual(mapped.iloc[0]["evidence_note"], "")
        self.assertEqual(mapped.iloc[0]["human_verified"], "")


class TestCleaning(unittest.TestCase):
    def test_university_aliases(self):
        self.assertEqual(main.clean_university("UBC"), "University of British Columbia")
        self.assertEqual(main.clean_university("  mcgill "), "McGill University")

    def test_university_lookup_ignores_accents_and_restores_them(self):
        self.assertEqual(main.clean_university("universite de montreal"), "Université de Montréal")

    def test_unknown_university_is_left_unchanged(self):
        self.assertEqual(main.clean_university("Some College"), "Some College")

    def test_whitespace_and_accents_are_preserved(self):
        self.assertEqual(main.clean_text("  Martin   Vallières "), "Martin Vallières")

    def test_decomposed_accents_are_composed_consistently(self):
        decomposed = "Valli" + "e\u0300" + "res"  # 'e' + combining grave accent -> 'è'
        self.assertEqual(main.clean_text(decomposed), "Vallières")

    def test_name_formats_are_normalized(self):
        self.assertEqual(main.clean_name("Vallières, Martin"), "Martin Vallières")
        self.assertEqual(main.clean_name("Dr. Martin  Vallières"), "Martin Vallières")

    def test_placeholders_become_empty(self):
        self.assertEqual(main.clean_text("N/A"), "")
        self.assertEqual(main.clean_text(" none "), "")

    def test_interest_separators_and_repeats(self):
        self.assertEqual(main.clean_record(source_to_clean("AI ;ML|  health;ai"))["research_interests"],
                         "AI; ML; health")


def source_to_clean(interests):
    record = {target: "x" for target in main.SOURCE_TO_TARGET.values()}
    record.update({"evidence_note": "", "human_verified": "", "research_interests": interests})
    return record


class TestValidationErrors(unittest.TestCase):
    def test_valid_record_has_no_errors(self):
        self.assertEqual(main.validate_record(good_record()), [])

    def test_missing_required_field_message_is_plain_english(self):
        errors = main.validate_record(good_record(research_interests=""))
        self.assertIn("Missing required field: research interests", errors)

    def test_placeholder_cleaned_to_empty_counts_as_missing(self):
        cleaned = main.clean_record(source_to_clean("n/a"))
        self.assertIn("Missing required field: research interests", main.validate_record(cleaned))

    def test_invalid_url(self):
        errors = main.validate_record(good_record(source_url="not a url"))
        self.assertTrue(any("not a valid http(s) link" in e for e in errors))

    def test_title_must_contain_professor(self):
        errors = main.validate_record(good_record(academic_title="Postdoctoral Fellow"))
        self.assertTrue(any("professor" in e for e in errors))

    def test_unknown_university_is_rejected(self):
        errors = main.validate_record(good_record(university="Some College"))
        self.assertTrue(any("Canadian universities" in e for e in errors))

    def test_unverified_profile_type_is_rejected(self):
        errors = main.validate_record(good_record(profile_type="unverified"))
        self.assertTrue(any("Profile type" in e for e in errors))


class TestSourceWarnings(unittest.TestCase):
    """Warnings keep the record but ask a person to review it."""

    def test_matching_university_domain_has_no_warnings(self):
        self.assertEqual(main.source_warnings(good_record()), [])

    def test_institutional_profile_is_a_warning_not_an_error(self):
        record = good_record(
            university="University of British Columbia", profile_type="institutional",
            university_profile_url="https://www.vchri.ca/researchers/kendall-ho",
        )
        self.assertEqual(main.validate_record(record), [])
        warnings = main.source_warnings(record)
        self.assertEqual(len(warnings), 1)
        self.assertIn("vchri.ca", warnings[0])
        self.assertIn("possible source", warnings[0])

    def test_news_style_url_is_not_flagged(self):
        record = good_record(
            university="University of British Columbia",
            university_profile_url="https://datascienceandhealth.ubc.ca/news/spotlight-series-meet-dr-ho",
        )
        self.assertEqual(main.source_warnings(record), [])
        self.assertEqual(main.validate_record(record), [])

    def test_university_type_on_other_domain_is_flagged(self):
        record = good_record(university_profile_url="https://www.vchri.ca/researchers/x")
        self.assertIn("not a utoronto.ca address", main.source_warnings(record)[0])

    def test_unusual_titles_are_flagged_but_valid(self):
        for title, term in (("Adjunct Associate Professor", "adjunct"),
                            ("Assistant Professor, Teaching Stream", "teaching stream")):
            record = good_record(academic_title=title)
            self.assertEqual(main.validate_record(record), [])
            self.assertIn(term, main.source_warnings(record)[0])

    def test_get_host_removes_www_and_port(self):
        self.assertEqual(main.get_host("https://www.vchri.ca:443/x"), "vchri.ca")

    def test_unknown_university_skips_domain_check(self):
        self.assertEqual(main.source_warnings(good_record(university="Some Unlisted University")), [])


class TestDuplicates(unittest.TestCase):
    def two_records(self):
        first = good_record(
            full_name="Martin Vallières", university="McGill University",
            research_interests="Machine learning; Medical image analysis; Precision medicine",
            university_profile_url="https://www.mcgill.ca/medphys/martin-vallieres",
            source_url="https://www.mcgill.ca/medphys/martin-vallieres", csv_rows="2",
        )
        second = good_record(
            full_name="martin vallieres", university="McGill University", profile_type="institutional",
            research_interests="machine learning; Federated learning",
            university_profile_url="https://www.ladydavis.ca/en/researcher/martin-vallieres/",
            source_url="https://www.ladydavis.ca/en/researcher/martin-vallieres/", csv_rows="3",
        )
        return first, second

    def test_duplicates_are_merged_and_traceable(self):
        merged = main.merge_duplicates(list(self.two_records()))
        self.assertEqual(len(merged), 1)
        record = merged[0]
        self.assertEqual(record["csv_rows"], "2; 3")
        self.assertIn("ladydavis.ca", record["other_source_urls"])
        self.assertEqual(record["university_profile_url"], "https://www.mcgill.ca/medphys/martin-vallieres")

    def test_merged_interests_contain_nothing_new(self):
        first, second = self.two_records()
        merged = main.merge_duplicates([first, second])[0]
        expected = set(main.split_interests(first["research_interests"])) | {"Federated learning"}
        self.assertEqual({i for i in main.split_interests(merged["research_interests"])}, expected)

    def test_merge_result_does_not_depend_on_row_order(self):
        first, second = self.two_records()
        forward = main.merge_duplicates([dict(first), dict(second)])[0]
        backward = main.merge_duplicates([dict(second), dict(first)])[0]
        self.assertEqual(forward, backward)

    def test_different_people_are_not_merged(self):
        first, _ = self.two_records()
        other = good_record(full_name="Someone Else", csv_rows="4")
        self.assertEqual(len(main.merge_duplicates([first, other])), 2)


class TestKeywordMatchingAndRanking(unittest.TestCase):
    def test_keyword_match_and_score(self):
        keywords, areas, score = main.match_keywords("Clinical decision support; Machine Learning")
        self.assertEqual(keywords, ["machine learning", "clinical decision support"])
        self.assertEqual(score, 1 + 2)
        self.assertIn("Clinical decision support", areas)

    def test_whole_word_matching(self):
        self.assertEqual(main.match_keywords("Biomedicalization studies")[2], 0)

    def test_ranking_order_and_ties(self):
        def rec(name, score):
            return {**good_record(full_name=name), "matched_keywords": "", "matched_areas": "",
                    "relevance_score": score}
        ranked = main.rank_records([rec("B Low", 2), rec("A High", 6), rec("C Low", 2)])
        self.assertEqual(list(ranked["full_name"]), ["A High", "B Low", "C Low"])
        self.assertEqual(list(ranked["rank"]), [1, 2, 2])

    def test_name_sorting_ignores_accents(self):
        def rec(name):
            return {**good_record(full_name=name), "matched_keywords": "", "matched_areas": "",
                    "relevance_score": 3}
        ranked = main.rank_records([rec("Zoe Zed"), rec("Émile Zola"), rec("Adam Able")])
        self.assertEqual(list(ranked["full_name"]), ["Adam Able", "Émile Zola", "Zoe Zed"])


class TestPipelineOnTemporaryData(unittest.TestCase):
    def test_human_verification_is_never_assumed(self):
        ranked, _, _, tmp = run_on_rows([source_row()])
        self.addCleanup(tmp.cleanup)
        self.assertEqual(ranked.iloc[0]["human_verification"], "Not done")

    def test_human_verification_only_when_csv_says_yes(self):
        ranked, _, _, tmp = run_on_rows([source_row(human_verified="yes")])
        self.addCleanup(tmp.cleanup)
        self.assertEqual(ranked.iloc[0]["human_verification"], "Done")

    def test_duplicate_rows_are_merged_not_rejected(self):
        rows = [source_row(name="Ada Example", institution="U of T"),
                source_row(name="ada  example", institution="University of Toronto",
                           interests="Telehealth")]
        ranked, rejected, out, tmp = run_on_rows(rows)
        self.addCleanup(tmp.cleanup)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(len(rejected), 0)
        self.assertEqual(ranked.iloc[0]["csv_rows"], "2; 3")
        self.assertIn("Telehealth", ranked.iloc[0]["research_interests"])

    def test_row_order_does_not_change_results(self):
        rows = [source_row(name="A One", interests="Digital health"),
                source_row(name="A One", institution="University of British Columbia",
                           interests="Telehealth; Digital health", profile_type="institutional"),
                source_row(name="B Two", interests="Machine learning"),
                source_row(name="C Three", interests="", profile_url="")]
        results = []
        for seed in (1, 2, 3):
            shuffled = rows[:]
            random.Random(seed).shuffle(shuffled)
            ranked, rejected, _, tmp = run_on_rows(shuffled)
            self.addCleanup(tmp.cleanup)
            results.append((list(ranked["full_name"]), list(ranked["relevance_score"]),
                            list(ranked["research_interests"]), len(rejected)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])

    def test_incomplete_record_is_rejected_with_reasons_not_invented(self):
        ranked, rejected, _, tmp = run_on_rows([source_row(interests="", profile_url="")])
        self.addCleanup(tmp.cleanup)
        self.assertEqual(len(ranked), 0)
        reasons = rejected.iloc[0]["rejection_reasons"]
        self.assertIn("Missing required field: research interests", reasons)
        self.assertIn("Missing required field: profile URL", reasons)

    def test_exported_headers_order_and_sorting(self):
        rows = [source_row(name="First", interests=""), source_row(name="Second", interests=""),
                source_row(name="Third", interests="Digital health")]
        _, _, out, tmp = run_on_rows(rows)
        self.addCleanup(tmp.cleanup)
        ranked = pd.read_csv(out / "ranked_professors.csv")
        self.assertEqual(list(ranked.columns[:3]), ["Rank", "Full Name", "University"])
        rejected = pd.read_csv(out / "rejected_records.csv")
        self.assertEqual(list(rejected.columns[:4]),
                         ["CSV Row(s)", "Full Name", "University", "Rejection Reasons"])
        self.assertEqual(list(rejected["CSV Row(s)"]), [2, 3])

    def test_accents_survive_the_csv_export(self):
        _, _, out, tmp = run_on_rows([source_row(name="Martin Vallières")])
        self.addCleanup(tmp.cleanup)
        ranked = pd.read_csv(out / "ranked_professors.csv", encoding="utf-8-sig")
        self.assertEqual(ranked.iloc[0]["Full Name"], "Martin Vallières")


class TestRealDataset(unittest.TestCase):
    """Checks on the shipped dataset and its generated output."""

    @classmethod
    def setUpClass(cls):
        cls.before = main.INPUT_CSV.read_bytes()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ranked, cls.rejected = main.run_pipeline(main.INPUT_CSV, Path(cls.tmp.name))
        cls.out = Path(cls.tmp.name)
        cls.input_rows = len(main.load_csv(main.INPUT_CSV))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_input_csv_is_never_modified(self):
        self.assertEqual(main.INPUT_CSV.read_bytes(), self.before)

    def test_row_counts_are_consistent(self):
        summary = main.build_summary(self.input_rows, self.ranked, self.rejected)
        self.assertTrue(summary["consistent"])
        self.assertEqual(
            self.input_rows,
            summary["ranked_records"] + summary["merged_duplicate_rows"] + summary["rejected_records"],
        )

    def test_exported_files_match_returned_data(self):
        ranked_csv = pd.read_csv(self.out / "ranked_professors.csv")
        rejected_csv = pd.read_csv(self.out / "rejected_records.csv")
        self.assertEqual(len(ranked_csv), len(self.ranked))
        self.assertEqual(len(rejected_csv), len(self.rejected))

    def test_no_duplicate_people_in_output(self):
        keys = [main.fold(n) for n in self.ranked["full_name"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_vallieres_is_one_traceable_record(self):
        row = self.ranked[self.ranked["full_name"] == "Martin Vallières"]
        self.assertEqual(len(row), 1)
        self.assertEqual(row.iloc[0]["csv_rows"], "6; 12")
        self.assertIn("ladydavis.ca", row.iloc[0]["other_source_urls"])

    def test_abidi_is_rejected_for_missing_profile_url(self):
        row = self.rejected[self.rejected["full_name"] == "Samina Abidi"]
        self.assertEqual(len(row), 1)
        self.assertIn("Missing required field: profile URL", row.iloc[0]["rejection_reasons"])

    def test_nobody_is_marked_human_verified(self):
        self.assertTrue((self.ranked["human_verification"] == "Not done").all())

    def test_every_ranked_record_has_urls_and_title(self):
        for column in ("university_profile_url", "source_url", "academic_title", "research_interests"):
            self.assertTrue((self.ranked[column].str.len() > 0).all(), column)


if __name__ == "__main__":
    unittest.main()

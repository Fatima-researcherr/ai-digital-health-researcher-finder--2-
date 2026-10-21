# Researcher Dataset Audit and Debugging

## Objective
Audit researcher records, correct data-quality issues, and validate the updated dataset using the existing test suite.

## Changes Made
- Added a profile URL for Samina Abidi.
- Consolidated duplicate records for Martin Vallieres into one researcher record.
- Reviewed researcher profile links, affiliations, titles, and research interests.
- Preserved the original dataset and kept the corrected dataset in a separate CSV file.

## Validation
The existing test suite was run against the corrected dataset in a temporary project copy.

- 46 tests passed
- 2 tests failed

### Failure Analysis
1. The Samina Abidi test expects the record to be rejected because its profile URL is missing. The corrected dataset now includes a profile URL.
2. The Martin Vallieres test expects the pipeline to merge two source rows and retain the row reference `6; 12`. The corrected dataset already contains a consolidated record, so the pipeline sees only row `6`.

These failures show a mismatch between the existing test assumptions and the corrected input data. They do not, by themselves, prove that the pipeline is defective.

## Scope and Limitations
This audit documents dataset corrections and test results. Researcher profile details and affiliations still require independent verification against authoritative sources.

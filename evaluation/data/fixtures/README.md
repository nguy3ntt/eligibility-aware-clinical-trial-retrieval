# Test fixtures

Only tiny, clearly synthetic patient and trial examples belong here. Fixtures should target parsing, retrieval, filtering, and safety edge cases.

`eligibility_criteria.json` contains 10 entirely invented trial-text cases with 27 manually specified expected criterion tuples. Labels cover exact wording, section, type tags, visible conjunctions, numeric bounds/units and parent order. These are development rule contracts, not held-out clinical labels or copied real patient records.

`screening.json` contains 34 invented patient–trial pairs with 41 expected rule outcomes and trial summaries. `semantic_screening.json` contains 24 calibration and 30 disjoint test text-relation pairs, labelled before running the selected NLI model. Neither file contains real patient data or independent clinical validation. Preserve these frozen versions; new research labels belong in a new dataset version rather than replacing failed examples.

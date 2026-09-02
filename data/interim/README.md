# Interim data

Reproducible normalized outputs belong here locally. Every file must be derivable from raw data plus versioned code and configuration.

Examples include flattened trial records, field-profile tables, and parsed eligibility sections.

The inspection pipeline writes profiles, a complete topic/qrel trace table with explicit trial-coverage gaps, original eligibility-format examples, and a small review worksheet. Generated worksheets preserve their initial `pending` state so derived outputs remain reproducible and immutable. No canonical ingestion or criterion parsing is performed yet. Every output directory is new, links to its raw manifest checksum, and records code, configuration, and output hashes. Use the offline profile command in `pipelines/README.md` to reproduce it. Generated files and synthetic narratives remain local and Git-ignored.

Historical corpus validation writes aggregate field states, explicit validation issues, and a trial index linking each NCT ID to its archive member, CRC, and uncompressed byte count. It does not copy trial text into reports or create eligibility assessments.

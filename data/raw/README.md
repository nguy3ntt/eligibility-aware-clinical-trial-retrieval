# Raw data

Immutable public-source snapshots belong here locally. Do not manually edit them. Record the retrieval timestamp, source URL or release, request parameters, checksum, and licence metadata in an accompanying manifest.

Inspection sources include bounded ClinicalTrials.gov API responses and official synthetic TREC 2022 topic/qrel files. See `pipelines/README.md` for the acquisition command.

Each run gets a new subdirectory. Response bodies have checksummed sidecars and a final manifest. Never reuse a run ID or alter a failed snapshot. Failed or interrupted runs remain audit evidence; the profiler rejects them. Successful snapshots are local research inputs, not the historical TREC trial corpus, and must not be published with the code.

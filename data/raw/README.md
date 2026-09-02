# Raw data

Immutable public-source snapshots belong here locally. Do not manually edit them. Record the retrieval timestamp, source URL or release, request parameters, checksum, and licence metadata in an accompanying manifest.

Inspection sources include bounded ClinicalTrials.gov API responses and official synthetic TREC 2022 topic/qrel files. See `pipelines/README.md` for the acquisition command.

Historical benchmark snapshots contain the five official April 27, 2021 TREC XML archives and an acquisition manifest. Downloads use a resumable `.incomplete` staging directory and become immutable only after every archive passes the recorded source-size and timestamp checks. Publisher checksums are unavailable, so the manifest distinguishes locally computed SHA-256 values from source-authenticated hashes.

Each run gets a new subdirectory. Response bodies have checksummed sidecars and a final manifest. Never reuse a run ID or alter a failed snapshot. Failed or interrupted runs remain audit evidence; the profiler rejects them. Successful snapshots are local research inputs, not the historical TREC trial corpus, and must not be published with the code.

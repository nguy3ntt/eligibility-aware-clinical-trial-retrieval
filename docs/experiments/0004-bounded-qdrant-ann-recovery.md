# Bounded Qdrant ANN and recovery diagnostic

- Date: 2026-09-05
- Scope: 443 historical trials selected using judgments, 50 official synthetic topics; not a full-corpus benchmark.
- Local primary report: `evaluation/reports/m4-ann-final/ann.json`.
- Local rebuild report: `evaluation/reports/m4-ann-rebuilt-final/ann.json`.
- Recovery evidence: `evaluation/reports/m4-recovery-final/`; backup manifest under `artifacts/qdrant-backups/m4-recovery-v2/`.
- Source artifact manifest SHA-256: `f66e32d568983d2061db23a92e2d781f8f46f69030f965cf901c4623792f7480`.
- Model: `sentence-transformers/all-MiniLM-L6-v2`, revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`; normalized 384-dimensional float32 title/condition vectors.
- Qdrant: official native Windows 1.19.0. Code provenance is recorded using source-file hashes in generated reports; no new code commit is asserted.

## Method

The previous collection had zero indexed vectors under default thresholds. The diagnostic explicitly built a graph covering all 443 vectors, with `m=16`, `ef_construct=100`, one indexing thread, `full_scan_threshold=10` KiB, `indexing_threshold=1` KiB, and one populated optimized segment. An empty appendable segment remained. These low thresholds are needed for the small diagnostic and are not recommended production defaults.

For each demographic-filter mode and search effort 10, 32, or 128, the experiment first checked exact server neighbors against a direct NumPy matrix calculation. It warmed both query methods once per topic, then measured three paired repetitions across all 50 topics with seeded query/method order randomization. Each configuration contains 150 exact and 150 ANN timed calls. All requests include an artifact digest filter, including the `none` demographic condition.

The collection's level-4 telemetry confirmed exactly 150 `filtered_large_cardinality` graph searches and 150 `filtered_exact` searches in every timed configuration, with stable graph identity and no scan fallback. This is evidence that the experiment exercised HNSW, not merely the server's exact fallback.

Recall@10 is strict overlap with exact neighbor IDs divided by the number of available exact neighbors (up to 10). Empty references would be excluded; none occurred. It is unrelated to qrel grade or medical eligibility. Timing covers warm sequential HTTP/JSON/result sorting, excluding query encoding, integrity checks, startup, and telemetry. No statistical significance or throughput claim is made.

## Results on the original graph

| Demographic filter | HNSW effort | Mean Recall@10 | Worst query recall | Exact median ms | ANN median ms | ANN p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| None | 10 | 0.954 | 0.8 | 1.153 | 1.137 | 1.414 |
| None | 32 | 0.996 | 0.9 | 1.086 | 1.134 | 1.448 |
| None | 128 | 1.000 | 1.0 | 1.285 | 1.324 | 2.203 |
| Age/sex | 10 | 0.958 | 0.7 | 1.150 | 1.151 | 1.344 |
| Age/sex | 32 | 0.994 | 0.8 | 1.176 | 1.187 | 1.418 |
| Age/sex | 128 | 1.000 | 1.0 | 1.200 | 1.249 | 1.486 |

Higher effort recovered more exact neighbors. At effort 128 all measured queries recovered all ten neighbors, with and without demographics filtering. There is no convincing speed advantage at 443 trials: network/serialization overhead is comparable to search time, and higher-effort ANN was slightly slower in the median. Exact search remains the default; ANN is explicitly requested.

## Recovery and reproducibility

The downloaded collection snapshot was 181,550,080 bytes (about 173 MiB) and matched the server's SHA-256 and size. It restored into a new collection without changing `trials_v1`. A separate collection was rebuilt directly from the saved dense artifact without using the snapshot or reading the original collection. Both recovered all vectors, raw demographic evidence, source provenance, five payload indexes, and HNSW readiness.

After restarting the native server, the original, restored, and rebuilt collections each passed 100 direct-matrix search comparisons across all 50 synthetic topics and both filters. Re-encoding all 443 saved source representations in batches of 16 differed from the saved vectors by at most `8.95e-8`, below the `1e-6` tolerance. This checks the path from versioned rendered source text through the pinned encoder to the database, not just snapshot copying.

A separate one-repetition ANN check on the rebuilt graph retained 1.000 mean/minimum recall at effort 128 in both filter modes. At lower efforts its filtered mean recall was 0.948 (effort 10) and 0.992 (effort 32), compared with 0.958/0.994 on the original graph. This variation is why a rebuild requires reevaluation rather than assuming graph-byte or approximate-ranking identity. Its shorter timing run is a recovery diagnostic, not a comparative performance experiment.

## Failure handling and limitations

Tests cover unbuilt/failed graph readiness, invalid parameters, scan/concurrent-query telemetry, duplicate or invalid results, malformed/truncated/corrupt backups, existing-target protection, source-vector drift, and separate immutable progress/final reports. A server validation error during development established that `full_scan_threshold=0` is unsupported in 1.19.0; the implemented profile uses the supported minimum of 10. A recovery-report overwrite attempt was corrected by giving progress and final state separate files, with regression tests.

All data remain public trials and synthetic topics. No patient–criterion assessments, new medical judgments, or eligibility probabilities were generated. Missing demographics are retained rather than treated as satisfying criteria. The small judged pool, sequential local timing, lack of concurrency testing, graph variability, and lack of full-corpus dense evaluation limit generalization. Snapshots reside on the same machine and are not off-device disaster protection. Docker configuration was validated, but container execution was not tested on this machine because Docker is absent.

The collection/repository and evidence contract can support subsequent hybrid retrieval. The next retrieval comparison must keep branch scores distinct and use a defined fusion method; these ANN results do not establish that hybrid retrieval improves relevance.

See [the operating guide](../local-vector-storage.md) for reproducible commands and [ADR 0006](../architecture/decisions/0006-measured-ann-and-isolated-recovery.md) for design and API references.

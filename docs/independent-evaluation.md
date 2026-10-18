# Independent evaluation workflow

This extension evaluates the frozen retrieval configurations on TREC 2021 synthetic
cases using external TREC relevance judgments. The original 50 TREC 2022 cases remain
development evidence. See [ADR 0017](architecture/decisions/0017-independent-trec2021-evaluation.md)
for the protocol and [the experiment report](experiments/0012-independent-trec2021-evaluation.md)
for execution results.

## What it evaluates

The primary question is whether the existing exact dense method improves nDCG@10 over
matched title/condition BM25 on a separate externally judged case set. Hybrid and fixed
reranking depths 10/20 are secondary exploratory comparisons. Every method uses the same
legacy age/sex policy and the full 375,580-trial corpus. Neither the app's 443-trial search
universe nor its curated case catalog is expanded.

These are historical relevance judgments. Source grade-2/grade-1 recall is not clinical
screening accuracy. Independent criterion judgments and clinical validation remain unmet.
No judgment is authored by the assistant or inferred from model output.

## Prerequisites

Run from the nested Git repository, with the existing research environment activated.
The [release guide](research-release.md) prepares the verified full render, sharded exact
index and pinned MiniLM/reranker model files. No PostgreSQL, Qdrant or frontend process
is required for this offline workflow. It needs the same encoder runtime as the saved
index. Use the existing environment rather than upgrading dependencies in place.

The original run uses `evaluation/reports/independent-trec2021-v2` and raw sources at
`data/raw/independent-trec2021-v1`. The earlier `independent-trec2021-v1` report folder
contains an unused freeze before a formatting-only correction; no 2021 data or labels
were acquired under that first freeze. Both records remain intact for audit.

## Original-run inspection (safe to repeat)

```powershell
python -m evaluation.independent verify --study evaluation/reports/independent-trec2021-v2
python -m pytest evaluation/tests/test_independent.py -p no:cacheprovider
```

Expect `status: verified`, 75 topics and five systems. Inspect these local files:

| File | Expected evidence |
|---|---|
| `protocol.json` and `protocol.sha256` | Frozen configuration, input/code/model identity, runtime and primary comparison |
| `overlap-audit.json` | Every new topic's nearest 2022 lexical overlap and the predeclared rejection gate |
| `seal.json` | Ranking files sealed before judgment acquisition |
| `ranked/rankings.json` | Every system/topic, raw scores, fusion branches, original ranks and reranker inputs |
| `ranked/*.run` | Depth-100 runs preserving sealed order with rank-surrogate scores |
| `ranked/query-audit.json` | Dense query token counts and truncation flags |
| `evaluation.json` and `evaluation.sha256` | All aggregate/per-topic metrics, paired intervals and judgment coverage |
| `data/raw/independent-trec2021-v1/topics/` | Immutable public synthetic-topic bytes and HTTP metadata |
| `data/raw/independent-trec2021-v1/qrels/` | External label bytes and acquisition metadata, acquired after the seal |

Changed implementation/runtime, frozen manifests or development-topic bytes fail verification.
The ranking stage additionally verifies the full shard/render contents and local model weights.
Intentional future
changes need a separately identified study; do not overwrite old protocols or relabel
reruns as new unseen-case validation. SHA256 identifies bytes, not an authenticated author.

## Reproduce into fresh destinations

Only acquisition stages use the network. Do not acquire the judgments before ranking.
Use new destinations for each attempt, including after an interrupted partial run:

```powershell
$study = 'evaluation/reports/independent-reproduction-01'
python -m evaluation.independent freeze --study $study --sources data/raw/independent-reproduction-01
python -m evaluation.independent acquire-topics --study $study
python -m evaluation.independent rank --study $study
python -m evaluation.independent acquire-qrels --study $study
python -m evaluation.independent score --study $study
python -m evaluation.independent verify --study $study
```

Stop on a failing stage. Ranking refuses a source root that already contains judgments.
Acquiring labels without an intact ranking seal fails. Frozen code/runtime changes,
invalid source records, topic omissions and missing corpus judgments are errors. Completed
rankings and evaluations cannot be overwritten. Partial attempts remain inspectable;
there is no ranking-stage resume or automatic retry that consumes partial results.

The source snapshots include source URL, download time, HTTP status, byte length and
checksum. The 2021 loader is isolated from the application's 2022-only case loader and
does not add an arbitrary patient-text input route.

## Manual checks

1. Run the original-run verification above and confirm 75 topics and five systems.
2. Open `protocol.json`, `seal.json` and the qrels `manifest.json`. Confirm freeze time
   precedes the ranking seal, which precedes qrels acquisition. Check the source URLs
   against the [official NIST page](https://trec.nist.gov/data/trials2021.html).
3. Inspect `evaluation.json`: dense versus BM25 must be the primary comparison;
   hybrid and both rerank depths must be labelled exploratory secondary contrasts.
4. Inspect a topic in `ranked/rankings.json`. Raw cosine, fusion and reranker scores
   remain separate. Compare its trial order with the corresponding run file; do not
   treat run-file rank surrogates as model scores or eligibility probabilities.
5. Run the fixture tests. They exercise tampered evidence, missing topic coverage,
   duplicate data, changed runtime/code and negative results without editing the real study.

The evaluation runs offline; there is no new web-page control to test. After viewing
these results, do not tune the methods on 2021 and claim another run is still held out.

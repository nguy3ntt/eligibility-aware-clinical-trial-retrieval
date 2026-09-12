# Themis Trial

**Explainable, eligibility-aware clinical-trial retrieval for synthetic patient profiles.**

This research and portfolio project retrieves clinical trials for a synthetic patient description and then distinguishes among:

- medically relevant trials for which the patient appears potentially eligible;
- medically relevant trials containing a likely exclusion;
- trials where the available patient information is insufficient; and
- trials that are not relevant.

The project combines classical information retrieval, dense embeddings, a vector database, structured filtering, reranking, criterion-level verification, and rigorous evaluation. It is deliberately not a generic “chat with medical documents” application.

> [!IMPORTANT]
> This is an educational research prototype. It must use public trial information and synthetic patient cases only. It must never claim to determine clinical eligibility, recommend treatment, diagnose a patient, or replace review by qualified professionals.

## See the project

[![Themis Trial academic portfolio interface in dark mode](docs/assets/showcase/about-dark.png)](docs/showcase.md)

**[Project showcase and guided demo](docs/showcase.md)** ·
**[Download the recorded walkthrough (WebM)](docs/assets/showcase/themis-trial-demo.webm)** ·
**[Run the local workspace](docs/research-workspace.md)**

An end-to-end academic portfolio demonstrating information retrieval, evidence-preserving
data engineering, honest ML evaluation and a React/FastAPI research interface.
The recording uses the real local services and synthetic cases; saved operations are
labelled as historical replay. It is not a public clinical service.

| Scope | What was built and evaluated |
|---|---|
| Offline benchmark | 375,580 frozen public trials, 50 synthetic topics, 35,394 relevance judgments |
| Interactive demonstration | Separate 443-trial search index; catalog includes three additional invented trials and 51 synthetic cases |
| Engineering | BM25, exact dense search, HNSW diagnostics, RRF, optional reranking, criterion evidence, durable operation replay |
| Research boundary | No held-out or clinical validation; learned screening outputs remain advisory |

## Central research question

> Can an eligibility-aware hybrid retrieval system distinguish genuinely eligible trials from trials that are medically relevant but exclude the patient?

## Why the problem is difficult

A search system can retrieve a trial because its condition resembles the patient’s condition while overlooking that:

- the patient is outside the permitted age range;
- a previous treatment is prohibited;
- a comorbidity violates an exclusion criterion;
- a required laboratory result is missing;
- the trial is not recruiting in an appropriate location; or
- the eligibility language is ambiguous.

The system therefore separates **relevance retrieval** from **eligibility assessment**. Similarity is used to find candidates; it is not treated as proof of eligibility.

## Implemented research capabilities

| Capability | Purpose |
|---|---|
| BM25 retrieval | Strong exact-term and lexical baseline |
| Dense retrieval | Exact MiniLM matching; separate biomedical-model diagnostic |
| Qdrant HNSW search | Approximate retrieval checked against exact neighbors on the bounded diagnostic |
| Hybrid retrieval | Fuse lexical and semantic rankings |
| Metadata filtering | Apply age, sex, status, phase, country, and other structured constraints |
| Reranking | Measure optional cross-encoder reordering, including negative results |
| Patient fact extraction | Structure age, conditions, medications, treatments, and measurements |
| Eligibility parsing | Split inclusion and exclusion text into atomic criteria |
| Criterion verification | Label individual criteria as satisfied, violated, unknown, or not applicable |
| Evidence explanations | Link every assessment to exact source text and patient facts |
| Retrieval laboratory | Compare methods, ablations, latency, and ANN recall |

The [full-corpus experiment](docs/experiments/0011-full-corpus-release-and-hardening.md)
evaluates 375,580 frozen trials against all 50 synthetic TREC 2022 cases. With age/sex
filtering, matched title/condition BM25 scores 0.2156 nDCG@10, dense 0.3471, hybrid 0.3487
and hybrid plus rerank-20 0.3689. The hybrid/reranking intervals include zero, the topics
are not held out, and all 150 displayed screening pairs remain insufficient information.
The [release guide](docs/research-release.md) covers reproducibility, incremental registry
updates, index migration/recovery, CI and a repeatable portfolio recording.

## Data sources

- **[ClinicalTrials.gov API v2](https://clinicaltrials.gov/data-api/api)** for public clinical-trial records.
- **[TREC Clinical Trials 2021/2022](https://trec.nist.gov/data/trials2022.html)** for synthetic patient topics and relevance judgments.
- **[Synthea](https://synthetichealth.github.io/synthea/)** as an optional later source of synthetic FHIR patient records.

No real patient records belong in this repository.

## Architecture

```mermaid
flowchart TD
    A["ClinicalTrials.gov and TREC"] --> B["Ingestion and normalization"]
    B --> C["PostgreSQL metadata"]
    B --> D["Dense and sparse indexing"]
    D --> E["Qdrant"]
    F["Synthetic patient profile"] --> G["Fact extraction"]
    C --> H["Hybrid retrieval"]
    E --> H
    G --> H
    H --> I["Eligibility verifier"]
    I --> J["FastAPI and React"]
    H --> K["Evaluation framework"]
```

## Repository map

| Path | Responsibility |
|---|---|
| `backend/` | FastAPI application, persistence interfaces, retrieval orchestration, and screening services |
| `pipelines/` | Source connectors, normalization, criterion parsing, embedding, and indexing |
| `evaluation/` | BM25/dense baselines, TREC evaluation, ablations, significance tests, and reports |
| `frontend/` | Local React/TypeScript search, evidence review, retrieval comparisons and saved experiments |
| `infrastructure/` | Docker Compose, container configuration, and later monitoring |
| `data/` | Local-only raw/interim/processed data boundaries; large data are Git-ignored |
| `notebooks/` | Exploration only; production logic must live in Python modules |
| `docs/` | Architecture, data contracts, evaluation, safety, experiments, and decisions |
| `scripts/` | Reproducible command wrappers |

See [docs/architecture/README.md](docs/architecture/README.md) for component boundaries.

## Current implementation

The [browser research workspace](docs/research-workspace.md) supports curated synthetic-case selection, read-only fact review, retrieval and trial/criterion source inspection. Its eligibility evidence panel connects every criterion outcome to exact synthetic facts and missing information; optional NLI advice remains visibly separate. A retrieval laboratory compares explicit configurations against the unchanged dense baseline, and an experiment dashboard reopens persisted operations and historical reports. Open it locally on port 5173 after starting the services. No real-patient input or clinical decisions are introduced.

The repository includes a bounded local FastAPI application with PostgreSQL evidence persistence, source inspection and historical corpus validation, reproducible full-corpus BM25/dense/hybrid evaluation, and a separate bounded interactive search index. Local Qdrant supports verified imports, exact/ANN search, measured neighbor recall and latency, and checked snapshot/restore/rebuild procedures. Held-out validation and clinical validation remain unmet.

The [local API guide](docs/local-research-api.md) provides startup and manual tests for 51 curated synthetic cases and 446 public/invented trials. Search, criterion screening, source lookup and saved experiments retain evidence and version identities. Defaults remain exact dense plus legacy age/sex filters; reranking is opt-in and learned screening advisories are never promoted. Results survive restarts in PostgreSQL and can be reviewed in the browser. See the [integration report](docs/experiments/0010-local-api-and-postgres-integration.md).

The bounded inspection retrieved **500 public trial records**, loaded **50 synthetic TREC 2022 topics and 35,394 judgments**, produced field profiles and complete selected-ID traces, and manually inspected ten topic–trial pairs for source consistency. Raw downloads and generated reports remain local and Git-ignored.

Read the [inspection results](docs/experiments/0001-bounded-data-inspection.md), the [BM25 baseline report](docs/experiments/0002-bm25-baseline.md), and the [reproduction guide](pipelines/README.md). The [canonical schema proposal](docs/data-model.md) now reflects observed missing fields, age units, partial dates, and multi-valued phases.

The BM25 metrics use the separately downloaded and validated April 27, 2021 corpus. Current API records remain unsuitable for benchmark scoring. TREC grades are source relevance labels, not current medical eligibility decisions.

The [dense workflow guide](evaluation/README.md#bounded-dense-retrieval) explains model preparation, sample encoding, offline synthetic-topic search, and real-model checks. Its [reviewed smoke-test report](docs/experiments/0003-bounded-dense-smoke.md) reports operational correctness, resource measurements, and truncation limitations without claiming superiority over BM25.

The [Qdrant diagnostic](docs/experiments/0004-bounded-qdrant-ann-recovery.md) records actual HNSW graph use, exact-versus-ANN neighbor recall and latency, snapshot recovery, and artifact-only rebuilding. Higher effort recovered all exact neighbors on the small pool, but the experiment did not demonstrate a meaningful speed advantage or full-corpus retrieval quality.

The [hybrid workflow](docs/hybrid-retrieval.md) adds versioned BM25 sparse vectors, identical dense/sparse filters, and Reciprocal Rank Fusion with branch scores and evidence. Its [controlled ablation](docs/experiments/0005-bounded-hybrid-ablation.md) improves top-100 recall but reduces average top-10 quality versus dense. Exact dense with age/sex filtering remains the command-line default; hybrid is an explicit research option. The later API and initial browser workspace reuse these services without changing their diagnostic limits.

The [synthetic fact workflow](docs/patient-facts.md) extracts bounded age, sex, condition, medication, treatment, and measurement mentions with exact source spans, negation, uncertainty, history, and experiencer context. It builds auditable age/sex filter plans and exposes unsupported content. [Development evaluation](docs/experiments/0006-synthetic-patient-facts.md) checks authored examples and audits all 50 synthetic topics without claiming general clinical accuracy. Profile-based search is explicitly opt-in; previous retrieval experiments retain their original extractor.

The [eligibility parsing workflow](docs/eligibility-parsing.md) preserves trial-side source wording, sections, clause order and evidence, with bounded deterministic type/numeric rules and explicit review flags. A separate small criterion collection supports dense and sparse similarity inspection. [Development and storage checks](docs/experiments/0007-bounded-eligibility-parsing.md) report exact authored-example results and honest historical coverage limits. This adds no patient eligibility decisions and does not change retrieval defaults.

The [research screening workflow](docs/eligibility-verification.md) connects synthetic facts to complete supported criteria, preserves evidence and reports blockers, unknowns and missing information. An optional local NLI model supplies separately labelled, non-promoted advisories. [Evaluation](docs/experiments/0008-bounded-screening-and-semantic-verification.md) reports successful authored rule checks, limited historical coverage and semantic confidence failures. No confirmed eligibility, automatic semantic screening or retrieval-default change is introduced.

The [reranking and explanation workflow](docs/reranking-and-explanations.md) optionally reorders a bounded exact-dense candidate prefix with a pinned local relevance model. It preserves original rankings, exposes shortened model inputs, and links fixed explanation statements to source fields and validated screening evidence. The [quality/latency experiment](docs/experiments/0009-bounded-reranking-and-explanations.md) compares fixed depths on the existing diagnostic pool. That diagnostic introduced no default promotion or eligibility-score fusion; later API/UI work preserves those limits.

## Local requirements

The reproducible research environment uses:

- Python 3.12 (observed 3.12.14; use a short virtual-environment path on Windows)
- PostgreSQL 17 and Qdrant 1.19.0 for the local application
- Docker with Compose, or the documented native Windows services
- Node.js 24.16+ and npm for the local frontend

No paid service or GPU is required.

## Quick start

```bash
cp .env.example .env
python -m venv .venv
```

Activate the environment, then install the lightweight engineering/test dependencies:

```bash
pip install -r requirements/ci.txt
pytest
```

This verifies invented fixtures without downloading models or the corpus. For the complete
app, follow [API preparation](docs/local-research-api.md) and the
[browser walkthrough](docs/research-workspace.md). The full offline experiment uses
`requirements/research.txt` and the [release preparation steps](docs/research-release.md).
Starting an empty database alone does not install the curated catalog or vectors.

Start the local databases only when working on features that use them:

```bash
docker compose -f infrastructure/compose.yaml up -d
```

Run the local API:

```bash
uvicorn backend.app.main:app --host 127.0.0.1 --no-access-log
```

Then open `http://localhost:8000/health` or the generated API documentation at `http://localhost:8000/docs`.

## Engineering principles

1. Establish BM25 before adding dense retrieval.
2. Compare exact search with approximate search before tuning HNSW.
3. Treat relevant, eligible, excluded, and unknown as different states.
4. Preserve source provenance for every transformed record and explanation.
5. Version embeddings, parsers, models, and experiments.
6. Make uncertain information visible rather than silently guessing.
7. Measure improvements using qrels, metrics, ablations, and error analysis.
8. Add scale only after correctness and reproducibility are established.

## Documentation

- [Architecture](docs/architecture/README.md)
- [Data model](docs/data-model.md)
- [Evaluation protocol](docs/evaluation.md)
- [Safety and limitations](docs/safety.md)
- [Local vector storage and exact-search checks](docs/local-vector-storage.md)
- [Contribution workflow](CONTRIBUTING.md)

## Licence

The code scaffold is provided under the MIT License. External datasets, model weights, and terminology resources retain their own licences and usage requirements.

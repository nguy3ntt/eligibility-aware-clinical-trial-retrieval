export function About() {
  return (
    <section className="about-page" aria-label="About Themis Trial">
      <div className="panel about-intro">
        <p className="eyebrow">THEMIS TRIAL · ACADEMIC PORTFOLIO</p>
        <h2>Retrieval with evidence. Conclusions with restraint.</h2>
        <p className="about-lead">
          Themis Trial is an academic portfolio and research demonstration
          exploring how clinical-trial search can remain explainable,
          reproducible and honest about uncertainty. It connects public trial
          records with synthetic patient cases, while keeping retrieval
          relevance separate from eligibility screening.
        </p>
        <p>
          Built to demonstrate applied information retrieval, machine learning
          evaluation and full-stack engineering, the project follows the
          evidence from immutable source data to indexed retrieval,
          criterion-level explanations and a reviewable interface. A similar
          document is a research lead—not a clinical decision.
        </p>
        <div className="about-links">
          <a
            href="https://github.com/nguy3ntt"
            target="_blank"
            rel="noopener noreferrer"
          >
            GitHub profile · @nguy3ntt ↗
          </a>
          <a
            href="https://github.com/nguy3ntt/eligibility-aware-clinical-trial-retrieval"
            target="_blank"
            rel="noopener noreferrer"
          >
            Explore the source code ↗
          </a>
        </div>
      </div>
      <div className="about-grid">
        <section className="panel">
          <p className="eyebrow">01 / RETRIEVAL</p>
          <h2>Compare methods, not incomparable scores.</h2>
          <p>
            BM25, exact dense retrieval, HNSW and reciprocal-rank fusion are
            evaluated with explicit baselines. Optional cross-encoder reranking
            preserves the original scores and candidate ranks.
          </p>
        </section>
        <section className="panel">
          <p className="eyebrow">02 / EVIDENCE</p>
          <h2>Keep every conclusion traceable.</h2>
          <p>
            Deterministic fact extraction and criterion screening retain source
            spans, context and missing information. Learned NLI suggestions
            remain separate, explicitly labelled and never promoted to
            eligibility decisions.
          </p>
        </section>
        <section className="panel">
          <p className="eyebrow">03 / ENGINEERING</p>
          <h2>Build for reproducible review.</h2>
          <p>
            Versioned FastAPI contracts, PostgreSQL evidence, Qdrant indexes and
            a React/TypeScript workspace are supported by regression tests,
            resumable ingestion, integrity checks and verified recovery
            procedures.
          </p>
        </section>
        <section className="panel">
          <p className="eyebrow">04 / RESEARCH INTEGRITY</p>
          <h2>Report the limits as carefully as the results.</h2>
          <p>
            The offline benchmark covers 375,580 frozen trials and 50 previously
            inspected synthetic topics. The interactive demo uses a separate
            bounded catalog. Full-corpus evaluation is not held-out or clinical
            validation; all 150 benchmark screening explanations remain
            insufficient information.
          </p>
        </section>
      </div>
      <div className="notice">
        <strong>Demonstration of skills—not a clinical service.</strong>
        This application is intended for academic assessment, portfolio review
        and technical exploration. It accepts no real patient records and must
        not be used to determine eligibility, diagnose conditions or recommend
        treatment. All potential matches require professional review. No public
        deployment or production clinical readiness is claimed.
      </div>
    </section>
  );
}

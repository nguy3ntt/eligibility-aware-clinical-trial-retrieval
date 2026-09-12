# 0016 — Themis Trial presentation and source highlights

Date: 2026-09-12. Status: accepted for the user-requested presentation extension.

## Context

The twelve engineering milestones are complete. The user requested a project name,
dark mode, an academic portfolio About page with GitHub links, emphasized result-title
phrases and hover statistics. These changes must preserve the distinction between
retrieval relevance and screening evidence.

## Decision

Use **Themis Trial** as the display/project name. Keep package IDs, Git remote,
database catalogs, artifact identifiers and historical reports unchanged.

Preserve the existing light theme and add a forest-ink dark palette across all shared
views and functional status colors. Follow the operating-system preference until an
explicit toggle choice. Persist only `light` or `dark` under `themis-trial-theme` in
local storage; never store cases, results or operation evidence. Blocked storage falls
back to an in-memory preference. No dependencies or network requests are added.

The About view is static and usable without the API. It presents the academic portfolio
purpose, demonstrated engineering skills, public/synthetic data boundaries and validation
limits. Profile/repository links use the owner of the existing Git remote, `nguy3ntt`;
they open only on explicit user navigation, with no analytics or remote embeds.

Title emphasis is a deterministic display aid: case-insensitive, whole Unicode word
overlap with the same result's normalized condition/intervention source fields.
Common generic words are excluded, adjacent matching words are grouped, and the original
title is preserved exactly. Missing fields yield no highlight. There is no stemming,
synonym expansion, diagnosis inference or claim to explain the embedding model's attention.
These are source-topic highlights, not evidence that a patient satisfies a criterion.

Result details show the already recorded base score and its method, rank/candidate count,
optional separate reranker logit/original rank, source topics and highlighted phrases.
Cosine, BM25 and RRF are not calibrated probabilities, so no invented “percentage match”
or normalized cross-method comparison is introduced. Hover previews can be pinned with
a button; keyboard and touch users can open/close the same content, Escape dismisses it,
and small screens use an inline panel. No extra inference or API request is performed.

## Consequences

The interface gains a professional identity and accessible presentation controls without
changing retrieval defaults, evidence packets, parser/model versions or benchmark results.
The original source text remains available; keyword highlighting is deliberately conservative
and may miss clinically related phrases that do not literally overlap. Historical release
recordings and source manifests retain their original identity and are not overwritten.

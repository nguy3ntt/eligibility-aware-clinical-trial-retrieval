# Reviewed portfolio media

These files are deliberately selected for public portfolio presentation. All are direct,
unretouched Chrome captures of Themis Trial running against the local API on 2026-09-13.
Only public historical trial records and synthetic or explicitly invented cases appear.
No real patient data, credentials, raw database exports or private planning is included.

| File | Content |
|---|---|
| `about-dark.png` | Academic purpose and GitHub links in the dark theme; README cover |
| `about-light.png` | The same About view in the light theme |
| `search-dark.png` | TREC synthetic case 29 and retrieved public trial records |
| `screening-dark.png` | Invented case/trial screening; insufficient information |
| `comparison-dark.png` | Baseline/candidate ranking comparison, with separate scores |
| `themis-trial-demo.webm` | Silent walkthrough: search, original source, screening, comparison, authored evaluation, About and themes |
| `manifest.json` | Capture specification identity, media byte sizes and SHA256 checksums |

The scene guide and research limitations are in [the showcase](../../showcase.md).
Saved Replay denotes historical evidence, not fresh model execution. Recorded timings
are not benchmark measurements. These images do not establish clinical validation.

To regenerate, follow [frontend verification](../../../frontend/README.md) and run the
opt-in `release-demo.spec.ts` against prepared services. Review the resulting ignored
`frontend/test-results/` files before copying a chosen selection here. Browser test runs
replace that generated directory. The video is the original Playwright WebM, without
an audio track; download and open it in a compatible browser/player.

The local allowlist ignores every other filename in this folder. Keep raw recordings,
test reports, data, models and private tracking in their existing ignored locations.
Do not widen those exclusions merely to publish a screenshot. Changing a selected asset
requires visual review and an updated manifest. Checksums identify bytes, not authorship.
The source trial content retains its original provenance and applicable usage terms;
these are demonstration captures, not a redistributed research dataset.

import { useId, useRef, useState } from "react";
import type { Search } from "../api/contracts";

type Result = Search["result"]["results"][number];
const generic = new Set(
  "a an the and or of in on for to with without by as at from study trial treatment therapy patients patient disease disorder clinical effects evaluation safety efficacy".split(
    " ",
  ),
);
const tokens = (value: string) => [...value.matchAll(/[\p{L}\p{N}]+/gu)];

// Literal source-field overlap only: no synonyms, diagnosis inference or model attribution.
export function titleSegments(title: string, source: string) {
  const terms = new Set(
    tokens(source)
      .map(([word]) => word.toLowerCase())
      .filter((word) => word.length >= 3 && !generic.has(word)),
  );
  const ranges: { start: number; end: number }[] = [];
  for (const match of tokens(title)) {
    if (!terms.has(match[0].toLowerCase())) continue;
    const start = match.index!;
    const last = ranges.at(-1);
    if (last && /^[\s-]*$/.test(title.slice(last.end, start)))
      last.end = start + match[0].length;
    else ranges.push({ start, end: start + match[0].length });
  }
  const parts: { text: string; highlighted: boolean }[] = [];
  let offset = 0;
  for (const range of ranges) {
    if (offset < range.start)
      parts.push({
        text: title.slice(offset, range.start),
        highlighted: false,
      });
    parts.push({
      text: title.slice(range.start, range.end),
      highlighted: true,
    });
    offset = range.end;
  }
  if (offset < title.length)
    parts.push({ text: title.slice(offset), highlighted: false });
  return parts;
}

export function sourceTopics(result: Result) {
  return [
    result.relevance.fields.conditions?.normalized,
    result.relevance.fields.interventions?.normalized,
  ]
    .filter((text): text is string => Boolean(text))
    .join(" · ");
}

export function HighlightedTitle({
  title,
  topics,
}: {
  title: string;
  topics: string;
}) {
  return (
    <>
      {titleSegments(title, topics).map((part, i) =>
        part.highlighted ? (
          <mark className="source-highlight" key={i}>
            {part.text}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </>
  );
}

export function ResultInsights({
  result,
  search,
  hovered,
  dismissHover,
}: {
  result: Result;
  search: Search;
  hovered: boolean;
  dismissHover: () => void;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const [pinned, setPinned] = useState(false);
  const open = hovered || pinned;
  const ranking = result.relevance.ranking;
  const topics = sourceTopics(result);
  const phrases = titleSegments(
    result.relevance.fields.brief_title?.normalized ?? "",
    topics,
  )
    .filter((p) => p.highlighted)
    .map((p) => p.text);
  const scoreName = {
    dense: "Cosine similarity",
    sparse: "BM25 score",
    hybrid: "RRF score",
  }[search.result.method];
  const close = () => {
    setPinned(false);
    dismissHover();
    trigger.current?.focus();
  };
  return (
    <div
      className="result-insights"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          close();
          event.stopPropagation();
        }
      }}
    >
      <button
        className="insight-trigger"
        ref={trigger}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => (pinned ? close() : setPinned(true))}
      >
        Result details <span aria-hidden="true">↗</span>
      </button>
      {open && (
        <div
          id={id}
          className="insight-panel"
          role="region"
          aria-label={`Result details for ${result.trial_id}`}
          onFocusCapture={() => setPinned(true)}
        >
          <div className="section-heading">
            <strong>Retrieval snapshot</strong>
            <button onClick={close} aria-label="Close result details">
              ×
            </button>
          </div>
          <dl className="insight-stats">
            <div>
              <dt>{scoreName}</dt>
              <dd>{ranking.score.toFixed(4)}</dd>
            </div>
            <div>
              <dt>Result rank</dt>
              <dd>
                {ranking.rank} of {search.result.candidate_count} retrieved
                candidates
              </dd>
            </div>
            {ranking.reranker && (
              <div>
                <dt>Cross-encoder logit</dt>
                <dd>
                  {ranking.reranker.score.toFixed(4)} · original rank{" "}
                  {ranking.original_rank}
                </dd>
              </div>
            )}
          </dl>
          <p className="small">
            Raw retrieval scores are not calibrated match percentages or
            eligibility probabilities. Scores from different methods are not
            comparable.
          </p>
          <p className="small">
            <strong>Highlighted title phrases</strong>
            <br />
            {phrases.length
              ? phrases.join(" · ")
              : "No literal title overlap with source topics."}
          </p>
          <details>
            <summary>Related source topics</summary>
            <p className="preserve small">
              {topics || "No condition or intervention text supplied."}
            </p>
          </details>
          <p className="small muted">
            Highlights mark literal words shared with the trial’s
            condition/intervention fields, not matching patient facts or an
            explanation of model attention.{" "}
            {search.replayed
              ? "Historical saved replay."
              : "Saved computed operation."}
          </p>
        </div>
      )}
    </div>
  );
}

"""Explicit whole-clause age grammar; no subject guessing or unit conversion."""

import math
import re
from dataclasses import dataclass

LABEL = r"(?:age[sd]?|adults?|patients?|participants?|subjects?|child|children)\s*:?\s*"
NUMBER = r"\d+(?:\.\d+)?"
UNIT = r"years?|months?|weeks?|days?"
OP = r">=|<=|≥|≤|>|<|above|over|under|below|at least|at most|more than|less than"
OPERATORS = {
    ">=": "ge",
    "≥": "ge",
    "at least": "ge",
    ">": "gt",
    "above": "gt",
    "over": "gt",
    "more than": "gt",
    "<=": "le",
    "≤": "le",
    "at most": "le",
    "<": "lt",
    "under": "lt",
    "below": "lt",
    "less than": "lt",
}


@dataclass(frozen=True)
class AgePredicate:
    unit: str
    lower: float | None = None
    upper: float | None = None
    lower_closed: bool = True
    upper_closed: bool = True

    def accepts(self, value: float) -> bool:
        lower = self.lower is None or (
            value >= self.lower if self.lower_closed else value > self.lower
        )
        upper = self.upper is None or (
            value <= self.upper if self.upper_closed else value < self.upper
        )
        return lower and upper


def whole_age(text: str) -> AgePredicate | None:
    """Every word must match; bare durations such as '> 18 years' stay unsupported."""
    text = re.sub(r"\s+", " ", text.strip()).casefold()
    if text.endswith((".", ",")):
        text = text[:-1].rstrip()
    patterns = (
        (
            "range",
            rf"{LABEL}(?P<lo>>=|≥|>)?\s*(?P<a>{NUMBER})\s*(?:-|–|to)\s*"
            rf"(?P<hi><=|≤|<)?\s*(?P<b>{NUMBER})\s*(?P<unit>{UNIT})(?: old| of age)?",
        ),
        (
            "range",
            rf"{LABEL}(?P<lo>>=|≥|>)\s*(?P<a>{NUMBER})\s+and\s+"
            rf"(?P<hi><=|≤|<)\s*(?P<b>{NUMBER})\s*(?P<unit>{UNIT})(?: old| of age)?",
        ),
        (
            "older",
            rf"(?P<label>{LABEL})?(?P<a>{NUMBER})\s*(?P<unit>{UNIT})"
            r"(?P<suffix> of age| old)?\s+(?:or|and)\s+(?P<direction>older|younger)",
        ),
        (
            "single",
            rf"(?P<label>{LABEL})?(?P<op>{OP})\s*(?P<a>{NUMBER})\s*"
            rf"(?P<unit>{UNIT})(?P<suffix> of age| old)?",
        ),
    )
    for kind, pattern in patterns:
        match = re.fullmatch(pattern, text)
        if match is None:
            continue
        groups = match.groupdict()
        if kind != "range" and not (groups["label"] or groups["suffix"]):
            return None
        a = float(groups["a"])
        b = float(groups["b"]) if kind == "range" else None
        if not math.isfinite(a) or (b is not None and (not math.isfinite(b) or b < a)):
            return None
        unit = groups["unit"].rstrip("s")
        if kind == "range":
            lo, hi = groups["lo"] != ">", groups["hi"] != "<"
            if a == b and not (lo and hi):
                return None
            return AgePredicate(unit, a, b, lo, hi)
        op = (
            ("ge" if groups["direction"] == "older" else "le")
            if kind == "older"
            else OPERATORS[groups["op"]]
        )
        return (
            AgePredicate(unit, lower=a, lower_closed=op == "ge")
            if op in {"ge", "gt"}
            else AgePredicate(unit, upper=a, upper_closed=op == "le")
        )
    return None


def context_text(parsed) -> str:
    # Only a fully recognized age clause can shield 'or older/younger' from the
    # shared-alternative guard. Exceptions, other clauses and ancestry remain intact.
    text = list(parsed.source.text)
    for criterion in parsed.criteria:
        if whole_age(criterion.evidence.text) is not None:
            text[criterion.evidence.start : criterion.evidence.end] = " " * len(
                criterion.evidence.text
            )
    return "".join(text)

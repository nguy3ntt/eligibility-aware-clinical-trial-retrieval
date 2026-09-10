"""Versioned, lossless section/list parsing; never an eligibility verdict."""

import json
import math
import re
from pathlib import Path

from backend.app.schemas.criteria import (
    Criterion,
    EligibilitySource,
    NumericConstraint,
    ParsedEligibility,
    Section,
)
from backend.app.schemas.patient import Span, text_hash

VERSION = "eligibility-parser-v1"
HEADER = re.compile(
    r"(?im)(?:(?<!\w)(inclusion|exclusion)\s+criteria\s*:"
    r"|^[ \t]*(inclusion|exclusion)(?:\s+criteria)?[ \t]*:?[ \t\r]*$)"
)
BULLET = re.compile(r"(?m)^(?P<indent>[ \t]*)(?:[-*•]|\d+[.)]|\([a-z0-9]+\)|[a-z][.)])\s+", re.I)
NEGATION = re.compile(r"\b(?:no|not|without|absence of|negative for|must not|never)\b", re.I)
NUMERIC = {
    "age": (r"age(?:d)?", r"years?|months?|weeks?|days?"),
    "hemoglobin": (r"ha?emoglobin|Hb", r"g/dL|g/L"),
    "hba1c": (r"HbA1c", r"%|mmol/mol"),
    "creatinine": (r"(?:serum\s+)?creatinine", r"mg/dL|[uµμ]mol/L"),
    "bmi": (r"BMI|body mass index", r"kg/m2|kg/m²"),
    "platelets": (r"platelets?|platelet count", r"/mm3|/mm³|x10\^9/L"),
}
TYPE_PATTERNS = {
    "age": r"\bage(?:d)?\b|\byears? old\b",
    "sex": r"\b(?:male|female|men|women|pregnan\w*|breast[- ]?feeding)\b",
    "condition": r"\b(?:diagnos\w*|disease|cancer|diabetes|asthma|infection|malignancy|"
    r"HIV|hepatitis|tuberculosis)\b",
    "medication": r"\b(?:medication|drug|prednisone|corticosteroids?|methotrexate|insulin|"
    r"warfarin|metformin)\b",
    "treatment": r"\b(?:chemotherapy|radiotherapy|surgery|surgical|dialysis|transplant\w*)\b",
    "measurement": r"\b(?:hemoglobin|haemoglobin|HbA1c|Hb|creatinine|BMI|platelets?|"
    r"laboratory|blood pressure)\b",
    "consent": r"\b(?:consent|assent)\b",
}
COMPARISON = (
    r"(?P<op>>=|<=|≥|≤|>|<|at least|at most|more than|less than|no more than|no less than|=)"
)
OPERATORS = {
    ">=": "ge",
    "≥": "ge",
    "at least": "ge",
    "no less than": "ge",
    ">": "gt",
    "more than": "gt",
    "<=": "le",
    "≤": "le",
    "at most": "le",
    "no more than": "le",
    "<": "lt",
    "less than": "lt",
    "=": "eq",
}


def parser_hash() -> str:
    return text_hash(Path(__file__).read_text(encoding="utf-8"))


def span(text, start, end):
    return Span(start=start, end=end, text=text[start:end])


def numeric_constraints(text: str, start: int, end: int):
    value_text = text[start:end]
    constraints, issues = [], []
    for name, (label, units) in NUMERIC.items():
        # Require an explicit label, numeric operator/range, and unit; no threshold guessing.
        base = rf"\b(?:{label})\b\s*(?:must be|of|:|is)?\s*"
        amount = r"(?P<value>\d+(?:\.\d+)?)"
        patterns = [
            base
            + r"(?:between\s+)?"
            + amount
            + r"\s*(?:-|–|to|and)\s*(?P<upper>\d+(?:\.\d+)?)\s*(?P<unit>"
            + units
            + r")(?!(?:[\w/^]|\s+per\b))",
            base
            + COMPARISON
            + r"\s*"
            + amount
            + r"\s*(?P<unit>"
            + units
            + r")(?!(?:[\w/^]|\s+per\b))",
        ]
        hits = []
        for pattern in patterns:
            for match in re.finditer(pattern, value_text, re.I):
                if any(match.start() < b and match.end() > a for a, b in hits):
                    continue
                hits.append((match.start(), match.end()))
                value = float(match["value"])
                upper = float(match["upper"]) if "upper" in match.groupdict() else None
                unit = (
                    match["unit"]
                    .lower()
                    .replace("µ", "u")
                    .replace("μ", "u")
                    .replace("²", "2")
                    .replace("³", "3")
                )
                if name == "age":
                    unit = unit.rstrip("s")
                else:
                    unit = {
                        "g/dl": "g/dL",
                        "g/l": "g/L",
                        "mg/dl": "mg/dL",
                        "umol/l": "umol/L",
                        "mmol/mol": "mmol/mol",
                        "x10^9/l": "x10^9/L",
                    }.get(unit, unit)
                if (
                    not math.isfinite(value)
                    or upper is not None
                    and (not math.isfinite(upper) or upper < value)
                ):
                    issues.append("invalid_numeric_constraint")
                    continue
                constraints.append(
                    NumericConstraint(
                        name=name,
                        operator="range" if upper is not None else OPERATORS[match["op"].lower()],
                        value=value,
                        upper=upper,
                        unit=unit,
                        evidence=span(text, start + match.start(), start + match.end()),
                    )
                )
        if (
            re.search(rf"\b(?:{label})\b", value_text, re.I)
            and re.search(r"\d", value_text)
            and not hits
        ):
            issues.append("unsupported_numeric_expression:" + name)
    return tuple(sorted(constraints, key=lambda c: c.evidence.start)), issues


def criterion_parts(text: str, start: int, end: int):
    body = text[start:end]
    markers = list(BULLET.finditer(body))
    if not markers:
        # Blank-line paragraphs are safe boundaries; ordinary wrapped lines are not.
        cuts = [start] + [start + m.end() for m in re.finditer(r"\r?\n[ \t]*\r?\n", body)] + [end]
        candidates = []
        for a, b in zip(cuts, cuts[1:], strict=False):
            if candidates and re.match(r"\s*(?:or|and|unless|except|however)\b", text[a:b], re.I):
                previous, _, indent = candidates.pop()
                candidates.append((previous, b, indent))
            else:
                candidates.append((a, b, 0))
    else:
        candidates = []
        if body[: markers[0].start()].strip():
            candidates.append((start, start + markers[0].start(), -1))
        for i, marker in enumerate(markers):
            finish = markers[i + 1].start() if i + 1 < len(markers) else len(body)
            candidates.append(
                (start + marker.end(), start + finish, len(marker["indent"].expandtabs(4)))
            )
    for a, b, indent in candidates:
        # Split semicolons only outside parentheses and before an explicit new subject.
        # A shared alternative/exception can govern both sides of a semicolon.
        shared_context = re.search(
            r"\b(?:or|unless|except|if|provided that|however)\b", text[a:b], re.I
        )
        cuts, depth = [a], 0
        for pos in range(a, b):
            if text[pos] == "(":
                depth += 1
            elif text[pos] == ")":
                depth = max(0, depth - 1)
            elif (
                text[pos] == ";"
                and depth == 0
                and not shared_context
                and re.match(
                    r"\s*(?:age|sex|hemoglobin|haemoglobin|HbA1c|creatinine|BMI|platelets|"
                    r"written consent)\b",
                    text[pos + 1 : b],
                    re.I,
                )
            ):
                cuts.append(pos + 1)
        cuts.append(b)
        for left, right in zip(cuts, cuts[1:], strict=False):
            while left < right and text[left].isspace():
                left += 1
            while right > left and (text[right - 1].isspace() or text[right - 1] == ";"):
                right -= 1
            if right > left:
                yield left, right, indent


def parse_eligibility(source: EligibilitySource) -> ParsedEligibility:
    source = EligibilitySource.model_validate(source.model_dump())
    text = source.text
    headers = list(HEADER.finditer(text))
    sections, criteria, issues = [], [], []
    starts = [(m.start(), m.end(), (m[1] or m[2]).lower()) for m in headers]
    if not starts or starts[0][0] > 0:
        starts.insert(0, (0, 0, "unknown"))
    fingerprint = parser_hash()
    for i, (start, body_start, label) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        if end == start:
            continue
        section = Section(
            ordinal=len(sections) + 1,
            label=label,
            evidence=span(text, start, end),
            body_start=body_start,
        )
        sections.append(section)
        stack = []
        for left, right, indent in criterion_parts(text, body_start, end):
            wording = text[left:right]
            while stack and stack[-1][0] >= indent:
                stack.pop()
            parent = stack[-1][1] if stack else None
            types = tuple(k for k, p in TYPE_PATTERNS.items() if re.search(p, wording, re.I)) or (
                "other",
            )
            conjunctions = {m[0].lower() for m in re.finditer(r"\b(?:and|or)\b", wording, re.I)}
            logic = "mixed" if len(conjunctions) > 1 else next(iter(conjunctions), "unspecified")
            constraints, numeric_issues = numeric_constraints(text, left, right)
            reasons = list(numeric_issues)
            if label == "unknown":
                reasons.append("unknown_section")
            if conjunctions:
                reasons.append("compound_logic_preserved")
            if re.search(r"\b(?:unless|except|if|provided that|however)\b", wording, re.I):
                reasons.append("conditional_or_exception")
            if parent:
                reasons.append("parent_context_required")
            if ";" in wording:
                reasons.append("unsplit_semicolon")
            if re.search(r"\.[ \t\r\n]+[A-Z]", wording):
                reasons.append("multiple_sentences_preserved")
            if wording.endswith(":"):
                reasons.append("group_heading")
            if re.search(r"\r?\n[ \t]*\r?\n", wording):
                reasons.append("multiple_paragraphs_preserved")
            if re.search(r"(?m)\n[ \t]*[^\r\n]+:[ \t\r]*$", wording):
                reasons.append("embedded_heading_requires_review")
            if wording.strip(" .;").lower() in {"none", "n/a", "not applicable", "not specified"}:
                reasons.append("placeholder_statement")
            if types == ("other",):
                reasons.append("unclassified_type")
            if wording.count("(") != wording.count(")"):
                reasons.append("unbalanced_parentheses")
            identity = text_hash(
                json.dumps(
                    [
                        source.trial_id,
                        source.source_sha256,
                        source.source_locator,
                        text_hash(text),
                        fingerprint,
                        left,
                        right,
                    ]
                )
            )
            criteria.append(
                Criterion(
                    criterion_id=identity,
                    ordinal=len(criteria) + 1,
                    section_ordinal=section.ordinal,
                    section=label,
                    parent_id=parent,
                    evidence=span(text, left, right),
                    types=types,
                    logic=logic,
                    negation_cues=tuple(
                        span(text, left + m.start(), left + m.end())
                        for m in NEGATION.finditer(wording)
                    ),
                    constraints=constraints,
                    review_reasons=tuple(dict.fromkeys(reasons)),
                )
            )
            stack.append((indent, identity))
    if not text.strip():
        issues.append("empty_eligibility_text")
    if not headers:
        issues.append("no_recognized_section_headers")
    for label in ("inclusion", "exclusion"):
        if sum(s.label == label for s in sections) > 1:
            issues.append("repeated_" + label + "_sections")
    return ParsedEligibility(
        parser_version=VERSION,
        parser_sha256=fingerprint,
        source=source,
        text_sha256=text_hash(text),
        sections=tuple(sections),
        criteria=tuple(criteria),
        issues=tuple(issues),
    )

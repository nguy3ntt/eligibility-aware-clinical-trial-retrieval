"""Bounded deterministic mention extraction with original Python-character offsets."""

import json
import math
import re
from pathlib import Path

from backend.app.schemas.patient import (
    KINDS,
    Fact,
    Issue,
    PatientProfile,
    Span,
    SyntheticCase,
    text_hash,
)
from backend.app.services.patient_extraction import rules

FLAGS = re.IGNORECASE
AGE = re.compile(
    r"\b(?P<value>\d{1,3}(?:\.\d+)?)\s*[- ]?(?P<unit>year|month|week|day)s?\s*[- ]?old\b", FLAGS
)
COMPACT = re.compile(r"\b(?P<value>\d{1,3})(?P<sex>[MF])\b")
SEX = re.compile(r"\b(?:female|male|woman|man|girl|boy|lady|gentleman)\b", FLAGS)
QUANTITY = r"(?P<op>>=|<=|≥|≤|>|<|~|about\s+|approximately\s+)?\s*(?P<value>-?\d+(?:\.\d+)?)"
OPERATORS = {
    ">=": "ge",
    "<=": "le",
    "≥": "ge",
    "≤": "le",
    ">": "gt",
    "<": "lt",
    "~": "approx",
    "about": "approx",
    "approximately": "approx",
    "": "eq",
}
BOUNDARY = re.compile(
    r"(?<!\d)\.|\.(?!\d)|[!?;\n]|\b(?:but|however|whereas)\b"
    r"|,?\s+and\s+(?=(?:the patient|he|she)\b)",
    FLAGS,
)


def rules_hash() -> str:
    paths = [Path(__file__), Path(rules.__file__)]
    return text_hash("\n".join(text_hash(p.read_text(encoding="utf-8")) for p in paths))


def span(text: str, start: int, end: int) -> Span:
    return Span(start=start, end=end, text=text[start:end])


def clauses(text: str):
    start = 0
    for match in BOUNDARY.finditer(text):
        if text[start : match.start()].strip():
            yield span(text, start, match.start())
        start = match.end()
    if text[start:].strip():
        yield span(text, start, len(text))


def context_attributes(context: Span, start: int, end: int) -> dict:
    before = context.text[: start - context.start]
    after = context.text[end - context.start :]
    # New explicit patient subjects reset a preceding relative's context.
    patient = list(re.finditer(rules.PATIENT, before, FLAGS))
    family = list(re.finditer(rules.FAMILY, before, FLAGS))
    experiencer = "patient"
    if family and (not patient or family[-1].start() > patient[-1].start()):
        experiencer = "family"
    if re.match(r"\s+(?:mother|father|sister|brother|daughter|son|friend)\b", after, FLAGS):
        experiencer = "family" if not re.match(r"\s+friend\b", after, FLAGS) else "other"
    other = list(
        re.finditer(
            r"\b(?:friends?|neighbors?|neighbours?|spouse|husband|wife|partners?)\b", before, FLAGS
        )
    )
    if (other and (not patient or other[-1].start() > patient[-1].start())) or re.match(
        r"\s+partners?\b", after, FLAGS
    ):
        experiencer = "other"
    if patient:
        before = before[patient[-1].start() :]
    predicates = list(
        re.finditer(
            r"(?:,\s*|\band\s+)(?=(?:has|takes|receives|denies|reports|underwent|currently)\b)",
            before,
            FLAGS,
        )
    )
    if predicates:
        before = before[predicates[-1].end() :]
    before = re.sub(r"\bnot only\b", "", before, flags=FLAGS)
    uncertain = bool(re.search(rules.UNCERTAIN, before, FLAGS))
    uncertain |= bool(re.match(r"\s+(?:is\s+)?(?:possible|suspected|uncertain)\b", after, FLAGS))
    negative = bool(re.search(rules.NEGATION, before, FLAGS))
    negative |= bool(re.match(r"\s+(?:is\s+|was\s+)?(?:absent|ruled out|negative)\b", after, FLAGS))
    assertion = "uncertain" if uncertain else "absent" if negative else "present"
    temporal = "current"
    if re.search(rules.HISTORICAL, before, FLAGS) or re.match(
        r"\s+(?:\d+\s+\w+\s+ago|in\s+\d{4}|resolved|was stopped|was discontinued)\b", after, FLAGS
    ):
        temporal = "historical"
    if re.search(rules.PLANNED, before, FLAGS):
        temporal = "planned"
    if re.match(r"\s+(?:is\s+)?(?:planned|scheduled|considered|recommended)\b", after, FLAGS):
        temporal = "planned"
    return {
        "assertion": assertion,
        "certainty": "uncertain" if uncertain else "asserted",
        "temporality": temporal,
        "experiencer": experiencer,
    }


def extract_profile(case: SyntheticCase) -> PatientProfile:
    # Revalidate instances too: callers cannot bypass the synthetic flag via model_construct.
    case = SyntheticCase.model_validate(case.model_dump())
    text = case.text
    fingerprint = rules_hash()
    facts, issues = [], []

    def add(kind, name, value, unit, context, start, end, rule_id, operator="eq"):
        attributes = context_attributes(context, start, end)
        if kind in {"age", "sex"}:
            prefix = text[context.start : start]
            presentation = bool(
                re.match(r"\s*(?:the\s+)?patient is\s+(?:a\s+|an\s+)?\d", context.text, FLAGS)
            )
            opening = (context.start <= len(text) - len(text.lstrip()) or presentation) and bool(
                re.match(
                    r"\s*(?:(?:the\s+)?patient is\s+)?(?:(?:a|an)\s+)?"
                    r"(?:\d|male\b|female\b|woman\b|man\b|girl\b|boy\b)",
                    context.text,
                    FLAGS,
                )
            )
            explicit = bool(
                re.search(
                    r"\b(?:patient(?:\s+is)?|age(?:\s+is)?|aged|sex(?:\s+is)?)\s*[:,]?\s*$",
                    prefix,
                    FLAGS,
                )
            )
            if not (opening or explicit) and attributes["temporality"] == "current":
                attributes["temporality"] = "unknown"
            if re.search(
                r"\b(?:about|approximately|around|between|over|under|at least|at most)\b"
                r"|[<>~]|\d\s*[-–]\s*$",
                prefix,
                FLAGS,
            ):
                attributes.update(assertion="uncertain", certainty="uncertain")
        evidence = span(text, start, end)
        identity = json.dumps(
            [case.case_id, text_hash(text), fingerprint, kind, name, start, end, rule_id]
        )
        facts.append(
            Fact(
                fact_id=text_hash(identity),
                kind=kind,
                name=name,
                value=value,
                unit=unit,
                evidence=evidence,
                context=context,
                rule_id=rule_id,
                operator=operator,
                **attributes,
            )
        )

    for context in clauses(text):
        occupied = []
        for match in AGE.finditer(context.text):
            start, end = context.start + match.start(), context.start + match.end()
            value = float(match["value"])
            if (
                context.text[max(0, match.start() - 1) : match.start()] in {"-", "."}
                or value > 130
                and match["unit"].lower() == "year"
            ):
                issues.append(
                    Issue(
                        code="invalid_age",
                        message="Age is outside the supported numeric contract.",
                        evidence=span(text, start, end),
                    )
                )
                continue
            add("age", "age", value, match["unit"].lower(), context, start, end, "age-unit-v1")
        for match in COMPACT.finditer(context.text):
            start, end = context.start + match.start(), context.start + match.end()
            if float(match["value"]) > 130:
                issues.append(
                    Issue(
                        code="invalid_age",
                        message="Compact age is outside the supported contract.",
                        evidence=span(text, start, end),
                    )
                )
                continue
            add(
                "age",
                "age",
                float(match["value"]),
                "year",
                context,
                start,
                end,
                "compact-demographic-v1",
            )
            add(
                "sex",
                "sex",
                "Female" if match["sex"] == "F" else "Male",
                None,
                context,
                start,
                end,
                "compact-demographic-v1",
            )
        for match in SEX.finditer(context.text):
            value = "Female" if match[0].lower() in {"female", "woman", "girl", "lady"} else "Male"
            add(
                "sex",
                "sex",
                value,
                None,
                context,
                context.start + match.start(),
                context.start + match.end(),
                "narrative-sex-label-v1",
            )
        candidates = []
        for kind, vocabulary in rules.LEXICON.items():
            for name, pattern in vocabulary.items():
                for match in re.finditer(r"\b(?:" + pattern + r")\b", context.text, FLAGS):
                    candidates.append((match.start(), match.end(), kind, name))
        # Longest overlapping mention wins: type 2 diabetes is not also generic diabetes.
        for start, end, kind, name in sorted(candidates, key=lambda m: (-(m[1] - m[0]), m[0])):
            if any(start < b and end > a for a, b in occupied):
                continue
            occupied.append((start, end))
            add(
                kind,
                name,
                name,
                None,
                context,
                context.start + start,
                context.start + end,
                "lexicon-v1:" + name,
            )
        for name, (label, units) in rules.MEASUREMENTS.items():
            pattern = (
                r"\b(?:"
                + label
                + r")\b\s*(?:is|of|=|:)?\s*"
                + QUANTITY
                + r"\s*(?P<unit>[^\s,;.!?]+)?"
            )
            for match in re.finditer(pattern, context.text, FLAGS):
                raw_unit = match["unit"] or ""
                unit = next(
                    (v for k, v in units.items() if k.casefold() == raw_unit.casefold()), None
                )
                start, end = context.start + match.start(), context.start + match.end()
                number = float(match["value"])
                if unit is None or not math.isfinite(number) or number < 0:
                    issues.append(
                        Issue(
                            code="unsupported_measurement",
                            message="Unsupported unit or invalid numeric measurement.",
                            evidence=span(text, start, end),
                        )
                    )
                    continue
                operator = OPERATORS[(match["op"] or "").strip()]
                add(
                    "measurement",
                    name,
                    float(match["value"]),
                    unit,
                    context,
                    start,
                    end,
                    "quantity-v1:" + name,
                    operator,
                )
        bp = r"\b(?:blood pressure|BP)\s*(?:is|of|=|:)?\s*(\d{2,3})/(\d{2,3})\s*(mmHg)?\b"
        for match in re.finditer(bp, context.text, FLAGS):
            start, end = context.start + match.start(), context.start + match.end()
            if not match[3]:
                issues.append(
                    Issue(
                        code="unsupported_measurement",
                        message="Blood pressure requires explicit mmHg units.",
                        evidence=span(text, start, end),
                    )
                )
                continue
            for name, value in (
                ("systolic_blood_pressure", match[1]),
                ("diastolic_blood_pressure", match[2]),
            ):
                add(
                    "measurement",
                    name,
                    float(value),
                    "mmHg",
                    context,
                    start,
                    end,
                    "blood-pressure-v1:" + name,
                )
        if not any(f.context == context for f in facts):
            issues.append(
                Issue(
                    code="unparsed_clause",
                    message="No supported fact extracted; this is not negative evidence.",
                    evidence=context,
                )
            )
    if re.search(
        r"\b(?:transgender|nonbinary|non-binary|intersex|sex unknown|sex unspecified)\b",
        text,
        FLAGS,
    ):
        issues.append(
            Issue(
                code="sex_requires_review",
                message="Narrative sex/gender context cannot safely supply a trial sex filter.",
            )
        )
    for kind in ("age", "sex"):
        current = [
            f
            for f in facts
            if f.kind == kind
            and f.experiencer == "patient"
            and f.temporality == "current"
            and f.assertion == "present"
        ]
        if len({(f.value, f.unit) for f in current}) > 1:
            issues.append(
                Issue(
                    code="conflicting_" + kind,
                    message="Conflicting demographics require review; filtering will abstain.",
                )
            )
    facts.sort(key=lambda f: (f.evidence.start, f.evidence.end, f.kind, f.name))
    return PatientProfile(
        extractor_version=rules.VERSION,
        rules_sha256=fingerprint,
        case=case,
        narrative_sha256=text_hash(text),
        facts=tuple(facts),
        issues=tuple(issues),
        missing_categories=tuple(k for k in KINDS if not any(f.kind == k for f in facts)),
    )

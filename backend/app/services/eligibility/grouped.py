"""Opt-in, source-aligned three-valued logic. Unsupported scope never becomes a decision."""

import json
import re
from pathlib import Path

from backend.app.schemas.patient import Span, text_hash
from backend.app.services.eligibility.age import whole_age
from backend.app.services.eligibility.rules import SEX, check_predicate, usable_facts, verify
from pipelines.criteria.parser import numeric_constraints

VERSION = "grouped-screening-v1"
MAX_DEPTH = 12
MAX_NODES = 256
HEADINGS = {
    "all of the following:": "and",
    "any of the following:": "or",
    "either of the following:": "or",
    "none of the following:": "none",
}
SCOPE = re.compile(
    r"\b(?:or|and|not|if|then|unless|except\w*|provided|however|either|any of|one of|"
    r"waiv\w*|only|otherwise|following)\b",
    re.I,
)


def fingerprint():
    return text_hash(Path(__file__).read_text(encoding="utf-8"))


def combine(operator, values):
    """Strong Kleene logic; a missing fact is never silently true or false."""
    if not values or any(v not in {"true", "false", "unknown"} for v in values):
        raise ValueError("nonempty three-valued operands required")
    if operator == "not" and len(values) == 1:
        return {"true": "false", "false": "true", "unknown": "unknown"}[values[0]]
    if operator == "implies" and len(values) == 2:
        return combine("or", [combine("not", values[:1]), values[1]])
    if operator == "waiver" and len(values) == 2:
        return combine("or", values)
    if operator == "except" and len(values) == 2:
        return combine("and", [values[0], combine("not", values[1:])])
    if operator in {"and", "or"}:
        decisive, neutral = ("false", "true") if operator == "and" else ("true", "false")
        return (
            decisive
            if decisive in values
            else neutral
            if all(v == neutral for v in values)
            else "unknown"
        )
    raise ValueError("unsupported operator or arity")


class Builder:
    def __init__(self, profile, parsed):
        self.profile, self.parsed = profile, parsed
        self.text = parsed.source.text
        self.nodes = 0
        self.unsafe_scope = False

    def node(self, op, a, b, ids, children=(), *, truth="unknown", facts=(), reason="", missing=()):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ValueError("grouped node bound exceeded")
        if children:
            truth = combine(op, [c["truth"] for c in children])
            facts = tuple(dict.fromkeys(f for c in children for f in c["fact_ids"]))
            missing = tuple(dict.fromkeys(m for c in children for m in c["missing_information"]))
        return {
            "node_id": text_hash(json.dumps([op, a, b, ids, [c["node_id"] for c in children]])),
            "operator": op,
            "evidence": Span(start=a, end=b, text=self.text[a:b]).model_dump(),
            "criterion_ids": list(ids),
            "children": list(children),
            "truth": truth,
            "fact_ids": list(facts),
            "reason": reason or "three_valued_" + op,
            "missing_information": list(missing),
        }

    def unknown(self, a, b, ids, reason="unsupported_or_ambiguous_logic", *, unsafe=True):
        self.unsafe_scope |= unsafe
        return self.node("unknown", a, b, ids, reason=reason, missing=("criterion interpretation",))

    def trim(self, a, b):
        while a < b and self.text[a].isspace():
            a += 1
        while a < b and self.text[b - 1].isspace():
            b -= 1
        return a, b

    def atom(self, a, b, ids):
        wording = self.text[a:b]
        age = whole_age(wording)
        sex = SEX.fullmatch(wording)
        constraints, _ = numeric_constraints(self.text, a, b)
        numeric = constraints[0] if len(constraints) == 1 else None
        if numeric and numeric.evidence.text.strip() != wording.strip():
            numeric = None
        if age is None and sex is None and numeric is None:
            return None
        name = "sex" if sex else "age" if age else numeric.name
        kind = "sex" if sex else "age" if age else "measurement"
        fact, mentions, issue = usable_facts(self.profile, kind, None if sex else name)
        facts = tuple(f.fact_id for f in mentions)
        if issue:
            return self.node(
                "atom",
                a,
                b,
                ids,
                facts=facts,
                reason=issue,
                missing=(f"reliable current patient {name}",),
            )
        unit = None if sex else age.unit if age else numeric.unit
        if not sex and fact.unit != unit:
            return self.node(
                "atom",
                a,
                b,
                ids,
                facts=facts,
                reason="units_differ_no_conversion",
                missing=(f"{name} in {unit}",),
            )
        truth = (
            fact.value.lower() == sex[1].lower()
            if sex
            else age.accepts(fact.value)
            if age
            else check_predicate(fact.value, numeric)
        )
        return self.node(
            "atom",
            a,
            b,
            ids,
            truth="true" if truth else "false",
            facts=facts,
            reason="complete_same_unit_predicate",
        )

    def expression(self, a, b, ids, section, depth=0):
        if depth > MAX_DEPTH:
            raise ValueError("grouped depth bound exceeded")
        original_a, original_b = a, b
        a, b = self.trim(a, b)
        if a < b and self.text[b - 1] == ".":
            b -= 1
            a, b = self.trim(a, b)
        if a == b:
            return self.unknown(original_a, original_b, ids)
        text = self.text[a:b]
        atom = self.atom(a, b, ids)
        if atom is not None:
            return atom
        # Only explicitly scoped canonical waiver/exception forms are supported.
        # Bare 'A unless B' has ambiguous clinical polarity and remains unknown.
        for pattern, operator, allowed in (
            (r"Required: (\(.+\)), unless (\(.+\))", "waiver", "inclusion"),
            (r"Exclude if (\(.+\)), unless (\(.+\))", "except", "exclusion"),
            (r"If (\(.+\)), then (\(.+\))", "implies", "inclusion"),
        ):
            m = re.fullmatch(pattern, text, re.I | re.S)
            if m and section == allowed:
                children = [
                    self.expression(a + m.start(i), a + m.end(i), ids, section, depth + 1)
                    for i in (1, 2)
                ]
                return self.node(operator, a, b, ids, children)
        # Strip a single enclosing pair only if it encloses the entire expression.
        nesting, balanced, outer = 0, True, text.startswith("(")
        for i, char in enumerate(text):
            nesting += (char == "(") - (char == ")")
            if nesting < 0:
                balanced = False
            if nesting == 0 and i != len(text) - 1:
                outer = False
        if nesting or not balanced:
            return self.unknown(a, b, ids)
        if outer:
            if not self.text[a + 1 : b - 1].strip():
                return self.unknown(a, b, ids)
            return self.node(
                "and", a, b, ids, [self.expression(a + 1, b - 1, ids, section, depth + 1)]
            )
        m = re.match(r"For (female|male) participants:\s*", text, re.I)
        if m and section == "inclusion":
            if not self.text[a + m.end() : b].strip():
                return self.unknown(a, b, ids)
            gate = self.atom(a + m.start(1), a + m.end(1), ids)
            child = self.expression(a + m.end(), b, ids, section, depth + 1)
            return self.node("implies", a, b, ids, [gate, child])
        either = re.match(r"Either\s+", text, re.I)
        start = a + either.end() if either else a
        cuts, nesting = [], 0
        for match in re.finditer(r"\(|\)|\b(?:AND|OR)\b", self.text[start:b], re.I):
            token = match[0].lower()
            if token == "(":
                nesting += 1
            elif token == ")":
                nesting -= 1
            elif nesting == 0:
                cuts.append((start + match.start(), start + match.end(), token))
        ops = {c[2] for c in cuts}
        if len(ops) == 1 and (not either or ops == {"or"}):
            intervals = list(
                zip([start] + [c[1] for c in cuts], [c[0] for c in cuts] + [b], strict=True)
            )
            if any(not self.text[x:y].strip(" .") for x, y in intervals):
                return self.unknown(a, b, ids)
            children = [self.expression(x, y, ids, section, depth + 1) for x, y in intervals]
            return self.node(next(iter(ops)), a, b, ids, children)
        m = re.match(r"NOT\s+(?=\()", text, re.I)
        if m and not cuts:
            child = self.expression(a + m.end(), b, ids, section, depth + 1)
            return self.node("not", a, b, ids, [child])
        return self.unknown(a, b, ids, unsafe=bool(SCOPE.search(text)) or text.endswith(":"))

    def group(self, criterion, descendants, section, depth=0):
        if depth > MAX_DEPTH:
            raise ValueError("grouped hierarchy depth exceeded")
        children = descendants.get(criterion.criterion_id, [])
        if not children:
            return self.expression(
                criterion.evidence.start, criterion.evidence.end, [criterion.criterion_id], section
            )
        heading = criterion.evidence.text.strip().casefold()
        operator = HEADINGS.get(heading)
        nodes = [self.group(c, descendants, section, depth + 1) for c in children]
        end = max(n["evidence"]["end"] for n in nodes)
        ids = [criterion.criterion_id] + [i for n in nodes for i in n["criterion_ids"]]
        if operator is None:
            # Retain the entire unrecognised subtree, not independent child decisions.
            self.unsafe_scope = True
            return self.node(
                "and",
                criterion.evidence.start,
                end,
                ids,
                [
                    self.unknown(
                        criterion.evidence.start, criterion.evidence.end, [criterion.criterion_id]
                    ),
                    *nodes,
                ],
            )
        group = self.node(
            "or" if operator == "none" else operator, criterion.evidence.start, end, ids, nodes
        )
        if operator == "none":
            group = self.node("not", criterion.evidence.start, end, ids, [group])
        return group


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node["children"])


def applicable_support(node):
    if node["truth"] != "true":
        return False
    if node["operator"] == "implies":
        return node["children"][0]["truth"] != "false" and applicable_support(node["children"][1])
    if node["operator"] in {"and", "or"}:
        return any(applicable_support(c) for c in node["children"])
    return bool(node["fact_ids"])


def verify_grouped(profile, parsed):
    """Keep the original parse and ordinary assessment; never flatten OR into blockers."""
    baseline = verify(profile, parsed)  # Reproduces and validates all original source evidence.
    builder = Builder(profile, parsed)
    descendants = {}
    for criterion in parsed.criteria:
        descendants.setdefault(criterion.parent_id, []).append(criterion)
    sections = []
    for section in parsed.sections:
        roots = [c for c in descendants.get(None, []) if c.section_ordinal == section.ordinal]
        if not roots:
            continue
        children = [builder.group(c, descendants, section.label) for c in roots]
        node = builder.node(
            "or" if section.label == "exclusion" else "and",
            section.body_start,
            section.evidence.end,
            [i for c in children for i in c["criterion_ids"]],
            children,
        )
        sections.append({"section": section.label, "ordinal": section.ordinal, "root": node})
        if section.label == "unknown":
            builder.unsafe_scope = True
    nodes = list(walk([s["root"] for s in sections]))
    if {i for n in nodes for i in n["criterion_ids"]} != {c.criterion_id for c in parsed.criteria}:
        raise ValueError("grouped tree lost criterion evidence")
    # An unresolved scope can govern another section; do not manufacture local blockers.
    if builder.unsafe_scope:
        for section in sections:
            section["root"]["truth"] = "unknown"
            section["root"]["reason"] = "unresolved_scope_requires_global_review"
    blockers = [
        s["root"]["node_id"]
        for s in sections
        if (s["section"] == "inclusion" and s["root"]["truth"] == "false")
        or (s["section"] == "exclusion" and s["root"]["truth"] == "true")
    ]
    unknown = [s["root"]["node_id"] for s in sections if s["root"]["truth"] == "unknown"]
    inclusion = [s for s in sections if s["section"] == "inclusion"]
    supported_inclusion = any(applicable_support(s["root"]) for s in inclusion)
    status = (
        "likely_exclusion"
        if blockers
        else "insufficient_information"
        if (unknown or not inclusion or not nodes or not supported_inclusion)
        else "potential_match"
    )
    return {
        "schema_version": VERSION,
        "implementation_sha256": fingerprint(),
        "baseline_assessment_id": baseline.assessment_id,
        "case_id": profile.case.case_id,
        "trial_id": parsed.source.trial_id,
        "source_sha256": parsed.source.source_sha256,
        "source_text_sha256": parsed.text_sha256,
        "parser_sha256": parsed.parser_sha256,
        "sections": sections,
        "status": status,
        "blocking_node_ids": blockers,
        "unknown_section_node_ids": unknown,
        "missing_information": list(
            dict.fromkeys(m for n in nodes for m in n["missing_information"])
        ),
        "scope_review_required": builder.unsafe_scope,
        "applicable_inclusion_supported": supported_inclusion,
        "requires_professional_review": True,
        "default_screening_changed": False,
        "clinical_validation": False,
    }


def validate_grouped(packet, profile, parsed):
    if verify_grouped(profile, parsed) != packet:
        raise ValueError("grouped assessment differs from source reproduction")
    return packet

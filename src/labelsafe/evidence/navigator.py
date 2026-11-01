"""
Evidence Navigator graph serializer.
Constructs Cytoscape / NetworkX-compatible directed provenance graph payloads
connecting medications, active ingredients, clinical safety findings, the matched rule,
and cited regulatory passages.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field

from src.labelsafe.core.contracts.evidence import EvidencePassage
from src.labelsafe.core.contracts.medication import MedicationConcept
from src.labelsafe.core.contracts.safety import SafetyFinding
from src.labelsafe.ingestion.dailymed import LABEL_URL_TEMPLATE
from src.labelsafe.safety.models import AllergyRule, DCIRule, DDIRule, DFIRule
from src.labelsafe.safety.rules_db import mentions

SafetyRule = DDIRule | DFIRule | DCIRule | AllergyRule

MAX_PASSAGES = 4
# Passages are stored with an embedding header like "[DRUG: X] [SECTION: Y] [LOINC: Z] ".
_HEADER = re.compile(r"^(\[[A-Z]+: [^\]]*\]\s*)+")
# Label sections that can support each finding type (LOINC codes).
SECTIONS = {
    "DRUG_DRUG_INTERACTION": {"34073-7"},
    "DRUG_FOOD_INTERACTION": {"34073-7", "43685-7"},
    "CONTRAINDICATION": {"34070-3", "34066-1"},
    "ALLERGY_EXCIPIENT": {"34070-3"},
}


class GraphNode(BaseModel):
    id: str
    label: str
    type: str = Field(..., description="'MEDICATION', 'INGREDIENT', 'FINDING', 'RULE', 'PASSAGE', 'SOURCE'")
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    relationship: str = Field(
        ...,
        description="'HAS_INGREDIENT', 'TRIGGERS_FINDING', 'MATCHED_RULE', 'CITES', 'SUPPORTED_BY', "
        "'EXTRACTED_FROM'",
    )
    properties: dict[str, Any] = Field(default_factory=dict)


class EvidenceProvenanceGraph(BaseModel):
    """NetworkX and Cytoscape.js compatible graph payload."""

    finding_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    metadata: dict[str, Any] = Field(default_factory=dict)


def _names(concept: MedicationConcept | None, rxcui: str) -> list[str]:
    if concept is None:
        return [rxcui]
    return [concept.canonical_name, *concept.synonyms, *(i.name for i in concept.ingredients if i.is_active)]


def select_passages(
    finding: SafetyFinding,
    rule: SafetyRule | None,
    concepts: Mapping[str, MedicationConcept],
    passages_by_rxcui: Mapping[str, Sequence[EvidencePassage]],
) -> list[EvidencePassage]:
    """Label passages that back a finding: the ones its rule cites, else the relevant section text."""
    every = [p for ps in passages_by_rxcui.values() for p in ps]
    cited = [p for p in every if p.passage_id in finding.supporting_evidence_ids]
    if cited:
        return cited[:MAX_PASSAGES]
    sections = SECTIONS.get(finding.finding_type, set())
    terms_for: dict[str, list[str]] = {}
    if isinstance(rule, DDIRule):
        a, b = rule.subject_rxcui, rule.interacting_rxcui
        terms_for = {a: _names(concepts.get(b), b), b: _names(concepts.get(a), a)}
    elif isinstance(rule, DFIRule):
        terms_for = {rule.subject_rxcui: [rule.food_identifier, *rule.food_aliases]}
    picked: list[EvidencePassage] = []
    for rxcui in finding.subject_medications:
        for p in passages_by_rxcui.get(rxcui, ()):
            if p.loinc_section_code not in sections:
                continue
            terms = terms_for.get(rxcui)
            if terms is not None and not any(mentions(p.content, t) for t in terms if len(t) >= 3):
                continue
            picked.append(p)
            if len(picked) >= MAX_PASSAGES:
                return picked
    return picked


class EvidenceNavigatorSerializer:
    """
    Serializes safety findings and evidence passages into directed provenance subgraphs.
    Enables interactive node-link exploration in Evidence Navigator UI.
    """

    @classmethod
    def serialize_finding_subgraph(
        cls,
        finding: SafetyFinding,
        passages: list[EvidencePassage] | None = None,
        rule: SafetyRule | None = None,
        concepts: Mapping[str, MedicationConcept] | None = None,
    ) -> EvidenceProvenanceGraph:
        """Medicines -> ingredients -> finding -> rule -> label passages -> source documents."""
        nodes: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []
        concepts = concepts or {}

        def add(node: GraphNode) -> None:
            nodes.setdefault(node.id, node)

        add(
            GraphNode(
                id=finding.finding_id,
                label=f"{finding.finding_type}: {finding.severity.value}",
                type="FINDING",
                properties={
                    "severity": finding.severity.value,
                    "clinical_explanation": finding.clinical_explanation,
                    "actionable_warning": finding.actionable_warning,
                },
            )
        )

        for med_id in finding.subject_medications:
            concept = concepts.get(med_id)
            add(
                GraphNode(
                    id=med_id,
                    label=concept.canonical_name if concept else med_id,
                    type="MEDICATION",
                    properties={"rxcui": med_id},
                )
            )
            active = []
            if concept is not None:
                active = [i for i in concept.ingredients if i.is_active]
                # A single-ingredient drug named after its ingredient adds nothing to the trail.
                if len(active) == 1 and active[0].name.lower() == concept.canonical_name.lower():
                    active = []
            for ingredient in active:
                ingredient_id = f"ING-{ingredient.unii}"
                add(
                    GraphNode(
                        id=ingredient_id,
                        label=ingredient.name,
                        type="INGREDIENT",
                        properties={"unii": ingredient.unii},
                    )
                )
                edges.append(GraphEdge(source=med_id, target=ingredient_id, relationship="HAS_INGREDIENT"))
                edges.append(
                    GraphEdge(
                        source=ingredient_id, target=finding.finding_id, relationship="TRIGGERS_FINDING"
                    )
                )
            if not active:
                edges.append(
                    GraphEdge(
                        source=med_id,
                        target=finding.finding_id,
                        relationship="TRIGGERS_FINDING",
                        properties={"rule_id": finding.rule_id},
                    )
                )

        rule_node = None
        if rule is not None:
            rule_node = f"RULE-{rule.rule_id}"
            add(
                GraphNode(
                    id=rule_node,
                    label=rule.rule_id,
                    type="RULE",
                    properties={"source": rule.rule_source, "reviewed": rule.reviewed},
                )
            )
            edges.append(GraphEdge(source=finding.finding_id, target=rule_node, relationship="MATCHED_RULE"))

        for p in passages or []:
            drug = concepts[p.rxcui].canonical_name if p.rxcui in concepts else p.rxcui
            add(
                GraphNode(
                    id=p.passage_id,
                    label=p.section_title,
                    type="PASSAGE",
                    properties={
                        "section": p.section_title,
                        "document_id": p.document_id,
                        "rxcui": p.rxcui,
                        "drug": drug,
                        "content": _HEADER.sub("", p.content),
                    },
                )
            )
            cited = rule_node is not None and p.passage_id in finding.supporting_evidence_ids
            edges.append(
                GraphEdge(
                    source=rule_node if cited and rule_node else finding.finding_id,
                    target=p.passage_id,
                    relationship="CITES" if cited else "SUPPORTED_BY",
                    properties={"status": p.embedding_status},
                )
            )
            add(
                GraphNode(
                    id=p.document_id,
                    label=f"{drug.capitalize()} label",
                    type="SOURCE",
                    properties={"url": LABEL_URL_TEMPLATE.format(setid=p.document_id)},
                )
            )
            edges.append(GraphEdge(source=p.passage_id, target=p.document_id, relationship="EXTRACTED_FROM"))

        return EvidenceProvenanceGraph(
            finding_id=finding.finding_id,
            nodes=list(nodes.values()),
            edges=edges,
            metadata={
                "node_count": len(nodes),
                "edge_count": len(edges),
                "rule_source": rule.rule_source if rule else finding.rule_source,
                "reviewed": rule.reviewed if rule else None,
                "passage_count": len(passages or []),
            },
        )

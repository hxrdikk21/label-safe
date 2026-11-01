"""Evidence Navigator provenance graph serialization."""

import hashlib

from src.rxguard.core.contracts.evidence import EvidencePassage
from src.rxguard.core.contracts.medication import MedicationConcept
from src.rxguard.core.contracts.safety import FindingSeverity, FindingStatus, SafetyFinding
from src.rxguard.evidence.navigator import EvidenceNavigatorSerializer, select_passages
from src.rxguard.safety.engine import SafetyEngine
from src.rxguard.safety.models import DDIRule


def test_evidence_navigator_serializer():
    """Verify directed provenance graph generation for Cytoscape/NetworkX compatibility."""
    finding = SafetyFinding(
        finding_id="FIND-101",
        finding_type="CONTRAINDICATION",
        subject_medications=["136443", "4917"],
        status=FindingStatus.RISK_IDENTIFIED,
        severity=FindingSeverity.CONTRAINDICATED,
        rule_id="DDI-SILDENAFIL-NITRATES",
        supporting_evidence_ids=["PASS-SILD"],
        clinical_explanation=(
            "Co-administration of sildenafil with nitrates is strictly contraindicated due to severe "
            "hypotensive shock."
        ),
        actionable_warning="Do not prescribe concurrently.",
        requires_professional_review=True,
    )

    text = "Do not use VIAGRA in patients who are using a prescription organic nitrate medicine."
    passage = EvidencePassage(
        passage_id="PASS-SILD",
        document_id="FDA-LABEL-VIAGRA",
        rxcui="136443",
        loinc_section_code="34070-3",
        section_title="Contraindications",
        passage_index=0,
        content=text,
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )

    graph = EvidenceNavigatorSerializer.serialize_finding_subgraph(finding, [passage])

    assert graph.finding_id == "FIND-101"
    # Expected nodes: Finding, 2 Medications, Passage, Source = 5
    assert len(graph.nodes) >= 4
    # Expected edges: 2 Medications->Finding, Finding->Passage, Passage->Source
    assert len(graph.edges) >= 3

    # Check node types
    node_types = {n.type for n in graph.nodes}
    assert "FINDING" in node_types
    assert "MEDICATION" in node_types
    assert "PASSAGE" in node_types
    assert "SOURCE" in node_types


def _passage(pid: str, rxcui: str, section: str, text: str) -> EvidencePassage:
    return EvidencePassage(
        passage_id=pid,
        document_id=f"SET-{rxcui}",
        rxcui=rxcui,
        loinc_section_code=section,
        section_title="Drug Interactions",
        passage_index=0,
        content=text,
        sha256_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def test_ddi_graph_uses_real_names_rule_and_passages_that_name_the_other_drug() -> None:
    concepts = {
        "703": MedicationConcept(rxcui="703", canonical_name="amiodarone", term_type="IN"),
        "3407": MedicationConcept(
            rxcui="3407", canonical_name="digoxin", term_type="IN", synonyms=["Lanoxin"]
        ),
    }
    rule = DDIRule(
        rule_id="DDINTER-3407-703",
        subject_rxcui="3407",
        interacting_rxcui="703",
        severity=FindingSeverity.MAJOR,
        mechanism_summary="x",
        clinical_consequence="x",
        actionable_warning="x",
        rule_source="ddinter",
        reviewed=False,
    )
    finding = SafetyEngine._finding_from_rule(rule)
    by_rxcui = {
        "703": [
            _passage(
                "P1",
                "703",
                "34073-7",
                "[DRUG: Amiodarone] [LOINC: 34073-7] Amiodarone raises serum digoxin levels.",
            ),
            _passage("P2", "703", "34073-7", "Warfarin doses may need lowering."),
            _passage("P3", "703", "34070-3", "Contraindicated with digoxin? (wrong section)"),
        ],
        "3407": [_passage("P4", "3407", "34073-7", "Pacerone and Lanoxin together: monitor.")],
    }
    assert [p.passage_id for p in select_passages(finding, rule, concepts, by_rxcui)] == ["P1"]

    graph = EvidenceNavigatorSerializer.serialize_finding_subgraph(
        finding, [by_rxcui["703"][0]], rule, concepts
    )
    labels = {n.type: n.label for n in graph.nodes}
    assert labels["MEDICATION"] in {"amiodarone", "digoxin"}
    assert labels["RULE"] == "DDINTER-3407-703" and labels["SOURCE"] == "Amiodarone label"
    rule_node = next(n for n in graph.nodes if n.type == "RULE")
    assert rule_node.properties == {"source": "ddinter", "reviewed": False}
    passage = next(n for n in graph.nodes if n.type == "PASSAGE")
    assert passage.properties["content"] == "Amiodarone raises serum digoxin levels."
    source = next(n for n in graph.nodes if n.type == "SOURCE")
    assert source.properties["url"].endswith("setid=SET-703")


def test_label_rule_passages_are_the_cited_ones() -> None:
    finding = SafetyFinding(
        finding_id="LABEL-DDI-1-2",
        finding_type="DRUG_DRUG_INTERACTION",
        subject_medications=["1", "2"],
        status=FindingStatus.RISK_IDENTIFIED,
        supporting_evidence_ids=["P9"],
        clinical_explanation="x",
        actionable_warning="x",
    )
    by_rxcui = {"1": [_passage("P8", "1", "34073-7", "a"), _passage("P9", "1", "34073-7", "b")]}
    assert [p.passage_id for p in select_passages(finding, None, {}, by_rxcui)] == ["P9"]

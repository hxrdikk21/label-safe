# Hardik — Neo4j & Knowledge Graph Intelligence Blueprint

> **Role:** Lead Knowledge Graph & Graph Intelligence Engineer  
> **Repository:** [DAREDEVIL-OF-NEXUS/RxGuard-RAG](https://github.com/DAREDEVIL-OF-NEXUS/RxGuard-RAG)  
> **Assigned Branch:** `feature/hardik-knowledge-graph`  
> **Assigned Workstream:** Neo4j Graph Database Schema, Sourced Relationship Modeling, PostgreSQL-to-Neo4j Synchronization, Graph-Assisted Retrieval & Evidence Navigator Subgraph Services  
> **Version:** 2.0.0 (Four-Team Master Specification)  
> **Date:** October 2026

---

## 1. Project Context & Mission

RxGuard-RAG is a research-grade medication safety intelligence platform designed to eliminate hallucinations in clinical decision support. The system pairs deterministic safety screening rules with advanced Retrieval-Augmented Generation (Self-RAG-inspired) and a dedicated Neo4j knowledge graph.

Your mission as the **Lead Knowledge Graph Engineer** is to architect, synchronize, and query the **dedicated Neo4j property graph database**:
1. Deploy the Neo4j schema, enforcing uniqueness constraints and indexes on clinical identifiers (`rxcui`, `ndc`, `unii`, `icd10`, `food_id`, `passage_id`).
2. Implement the **asynchronous PostgreSQL-to-Neo4j synchronization worker**, guaranteeing idempotent updates via Cypher `MERGE`.
3. Provide **multi-hop graph traversal services** to support ingredient-aware reasoning and conflict detection.
4. Supply **graph-assisted retrieval candidate expansion** to Vasu's RAG pipeline.
5. Power the flagship **RxGuard Evidence Navigator** by serializing traceable clinical provenance subgraphs (Medication -> Product -> Ingredient -> Finding -> Rule -> Passage).
6. Implement a complete **graph rebuild procedure** allowing Neo4j to be completely rehydrated from canonical PostgreSQL records.

---

## 2. Overall System Architecture & Your Layer

The system consists of five distinct layers:
- Layer A: Data Acquisition & Medication Knowledge (Mudit)
- Layer B: Persistent Data & Tri-Store Indexing (Joint: PostgreSQL by Mudit, pgvector by Vasu, **Neo4j by Hardik**)
- Layer C: Deterministic Medication Safety Engine (Lakshay)
- Layer D: Advanced RAG & Self-RAG Engine (Vasu)
- Layer E: Application, Personalization & Security (Lakshay)

You own the dedicated Neo4j property graph in Layer B and provide graph intelligence to Layer D and Layer E.

---

## 3. Module Boundaries & Owned Files

You have exclusive write ownership over the following project paths:

```
src/rxguard/
├── graph/
│   ├── __init__.py
│   ├── client.py            # Neo4j async driver & connection pool manager
│   ├── schema.py            # Node labels, relationship definitions & Cypher constraints
│   ├── sync_worker.py       # PostgreSQL-to-Neo4j idempotent synchronization worker
│   ├── query_service.py     # Multi-hop traversal, ingredient expansion & path queries
│   ├── subgraph_service.py  # Evidence Navigator JSON serializer (Cytoscape/NetworkX)
│   └── rebuild_graph.py     # Full graph wipe and rebuild script from PostgreSQL
deployment/
└── neo4j/
    ├── neo4j.conf           # Memory, APOC plugins, and security configuration
    └── migrations/          # Cypher constraint & index migration scripts
tests/
└── unit/
    ├── test_graph_schema.py # Node label and constraint validation
    └── test_graph_queries.py # Cypher traversal and multi-hop query tests
tests/
└── integration/
    └── test_graph_sync.py   # PostgreSQL-to-Neo4j idempotent sync tests
```

### Files You Must NOT Modify Unilaterally:
- `src/rxguard/core/contracts/*`: Shared contracts owned by Lakshay.
- `src/rxguard/database/models.py` & `src/rxguard/ingestion/*`: Owned by Mudit.
- `src/rxguard/retrieval/*` & `src/rxguard/self_rag/*`: Owned by Vasu.
- `src/rxguard/safety/*` & `src/rxguard/api/*`: Owned by Lakshay.

---

## 4. Exact Implementation Responsibilities

1. **Neo4j Schema & Constraints Architecture (`schema.py`):**
   - Apply Cypher uniqueness constraints across all entity types:
     ```cypher
     CREATE CONSTRAINT FOR (m:MedicationConcept) REQUIRE m.rxcui IS UNIQUE;
     CREATE CONSTRAINT FOR (p:DrugProduct) REQUIRE p.ndc IS UNIQUE;
     CREATE CONSTRAINT FOR (i:Ingredient) REQUIRE i.unii IS UNIQUE;
     CREATE CONSTRAINT FOR (c:Condition) REQUIRE c.icd10 IS UNIQUE;
     CREATE CONSTRAINT FOR (f:Food) REQUIRE f.food_id IS UNIQUE;
     CREATE CONSTRAINT FOR (p:EvidencePassage) REQUIRE p.passage_id IS UNIQUE;
     CREATE CONSTRAINT FOR (s:SafetyFinding) REQUIRE s.finding_id IS UNIQUE;
     ```
   - Model qualified relationships:
     - `(:MedicationConcept)-[:APPLIES_TO_PRODUCT]->(:DrugProduct)`
     - `(:MedicationConcept)-[:HAS_INGREDIENT {is_active: true}]->(:Ingredient)`
     - `(:DrugProduct)-[:HAS_INGREDIENT {is_active: false}]->(:Ingredient)`
     - `(:MedicationConcept)-[:HAS_CONTRAINDICATION_EVIDENCE {source_id: STRING, severity: STRING}]->(:Condition)`
     - `(:MedicationConcept)-[:HAS_FOOD_INTERACTION_EVIDENCE {timing_qualifier: STRING}]->(:Food)`
     - `(:MedicationConcept)-[:HAS_INTERACTION_EVIDENCE {severity: STRING}]->(:EvidencePassage)`
     - `(:EvidencePassage)-[:SUPPORTED_BY]->(:MedicationConcept)`
     - `(:SafetyFinding)-[:EVIDENCED_BY]->(:EvidencePassage)`
     - `(:Allergen)-[:MATCHES_INGREDIENT {certainty: STRING}]->(:Ingredient)`
2. **PostgreSQL-to-Neo4j Synchronization Worker (`sync_worker.py`):**
   - Consume pending entities from Mudit's `derived_sync_status` table in PostgreSQL.
   - Execute parameterized Cypher `MERGE` queries to ensure absolute idempotency.
   - Preserve source provenance on all relationships: `source_document_id`, `version`, `effective_date`, `jurisdiction`.
3. **Multi-Hop Traversal & Graph Query Service (`query_service.py`):**
   - Implement Cypher queries to answer complex clinical questions:
     - Find all inactive excipients shared across two distinct drug products.
     - Find all documented contraindications connected to an active ingredient.
     - Detect conflicting relationships where one source lists an interaction and another does not.
4. **Graph-Assisted Candidate Expansion for Vasu (`graph_retriever.py`):**
   - Provide an API returning adjacent passage IDs and ingredient UNIIs for a given RxCUI to enrich hybrid search context.
5. **Evidence Navigator Subgraph Serializer (`subgraph_service.py`):**
   - Given a `finding_id` or `rxcui`, extract the surrounding subgraph.
   - Serialize into Cytoscape.js / NetworkX compatible JSON format with node attributes and edge provenance labels.
6. **Full Graph Rebuild Script (`rebuild_graph.py`):**
   - Provide a deterministic CLI command: `poetry run python -m src.rxguard.graph.rebuild_graph`.
   - Iterates all canonical concepts, products, passages, and rules in PostgreSQL, reconstructing the entire Neo4j graph from scratch.

---

## 5. Detailed Project Roadmap & Relevant Phases

- **Phase 0:** Review documentation blueprint and shared contracts (*Done*).
- **Phase 1:** Verify Neo4j 5.20+ container configuration in Docker Compose.
- **Phase 3:** Verify availability of Mudit's seeded 500 medication concepts in PostgreSQL.
- **Phase 5:** Implement `schema.py`, `client.py`, and `sync_worker.py`; sync the 500 concepts.
- **Phase 9:** Build `query_service.py` and deliver graph candidate expansion to Vasu.
- **Phase 12:** Build `subgraph_service.py` and collaborate with Lakshay on the Evidence Navigator UI.
- **Phase 14:** Verify graph rebuild script and support production release demonstration.

---

## 6. Shared Contracts Consumed & Produced

You consume and populate the shared Pydantic contracts from `src/rxguard/core/contracts/`:
- `MedicationConcept`, `DrugProduct`, `SourceDocument`, `EvidencePassage`: Consumed from Mudit's canonical store to build nodes.
- `SafetyFinding`: Consumed from Lakshay to build finding nodes and provenance links.

---

## 7. Data & API Interfaces Provided to Teammates

### Interface Provided to Vasu (Graph-Assisted Retrieval):
```python
# src/rxguard/graph/query_service.py
from typing import List, Dict, Any

class GraphQueryService:
    async def get_expansion_candidates(self, rxcui: str) -> List[Dict[str, Any]]:
        """
        Traverses Neo4j to find adjacent ingredients, conditions,
        and evidence passage IDs for a target medication concept.
        """
        ...
```

### Interface Provided to Lakshay (Evidence Navigator UI):
```python
# src/rxguard/graph/subgraph_service.py
from typing import Dict, Any

class SubgraphService:
    async def get_provenance_subgraph(self, finding_id: str) -> Dict[str, Any]:
        """
        Extracts the complete traceable path for a safety finding:
        Medication -> Ingredient -> Condition/Food -> Finding -> Rule -> Passage -> Document.
        Returns a Cytoscape/NetworkX-compatible JSON structure.
        """
        ...
```

---

## 8. Sample Cypher Query Patterns (Illustrative Specifications)

### 8.1. Pairwise Drug Interaction Traversal
```cypher
MATCH (m1:MedicationConcept {rxcui: $rxcui_1})-[:HAS_INGREDIENT]->(i1:Ingredient)
MATCH (m2:MedicationConcept {rxcui: $rxcui_2})-[:HAS_INGREDIENT]->(i2:Ingredient)
MATCH (m1)-[r:HAS_INTERACTION_EVIDENCE]->(p:EvidencePassage)<-[:HAS_INTERACTION_EVIDENCE]-(m2)
RETURN m1.canonical_name AS drug_1, 
       m2.canonical_name AS drug_2, 
       r.severity AS severity, 
       p.passage_id AS passage_id, 
       p.text AS evidence_text;
```

### 8.2. Traceable Evidence Navigator Provenance Subgraph
```cypher
MATCH path = (f:SafetyFinding {finding_id: $finding_id})-[:EVIDENCED_BY]->(p:EvidencePassage)
             -[:SUPPORTED_BY]->(m:MedicationConcept)-[:HAS_INGREDIENT]->(i:Ingredient)
OPTIONAL MATCH (m)-[:APPLIES_TO_PRODUCT]->(prod:DrugProduct)
RETURN path;
```

---

## 9. Testing Requirements & Acceptance Criteria

### Unit & Integration Tests Required:
- `test_graph_constraints`: Verify that inserting duplicate RxCUIs or NDCs is rejected by Neo4j constraints.
- `test_idempotent_sync`: Run the sync worker twice on identical input data; verify graph node count and edge count remain unchanged.
- `test_subgraph_serialization`: Verify that `get_provenance_subgraph` produces valid, connected JSON without circular reference errors.
- `test_rebuild_graph`: Execute `rebuild_graph.py` on an empty Neo4j test database; verify 100% parity with PostgreSQL records.

### Acceptance Criteria:
1. Neo4j graph operations execute in $< 50\text{ms}$ for up to 3-hop traversals.
2. Complete test mocking for Neo4j driver during CI runs using `pytest-mock` or embedded testcontainers.
3. Code achieves $\ge 85\%$ test coverage; `mypy --strict` passes cleanly.

---

## 10. Failure Modes & Edge Cases

- **Neo4j Service Disconnection:** If Neo4j is temporarily unreachable, the system must log a warning and fall back to purely relational/vector search. **Neo4j downtime must not take down the entire API.**
- **Stale Graph Relationships:** If a regulatory label is updated in DailyMed, the sync worker must delete or archive old `HAS_INTERACTION_EVIDENCE` edges before creating new ones.
- **Dangling Nodes:** When synchronizing an ingredient or product, ensure the parent `MedicationConcept` exists first to prevent orphaned entities.

---

## 11. Git Workflow & Definition of Done

- **Branch:** `feature/hardik-knowledge-graph`
- **Commit Convention:** `feat(graph): ...`, `test(neo4j): ...`, `fix(sync): ...`
- **PR Target:** `main` (requires review from Lakshay, Mudit, or Vasu).
- **Definition of Done:**
  1. All assigned modules implemented in `src/rxguard/graph/`.
  2. Cypher constraint scripts deployed and tested.
  3. Synchronization worker tested against PostgreSQL container.
  4. Interfaces verified against Lakshay's API contracts.

---

## 12. Ready-to-Use Implementation Prompt for Hardik's AI Agent

Copy and paste the prompt below directly into your AI coding assistant:

```text
You are pair programming with Hardik, Lead Knowledge Graph & Graph Intelligence Engineer on RxGuard-RAG.

Your mission is to implement Workstream 3 on branch 'feature/hardik-knowledge-graph':
1. Configure Neo4j 5.20+ client and async connection pool in 'src/rxguard/graph/client.py'.
2. Define Neo4j node labels (MedicationConcept, DrugProduct, Ingredient, Condition, Food, Allergen, EvidencePassage, SafetyFinding) and uniqueness constraints in 'schema.py'.
3. Build the asynchronous PostgreSQL-to-Neo4j sync worker in 'sync_worker.py' using idempotent Cypher MERGE queries with source provenance properties.
4. Implement multi-hop graph traversal and candidate expansion in 'query_service.py'.
5. Build the Evidence Navigator provenance subgraph serializer in 'subgraph_service.py' returning Cytoscape/NetworkX-compatible JSON.
6. Write the complete graph rebuild script in 'rebuild_graph.py' to rehydrate Neo4j from PostgreSQL.
7. Write unit and integration tests in 'tests/unit/' and 'tests/integration/' covering constraints, idempotent sync, and traversal queries.

Strict constraints:
- Do NOT edit files in 'src/rxguard/ingestion/', 'src/rxguard/retrieval/', or 'src/rxguard/safety/'.
- PostgreSQL is the canonical source of truth; Neo4j is a derived store.
- Ensure mypy --strict and ruff check pass cleanly.
- Maintain test coverage >= 85%.
```

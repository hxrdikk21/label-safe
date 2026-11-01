# Mudit Bansal — Data Engineering & Medication Knowledge Blueprint

> **Role:** Lead Data & Medication Knowledge Engineer  
> **Repository:** [DAREDEVIL-OF-NEXUS/RxGuard-RAG](https://github.com/DAREDEVIL-OF-NEXUS/RxGuard-RAG)  
> **Assigned Branch:** `feature/mudit-data`  
> **Assigned Workstream:** Source Adapters, Clinical Label Parsing, RxNorm Terminology Normalization, PostgreSQL Canonical Data Model & Ingestion Pipelines  
> **Version:** 2.0.0 (Four-Team Master Specification)  
> **Date:** October 2026

---

## 1. Project Context & Mission

RxGuard-RAG is an evidence-grounded medication safety intelligence platform combining deterministic clinical safety rules with advanced Retrieval-Augmented Generation (Self-RAG-inspired) and a dedicated Neo4j knowledge graph.

Your mission as the **Lead Data Engineer** is to build the authoritative, normalized data layer upon which the entire system depends:
1. Build external adapters for DailyMed (SPL XML), openFDA, and NIH RxNav (RxNorm).
2. Seed the initial **500 high-priority medication concepts** and associate them with verified regulatory labels.
3. Enforce **cache-first / local-first lookup** with a 7-day negative caching policy for 404s.
4. Maintain the **canonical PostgreSQL relational models** as the single source of truth.
5. Provide clean, idempotent data synchronization interfaces for Vasu (Vector retrieval) and Hardik (Neo4j graph).

You ensure that every piece of clinical text indexed in the system carries an immutable SHA-256 fingerprint, LOINC section code, and source provenance.

---

## 2. Overall System Architecture & Your Layer

The system consists of five distinct layers:
- Layer A: Data Acquisition & Medication Knowledge (**Mudit — Your Layer**)
- Layer B: Persistent Data & Tri-Store Indexing (Joint: PostgreSQL by Mudit, pgvector by Vasu, Neo4j by Hardik)
- Layer C: Deterministic Medication Safety Engine (Lakshay)
- Layer D: Advanced RAG & Self-RAG Engine (Vasu)
- Layer E: Application, Personalization & Security (Lakshay)

You sit squarely at the foundation of Layer A and own the relational schema in Layer B.

---

## 3. Module Boundaries & Owned Files

You have exclusive write ownership over the following project paths:

```
src/rxguard/
├── ingestion/
│   ├── __init__.py
│   ├── dailymed.py          # DailyMed REST and SPL XML client
│   ├── openfda.py           # openFDA label and recall client (rate limited 240/min)
│   ├── rxnav.py             # NLM RxNav / RxNorm terminology resolver
│   ├── seed_loader.py       # Automated 500-concept database seeder
│   └── cache_manager.py     # Local-first lookup & negative caching worker
├── knowledge/
│   ├── __init__.py
│   ├── normalizer.py        # Brand-to-generic, RxCUI & UNII mapper
│   └── loinc_taxonomy.py    # LOINC clinical section definitions
├── database/
│   ├── __init__.py
│   ├── models.py            # Canonical SQLAlchemy 2.0 / SQLModel definitions
│   ├── connection.py        # Async engine & sessionmaker pool
│   └── sync_tracker.py      # derived_sync_status update utilities
data/
└── seed/
    └── top_500_concepts.json # Catalog of 500 high-priority medication concepts
tests/
└── unit/
    ├── test_dailymed.py     # Mocked SPL XML parsing tests
    ├── test_openfda.py      # openFDA rate-limiting and deduplication tests
    ├── test_rxnav.py        # RxNorm entity resolution tests
    └── test_cache_first.py  # Cache hit/miss and negative cache TTL tests
```

### Files You Must NOT Modify Unilaterally:
- `src/rxguard/core/contracts/*`: Shared contracts owned by Lakshay; requires team consensus.
- `src/rxguard/vector_store/*`: Owned by Vasu.
- `src/rxguard/graph/*`: Owned by Hardik.
- `src/rxguard/safety/*` & `src/rxguard/api/*`: Owned by Lakshay.

---

## 4. Exact Implementation Responsibilities

1. **DailyMed SPL Ingestion Pipeline:**
   - Fetch Structured Product Labeling (SPL) XMLs via DailyMed REST API.
   - Extract LOINC sections: Boxed Warning (`34066-1`), Contraindications (`34070-2`), Drug Interactions (`34073-6`), Warnings/Precautions (`43685-7`), Inactive Ingredients (`51727-6`), and Dietary/Food Precautions.
   - Strip XML/HTML tags while strictly preserving clinical tabular structures.
2. **openFDA Drug Labeling Adapter:**
   - Connect to `https://api.fda.gov/drug/label.json`.
   - Implement token-bucket rate limiter (240 req/min) and exponential backoff retry.
   - Deduplicate incoming records against DailyMed SetIDs using SHA-256 fingerprinting.
3. **RxNorm & RxNav Normalization Client:**
   - Resolve brand and generic strings to canonical RxCUIs and Term Types (`SCD`, `SBD`, `IN`).
   - Decompose multi-ingredient drugs (e.g., Augmentin -> Amoxicillin + Clavulanate).
   - Detect ambiguity (e.g., Metoprolol Tartrate vs Succinate) and flag `is_ambiguous=True`.
4. **The 500-Medication Seeder (`seed_loader.py`):**
   - Populate PostgreSQL with the curated list of 500 core outpatient and narrow-therapeutic-index drugs.
   - Execute idempotent batch ingestion with SHA-256 hashing.
5. **Cache-First Local Lookup & Negative Caching:**
   - On incoming query: check PostgreSQL cache first.
   - If not found or expired, query RxNav/DailyMed.
   - If external API returns 404, store negative cache entry with **7-day TTL**.
   - If external API fails (5xx/timeout), return explicit failure state; **never assume drug is safe**.
6. **Derived Sync Interface:**
   - Maintain the `derived_sync_status` table in PostgreSQL to notify Hardik's graph worker and Vasu's vector worker of new or updated passages.

---

## 5. Detailed Project Roadmap & Relevant Phases

- **Phase 0:** Review documentation blueprint and shared contracts (*Done*).
- **Phase 1:** Verify Docker Compose boots PostgreSQL 16 with required schemas.
- **Phase 2:** Implement `rxnav.py`, `dailymed.py`, `openfda.py`, and `models.py`.
- **Phase 3:** Curate `top_500_concepts.json` and deploy `seed_loader.py` and `cache_manager.py`.
- **Phase 5:** Expose canonical data hooks for Hardik's Neo4j sync worker.
- **Phase 7:** Support Lakshay in validating deterministic safety rules with seed data (CORE MVP).
- **Phase 14:** Verify production data refresh and final demonstration readiness.

---

## 6. Shared Contracts Consumed & Produced

You consume and populate the shared Pydantic contracts from `src/rxguard/core/contracts/`:
- `MedicationConcept`: Produced by `normalizer.py`.
- `DrugProduct`: Produced by `dailymed.py` and `openfda.py`.
- `SourceDocument`: Produced by ingestion pipeline.
- `EvidencePassage`: Produced by section extraction worker.

---

## 7. Data & API Interfaces Provided to Teammates

### Interface Provided to Lakshay (Safety Engine & API):
```python
# src/rxguard/knowledge/normalizer.py
from src.rxguard.core.contracts.medication import MedicationConcept

class MedicationNormalizer:
    async def normalize(self, query: str, jurisdiction: str = "US") -> MedicationConcept:
        """
        Resolves a user-entered medication string to a canonical MedicationConcept.
        Checks local PostgreSQL cache first. Queries RxNav API on cache miss.
        """
        ...
```

### Interface Provided to Vasu (Vector & Hybrid Retrieval):
```python
# src/rxguard/database/passage_repository.py
from typing import List, Optional
from src.rxguard.core.contracts.evidence import EvidencePassage

class PassageRepository:
    async def get_passages_by_rxcui(
        self, rxcui: str, loinc_section: Optional[str] = None
    ) -> List[EvidencePassage]:
        """Fetches canonical raw text passages for vectorization or lexical filtering."""
        ...
```

### Interface Provided to Hardik (Neo4j Knowledge Graph):
```python
# src/rxguard/database/sync_tracker.py
from typing import List, Dict, Any

class SyncTracker:
    async def get_pending_sync_entities(self, target_store: str = "NEO4J") -> List[Dict[str, Any]]:
        """Returns canonical concepts, products, and rules awaiting graph ingestion."""
        ...
    async def mark_synced(self, entity_id: str, target_store: str = "NEO4J") -> None:
        """Marks entity as successfully synchronized in derived_sync_status."""
        ...
```

---

## 8. Testing Requirements & Acceptance Criteria

### Unit Tests Required (`tests/unit/`):
- `test_dailymed_parser`: Verify extraction of Section 7 (`34073-6`) and Contraindications (`34070-2`) from cached XML fixtures.
- `test_openfda_rate_limiter`: Mock 300 rapid requests; ensure rate limiter restricts dispatch to 240 req/min.
- `test_rxnav_normalizer`: Verify normalization of brand names (e.g., "Lipitor" -> Atorvastatin RxCUI `83367`) and salt forms.
- `test_cache_first_lookup`: Test cache hit (0 HTTP calls), cache miss (1 HTTP call + cache write), and negative cache TTL.

### Acceptance Criteria:
1. 100% of network calls mocked in unit tests using `pytest-mock` or `respx`.
2. Deterministic ingestion: running seeder twice produces identical database hashes with zero duplicate rows.
3. Code achieves $\ge 85\%$ test coverage and passes `mypy --strict` and `ruff check`.

---

## 9. Failure Modes & Edge Cases

- **External API Outage:** If DailyMed or RxNav fails, the system logs the failure and falls back to local cached snapshots. It never fabricates an empty label.
- **Ambiguous Brand Query:** If a brand query maps to multiple active ingredient formulations, set `is_ambiguous=True` and list all candidate RxCUIs.
- **Missing Inactive Ingredients:** If LOINC `51727-6` is missing from an SPL label, explicitly record `missing_excipient_data=True` rather than an empty list.

---

## 10. Git Workflow & Definition of Done

- **Branch:** `feature/mudit-data`
- **Commit Convention:** `feat(ingestion): ...`, `fix(normalizer): ...`, `test(data): ...`
- **PR Target:** `main` (requires review from Lakshay, Vasu, or Hardik).
- **Definition of Done:**
  1. All assigned modules implemented in designated directories.
  2. Unit tests pass with $\ge 85\%$ coverage.
  3. Alembic migration scripts tested against PostgreSQL container.
  4. Interfaces verified against shared Pydantic contracts.

---

## 11. Ready-to-Use Implementation Prompt for Mudit's AI Agent

Copy and paste the prompt below directly into your AI coding assistant:

```text
You are pair programming with Mudit Bansal, Lead Data & Medication Knowledge Engineer on RxGuard-RAG.

Your mission is to implement Workstream 1 on branch 'feature/mudit-data':
1. Implement source adapters in 'src/rxguard/ingestion/' for DailyMed (SPL XML parser extracting LOINC sections 34066-1, 34070-2, 34073-6, 43685-7, 51727-6), openFDA (with 240 req/min rate limiter and SHA-256 deduplication), and NIH RxNav (resolving brand/generic strings to RxCUIs and UNII ingredients).
2. Build canonical PostgreSQL models in 'src/rxguard/database/models.py' using SQLAlchemy 2.0 for users, medication_concepts, drug_products, source_documents, evidence_passages, and derived_sync_status.
3. Build 'seed_loader.py' and 'data/seed/top_500_concepts.json' to seed 500 high-priority medication concepts.
4. Implement local-first / cache-first lookup in 'cache_manager.py' with 7-day negative caching for 404s.
5. Provide the 'MedicationNormalizer' and 'SyncTracker' interfaces.
6. Write unit tests in 'tests/unit/' mocking all external HTTP calls with respx/pytest-mock.

Strict constraints:
- Do NOT edit files in 'src/rxguard/retrieval/', 'src/rxguard/graph/', or 'src/rxguard/safety/'.
- Adhere strictly to the Pydantic schemas in 'src/rxguard/core/contracts/'.
- Ensure mypy --strict and ruff check pass cleanly.
- Maintain test coverage >= 85%.
```

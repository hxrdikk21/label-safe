# RxGuard-RAG: Central Project Execution Tracker & Task Checklist

> **Repository:** [DAREDEVIL-OF-NEXUS/RxGuard-RAG](https://github.com/DAREDEVIL-OF-NEXUS/RxGuard-RAG)  
> **Team:** Lakshay Bharti, Vasu Mittal, Mudit Bansal, Hardik  
> **Version:** 2.0.0  
> **Date:** October 2026

---

## 1. Checklist Maintenance Convention & Status Definitions

All team members must maintain this checklist throughout project execution. When starting, completing, or blocking a task:
1. Update the status tag:
   - `[DONE]`: Completed, tested, and merged into `main`.
   - `[IN PROGRESS]`: Currently being implemented on an active feature branch.
   - `[REVIEW]`: PR open, awaiting peer review and CI check completion.
   - `[BLOCKED]`: Waiting on a prerequisite deliverable or dependency.
   - `[NOT STARTED]`: Planned for upcoming phase; work has not begun.
2. Toggle the Markdown checkbox (`[ ]` to `[x]`).
3. Add a log entry in Section 15 (Changelog & Update History).

---

## 2. Phase 0: Repository Foundation & Documentation Blueprint

- [x] **Task 0.1: Initialize Git & Repository Scaffold**  
  *Owner:* Lakshay | *Phase:* 0 | *Dependencies:* None | *Status:* `DONE`  
  *Acceptance Criteria:* Git initialized on `main`, remote configured to `DAREDEVIL-OF-NEXUS/RxGuard-RAG`, directory scaffold created with `.gitkeep` placeholders.
- [x] **Task 0.2: Author Master Architecture Blueprint (`architecture.md`)**  
  *Owner:* Lakshay (lead) with Mudit, Vasu, Hardik | *Phase:* 0 | *Dependencies:* None | *Status:* `DONE`  
  *Acceptance Criteria:* 5 layers, 15 Mermaid diagrams, ADRs, tri-store consistency model, and shared contracts defined.
- [x] **Task 0.3: Author Phased Implementation Roadmap (`phases.md`)**  
  *Owner:* Lakshay | *Phase:* 0 | *Dependencies:* Task 0.2 | *Status:* `DONE`  
  *Acceptance Criteria:* 15 phases (Phases 0–14) documented with owners, deliverables, tests, and criteria.
- [x] **Task 0.4: Author Clinical Data Catalog & Tri-Store Schemas (`data.md`)**  
  *Owner:* Mudit & Hardik | *Phase:* 0 | *Dependencies:* Task 0.2 | *Status:* `DONE`  
  *Acceptance Criteria:* DailyMed, openFDA, RxNav, 500-seed strategy, PostgreSQL DDL, Neo4j Cypher, and 50-case evaluation plan documented.
- [x] **Task 0.5: Author Individual Member Blueprints (`Mudit.md`, `Vasu.md`, `Hardik.md`, `Lakshay.md`)**  
  *Owner:* All | *Phase:* 0 | *Dependencies:* Tasks 0.2, 0.3 | *Status:* `DONE`  
  *Acceptance Criteria:* Self-contained instructions with ready-to-use coding agent prompts for all four workstreams.
- [x] **Task 0.6: Author Master Project README (`README.md`)**  
  *Owner:* Lakshay | *Phase:* 0 | *Dependencies:* Tasks 0.2–0.5 | *Status:* `DONE`  
  *Acceptance Criteria:* Comprehensive project overview covering all clinical, technical, and operational facets.

---

## 3. Phase 1: Shared Contracts & Multi-Database Environment

- [x] **Task 1.1: Docker Compose Configuration (PostgreSQL, pgvector, Neo4j, Redis)**  
  *Owner:* Lakshay | *Phase:* 1 | *Dependencies:* Phase 0 | *Status:* `DONE`  
  *Acceptance Criteria:* `docker compose up` brings up PostgreSQL 16 with pgvector extension, Neo4j 5.20+, and Redis with persistent volume mounts.
- [x] **Task 1.2: Implement Canonical Pydantic Schemas (`src/rxguard/core/contracts/`)**  
  *Owner:* Lakshay | *Phase:* 1 | *Dependencies:* Task 1.1 | *Status:* `DONE`  
  *Acceptance Criteria:* 8 shared contracts implemented with strict typing and schema serialization unit tests.
- [x] **Task 1.3: Configure CI Pipeline & Linters (Ruff, Mypy, Pytest)**  
  *Owner:* Lakshay | *Phase:* 1 | *Dependencies:* Task 1.1 | *Status:* `DONE`  
  *Acceptance Criteria:* GitHub Actions workflow verifies linting, formatting, and contract tests on every PR.

---

## 4. Phase 2: PostgreSQL Schema & Source Ingestion Adapters

- [x] **Task 2.1: PostgreSQL Relational Models & Alembic Migrations**  
  *Owner:* Mudit | *Phase:* 2 | *Dependencies:* Phase 1 | *Status:* `DONE`  
  *Acceptance Criteria:* Tables for concepts, products, source documents, evidence passages, rules, and sync status created.
- [x] **Task 2.2: DailyMed SPL XML Parser & Section Extractor**  
  *Owner:* Mudit | *Phase:* 2 | *Dependencies:* Task 2.1 | *Status:* `DONE`  
  *Acceptance Criteria:* Extracts LOINC sections 34066-1, 34070-2, 34073-6, 43685-7, 51727-6 cleanly with table preservation.
- [x] **Task 2.3: openFDA Drug Labeling REST Adapter**  
  *Owner:* Mudit | *Phase:* 2 | *Dependencies:* Task 2.1 | *Status:* `DONE`  
  *Acceptance Criteria:* REST client with 240 req/min rate limiter and SHA-256 deduplication against DailyMed SetIDs.
- [x] **Task 2.4: RxNorm / RxNav Normalization Client**  
  *Owner:* Mudit | *Phase:* 2 | *Dependencies:* Task 2.1 | *Status:* `DONE`  
  *Acceptance Criteria:* Maps raw query strings to canonical RxCUIs, active moieties, and ingredient UNIIs.

---

## 5. Phase 3: 500-Medication Seed & Cache-First Lookup

- [x] **Task 3.1: Curate 500 High-Priority Medication Concepts Catalog**  
  *Owner:* Mudit | *Phase:* 3 | *Dependencies:* Phase 2 | *Status:* `DONE`  
  *Acceptance Criteria:* JSON seed file containing top 200 outpatient, top 150 NTI, and top 150 interaction-prone drugs.
- [x] **Task 3.2: Automated Seeding Pipeline**  
  *Owner:* Mudit | *Phase:* 3 | *Dependencies:* Task 3.1 | *Status:* `DONE`  
  *Acceptance Criteria:* Script populates PostgreSQL with 500 canonical concepts and associated DailyMed SPL passages.
- [x] **Task 3.3: Cache-First Local Lookup & Negative Caching Worker**  
  *Owner:* Mudit | *Phase:* 3 | *Dependencies:* Task 3.2 | *Status:* `DONE`  
  *Acceptance Criteria:* Queries check local PostgreSQL first; missing items hit external APIs; genuine 404s cached with 7-day TTL.

---

## 6. Phase 4: Chunking, Embeddings, Lexical & Vector Retrieval

- [x] **Task 4.1: Clinical Boundary Chunker with Contextual Headers**  
  *Owner:* Vasu | *Phase:* 4 | *Dependencies:* Phase 3 | *Status:* `DONE`  
  *Acceptance Criteria:* Chunks label sections into 300–500 token windows with drug/section semantic header injection.
- [x] **Task 4.2: pgvector Vector Storage & Dense Embedding Interface**  
  *Owner:* Vasu | *Phase:* 4 | *Dependencies:* Task 4.1 | *Status:* `DONE`  
  *Acceptance Criteria:* Embeddings generated and indexed via HNSW index (`m=16, ef_construction=64`); cosine latency < 80ms.
- [x] **Task 4.3: PostgreSQL tsvector GIN Lexical Search**  
  *Owner:* Vasu | *Phase:* 4 | *Dependencies:* Task 4.1 | *Status:* `DONE`  
  *Acceptance Criteria:* Full-text search over clinical passages preserving exact chemical names and dosages.
- [x] **Task 4.4: Reciprocal Rank Fusion (RRF) & Cross-Encoder Reranker**  
  *Owner:* Vasu | *Phase:* 4 | *Dependencies:* Tasks 4.2, 4.3 | *Status:* `DONE`  
  *Acceptance Criteria:* Merges vector and lexical results with RRF (k=60); reranks top 25 down to top 5 high-precision passages.

---

## 7. Phase 5: Neo4j Schema & Graph Synchronization

- [x] **Task 5.1: Neo4j Constraints, Node Labels & Relationship Types**  
  *Owner:* Hardik | *Phase:* 5 | *Dependencies:* Phase 3 | *Status:* `DONE`  
  *Acceptance Criteria:* Constraints applied for MedicationConcept, DrugProduct, Ingredient, Condition, Food, Passage.
- [x] **Task 5.2: Asynchronous PostgreSQL-to-Neo4j Sync Worker**  
  *Owner:* Hardik | *Phase:* 5 | *Dependencies:* Task 5.1 | *Status:* `DONE`  
  *Acceptance Criteria:* Worker reads canonical PostgreSQL records and executes idempotent Cypher `MERGE` statements with provenance.
- [x] **Task 5.3: Graph Traversal & Subgraph Extraction Service**  
  *Owner:* Hardik | *Phase:* 5 | *Dependencies:* Task 5.2 | *Status:* `DONE`  
  *Acceptance Criteria:* Cypher service returns multi-hop evidence subgraphs for any target RxCUI.

---

## 8. Phase 6 & 7: Safety Engine & Four Clinical Workflows (CORE MVP)

- [x] **Task 6.1: Master Safety Engine Orchestrator**  
  *Owner:* Lakshay | *Phase:* 6 | *Dependencies:* Phases 4, 5 | *Status:* `DONE`  
  *Acceptance Criteria:* Coordinates deterministic screening, missing data handling, and fail-safe result formatting.
- [x] **Task 7.1: Pairwise Drug–Drug Interaction (DDI) Checker**  
  *Owner:* Lakshay | *Phase:* 7 | *Dependencies:* Task 6.1 | *Status:* `DONE`  
  *Acceptance Criteria:* Evaluates $n(n-1)/2$ medication pairs against validated rules and DailyMed Section 7 evidence.
- [x] **Task 7.2: Drug–Food Interaction (DFI) Checker**  
  *Owner:* Lakshay | *Phase:* 7 | *Dependencies:* Task 6.1 | *Status:* `DONE`  
  *Acceptance Criteria:* Matches medications against dietary items (Grapefruit, Calcium/Dairy, Tyramine, Alcohol).
- [x] **Task 7.3: Drug–Condition Contraindication (DCI) Checker**  
  *Owner:* Lakshay | *Phase:* 7 | *Dependencies:* Task 6.1 | *Status:* `DONE`  
  *Acceptance Criteria:* Distinguishes absolute Boxed Contraindications from relative Warnings/Precautions mapped to ICD-10.
- [x] **Task 7.4: Medication Allergy & Excipient Checker**  
  *Owner:* Lakshay | *Phase:* 7 | *Dependencies:* Task 6.1 | *Status:* `DONE`  
  *Acceptance Criteria:* Cross-matches patient allergy profile against active moieties and inactive excipient UNIIs.
- [x] **Task 7.5: End-to-End Core MVP Integration (`POST /api/v1/safety/analyze`)**  
  *Owner:* Lakshay (lead) with Team | *Phase:* 7 | *Dependencies:* Tasks 7.1–7.4 | *Status:* `DONE`  
  *Acceptance Criteria:* **CORE MVP MILESTONE.** Full system executes all 4 workflows in < 2.5s with zero unhandled exceptions.

---

## 9. Phase 8: Self-RAG Critique & Corrective Retrieval (CRAG)

- [x] **Task 8.1: Corrective RAG (CRAG) Confidence Evaluator**  
  *Owner:* Vasu | *Phase:* 8 | *Dependencies:* Phase 7 | *Status:* `DONE`  
  *Acceptance Criteria:* Scores retrieval relevance; triggers bounded query rewrite (scores 0.40–0.74) or safe abstention (< 0.40).
- [x] **Task 8.2: Query Decomposer & Bounded Rewriter**  
  *Owner:* Vasu | *Phase:* 8 | *Dependencies:* Task 8.1 | *Status:* `DONE`  
  *Acceptance Criteria:* Decomposes multi-morbid queries into targeted sub-queries; limits retries to max 2 iterations.
- [x] **Task 8.3: Self-RAG-Inspired Reflection Tokens & Answer Critique**  
  *Owner:* Vasu | *Phase:* 8 | *Dependencies:* Task 8.2 | *Status:* `DONE`  
  *Acceptance Criteria:* Evaluates answer faithfulness against cited passages; suppresses ungrounded or contradictory assertions.

---

## 10. Phase 9: Graph-Assisted Retrieval & Evidence Verification

- [x] **Task 9.1: Graph-Assisted Candidate Expansion**  
  *Owner:* Hardik & Vasu | *Phase:* 9 | *Dependencies:* Phases 5, 8 | *Status:* `DONE`  
  *Acceptance Criteria:* Traverses Neo4j to find adjacent contraindications and ingredients to enrich hybrid search context.
- [x] **Task 9.2: Sentence-Level NLI Claim-to-Source Verifier**  
  *Owner:* Lakshay | *Phase:* 9 | *Dependencies:* Phase 8 | *Status:* `DONE`  
  *Acceptance Criteria:* NLI cross-encoder scores sentence-to-passage entailment; attaches `VERIFIED` vs `UNVERIFIED` badges.

---

## 11. Phase 10: Personalized Chatbot & User Context

- [x] **Task 10.1: User Profile & Clinical Context Storage**  
  *Owner:* Lakshay | *Phase:* 10 | *Dependencies:* Phase 7 | *Status:* `DONE`  
  *Acceptance Criteria:* PostgreSQL schemas and APIs for user active medications, conditions, and allergy history.
- [x] **Task 10.2: Safety-Grounded Chatbot Orchestrator (`POST /api/v1/chat/message`)**  
  *Owner:* Lakshay | *Phase:* 10 | *Dependencies:* Task 10.1 | *Status:* `DONE`  
  *Acceptance Criteria:* Chatbot retrieves only authorized user context; prevents cross-user leakage; grounds replies in safety findings.

---

## 12. Phase 11: Authentication, RBAC, 2FA & Emergency Contacts

- [x] **Task 11.1: Authentication & Argon2id Password Hashing**  
  *Owner:* Lakshay | *Phase:* 11 | *Dependencies:* Phase 10 | *Status:* `DONE`  
  *Acceptance Criteria:* JWT issuance with RS256/HS256, expiration <= 60m, refresh token rotation, and rate-limited login.
- [x] **Task 11.2: Role-Based Access Control (RBAC: `ROLE_USER`, `ROLE_ADMIN`)**  
  *Owner:* Lakshay | *Phase:* 11 | *Dependencies:* Task 11.1 | *Status:* `DONE`  
  *Acceptance Criteria:* Enforces user ownership decorators on all patient endpoints; admin endpoints restricted.
- [x] **Task 11.3: Two-Factor Authentication (TOTP RFC 6238)**  
  *Owner:* Lakshay | *Phase:* 11 | *Dependencies:* Task 11.1 | *Status:* `DONE`  
  *Acceptance Criteria:* QR code secret provisioning, 6-digit TOTP verification, and encrypted backup recovery codes.
- [x] **Task 11.4: Consent-Driven Emergency Contacts Workflow**  
  *Owner:* Lakshay | *Phase:* 11 | *Dependencies:* Task 11.1 | *Status:* `DONE`  
  *Acceptance Criteria:* User-managed emergency contacts; zero automated broadcast without explicit step-by-step confirmation.

---

## 13. Phase 12: RxGuard Evidence Navigator (Flagship Wow Feature)

- [x] **Task 12.1: Subgraph API & Provenance Serializer**  
  *Owner:* Hardik | *Phase:* 12 | *Dependencies:* Phases 5, 9 | *Status:* `DONE`  
  *Acceptance Criteria:* Endpoint `GET /api/v1/evidence/subgraph/{finding_id}` returns Cytoscape/NetworkX-compatible JSON.
- [x] **Task 12.2: Interactive Evidence Navigator Visualization Component**  
  *Owner:* Lakshay & Hardik | *Phase:* 12 | *Dependencies:* Task 12.1 | *Status:* `DONE`  
  *Acceptance Criteria:* UI renders interactive graph linking user input -> normalized entity -> finding -> rule -> passage -> claim.

---

## 14. Phase 13 & 14: Evaluation, Hardening & Deployment

- [x] **Task 13.1: 50-Scenario Gold-Standard Evaluation Harness**  
  *Owner:* Lakshay & Vasu | *Phase:* 13 | *Dependencies:* Phases 8, 9 | *Status:* `DONE`  
  *Acceptance Criteria:* Measures Precision@K, Recall@K, MRR, RAGAS Faithfulness, and clinical safety sensitivity across 4 RAG tiers.
- [x] **Task 13.2: Security Hardening & Vulnerability Scan**  
  *Owner:* Lakshay | *Phase:* 13 | *Dependencies:* Phase 11 | *Status:* `DONE`  
  *Acceptance Criteria:* Zero critical issues in `bandit` and `safety` scans; sanitized audit logging verified.
- [ ] **Task 14.1: Production Docker Compose & Final Release**  
  *Owner:* Joint Team | *Phase:* 14 | *Dependencies:* All preceding phases | *Status:* `IN PROGRESS`  
  *Acceptance Criteria:* Single-command deployment (`docker compose -f deployment/docker-compose.prod.yml up`); demonstration video produced.  
  *Note:* Single-command deployment done and verified (`deployment/docker-compose.prod.yml`); demonstration video not yet recorded.

---

## 15. Changelog & Update History

| Date | Author | Tasks Modified | Summary of Updates |
|---|---|---|---|
| 2026-10-15 | Lakshay | Tasks 0.1 – 0.6 | Initialized Master 4-team checklist; marked all Phase 0 documentation foundation tasks as DONE. |
| 2026-10-16 | Hardik (team-approved integration) | Tasks 1.1 – 13.2 | Merged all workstreams into `main` via `integration/merge-all`; added CI, compose stacks and Dockerfile; fixed four runtime crashes and a registration privilege escalation; persisted users/credentials/profiles (migration 0002); added refresh rotation, login rate limiting, the Evidence Navigator UI, graph sync worker and optional real model backends. 373 tests, 95% coverage, ruff and mypy --strict clean; bandit: 0 high, pip-audit: 0 known vulnerabilities. |
| 2026-10-16 | Hardik | Task 14.1 | Production stack verified end-to-end (PostgreSQL → graph-sync → Neo4j → Evidence Navigator); demonstration video outstanding. |

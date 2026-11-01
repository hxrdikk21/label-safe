# Lakshay Bharti — Safety Engine, Platform, Security & Integration Blueprint

> **Role:** Project Lead, Safety Systems Architect & Platform Integration Engineer  
> **Repository:** [DAREDEVIL-OF-NEXUS/RxGuard-RAG](https://github.com/DAREDEVIL-OF-NEXUS/RxGuard-RAG)  
> **Assigned Branch:** `feature/lakshay-safety-platform`  
> **Assigned Workstream:** Canonical Pydantic Contracts, Deterministic Safety Engine (DDI, DFI, DCI, Allergies), FastAPI Gateway, Authentication, RBAC, 2FA, Personalized Chatbot, Claim Verification & System Evaluation  
> **Version:** 2.0.0 (Four-Team Master Specification)  
> **Date:** October 2026

---

## 1. Project Context & Mission

RxGuard-RAG is an evidence-grounded medication safety intelligence platform designed to eliminate the risks of language model hallucinations in clinical settings. The platform pairs deterministic clinical safety screening with advanced Retrieval-Augmented Generation (Self-RAG-inspired) and a dedicated Neo4j knowledge graph.

Your mission as **Project Lead and Safety Systems Architect** is to maintain technical coherence across all four workstreams and enforce strict clinical safety:
1. Maintain the canonical system-wide **Pydantic contracts** in `src/rxguard/core/contracts/`.
2. Implement the **Deterministic Medication Safety Engine** spanning all four screening categories: Drug–Drug (DDI), Drug–Food (DFI), Drug–Condition (DCI), and Allergy/Excipient cross-sensitivities.
3. Build the **FastAPI gateway** and routing layer.
4. Architect the **Security & Personalization layer**: Argon2id password hashing, JWT sessions, Role-Based Access Control (RBAC), Two-Factor Authentication (2FA - TOTP RFC 6238), and consent-driven emergency contacts.
5. Deploy the **personalized, context-isolated medication safety chatbot**.
6. Implement **claim-level citation verification** using NLI entailment.
7. Integrate the flagship **RxGuard Evidence Navigator** with Hardik's subgraph API.
8. Lead the **50-scenario benchmark evaluation** and final release orchestration.

---

## 2. Overall System Architecture & Your Layer

The system consists of five distinct layers:
- Layer A: Data Acquisition & Medication Knowledge (Mudit)
- Layer B: Persistent Data & Tri-Store Indexing (Joint: PostgreSQL by Mudit, pgvector by Vasu, Neo4j by Hardik)
- Layer C: Deterministic Medication Safety Engine (**Lakshay — Your Layer**)
- Layer D: Advanced RAG & Self-RAG Engine (Vasu)
- Layer E: Application, Personalization & Security (**Lakshay — Your Layer**)

You own the symbolic safety logic in Layer C and the user-facing application, security, and integration layers in Layer E.

---

## 3. Module Boundaries & Owned Files

You have exclusive write ownership over the following project paths:

```
src/rxguard/
├── core/
│   ├── __init__.py
│   ├── config.py              # Pydantic BaseSettings (environment variables)
│   └── contracts/             # Canonical System-Wide Pydantic Data Contracts
│       ├── __init__.py
│       ├── medication.py      # MedicationConcept
│       ├── product.py         # DrugProduct
│       ├── document.py        # SourceDocument
│       ├── evidence.py        # EvidencePassage & SourceEvidence
│       ├── safety.py          # SafetyFinding, Severity, Status enums
│       ├── rag_response.py    # RAGResponse, VerifiedCitation
│       └── user_context.py    # UserContext, UserAllergyRecord, UserConditionRecord
├── safety/
│   ├── __init__.py
│   ├── engine.py              # Master Deterministic Safety Orchestrator
│   ├── ddi.py                 # Pairwise Drug-Drug interaction matcher
│   ├── dfi.py                 # Drug-Food interaction matcher
│   ├── contraindications.py   # Condition-to-Drug contraindication matcher
│   ├── allergies.py           # Ingredient and excipient allergy matcher
│   └── rules_db.py            # Local SQLite / relational rule repository
├── api/
│   ├── __init__.py
│   ├── main.py                # FastAPI application entrypoint
│   ├── middleware.py          # Request tracing, rate limiting & error handling
│   └── routes/
│       ├── __init__.py
│       ├── health.py          # Liveness & readiness probes
│       ├── safety.py          # POST /api/v1/safety/analyze
│       ├── chat.py            # POST /api/v1/chat/message
│       ├── auth.py            # POST /api/v1/auth/login, /register, /2fa
│       └── evidence.py        # GET /api/v1/evidence/subgraph/{finding_id}
├── auth/
│   ├── __init__.py
│   ├── jwt.py                 # JWT token generation, rotation & verification
│   ├── hasher.py              # Argon2id password hashing
│   ├── two_factor.py          # TOTP RFC 6238 2FA enrollment & validation
│   └── emergency.py           # Consent-driven emergency contact workflow
├── users/
│   ├── __init__.py
│   ├── service.py             # User profile, condition & allergy manager
│   └── context_guard.py       # User data isolation & authorization filters
├── chatbot/
│   ├── __init__.py
│   ├── orchestrator.py        # Personalized chat pipeline & history manager
│   └── prompt_manager.py      # Prompt construction with strict isolation
├── evidence/
│   ├── __init__.py
│   ├── claim_verifier.py      # NLI entailment checker (Claim-to-Passage)
│   └── navigator.py           # Evidence Navigator UI data serializer
└── evaluation/
    ├── __init__.py
    ├── harness.py             # Automated 50-case benchmark runner
    └── metrics.py             # RAGAS Faithfulness & Clinical Safety Sensitivity
tests/
├── contract/                  # Pydantic contract serialization tests
├── safety/                    # Deterministic rule unit tests (DDI, DFI, DCI, Allergies)
├── security/                  # Auth, RBAC, 2FA & user-data isolation tests
└── end_to_end/                # Full-pipeline integration tests
```

### Files You Must NOT Modify Unilaterally:
- `src/rxguard/ingestion/*` & `src/rxguard/knowledge/*`: Owned by Mudit.
- `src/rxguard/retrieval/*` & `src/rxguard/self_rag/*`: Owned by Vasu.
- `src/rxguard/graph/*`: Owned by Hardik.

---

## 4. Exact Implementation Responsibilities

1. **System-Wide Core Contracts:**
   - Define and version the 8 canonical Pydantic models in `src/rxguard/core/contracts/`.
   - Guarantee zero schema drift across Mudit, Vasu, Hardik, and Lakshay.
2. **Deterministic Medication Safety Engine (`src/rxguard/safety/`):**
   - **DDI Workflow:** Enumerate $n(n-1)/2$ medication pairs and evaluate against verified rules.
   - **DFI Workflow:** Check medications against dietary substances (Grapefruit, Calcium, Tyramine, Alcohol).
   - **DCI Workflow:** Match patient conditions (ICD-10) against Boxed Warnings and Contraindications.
   - **Allergy Workflow:** Match patient allergens against active moieties and inactive excipients (UNII).
   - **Structured Statuses:** Return `risk_identified`, `no_issue_found_in_checked_sources`, `insufficient_evidence`, `ambiguous_medication_identity`, `conflicting_evidence`, `requires_professional_review`, `check_unavailable`.
3. **FastAPI Gateway & Route Handlers:**
   - Implement `POST /api/v1/safety/analyze`, `POST /api/v1/chat/message`, `POST /api/v1/auth/login`, `POST /api/v1/auth/2fa/verify`, and `GET /api/v1/evidence/subgraph/{finding_id}`.
   - Inject the mandatory clinical safety disclaimer into every outgoing response.
4. **Security, RBAC, 2FA & Emergency Contacts:**
   - Hash passwords with Argon2id; issue short-lived JWTs (`exp <= 60m`).
   - Implement RBAC (`ROLE_USER`, `ROLE_ADMIN`).
   - Implement TOTP RFC 6238 2FA with secret provisioning and QR verification.
   - Implement the consent-based emergency contacts workflow.
5. **Personalized Chatbot Orchestrator (`src/rxguard/chatbot/`):**
   - Retrieve authorized user clinical profile (active medications, allergies, conditions).
   - Ground chatbot prompts in deterministic safety findings and retrieved evidence.
   - Enforce strict session isolation: user A's context can **never** be passed into user B's session.
6. **Sentence-Level NLI Claim Verification (`claim_verifier.py`):**
   - Decompose generated narrative explanation into atomic sentences.
   - Score entailment against cited passage text using NLI cross-encoder (`roberta-large-mnli`).
   - Attach `VERIFIED` or `UNVERIFIED` badges.
7. **Flagship Evidence Navigator Integration:**
   - Combine entity data (Mudit), rule findings (Lakshay), graph subgraphs (Hardik), and passages (Vasu) into the unified Evidence Navigator response.
8. **Evaluation Harness & Benchmark Coordination:**
   - Coordinate execution of the 50-scenario gold-standard evaluation suite (`evaluation/harness.py`).
   - Generate comparative tables across baseline, hybrid, and Self-RAG tiers.

---

## 5. Detailed Project Roadmap & Relevant Phases

- **Phase 0:** Establish documentation blueprint and directory scaffold (*Done*).
- **Phase 1:** Publish shared Pydantic contracts and configure Docker Compose / CI hooks.
- **Phase 6:** Build baseline RAG integration and initial DDI screening API.
- **Phase 7:** **Deliver the WORKING CORE MVP** with all 4 clinical screening workflows.
- **Phase 9:** Implement sentence-level NLI claim verification.
- **Phase 10:** Deploy the personalized, context-isolated chatbot.
- **Phase 11:** Implement Authentication, RBAC, TOTP 2FA, and emergency contacts.
- **Phase 12:** Integrate the RxGuard Evidence Navigator with Hardik's subgraph service.
- **Phase 13:** Execute 50-case benchmark harness and security vulnerability scans.
- **Phase 14:** Orchestrate final release integration, container verification, and demo video.

---

## 6. Shared Contracts Consumed & Produced

You define and own all 8 canonical Pydantic contracts:
- `MedicationConcept`
- `DrugProduct`
- `SourceDocument`
- `EvidencePassage`
- `SafetyEvidence`
- `SafetyFinding`
- `RAGResponse`
- `UserContext`

---

## 7. Interfaces Consumed from Teammates

### From Mudit (Data Layer):
```python
# Ingests normalized drug concepts
med_concept = await medication_normalizer.normalize(query_string)
```

### From Vasu (RAG & Retrieval Layer):
```python
# Ingests grounded explanations with passage citations
rag_response = await rag_orchestrator.generate_grounded_explanation(
    medications=med_concepts,
    deterministic_findings=findings
)
```

### From Hardik (Neo4j Graph Layer):
```python
# Ingests provenance subgraphs for Evidence Navigator
subgraph_json = await subgraph_service.get_provenance_subgraph(finding_id)
```

---

## 8. Testing Requirements & Acceptance Criteria

### Unit & Security Tests Required:
- `test_deterministic_ddi`: High-risk pairs (e.g., Methotrexate + NSAID) emit `CONTRAINDICATED`.
- `test_deterministic_dfi`: Statin + Grapefruit emits food interaction warning with administration qualifiers.
- `test_deterministic_dci`: Beta-blocker in active asthma emits absolute contraindication finding.
- `test_allergy_cross_reactivity`: Penicillin-allergic patient prescribed Amoxicillin emits direct allergy contraindication.
- `test_user_isolation`: Verify that querying user B's profile with user A's token raises HTTP 403 Forbidden.
- `test_totp_2fa_verification`: Verify valid 6-digit TOTP code accepts and invalid code rejects.
- `test_claim_verifier_hallucination`: Verify that an unbacked sentence fails NLI entailment check.

### Acceptance Criteria:
1. Zero false negatives on critical contraindications within the validated test suite.
2. 100% of API responses include the mandatory clinical safety disclaimer.
3. CI pipeline passes with $\ge 85\%$ test coverage across safety and security modules.

---

## 9. Failure Modes & Edge Cases

- **Missing Patient Allergy History:** If patient profile has no recorded allergies, emit `warning_missing_allergy_history=True`. **Never assume absence of record means zero allergies.**
- **Unverified AI Claim:** If LLM generates an explanation claim that fails NLI entailment, flag the sentence as `UNVERIFIED_CLAIM` and recalculate report confidence.
- **Safety Rule Override:** If the LLM generates a reassuring sentence while Layer C flags a contraindication, the deterministic contraindication must override the narrative.

---

## 10. Git Workflow & Definition of Done

- **Branch:** `feature/lakshay-safety-platform`
- **Commit Convention:** `feat(safety): ...`, `feat(auth): ...`, `feat(api): ...`, `test(e2e): ...`
- **PR Target:** `main` (requires review from Mudit, Vasu, or Hardik).
- **Definition of Done:**
  1. All assigned modules implemented in designated directories.
  2. Automated tests pass with $\ge 85\%$ coverage.
  3. No breaking contract changes without unanimous team agreement.
  4. Integration verified with end-to-end test suite (`tests/end_to_end/`).

---

## 11. Ready-to-Use Implementation Prompt for Lakshay's AI Agent

Copy and paste the prompt below directly into your AI coding assistant:

```text
You are pair programming with Lakshay Bharti, Project Lead & Safety Systems Architect on RxGuard-RAG.

Your mission is to implement Workstream 4 on branch 'feature/lakshay-safety-platform':
1. Implement canonical Pydantic contracts in 'src/rxguard/core/contracts/' (medication.py, product.py, document.py, evidence.py, safety.py, rag_response.py, user_context.py).
2. Implement the Deterministic Medication Safety Engine in 'src/rxguard/safety/' covering:
   - DDI (pairwise screening across n(n-1)/2 pairs) in 'ddi.py'
   - DFI (drug-food screening) in 'dfi.py'
   - DCI (drug-condition contraindication screening) in 'contraindications.py'
   - Allergies (active moiety & excipient UNII matching) in 'allergies.py'
   - Master orchestrator returning structured result states in 'engine.py'
3. Build the FastAPI gateway in 'src/rxguard/api/' implementing routes:
   - POST /api/v1/safety/analyze
   - POST /api/v1/chat/message
   - POST /api/v1/auth/login, /register, /2fa
   - GET /api/v1/evidence/subgraph/{finding_id}
4. Implement security in 'src/rxguard/auth/': Argon2id hashing, JWT tokens, RBAC, TOTP RFC 6238 2FA, and consent-driven emergency contacts.
5. Implement the personalized chatbot in 'src/rxguard/chatbot/' with strict user-context isolation.
6. Build sentence-level NLI claim verification in 'src/rxguard/evidence/claim_verifier.py' and Evidence Navigator integrator in 'navigator.py'.
7. Coordinate the 50-scenario benchmark evaluation harness in 'src/rxguard/evaluation/'.

Strict constraints:
- Do NOT implement ingestion adapters (Mudit), vector retrieval internals (Vasu), or Neo4j Cypher workers (Hardik).
- Deterministic rules in Layer C must NEVER be overridden by LLM narratives.
- Ensure mypy --strict and ruff check pass cleanly.
- Maintain test coverage >= 85%.
```

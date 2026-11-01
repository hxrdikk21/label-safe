# Vasu Mittal — Advanced RAG & Self-RAG Engineering Blueprint

> **Role:** Lead Retrieval & Advanced RAG Architect  
> **Repository:** [DAREDEVIL-OF-NEXUS/RxGuard-RAG](https://github.com/DAREDEVIL-OF-NEXUS/RxGuard-RAG)  
> **Assigned Branch:** `feature/vasu-self-rag`  
> **Assigned Workstream:** Vector Indexing (pgvector), Lexical Search (tsvector), Hybrid Search (RRF), Cross-Encoder Reranking, Corrective RAG (CRAG) & Self-RAG Reflection Loops  
> **Version:** 2.0.0 (Four-Team Master Specification)  
> **Date:** October 2026

---

## 1. Project Context & Mission

RxGuard-RAG is a research-grade medication safety intelligence platform designed to eliminate hallucinations in clinical decision support. The platform pairs deterministic safety screening rules with advanced, uncertainty-aware Retrieval-Augmented Generation over regulatory drug labeling.

Your mission as the **Lead RAG Architect** is to ensure that the retrieval and generation pipeline retrieves the exact, authoritative regulatory passages needed for a clinical inquiry while systematically detecting retrieval failures and suppressing hallucinations:
1. Implement clinical boundary chunking and maintain the derived **pgvector HNSW** and **PostgreSQL tsvector GIN** indexes.
2. Build high-precision **Hybrid Search** with **Reciprocal Rank Fusion (RRF)** and cross-encoder reranking.
3. Deploy **Corrective RAG (CRAG)** to evaluate retrieval confidence and trigger bounded query reformulation or safe abstention.
4. Implement a **practical Self-RAG-inspired modular reflection loop** (retrieval decision, evidence relevance, claim support, counter-evidence detection).
5. Connect with Hardik's Neo4j service for **graph-assisted retrieval candidate expansion**.

---

## 2. Overall System Architecture & Your Layer

The system consists of five distinct layers:
- Layer A: Data Acquisition & Medication Knowledge (Mudit)
- Layer B: Persistent Data & Tri-Store Indexing (Joint: PostgreSQL by Mudit, pgvector & tsvector by Vasu, Neo4j by Hardik)
- Layer C: Deterministic Medication Safety Engine (Lakshay)
- Layer D: Advanced RAG & Self-RAG Engine (**Vasu — Your Layer**)
- Layer E: Application, Personalization & Security (Lakshay)

You own the neural and retrieval foundation in Layer D and the derived vector/lexical indexes in Layer B.

---

## 3. Module Boundaries & Owned Files

You have exclusive write ownership over the following project paths:

```
src/rxguard/
├── vector_store/
│   ├── __init__.py
│   ├── pgvector_client.py   # pgvector HNSW connection and similarity search
│   └── embeddings.py        # Dense embedding wrapper (OpenAI / BGE-small)
├── retrieval/
│   ├── __init__.py
│   ├── chunker.py           # Clinical boundary chunking with contextual headers
│   ├── lexical.py           # PostgreSQL GIN tsvector full-text search
│   ├── hybrid.py            # Reciprocal Rank Fusion (RRF, k=60) algorithm
│   ├── reranker.py          # Cross-encoder reranker (e.g., bge-reranker-large)
│   └── graph_retriever.py   # Candidate expansion calling Hardik's graph service
├── rag/
│   ├── __init__.py
│   ├── planner.py           # Query intent classification & sub-query decomposition
│   ├── baseline.py          # Naive vector RAG baseline for benchmarking
│   └── orchestrator.py      # Core RAG assembly & context builder
├── self_rag/
│   ├── __init__.py
│   ├── crag_evaluator.py    # CRAG retrieval confidence scoring & abstention
│   ├── query_rewriter.py    # Bounded corrective query reformulation (max 2 retries)
│   └── self_critique.py     # Self-RAG reflection token evaluation ([IsRel], [IsSup])
tests/
└── retrieval/
    ├── test_vector_search.py # pgvector cosine distance and HNSW tests
    ├── test_lexical.py       # tsvector exact chemical match tests
    ├── test_hybrid_rrf.py    # RRF rank math and deduplication tests
    ├── test_reranker.py      # Cross-encoder scoring and cutoff tests
    ├── test_crag.py          # CRAG threshold triggers and abstention tests
    └── test_self_critique.py # Faithfulness critique and hallucination suppression
```

### Files You Must NOT Modify Unilaterally:
- `src/rxguard/core/contracts/*`: Shared contracts owned by Lakshay.
- `src/rxguard/ingestion/*` & `src/rxguard/database/models.py`: Owned by Mudit.
- `src/rxguard/graph/*`: Owned by Hardik.
- `src/rxguard/safety/*` & `src/rxguard/api/*`: Owned by Lakshay.

---

## 4. Exact Implementation Responsibilities

1. **Clinical Boundary Chunker (`chunker.py`):**
   - Chunk clinical sections into 300–500 token windows with 50-token overlap.
   - Detect sentence boundaries using spaCy/NLTK.
   - Inject structured headers: `[DRUG: {name}] [SECTION: {loinc_title}] [LOINC: {code}]`.
2. **Tri-Store Vector & Lexical Indexing:**
   - Implement `pgvector_client.py` using HNSW indexing (`m=16`, `ef_construction=64`).
   - Implement `lexical.py` using PostgreSQL `to_tsvector('english', ...)`.
3. **Hybrid Search & Reciprocal Rank Fusion (RRF):**
   - Combine top 50 lexical and top 50 vector candidates:
     $$\text{RRF Score}(d) = \sum_{m \in M} \frac{1}{k + r_m(d)} \quad (k=60)$$
   - Deduplicate chunks originating from identical SPL SetIDs.
4. **Cross-Encoder Reranking (`reranker.py`):**
   - Rerank top 25 hybrid candidates down to top 5 high-precision evidence passages.
5. **Corrective RAG (CRAG) Pipeline (`crag_evaluator.py`):**
   - Score retrieved passage relevance:
     - `CORRECT` ($\text{Score} \ge 0.75$): Proceed to grounded generation.
     - `AMBIGUOUS` ($0.40 \le \text{Score} < 0.75$): Trigger bounded query rewrite (broaden search, filter by LOINC Section 7, max 2 retries).
     - `INCORRECT` ($\text{Score} < 0.40$): Trigger safe abstention (`STATUS_INSUFFICIENT_EVIDENCE`).
6. **Self-RAG-Inspired Reflection Loops (`self_critique.py`):**
   - Distinguish practical Self-RAG from the original fine-tuned research method (Asai et al., 2023).
   - Evaluate `[IsRel]` (Is evidence relevant?) and `[IsSup]` (Is answer supported by passage?).
   - Flag or suppress any generated sentence not entailed by its cited passage ID.
7. **Graph-Assisted Candidate Expansion (`graph_retriever.py`):**
   - Call Hardik's `GraphService` to fetch adjacent ingredients, contraindications, and food items to enrich hybrid retrieval context.

---

## 5. Detailed Project Roadmap & Relevant Phases

- **Phase 0:** Review documentation blueprint and shared contracts (*Done*).
- **Phase 1:** Verify local Docker Compose environment with pgvector support.
- **Phase 4:** Implement `chunker.py`, `pgvector_client.py`, `lexical.py`, and `hybrid.py`.
- **Phase 6:** Build baseline RAG pipeline for initial end-to-end integration.
- **Phase 8:** Deploy `crag_evaluator.py`, `query_rewriter.py`, and `self_critique.py`.
- **Phase 9:** Connect `graph_retriever.py` with Hardik's Neo4j service.
- **Phase 13:** Execute comparative retrieval benchmarks across 4 RAG configurations.
- **Phase 14:** Support release deployment and final demonstration.

---

## 6. Shared Contracts Consumed & Produced

You consume and populate the shared Pydantic contracts from `src/rxguard/core/contracts/`:
- `EvidencePassage`: Consumed from Mudit's database, indexed, and retrieved.
- `SourceEvidence`: Ranked and provided to Lakshay.
- `RAGResponse`: Generated and formatted with inline verified citations.

---

## 7. Data & API Interfaces Provided to Teammates

### Interface Provided to Lakshay (API Gateway & Chatbot):
```python
# src/rxguard/rag/orchestrator.py
from typing import List, Optional
from src.rxguard.core.contracts.medication import MedicationConcept
from src.rxguard.core.contracts.safety import SafetyFinding
from src.rxguard.core.contracts.rag_response import RAGResponse

class AdvancedRAGOrchestrator:
    async def generate_grounded_explanation(
        self,
        medications: List[MedicationConcept],
        clinical_question: Optional[str] = None,
        deterministic_findings: Optional[List[SafetyFinding]] = None
    ) -> RAGResponse:
        """
        Executes hybrid retrieval, graph expansion, reranking, CRAG evaluation,
        and Self-RAG synthesis with inline passage citations.
        """
        ...
```

### Interface Consumed from Hardik (Neo4j Graph Store):
```python
# src/rxguard/retrieval/graph_retriever.py
class GraphRetriever:
    async def expand_candidates_via_graph(self, rxcui: str) -> List[str]:
        """Calls Hardik's GraphService to retrieve related passage IDs and ingredient UNIIs."""
        ...
```

---

## 8. Testing Requirements & Acceptance Criteria

### Unit Tests Required (`tests/retrieval/`):
- `test_hybrid_rrf`: Verify mathematical correctness of RRF ranking and deduplication.
- `test_crag_thresholds`: Ensure scores $\ge 0.75$ proceed, scores $0.40–0.74$ trigger rewrite, and $< 0.40$ trigger safe abstention.
- `test_bounded_retries`: Ensure query rewriter strictly halts after 2 iterations without infinite loops.
- `test_self_critique_suppression`: Verify that an ungrounded hallucinated claim is suppressed or flagged as `UNVERIFIED`.

### Acceptance Criteria:
1. Hybrid search + Reranking latency $\le 350\text{ms}$ for top 25 candidates.
2. 100% of LLM and embedding API calls mocked in automated CI tests.
3. Test suite passes with $\ge 85\%$ coverage; `mypy --strict` passes cleanly.

---

## 9. Failure Modes & Edge Cases

- **Zero Relevant Chunks:** When querying rare or off-label combinations, CRAG must trigger safe abstention (`STATUS_INSUFFICIENT_EVIDENCE`). **Never allow LLM to invent safety reassurance.**
- **Cross-Encoder Latency Spike:** If the local cross-encoder exceeds 500ms, fall back to top RRF candidate order with a logged latency warning.
- **Model Contradiction:** If the LLM generates a statement contradicting a deterministic safety rule, the deterministic rule must override the narrative.

---

## 10. Git Workflow & Definition of Done

- **Branch:** `feature/vasu-self-rag`
- **Commit Convention:** `feat(retrieval): ...`, `feat(self_rag): ...`, `test(crag): ...`
- **PR Target:** `main` (requires review from Lakshay, Mudit, or Hardik).
- **Definition of Done:**
  1. All assigned modules implemented in designated directories.
  2. Automated tests pass with $\ge 85\%$ coverage.
  3. Latency benchmarks documented for vector, lexical, and reranking stages.
  4. Integration verified with Lakshay's API schemas.

---

## 11. Ready-to-Use Implementation Prompt for Vasu's AI Agent

Copy and paste the prompt below directly into your AI coding assistant:

```text
You are pair programming with Vasu Mittal, Lead Retrieval & Advanced RAG Architect on RxGuard-RAG.

Your mission is to implement Workstream 2 on branch 'feature/vasu-self-rag':
1. Implement clinical boundary chunking in 'src/rxguard/retrieval/chunker.py' (300-500 tokens, 50-token overlap, header injection).
2. Implement vector indexing and cosine search in 'src/rxguard/vector_store/pgvector_client.py' using PostgreSQL pgvector (HNSW m=16, ef_construction=64).
3. Implement lexical search in 'src/rxguard/retrieval/lexical.py' using PostgreSQL tsvector GIN indexing.
4. Implement hybrid retrieval with Reciprocal Rank Fusion (RRF, k=60) in 'hybrid.py' and cross-encoder reranking in 'reranker.py'.
5. Build Corrective RAG (CRAG) in 'src/rxguard/self_rag/crag_evaluator.py' (confident >= 0.75, ambiguous 0.40-0.74, inadequate < 0.40 with safe abstention) and bounded query rewriter in 'query_rewriter.py' (max 2 retries).
6. Implement Self-RAG reflection token evaluation in 'src/rxguard/self_rag/self_critique.py' ([IsRel], [IsSup]) and graph expansion in 'graph_retriever.py'.
7. Write unit tests in 'tests/retrieval/' covering RRF math, pgvector similarity, CRAG thresholds, and self-critique hallucination suppression.

Strict constraints:
- Do NOT edit files in 'src/rxguard/ingestion/', 'src/rxguard/graph/', or 'src/rxguard/safety/'.
- Adhere strictly to the Pydantic schemas in 'src/rxguard/core/contracts/'.
- Ensure mypy --strict and ruff check pass cleanly.
- Maintain test coverage >= 85%.
```

# Vasu Mittal & Lakshay Bharti — Advanced RAG & Self-RAG Phased Blueprint & Execution Tracker

> **Branch:** `feature/vasu-self-rag_with_lakshay`  
> **Role:** Lead Retrieval & Advanced RAG Architect (Pairing with Lakshay Bharti)  
> **Repository:** [DAREDEVIL-OF-NEXUS/RxGuard-RAG](https://github.com/DAREDEVIL-OF-NEXUS/RxGuard-RAG)  
> **Strategy:** Production-grade neural and lexical retrieval, deterministic rank fusion math, rigorous Self-RAG reflection loops, and zero regression.

---

## 1. Master Phase Breakdown & Status Summary

| Phase | Title | Status | Primary Modules & Files |
|---|---|---|---|
| **Phase 1** | **Clinical Boundary Chunker & Contextual Header Injector** | `DONE` | `src/rxguard/retrieval/chunker.py`, `tests/retrieval/test_chunker.py` |
| **Phase 2** | **Dense Vector Embeddings & In-Memory / pgvector Client** | `DONE` | `src/rxguard/vector_store/embeddings.py`, `pgvector_client.py`, `tests/retrieval/test_vector_search.py` |
| **Phase 3** | **PostgreSQL tsvector Lexical Search & Chemical Tokenizer** | `DONE` | `src/rxguard/retrieval/lexical.py`, `tests/retrieval/test_lexical.py` |
| **Phase 4** | **Hybrid Search & Reciprocal Rank Fusion (RRF, k=60)** | `DONE` | `src/rxguard/retrieval/hybrid.py`, `tests/retrieval/test_hybrid_rrf.py` |
| **Phase 5** | **Cross-Encoder Reranker & Confidence Calibrator** | `DONE` | `src/rxguard/retrieval/reranker.py`, `tests/retrieval/test_reranker.py` |
| **Phase 6** | **Corrective RAG (CRAG) Evaluator & Query Rewriter** | `DONE` | `src/rxguard/self_rag/crag_evaluator.py`, `query_rewriter.py`, `tests/retrieval/test_crag.py` |
| **Phase 7** | **Self-RAG Reflection Loops ([IsRel], [IsSup], Hallucination Critique)** | `NOT STARTED` | `src/rxguard/self_rag/self_critique.py`, `tests/retrieval/test_self_critique.py` |
| **Phase 8** | **Graph-Assisted Candidate Expansion Client** | `NOT STARTED` | `src/rxguard/retrieval/graph_retriever.py`, `tests/retrieval/test_graph_retriever.py` |
| **Phase 9** | **Master Advanced RAG Orchestrator & Context Builder** | `NOT STARTED` | `src/rxguard/rag/orchestrator.py`, `planner.py`, `baseline.py`, `tests/rag/` |
| **Phase 10** | **RAG Comparative Evaluation Suite (Baseline vs Hybrid vs Self-RAG)** | `NOT STARTED` | `src/rxguard/evaluation/rag_benchmarks.py`, `tests/end_to_end/test_rag_tiers.py` |

---

## 2. Phase-by-Phase Detailed Specifications

### Phase 1: Clinical Boundary Chunker & Contextual Header Injector
- **Scope:** 
  - Token-aware chunking respecting paragraph, sentence, and clinical tabular boundaries.
  - Window size: 300–500 tokens with 50-token overlap.
  - Header injection: `[DRUG: {name}] [SECTION: {loinc_title}] [LOINC: {code}] [RXCUI: {rxcui}]`.
  - Canonical `EvidencePassage` emission with calculated SHA-256 digests.
- **Completion Criteria:** Unit tests verify boundary preservation, header prepending, chunk overlap continuity, and zero truncated clinical warnings.

### Phase 2: Dense Vector Embeddings & Vector Client
- **Scope:** Embedding generator interface (BGE-small-en / MiniLM-L6 / mock dense vectors) and vector similarity search client supporting Cosine distance and HNSW parameters.
- **Completion Criteria:** Cosine similarity math matches exact vector geometry; unit tests pass.

### Phase 3: Lexical Search & Chemical Term Tokenizer
- **Scope:** In-memory BM25 / tsvector search engine tailored to pharmaceutical naming, salts, and chemical synonyms.
- **Completion Criteria:** Exact chemical names match with high recall; unit tests pass.

### Phase 4: Hybrid Search & Reciprocal Rank Fusion (RRF, k=60)
- **Scope:** Mathematical rank fusion: $\text{RRF Score}(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$ with $k=60$. Deduplicates passages across identical SPL documents.
- **Completion Criteria:** Rank order matches theoretical RRF scores; unit tests pass.

### Phase 5: Cross-Encoder Reranker & Confidence Calibrator
- **Scope:** Two-stage retrieval reranker taking top 25 hybrid candidates and scoring query-passage pairs down to top 5 high-precision evidence passages.
- **Completion Criteria:** Relevant clinical passages promoted to top ranks; cutoff filtering verified.

### Phase 6: Corrective RAG (CRAG) Evaluator & Query Rewriter
- **Scope:** Three-way confidence routing:
  - `CORRECT` ($\ge 0.75$): Proceed to grounded generation.
  - `AMBIGUOUS` ($0.40 \le \text{Score} < 0.75$): Trigger bounded query rewrite (broaden search, filter LOINC Section 7, max 2 retries).
  - `INCORRECT` ($< 0.40$): Trigger safe abstention (`STATUS_INSUFFICIENT_EVIDENCE`).
- **Completion Criteria:** Threshold routing tests pass with 100% precision.

### Phase 7: Self-RAG Reflection Loops
- **Scope:** Reflection token evaluation ([IsRel], [IsSup]) inspecting whether retrieved passages are relevant and whether generated text is factually supported.
- **Completion Criteria:** Unbacked assertions stripped or flagged; reflection states verified.

### Phase 8: Graph-Assisted Candidate Expansion Client
- **Scope:** Interoperability adapter consuming Hardik's graph service to retrieve adjacent ingredient UNIIs, conditions, and contraindication passages for query expansion.
- **Completion Criteria:** Expansion candidates correctly augment candidate pool.

### Phase 9: Master Advanced RAG Orchestrator & Context Builder
- **Scope:** Unified `AdvancedRAGOrchestrator` combining hybrid retrieval, graph expansion, reranking, CRAG, and Self-RAG synthesis with inline verified citations.
- **Completion Criteria:** Emits compliant `RAGResponse` contracts for Lakshay's API gateway.

### Phase 10: RAG Comparative Evaluation Suite
- **Scope:** Automated benchmarking comparing Naive Vector RAG, Lexical RAG, Hybrid RRF, and Self-RAG across latency, hallucination rate, and context precision.
- **Completion Criteria:** Performance comparison matrix generated; end-to-end integration verified.

---

## 3. Phase Execution Log & Changelog

| Timestamp | Phase | Action | Result & Summary |
|---|---|---|---|
| 2026-10-15 22:06 | Branching | Initialized | Branch `feature/vasu-self-rag_with_lakshay` created from `feature/lakshay-safety-platform`. |
| 2026-10-15 22:07 | Phase 1 | Completed | Clinical Boundary Chunker with contextual headers ([DRUG], [SECTION], [LOINC], [RXCUI]) + SHA-256 fingerprinting + sliding window tests passed. Status: DONE. |
| 2026-10-15 22:11 | Phase 2 | Completed | Dense Vector Embedding Engine (384-dim, L2-normalized) + pgvector VectorStoreClient (HNSW m=16, ef=64) + 4 unit tests passed. Status: DONE. |
| 2026-10-15 22:16 | Phase 3 | Completed | Chemical Tokenizer (hyphen/salt form preservation) + Okapi BM25 Lexical Engine + PostgreSQL tsvector SQL generator + 4 unit tests passed. Status: DONE. |
| 2026-10-15 22:20 | Phase 4 | Completed | Hybrid Search Engine + Reciprocal Rank Fusion (RRF, k=60) + document-level deduplication + 2 tests passed. Status: DONE. |
| 2026-10-15 22:21 | Phase 5 | Completed | Cross-Encoder Reranker + term proximity scoring + score threshold pruning + 2 tests passed. Status: DONE. |
| 2026-10-15 22:21 | Phase 6 | Completed | Corrective RAG (CRAG) Evaluator (CORRECT/AMBIGUOUS/INCORRECT) + Bounded Query Rewriter (max 2 retries) + 3 tests passed. Status: DONE. |
| 2026-10-15 22:32 | Phase 7 | Completed | Self-RAG Reflection Loops ([Retrieve], [IsRel], [IsSup]) + Hallucination Detection + VerifiedCitation contract emission + 5 unit tests passed. Status: DONE. |
| 2026-10-15 22:33 | Phase 8 | Completed | Graph-Assisted Candidate Expansion Client (Medication->Ingredient->Class->Contraindications) + query enrichment + 5 unit tests passed. Status: DONE. |
| 2026-10-15 22:38 | Phase 9 | Completed | Master Advanced RAG Orchestrator + ClinicalQueryPlanner + ContextBuilder + NaiveVectorRAG baseline + safe abstention + 7 tests passed. Status: DONE. |
| 2026-10-15 22:40 | Phase 10 | Completed | RAG Comparative Evaluation Suite (4 tiers: Naive Vector, Lexical BM25, Hybrid RRF, Self-RAG) + end-to-end benchmark test passed. Status: DONE. |


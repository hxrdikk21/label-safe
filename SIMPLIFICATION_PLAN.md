# RxGuard-RAG: Simplification Plan

> Handoff for Claude Code. Scope: **simplify the architecture, tech stack and RAG pipeline only.**
> Bugs, missing data wiring, security defaults and rule coverage are deliberately **out of scope for now** and are parked in `AUDIT_BROKEN_PARTS_LATER.md`.
> Based on a read-through of `src/rxguard/` on 2026-10-28.

## 1. Principles

1. **One of everything.** One datastore on the main path, one retrieval path, one quality gate, one place for thresholds.
2. **Keep ADR-001.** The deterministic `SafetyEngine` decides danger. RAG only explains and can never change, soften or hide a finding.
3. **Pick CRAG, drop Self-RAG** (reasoning in section 4).
4. **Simplify by deleting and merging, not by adding.** Do not fix unrelated bugs in this pass.
5. **Keep public contracts stable** (`RAGResponse`, `VerifiedCitation`, `SafetyFinding`, API routes) so the frontend and tests keep working.

## 2. Current state (what is being simplified)

- Three data stores: PostgreSQL, pgvector, Neo4j. Plus Redis configured but unused.
- RAG query path has 8 stages and 5 overlapping modules: Self-RAG `[Retrieve]` decision, query planner, graph expansion, hybrid search, reranker, CRAG gate, narrative, Self-RAG critique. Separately, a second verifier (`NLIClaimVerifier`) is used by the chatbot.
- Duplicates: two chunkers (`retrieval/chunker.py` vs `pack_blocks` in `ingestion/dailymed.py`), two vector stores (`VectorStoreClient` in memory vs `PgVectorStore`), two verifiers, three different "verified" thresholds, two sets of CRAG thresholds.
- Backends are selected through four env switches (`EMBEDDING_BACKEND`, `RERANKER_BACKEND`, `NLI_BACKEND`, `LLM_BACKEND`), each with a heuristic fake and a real implementation.
- Large side systems: Neo4j sync worker (~1000 lines), 2FA/backup codes/emergency contacts/email OTP, per-person planning docs.

## 3. Target architecture

### 3.1 Stores: PostgreSQL + pgvector only

| Concern | Before | After |
|---|---|---|
| Passages, documents, users, rules | PostgreSQL | PostgreSQL (unchanged) |
| Embeddings | pgvector + in-memory `VectorStoreClient` | pgvector only (in-memory kept as a test double) |
| Keyword search | custom in-memory BM25 | Postgres `tsvector` + GIN (the SQL already exists in `LexicalSearchEngine`) |
| Evidence graph | Neo4j + sync worker | Built on demand from relational joins: finding -> rule -> passage -> document |
| Cache / rate limit | Redis (unused) | Removed |

The Evidence Navigator keeps its JSON shape (`EvidenceProvenanceGraph`); only its data source changes.

### 3.2 Layers after simplification

```
API (FastAPI)
  ├─ SafetyEngine  (deterministic rules; unchanged; the only authority on danger)
  └─ RagService    (one class; explains findings with cited label text)
        ├─ Retriever     -> Postgres: pgvector + tsvector, RRF, filtered by rxcui
        ├─ Reranker      -> cross-encoder, top 5
        ├─ Gate (CRAG)   -> CORRECT / REWRITE(1x) / ABSTAIN
        └─ Generator     -> template or Claude, cites [passage_id]
Storage: PostgreSQL 16 + pgvector
Ingestion (offline): DailyMed/openFDA -> parse -> chunk -> embed -> Postgres
```

## 4. Decision: CRAG, not Self-RAG

Keep **Corrective RAG**. Remove the Self-RAG layer.

Why CRAG:
- It acts **before generation** on the thing that matters most here: is the retrieved evidence good enough? If not, rewrite once or abstain. This directly implements the project's rule that missing evidence is never proof of safety.
- Self-RAG proper depends on a model trained to emit reflection tokens (`[Retrieve]`, `[IsRel]`, `[IsSup]`). This repo only imitates them with word overlap, so it adds code and an illusion of verification without the real benefit.
- The `[Retrieve]` decision is trivial here: a safety question about named drugs always retrieves.
- The sentence critique mostly duplicates the gate when the narrative is the passage text itself.

What replaces the dropped Self-RAG parts, kept deliberately simple:
- **Citation check (no NLI model):** require every factual sentence to carry a `[passage_id]`; after generation, deterministically verify each cited ID is in the retrieved set. Sentences without a valid citation are removed or marked `UNVERIFIED`.
- Populate the existing `VerifiedCitation` contract from this check so the API response shape does not change.
- An NLI entailment model can be added later as an optional upgrade behind the same interface. Not part of this pass.

## 5. Target RAG pipeline

**Ingestion (offline).** DailyMed SPL XML -> parse target LOINC sections -> chunk -> embed once -> store in Postgres + pgvector.
- One chunker: keep `pack_blocks` (1500 chars, sentence-safe) from `ingestion/dailymed.py`. Prepend the `[DRUG][SECTION][LOINC][RXCUI]` header (from `ClinicalChunker.build_contextual_header`) to each chunk before embedding.
- Delete `retrieval/chunker.py` afterward.

**Query (online), 6 steps:**
1. **Resolve scope.** The request already has medications and RxCUIs. Filter candidates by `rxcui` (and prefer the Drug Interactions / Contraindications / Warnings sections). This replaces graph expansion and the query planner.
2. **Retrieve.** Postgres hybrid: pgvector cosine top 30 + `tsvector` top 30, fused with RRF (k=60). Reuse the existing RRF code.
3. **Rerank.** Cross-encoder scores (query, passage); keep the top 5 above a minimum score.
4. **CRAG gate.** Using the top rerank score against **one** threshold from config:
   - above threshold: continue;
   - between lower and upper: rewrite the query once (reuse `QueryRewriter` strategy 1), retrieve again, re-gate;
   - below: abstain with `evidence_sufficiency_state="INSUFFICIENT"`. An ambiguous result after the one retry also abstains or returns `PARTIAL`; it never proceeds silently.
5. **Generate.** Format the top passages (`ContextBuilder`). Generator is `template` or Claude (existing `NarrativeGenerator`), prompt unchanged: use only passages, cite `[passage_id]`, never contradict findings.
6. **Check citations and return.** Deterministic citation check (section 4), build `RAGResponse` with the `SafetyEngine` findings attached unchanged.

## 6. Target tech stack

| Keep | Remove / merge |
|---|---|
| FastAPI, Pydantic, Uvicorn | Neo4j, `neo4j` driver, graph sync worker, `deployment/neo4j/` |
| PostgreSQL 16 + pgvector, SQLAlchemy async, Alembic | Redis service and `REDIS_URL` |
| `sentence-transformers` with `BAAI/bge-small-en-v1.5` (384-d) for embeddings | Hashed-n-gram "embedding" as the default (keep only as a test fake) |
| Cross-encoder reranker (`BAAI/bge-reranker-base` or `-large`) | Term-overlap "cross-encoder" as default (test fake only) |
| Claude via `anthropic` SDK as optional generator, template as fallback | `roberta-large-mnli` NLI backend and `NLI_BACKEND` switch (defer) |
| React + Vite frontend | Separate Self-RAG module and `[Retrieve]` logic |
| Docker Compose with `postgres` only | Duplicate chunker, duplicate verifier, `rag/baseline.py` (unless a benchmark needs it) |

Config reduction: from four backend switches to **`MODEL_MODE=real|fake`** (real for the app, fake for unit tests) plus `LLM_BACKEND=template|anthropic`. All thresholds live in one block in `core/config.py`:

```
RETRIEVAL_TOP_K, RERANK_TOP_K, GATE_PROCEED_SCORE, GATE_REWRITE_SCORE, MAX_REWRITES=1
```

## 7. Target module layout

```
src/rxguard/
  api/            routes (safety, evidence, chat, auth, users, health)   [unchanged]
  safety/         deterministic rule engine                              [unchanged]
  ingestion/      dailymed.py, openfda.py, rxnav.py, cache, seed_loader  [unchanged]
  database/       models, repositories                                   [unchanged]
  rag/
    service.py        RagService: the 6-step pipeline (replaces orchestrator.py)
    retriever.py      Postgres hybrid retrieval + RRF
    reranker.py       cross-encoder (+ fake for tests)
    gate.py           CRAG gate + one-shot rewrite
    generator.py      template / Claude narrative
    citations.py      deterministic citation check -> VerifiedCitation
  evidence/       navigator built from relational data (no Neo4j)
```

Removed: `graph/`, `self_rag/`, `retrieval/graph_retriever.py`, `retrieval/chunker.py`, `retrieval/lexical.py` (BM25 class; keep only the tsvector SQL), `vector_store/pgvector_client.py` in-memory path (keep as test double), `evidence/claim_verifier.py` (later optional), `rag/planner.py`, `rag/baseline.py`.

## 8. Implementation tasks (refactor only)

Work on a branch. After each task: `pytest`, `ruff`, `mypy` pass (update tests that referenced removed modules; do not delete tests that cover kept behavior).

1. **Baseline.** Run the existing test suite and record pass/fail counts so regressions from this refactor are visible. Do not fix pre-existing failures here.
2. **Add the new `rag/` modules** (`service.py`, `retriever.py`, `reranker.py`, `gate.py`, `generator.py`, `citations.py`) by moving and trimming existing code: RRF from `hybrid.py`, rerank from `reranker.py`, thresholds and rewrite from `crag_evaluator.py`, narratives from `narrative.py`, context from `context_builder.py`.
3. **Single config block** for thresholds and `MODEL_MODE`; delete duplicates and the four backend switches.
4. **Switch `safety.py` route** to `RagService` with the same request/response contract. Keep `include_explanation` and `clinical_question`.
5. **Retriever interface.** Define a small `Retriever` protocol with two implementations: Postgres (real) and in-memory (tests). The service depends only on the protocol.
6. **Replace graph expansion and planner** with the rxcui filter (step 1 of the pipeline). Remove `graph_retriever.py` and `planner.py`.
7. **Navigator without Neo4j.** Keep `EvidenceNavigatorSerializer`; remove the Neo4j branch in `api/routes/evidence.py` and the background `project_findings_to_graph` task.
8. **Delete Neo4j, Self-RAG and duplicates** listed in section 7; remove Neo4j/Redis from `docker-compose.yml`, `.env.example`, `pyproject.toml` extras and `README` references.
9. **Merge chunkers** (add the contextual header in `dailymed.py`; delete `chunker.py`).
10. **Tidy repo.** Add `.coverage`, `.mypy_cache/`, `.ruff_cache/`, `*.egg-info/` to `.gitignore` and untrack them. Move the planning docs (`phases.md`, `lakshay_phases.md`, `vasu_phases.md`, `checklist.md`, `Hardik.md`, `Lakshay.md`, `Mudit.md`, `Vasu.md`) to `docs/archive/`.
11. **Update docs.** Rewrite the architecture diagram in `README.md` and `architecture.md` to the new 2-layer view (SafetyEngine + RagService on Postgres+pgvector).

## 9. Acceptance criteria

- `docker compose up` starts only Postgres.
- No imports of `neo4j`, `redis` or `self_rag` remain.
- RAG code is the six modules in section 7; each pipeline step maps to one module.
- All thresholds are set in one config block.
- `RAGResponse`, `VerifiedCitation`, `SafetyFinding` and API routes keep their current shapes.
- A test proves a deterministic finding is returned unchanged whatever the RAG layer returns.
- A test proves the gate abstains (`INSUFFICIENT`) when retrieval returns nothing or low scores.
- Test suite status is no worse than the baseline from task 1.

## 10. Explicitly out of scope (see `AUDIT_BROKEN_PARTS_LATER.md`)

Wiring label ingestion into Postgres, populating pgvector, expanding safety rules, fixing benchmark rule IDs, chatbot improvements, auth/security defaults, `/ready`, frontend bugs, adding an NLI model, evaluation work. Do not fix these during this pass unless a task above cannot be completed without it.

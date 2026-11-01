# RxGuard-RAG: Audit and Simplification Plan

> Handoff document for Claude Code. Written 2026-10-28 from a read-through of `src/rxguard/` on the current checkout.
> Findings marked **(verified)** were confirmed by reading the code. Findings marked **(from explain.md)** come from the repo's own `explain.md`, which describes older commit `0417f0f`; re-verify before acting.

## 0. Goal

Make the project actually work end to end with the least moving parts. Today the RAG pipeline is well designed on paper but the data never reaches it. Priorities:

1. Get real FDA label text into the database and searchable.
2. Use real models instead of heuristic fakes.
3. Measure quality with the benchmark set.
4. Delete dead and duplicate code.
5. Fix the security defaults.

**Non-negotiable invariant (ADR-001):** the deterministic `SafetyEngine` decides danger. RAG only explains. RAG output must never override, soften or contradict a safety finding. Keep this.

## 1. Project in brief

- **Purpose:** medication safety checker. Input: medications, foods, conditions, allergies. Output: severity findings from a rule book, plus an optional cited explanation built from FDA label text.
- **Stack:** FastAPI, Pydantic, SQLAlchemy (async), Alembic, PostgreSQL 16 + pgvector, Neo4j 5, Redis (configured, unused), React + Vite frontend, Docker Compose.
- **Layers:** A ingestion, B storage, C safety rules, D RAG, E API/auth/chatbot/navigator.
- **Medicine data sources:** NIH RxNav/RxNorm (IDs), NLM DailyMed (SPL XML, main evidence), openFDA (JSON labels), FDA UNII (ingredient IDs). CDSCO (India) is planned only.
- **Data in repo (`data/`):**
  - `seed/top_500_concepts.json`: 500 medicine concepts (RxCUI, ingredients, UNII, category, NTI flag), built by `scripts/build_seed_catalog.py`.
  - `seed/safety_rules.json`: only 6 DDI + 4 DFI + 4 DCI + 3 allergy rules.
  - `benchmark/scenarios_50.json`: 50 evaluation scenarios.

## 2. The RAG pipeline as it exists

Query path (`src/rxguard/rag/orchestrator.py`):

1. Self-RAG `[Retrieve]` decision (`self_rag/self_critique.py`)
2. Query planner: regex intent + 15 hardcoded drug names (`rag/planner.py`)
3. Graph expansion: adds class/ingredient/condition terms (`retrieval/graph_retriever.py`)
4. Hybrid search: dense cosine + BM25, fused with RRF k=60, top 20 (`retrieval/hybrid.py`, `lexical.py`, `vector_store/`)
5. Rerank to top 5 (`retrieval/reranker.py`)
6. CRAG gate: CORRECT / AMBIGUOUS (rewrite, max 2 retries) / INCORRECT (abstain) (`self_rag/crag_evaluator.py`)
7. Context build + narrative (`rag/context_builder.py`, `rag/narrative.py`; template or Claude)
8. Self-RAG sentence critique producing `VerifiedCitation`s (`self_rag/self_critique.py`)

Ingestion path (offline): DailyMed SPL XML -> `ingestion/dailymed.py` (LOINC sections, `pack_blocks` at 1500 chars, deterministic UUID + SHA-256) -> `LabelRepository.save_label` -> Postgres `evidence_passages` -> (intended) embeddings -> pgvector `evidence_embeddings` (HNSW m=16, ef=64).

Backends are chosen in `core/config.py`: `EMBEDDING_BACKEND`, `RERANKER_BACKEND`, `NLI_BACKEND`, `LLM_BACKEND`. All default to offline heuristics.

## 3. What is broken

### 3.1 Core pipeline

| # | Problem | Evidence | Impact |
|---|---|---|---|
| B1 | Label data never reaches the database. | **(verified)** Nothing in `src/` calls the DailyMed parser or `LabelRepository.save_label`. `SeedLoader` loads concepts only. `scripts/` has only `build_seed_catalog.py`. | `/safety/analyze?include_explanation` loads zero passages, so RAG abstains on everything. |
| B2 | pgvector is not wired in. | **(verified)** `PgVectorStore` is referenced only in `tests/integration/test_pgvector_store.py`. `sync_tracker.py` queues PASSAGE jobs for PGVECTOR, but no pgvector worker exists. | Embeddings are never persisted. |
| B3 | Index rebuilt on every request. | **(verified)** `safety.py` builds `AdvancedRAGOrchestrator(passages=...)` per call, which re-embeds and re-indexes in memory. | Slow, and ignores the persistent store. |
| B4 | Only 17 safety rules for 500 drugs. | **(verified)** counts in `safety_rules.json`. | Unlisted combinations return "no finding", which reads as "safe". Dangerous for a medical tool. |
| B5 | Default models are fakes. | **(verified)** hashed n-gram embeddings; term-overlap "cross-encoder"; token-overlap "NLI". | Weak retrieval; "verified" citations are near meaningless with the template backend (the template narrative is the passage text itself). |
| B6 | Inconsistent thresholds. | **(verified)** CRAG: class default 0.75/0.40 but orchestrator passes 0.65/0.35. "Verified" bar: 0.40 (`NLIClaimVerifier`), 0.70 (transformer NLI and `VerifiedCitation` docs), 0.50 (`SelfRAGReflector`). | Behavior changes when backends change; confusing audit trail. |
| B7 | After 2 failed rewrites an AMBIGUOUS result still proceeds to generation. | **(verified)** only INCORRECT abstains. | Weak evidence can produce an answer. |
| B8 | Planner output unused. | **(verified)** `sub_queries` are never used for retrieval; only intent reaches the narrative step. | Dead logic. |
| B9 | Benchmark rule IDs do not match the rule book. | **(from explain.md)** scenarios expect e.g. `DDI-WARFARIN-NSAID`; rules use `RULE-DDI-001`. | Evaluation scores unreliable. Re-verify. |
| B10 | Chatbot ignores the question text and food items; no retrieval, no LLM. | **(from explain.md)** and **(verified)** `chatbot/orchestrator.py` builds the reply only from safety findings. | "Personalized chatbot" is a rule printout. |
| B11 | Passage ID formats disagree. | **(verified)** `ClinicalChunker` makes `PASS-{rxcui}-{loinc}-{idx}`; the DB and `PgVectorStore` use UUIDs; graph seed uses `PASS-WARFARIN-01`. | Graph-suggested passage IDs never match real passages. |

### 3.2 Smaller bugs (from explain.md; re-verify)

- `/ready` always reports ONLINE without testing databases.
- Role chosen at registration is stored as `ROLE_USER` in DB mode.
- Email OTP codes and emergency contacts are RAM-only.
- Mock email writes the OTP into the server log.
- Login rate limiter is in RAM (Redis unused).
- Alembic reads `RXGUARD_DATABASE_URL`; the app reads `DATABASE_URL`.
- `.env` alone does not enable DB/graph mode; the app reads real environment variables.
- Two Safety Engine caches (chat vs `/safety/analyze`).
- Frontend: loading spinner never shown (`setLoading(true)` never called); refresh token never used; contact form sends nothing.

### 3.3 Security (fix before any deployment)

- CORS allows `*` together with credentials.
- `JWT_SECRET_KEY` has a hard-coded default.
- Confirm `.env` is git-ignored and was never committed (`git log --all -- .env`). Rotate secrets if it was.

## 4. What to drop or merge

### Delete now (dead or duplicate)

- One of the two chunkers: either `retrieval/chunker.py` (`ClinicalChunker`) or `pack_blocks` in `ingestion/dailymed.py`. Recommended: keep the section-aware `pack_blocks` and add the `[DRUG][SECTION][LOINC][RXCUI]` header from `ClinicalChunker.build_contextual_header` to each passage before embedding.
- One of the two verifiers: keep a single sentence-level NLI verifier; remove the duplicate logic in `SelfRAGReflector.critique_narrative` or in `NLIClaimVerifier`.
- The in-memory `VectorStoreClient` as a production path once pgvector is wired. Keep only as a test double.
- `rag/baseline.py`, unless used by a benchmark you keep.
- Unused: Redis service and config, `PromptManager`, `require_role` (unless used), the planner's unused sub-query code.
- Committed junk: `.coverage`, `.mypy_cache/`, `.ruff_cache/`, `rxguard_rag.egg-info/`. Add to `.gitignore` and `git rm --cached`.
- Overlapping planning docs: `phases.md`, `lakshay_phases.md`, `vasu_phases.md`, `checklist.md`, `Hardik.md`, `Lakshay.md`, `Mudit.md`, `Vasu.md`. Move to `docs/archive/` or delete. Keep `README.md`, `architecture.md`, `data.md`.

### Defer or cut (complexity without payoff yet)

- **Neo4j and `graph/sync_worker.py` (~1000 lines).** Build the Evidence Navigator graph from relational joins (finding -> rule -> passage -> document) and render in the frontend. Reintroduce Neo4j only if graph retrieval measurably improves benchmark results.
- **2FA, backup codes, emergency contacts, email OTP, token rotation.** Large auth surface that does not affect medical accuracy. Keep basic login only.
- **Separate CRAG and Self-RAG layers.** Merge into one relevance gate plus one verifier (see section 5).
- **CDSCO/India source.** Planned only; no API.

## 5. Target simplified architecture

```
Ingest:  RxCUI list -> DailyMed SPL -> parse LOINC sections -> chunk (+context header)
         -> embed once (bge-small, 384-d) -> Postgres evidence_passages + pgvector
Query:   resolve drugs -> filter by rxcui (+ interaction/contraindication sections)
         -> hybrid: pgvector cosine + Postgres tsvector -> RRF
         -> cross-encoder rerank (top 5)
         -> single gate: top rerank score < threshold => abstain (one rewrite retry max)
         -> LLM answer using only passages, cited [passage_id]
         -> NLI check each cited sentence (threshold in one config value)
         -> RAGResponse (findings from SafetyEngine attached unchanged)
```

Key choices:

- **Postgres + pgvector + tsvector is the only data store** on the main path.
- **Filter by RxCUI before ranking.** The drugs are already known, so this beats graph expansion for accuracy.
- **Embed at ingest time**, never at query time except for the query itself.
- **One threshold set**, defined once in `core/config.py`, used by the gate and the verifier.
- Abstain explicitly; never treat missing evidence as safety.

## 6. Task list (do in order)

Each task should end with tests passing (`pytest`) and `ruff`/`mypy` clean.

### Task 1: Ingestion script (fixes B1, B2 partly)
- Create `scripts/ingest_labels.py` (or `python -m src.rxguard.ingestion.run`).
- For each concept in the seed catalog (start with a `--limit N`, e.g. 10 drugs including warfarin, ibuprofen, metformin, lisinopril, aspirin): fetch the label (DailyMed first, openFDA fallback, using the existing cache manager), parse with `dailymed.py`, call `LabelRepository.save_label`.
- Respect rate limits already coded in `ingestion/http.py`.
- **Done when:** `SELECT count(*) FROM evidence_passages` is > 0 for those RxCUIs, and re-running the script writes nothing (idempotent).

### Task 2: Embeddings into pgvector (fixes B2)
- After saving passages, embed and call `PgVectorStore.upsert`; or implement the missing pgvector worker that drains the `PGVECTOR` sync queue. Pick one and document it.
- Fix the passage-ID/UUID mismatch (B11) so all stores use the same ID.
- **Done when:** `evidence_embeddings` row count equals passage count, and `PgVectorStore.search("warfarin ibuprofen bleeding", rxcui=...)` returns relevant passages.

### Task 3: Retrieval uses the database (fixes B3)
- Add a Postgres-backed hybrid retriever: pgvector cosine + `tsvector` (SQL already in `LexicalSearchEngine.generate_postgres_tsvector_sql`; bind parameters, do not inline), fused by existing RRF code.
- Filter by RxCUI (and optionally LOINC section) before ranking.
- Build `AdvancedRAGOrchestrator` once (dependency-injected singleton) instead of per request.
- **Done when:** `/api/v1/safety/analyze` with `include_explanation=true` for warfarin + ibuprofen returns a narrative with cited real passage IDs.

### Task 4: Real models and one set of thresholds (fixes B5, B6, B7)
- Install the `ml` and `llm` extras. Set defaults to `sentence-transformers` (BAAI/bge-small-en-v1.5), `cross-encoder`, `transformers` NLI. Keep heuristics only for tests (`*_BACKEND=heuristic` in test env).
- Define CRAG/gate and verification thresholds once in `core/config.py`; remove the duplicates.
- Make AMBIGUOUS-after-retries abstain (or return `evidence_sufficiency_state="PARTIAL"` with a clear warning), not silently proceed.
- **Done when:** one config location controls all thresholds; changing a backend does not change threshold semantics.

### Task 5: Merge Self-RAG and CRAG (simplify)
- Collapse into: relevance gate (reranker score) + sentence verifier (NLI). Remove the duplicate overlap-based critique and the unused `[IsUse]` code paths.
- Keep the `RAGResponse` / `VerifiedCitation` contracts stable so the API and frontend do not break.

### Task 6: Fix evaluation (fixes B9)
- Reconcile benchmark expected rule IDs with `safety_rules.json` (or the reverse).
- Run `evaluation/harness.py` on `data/benchmark/scenarios_50.json`; record baseline (current) and after-changes metrics in `docs/eval_results.md`.
- **Done when:** the benchmark runs green and reports recall of expected findings and citation support rate.

### Task 7: Safety coverage honesty (fixes B4)
- When a medication has no rule coverage, return an explicit `UNKNOWN_SEVERITY` / "not checked" finding, never an empty "no finding".
- Expand rules for the highest-risk pairs among the NTI drugs in the seed catalog (warfarin, digoxin, lithium, methotrexate, etc.), each with a label citation. Rules must be authored/reviewed by a human with clinical sources.

### Task 8: Remove dead code (section 4)
- Delete items under "Delete now". Update `__init__.py` exports and tests. Do this after Tasks 1-6 so nothing needed is removed.

### Task 9: Defer Neo4j and heavy auth (section 4)
- Make the Evidence Navigator work from relational data; guard Neo4j code behind an optional extra or remove it.
- Reduce auth to basic login unless required. Remove Redis from compose if unused.

### Task 10: Security and smaller bugs (section 3.2, 3.3)
- Restrict CORS to configured origins; require `JWT_SECRET_KEY` from env (fail startup if default).
- Make `/ready` check Postgres.
- Unify `DATABASE_URL` naming for app and Alembic.
- Fix frontend loading state, refresh-token use, contact form (or remove it).

## 7. Definition of done

- A fresh clone plus `docker compose up`, one ingest command, and one seed command yields a working `/safety/analyze` with cited explanations for at least 10 drugs.
- A query with no matching evidence abstains with `INSUFFICIENT` (verified by a test).
- A deterministic finding is never changed by the RAG layer (verified by a test).
- The 50-scenario benchmark runs and results are recorded.
- No dead modules from section 4 remain; `pytest`, `ruff`, `mypy` pass.

## 8. Notes for Claude Code

- Read `architecture.md`, `data.md` and `README.md` for intent, but trust the code over the docs; several docs describe planned rather than implemented behavior.
- `explain.md` is a plain-language tour of an older commit (`0417f0f`); treat its bug list as leads to verify.
- Do not weaken ADR-001. Do not let the LLM output change severity or suppress a finding.
- Parameterize all SQL (the tsvector helper documents `$1` binding; never inline user text).
- Treat downloaded label XML as untrusted input when parsing.
- Keep changes small and committed per task so each can be reviewed or reverted.

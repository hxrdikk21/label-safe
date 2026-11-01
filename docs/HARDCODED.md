# Is RxGuard a real RAG app? What is hardcoded?

Audit of `feature/hardik`, 1 Nov 2026. Every number below was measured on the local stack with `MODEL_MODE=real` and `LLM_BACKEND=gemini` (`gemini-3.6-flash`).

## Verdict

**Every check runs RAG to explain each finding, and the chat is RAG. The risk decision itself is deliberately not RAG.**

- **Every check:** the rules return the findings at once. Then each finding is explained from its own FDA label passages, all in one Gemini call (`POST /safety/explain-findings`, [`rag/finding_explainer.py`](../src/rxguard/rag/finding_explainer.py)). Sentences taken from a label are numbered and link to DailyMed.
- **Explanations and chat:** an answer about your medicines is assembled at request time.
  - Passages are retrieved from 4,292 FDA label passages (471 drugs) in PostgreSQL.
  - They are reranked by a cross-encoder and checked for relevance.
  - Gemini writes the answer, which is then checked for valid citations.
  - Nothing in an answer is canned. Change the question or the medicines and the retrieved passages and the answer change.
- **Risk decisions** (contraindicated, major, …) come from about 50,000 rules in data files, not from the language model. This is the design rule in ADR-001: generated text can explain a finding but never create, change or hide one. The rules are data, not hardcoded logic:

  | Source | Rules |
  |---|---|
  | DDInter | 49,274 |
  | FDA label text | about 1,100 after de-duplication |
  | Curated (reviewed) | 17 |

### What happens for one question

| Step | What it does | Code |
|---|---|---|
| 1. Rules | Deterministic screening of drugs, foods, conditions and allergies | [`safety/engine.py`](../src/rxguard/safety/engine.py) |
| 2. Retrieve | pgvector (BGE-small embeddings) + PostgreSQL full-text search, fused with RRF, limited to the user's drugs. A question that names no drug is searched with the drug names added | [`rag/retriever.py`](../src/rxguard/rag/retriever.py), [`rag/service.py`](../src/rxguard/rag/service.py) `retrieve_context` |
| 3. Rerank | BGE cross-encoder keeps the 5 best passages | [`rag/reranker.py`](../src/rxguard/rag/reranker.py) |
| 4. Relevance check | Proceed, rewrite the query once, or abstain | [`rag/gate.py`](../src/rxguard/rag/gate.py) |
| 5. Generate | Gemini, given the findings, passages, profile and conversation | [`rag/generator.py`](../src/rxguard/rag/generator.py), [`chatbot/prompt_manager.py`](../src/rxguard/chatbot/prompt_manager.py) |
| 6. Cite | Citations to passages that weren't retrieved are stripped. Cited sentences link to their label passage on DailyMed; uncited ones are marked as general information | [`rag/citations.py`](../src/rxguard/rag/citations.py), [`chatbot/orchestrator.py`](../src/rxguard/chatbot/orchestrator.py) |

### Evidence it works (`make rag-eval`)
The evaluation runs 17 questions phrased the way people type them, several without naming a drug, against the live corpus:

| Metric | Result |
|---|---|
| Right passage in top 5 (hit@5) | **15 / 15** |
| Mean reciprocal rank | 0.93 |
| Off-topic questions that correctly abstained | 2 / 2 |
| Retrieval latency, p50 / p95 | 0.64 s / 2.43 s (first query adds about 12 s model load) |

Example chat reply (warfarin + fluconazole, "Does fluconazole change how my warfarin works?"):
> Fluconazole acts as a CYP2C9 inhibitor, which slows down the breakdown of warfarin **[1]**. This interaction can increase your prothrombin time … and raise the risk of bleeding **[2]**.
>
> [1] warfarin label · drug interactions · "Table 2: Examples of CYP450 Interactions with Warfarin …"
> [2] fluconazole label · drug interactions

### When it is *not* doing RAG
| Situation | What you get | How to tell |
|---|---|---|
| `MODEL_MODE=fake` | Hashed bag-of-words "embeddings" and a word-overlap reranker (test doubles) | `make llm-status` prints the model mode |
| `LLM_BACKEND=template`, no `GEMINI_API_KEY`, or Gemini fails or is out of quota | Retrieval still runs; the reply quotes label sentences instead of writing an answer | Chat shows "The assistant is offline…" |
| `make dev` (no database) | Empty corpus; explanations always abstain | No label sources ever appear |

---

## Hardcoded inventory

Effort: **S** = hours, **M** = a day or two, **L** = several days.

### A. Fake or stubbed functionality
| What | Where | Replace with real functionality? | Effort |
|---|---|---|---|
| **Emergency alert is never sent.** `trigger_emergency_alert` returns `True` if contacts exist ("In production, dispatches via Twilio / SendGrid") | [`auth/emergency.py`](../src/rxguard/auth/emergency.py) | Yes. Send SMS (Twilio) or email through the existing `EmailDeliveryService`, and report failures to the user | M |
| **Email OTP is simulated** when neither Brevo nor SMTP is configured: it logs instead of sending | [`auth/email_service.py`](../src/rxguard/auth/email_service.py) | Yes. Set the Brevo or SMTP settings; in production, fail loudly instead of pretending | S |
| **Emergency contacts live in process memory** and are lost on restart | [`auth/emergency.py`](../src/rxguard/auth/emergency.py) `EmergencyWorkflowManager` | Yes. Add a `user_emergency_contacts` table and migration, like the profile tables (migration 0005) | M |
| Users and profiles in memory when `DATABASE_URL` is unset | [`api/dependencies.py`](../src/rxguard/api/dependencies.py) | Intentional for offline development (`make dev`); `make start` uses PostgreSQL | none |

### B. Static data standing in for live data
| What | Where | Replace with real functionality? | Effort |
|---|---|---|---|
| **The medicine catalogue is a fixed 500-drug snapshot** (RxNav, catalogue version 2026.10.0). Drugs outside it can't be searched or explained; e.g. sildenafil has rules but no label | [`data/seed/top_500_concepts.json`](../data/seed/top_500_concepts.json) | Yes. When local search finds nothing, look the name up live with the existing `MedicationNormalizer` ([`knowledge/normalizer.py`](../src/rxguard/knowledge/normalizer.py), [`ingestion/rxnav.py`](../src/rxguard/ingestion/rxnav.py)), then ingest that drug's label on first use | M |
| **About 49,000 generated rules have template text**: "DDInter lists X and Y as a moderate interaction. Check both drug labels…", plus one fixed piece of advice per severity. DDInter supplies no mechanism | [`safety/build_rules.py`](../src/rxguard/safety/build_rules.py) `ACTIONS`, `ddinter_rules` | Partly. Fill the mechanism from the drug's own label passage (`select_passages` in [`evidence/navigator.py`](../src/rxguard/evidence/navigator.py)) or have Gemini summarise it at build time. Severity stays from DDInter | M |
| Label-derived rule severity is guessed from wording ("contraindicated" → CONTRAINDICATED, "avoid"/"do not" → MAJOR, else MODERATE) | [`safety/build_rules.py`](../src/rxguard/safety/build_rules.py) `_label_severity` | Partly. Gemini classification with a human review queue | M |
| Only 17 curated (clinically reviewed) rules and 3 allergy cross-reactivity groups | [`data/seed/safety_rules.json`](../data/seed/safety_rules.json) | Needs clinical review, not code. An allergy to a medicine's own ingredient is already matched by UNII without any rule | L (clinical) |
| Food vocabulary: 12 foods with everyday aliases | [`data/seed/foods.json`](../data/seed/foods.json) | Could be mined from label "avoid … juice/alcohol/…" sentences; a small curated list is a reasonable default | S |
| Only 4 label sections are indexed (boxed warning, contraindications, drug interactions, warnings and precautions), so pregnancy, lactation and side-effect questions aren't answered from labels | [`knowledge/loinc_taxonomy.py`](../src/rxguard/knowledge/loinc_taxonomy.py) `TARGET_SECTIONS` | Yes. Add "Use in specific populations" (43684-0) and "Adverse reactions" (34084-4), then re-ingest (about 20 min). Deferred by choice | S |

### C. Frontend example and marketing content
| What | Where | Replace with real functionality? | Effort |
|---|---|---|---|
| Landing "Rules decide. The AI only explains." cards: a fixed warfarin + ibuprofen finding and explanation with a made-up `P-1` citation | [`pages/Landing.jsx`](../frontend/src/pages/Landing.jsx) | Yes. Fetch `/safety/analyze` with `include_explanation` for the example and render it with `CitedText` | S |
| Risk-type examples, the prescription-bottle illustration, the pipeline animation | [`pages/Landing.jsx`](../frontend/src/pages/Landing.jsx), [`components/RxLabel.jsx`](../frontend/src/components/RxLabel.jsx), [`components/pipeline/StageSvg.jsx`](../frontend/src/components/pipeline/StageSvg.jsx) | Illustrations; fine as static | none |
| Check page starts with warfarin + ibuprofen filled in | [`pages/Check.jsx`](../frontend/src/pages/Check.jsx) `EXAMPLE` | Fine as a demo; signed-in users already start from their saved profile | none |
| Chat suggestion chips are three fixed questions | [`components/FollowUp.jsx`](../frontend/src/components/FollowUp.jsx) `SUGGESTIONS` | Yes. Build them from the findings (e.g. "Why is warfarin + ibuprofen contraindicated?") | S |
| UI label maps: severity names, colours, finding-type names | [`data/catalog.js`](../frontend/src/data/catalog.js), [`components/SeverityBadge.jsx`](../frontend/src/components/SeverityBadge.jsx) | Presentation, not data; fine | none |

### D. Legacy and test-only
| What | Where | Note |
|---|---|---|
| RAG benchmark on a synthetic in-memory corpus | [`evaluation/rag_benchmarks.py`](../src/rxguard/evaluation/rag_benchmarks.py) | Use [`evaluation/live_eval.py`](../src/rxguard/evaluation/live_eval.py) (`make rag-eval`) for the real corpus; keep the synthetic one for CI without a database |
| Old standalone Evidence Navigator page at `/navigator`, not linked from the new UI | [`api/routes/navigator.py`](../src/rxguard/api/routes/navigator.py), [`evidence/navigator_page.py`](../src/rxguard/evidence/navigator_page.py) | Remove, or link it from the evidence trail |
| 50 rule-engine scenarios | [`data/benchmark/scenarios_50.json`](../data/benchmark/scenarios_50.json) | Test fixture; fine |

### Confirmed live (not hardcoded)
- **Search boxes:** medicine search (catalogue + rule drugs); food, condition and allergen search. Conditions come from the full ICD-10-CM list through NLM Clinical Tables.
- **Landing statistics:** from `/api/v1/stats`.
- **Label content:** the evidence graph, label passages and DailyMed links.
- **Answers:** Gemini's answers and citations.
- **Saved profile data:** medicines, conditions, allergies, hospitals, doctors, visits, prescriptions.

## Suggested order
1. **The emergency alert stub and contact persistence:** a safety feature that silently does nothing.
2. **The landing example from the live API.**
3. **Mechanism text for the generated rules** from label passages.
4. **A live RxNav fallback** for drugs outside the 500.

## Fixed during this audit
- **Stale duplicate labels.** When DailyMed's label for a drug moved to a different document, the old one stayed searchable, so 150 drugs had two labels' passages. `LabelRepository.save_label` now replaces the drug's previous document; the existing stale rows were removed.
- **Real-question explanations.** "Explain with drug-label evidence" now answers questions that don't name the drug, with numbered DailyMed sources instead of raw IDs.
- **Per-finding RAG on every check.** The old opt-in "Explain with drug-label evidence" tick box is gone; every finding card now carries its own label explanation.
  - **When Gemini is unavailable or out of quota:** the card quotes only label sentences that name the other drug, food or condition, and otherwise says no label text was found.
- **Concurrent model crash.** PyTorch inference from parallel threads crashed the API process, which would also happen when two users checked at once. Embedding and reranking now share one inference lock.
- **Landing copy.** The pipeline story no longer claims a single curated rulebook.
- **Oversized passages.** Interaction tables over the 1,500-character passage limit are split by row (chunk version 2.1.0), so the embedding and rerank models see the whole table.

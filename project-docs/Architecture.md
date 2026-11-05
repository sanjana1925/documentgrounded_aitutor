ARCHITECTURE: AI TUTOR GUIDE

Technical reference for the backend and how the frontend attaches to it. For a plain-language tour, see [02-architecture.md](../docs/02-architecture.md).
Related: [PRD](PRD.md) · [Rules](Rules.md) · [Design](Design.md) · [Tasks](Tasks.md) · [Memory](../docs/Memory.md)

---

1. PRINCIPLES

1. Agents decide, Python enforces. LLMs choose intent, strategy, sufficiency, revisions, and wording. Python owns isolation, limits, scoring, validation, persistence, and safety.
2. Every LLM output is a validated, typed object (Pydantic) or is treated as absent.
3. Every loop-back consumes a bounded budget. No unbounded cycles.
4. Single choke points: one class touches ChromaDB, one module calls Gemini, one place builds isolation filters.
5. Observable by construction: named runs, tags, metadata. Failures stay visible.
6. Measured, not claimed: evaluation only scores verified examples.

---

2. SYSTEM CONTEXT

```text
Browser (React, :5173)
   ↓ HTTP / JSON
FastAPI backend (:8000)
   ├→ Gemini API       LLM
   ├→ ChromaDB         chunks, embeddings, metadata     (./data/chroma_db)
   ├→ SQLite           chat sessions, messages, sources (./data/tutor.db)
   ├→ JSON files       quiz progress per learner and document (./data/learner_states)
   ├→ LangSmith        traces, datasets, experiments (cloud)
   └→ MiniLM           local embeddings (sentence-transformers)
```

---

3. MODULE MAP AND DEPENDENCY RULES

```text
app.py → backend/main.py → api/routes → container → graph/workflow → graph/nodes → agents → tools → services
guardrails and observability are used everywhere and never raise
```

| Layer | Path | Responsibility |
|---|---|---|
| Entry | app.py, backend/main.py | Create the FastAPI app, CORS, routers, tracing setup, legacy re-exports |
| API | backend/api/ | Routes, request and response schemas, API-key and benchmark-password checks |
| Composition | backend/container.py | Build real services once (Chroma, Gemini, SQLite, graph) |
| Workflow | backend/graph/ | LangGraph state, thin nodes, routing and loop limits |
| Agents | backend/agents/ | Decision-making units and their Pydantic schemas |
| Tools | backend/tools/ | Typed, allow-listed, budgeted, traced actions |
| Services | backend/services/ | Deterministic workers with no agent logic |
| Guardrails | backend/guardrails/ | Input, retrieval, and output checks (pure functions) |
| Evaluation | backend/evaluation/, services/evaluation_service.py | Dataset verification, metrics, experiments |
| Domain rules | backend/domain/quiz_engine.py, backend/domain/planner.py | Phase progression, accuracy, weak topics, base study plan |

Rules:

* Services never import agents (one documented exception: quiz_service uses agents.schemas, and agents.retrieval reuses quiz_service.normalize).
* Nothing outside retrieval_service touches ChromaDB.
* Nothing outside llm_service calls Gemini.
* The LLM never supplies session or document ids.

---

4. REQUEST LIFECYCLE (POST /agent)

1. Validate identity (session id pattern, filename shape). Failure gives 400.
2. Input guardrail. A block returns a guardrail_blocked reply with no model call.
3. Reject unknown mode (400). Document-needing modes on unindexed documents give 404.
4. Apply reset_quiz and handle quiz exit phrases (deterministic).
5. Load memory: last 6 chat messages and the rolling summary from SQLite. The client-supplied history is a fallback.
6. Run the LangGraph workflow with a fresh Budget.
7. Map provider failures to the same HTTP status (429, 503, 502).
8. Persist the user and assistant messages in one transaction with cited chunk ids. Quiz turns are not persisted.
9. Return AgentResponse with agent_trace, and schedule the background summary refresh.

---

5. THE WORKFLOW (LangGraph)

```text
START → supervisor_agent
   retrieve   → retrieval_agent → evidence_evaluator → tutor_agent → critic_agent → output_guardrail → END
   summarize  → guide_agent → END
   quiz       → quiz_agent → END
   plan       → study_planner_agent → END
   other      → respond_other → END

Loop-backs:  evaluator → retrieval_agent (retrieve again)
             critic → tutor_agent (revise) or retrieval_agent (more evidence)
Any failure or budget stop → safe_fallback → END
```

ROUTING RULES (all in graph/workflow.py, pure Python)

| After | Condition | Next |
|---|---|---|
| supervisor | stop_reason or time expired | safe_fallback |
| supervisor | next_action retrieve, summarize, quiz, plan, other | retrieval_agent, guide_agent, quiz_agent, study_planner_agent, respond_other |
| retrieval_agent | retrieval exhausted | tutor if relevant and coverage is 0.6 or more, else fallback |
| retrieval_agent | otherwise | evidence_evaluator |
| evidence_evaluator | use_evidence | tutor_agent |
| evidence_evaluator | retrieve_again or rewrite_query | retrieval_agent if the budget allows, else tutor if coverage is 0.6 or more, else fallback |
| evidence_evaluator | answer_not_supported | one more retrieval if attempts are under 2 and allowed, else fallback |
| tutor_agent | answer | critic_agent |
| tutor_agent | need_more_evidence | retrieval_agent if allowed, else fallback |
| tutor_agent | invalid (retry granted) | tutor_agent |
| tutor_agent | insufficient, failed, or invalid_final | safe_fallback |
| critic_agent | finish | output_guardrail |
| critic_agent | revise or retrieve_again | tutor_agent or retrieval_agent |
| critic_agent | fallback | safe_fallback |
| output_guardrail and terminal agents | stop_reason set | safe_fallback, else END |

LOOP BOUNDS (why it terminates)

| Loop | Consumes | Limit |
|---|---|---|
| retrieval_agent, evaluator, retrieval_agent | retrieval_attempts | 3 |
| tutor (need_more_evidence) to retrieval_agent | retrieval_attempts | 3 (shared) |
| critic to tutor (revise or retrieve_again) | revisions | 2 |
| tutor invalid to tutor | revisions | 2 (shared) |
| every edge | wall clock | 45 s |
| backstop | LangGraph recursion limit | 30 |

BUDGET (backend/budget.py, values in config.py)

max_llm_calls 12, max_tool_calls 6, max_retrieval_attempts 3, max_revisions 2, max_seconds 45. Counters are thread-safe. can_retrieve() also keeps two LLM calls in reserve for tutor and critic, and can_revise() keeps one. The budget is passed through config["configurable"]["budget"], not graph state, because it is not serialisable and must not appear in traces.

GRAPH STATE (graph/state.py)

* Request: message, session_id, document_id, history, conversation_summary, mode_override, quiz_pending
* Decision: decision, standalone_query, mode
* Retrieval: evidence, tried, last_eval, search_query, retrieval_exhausted
* Answering: draft, draft_status, critic, critic_action, critic_feedback, generation_attempts
* Output: reply, retrieved_chunks, source_chunk_ids, quiz_details, quiz_score, quiz_total, stop_reason, llm_error
* trace: an append-only list of step events, returned to the client as agent_trace.events

---

6. AGENTS

| Agent | File | LLM call name | Output schema | Python controls |
|---|---|---|---|---|
| Supervisor | agents/supervisor.py | supervisor_agent.decide | SupervisorDecision | Fast paths (explicit mode, quiz answer), intent and action normalisation, fallback to qa |
| Retrieval Agent | agents/retrieval.py | retrieval_agent.choose_strategy (retries only) | RetrievalDecision | First attempt deterministic, allow-listed tools, no repeated search, attempts cap |
| Evidence Evaluator | agents/retrieval.py | evidence_evaluator.evaluate | EvidenceEvaluation | No LLM call when no evidence, action coercion, failure means proceed |
| Tutor | agents/tutor.py | tutor_agent.write | TutorOutput | Must cite at least one retrieved chunk, invalid means revision |
| Critic | agents/critic.py | critic_agent.review | CriticEvaluation | Final finish, revise, retrieve, or fallback is decided by CriticAgent.decide |
| Quiz Agent | agents/quiz.py | quiz_agent.generate_question | QuizQuestion | Grading, phase, duplicates, schema, quote grounding, 3 attempts, fallback |
| Study Planner | agents/planner.py | study_planner_agent.propose | StudyPlanProposal | Numbers from Python, proposal validated against real stats, cached by learner-data signature, no LLM call when no topic has 2 answers |
| Guide Agent | agents/guide.py | guide_agent.summarize, map, reduce | text | Single pass vs parallel map-reduce, length validation, retry once |
| Memory | agents/memory.py | conversation_memory.summarize | text | Background, at most 1 call, discards injection-like summaries |

All calls go through services/llm_service.py (GeminiLLM): structured output via Gemini response_schema, one repair retry on invalid JSON, retry on transport, 5xx, and 429 within the time budget, LLMError(status) when unrecoverable, and token counts attached to the LangSmith run only when Gemini returns them.

---

7. TOOLS (backend/tools/)

ToolRegistry.run(name, ctx, raw_args) does: allow-list check, argument validation (extra fields forbidden), budget charge, traced execution, and a typed ToolResult(ok, tool, chunks, data, error). Failures become results, not exceptions. ToolContext(scope, budget) is built by Python.

| Tool | Args | Allowed for |
|---|---|---|
| get_document_metadata | none | Retrieval Agent |
| search_document | query, top_k | Retrieval Agent |
| search_topic | topic, top_k | Retrieval Agent |
| search_similar_chunks | chunk_index, top_k | Retrieval Agent |
| get_neighbor_chunks | chunk_index, window | Retrieval Agent |
| search_by_metadata | page | Retrieval Agent |
| get_learning_history, get_topic_performance | none, topic | Study Planner |
| get_quiz_history, sample_document_excerpts | limit, n | Quiz Agent |

---

8. DATA STORES

ChromaDB, collection pdf_chunks

Document is the chunk text (about 800 characters, 150 overlap). Metadata: source (document name), session_id, chunk_index, content_hash, page (new uploads). Every query is filtered by source and session_id inside RetrievalService._where. Legacy documents lack page.

SQLite, data/tutor.db (WAL mode, foreign keys on)

```text
chat_sessions(id, user_id, document_id, title, summary, summarized_upto, created_at, updated_at)
chat_messages(id, session_id → chat_sessions ON DELETE CASCADE, role in user/assistant/system, content, created_at)
message_sources(id, message_id → chat_messages ON DELETE CASCADE, source_document, source_chunk_ids JSON)
```

user_id holds the client session id. Sessions are found by (user_id, document_id). Clients never address them by id.

Learner state, data/learner_states/<session>__<sha256(document)[:16]>.json

quiz_engine.LearnerState holds the phase, per-phase and per-topic stats, asked questions, and the pending question including the correct index. It is stored per session and document. A legacy learner_state_<session>.json is read if its filename matches. A per-learner lock serialises quiz turns.

Evaluation report, data/evaluation_report.json (schema v2)

system_evaluation, results, arms (baseline_rag, agentic_rag), comparison, dataset, metric_notes. Older schemas load as no_data.

---

9. API CONTRACT

| Endpoint | Notes |
|---|---|
| GET / | Health and chunk count |
| POST /upload | multipart file and session_id, PDF up to 25 MB, page-aware chunking, idempotent by hash |
| DELETE /documents/{filename}?session_id= | Removes chunks, learner state, and chat |
| POST /agent | See section 4. Response adds agent_trace {events, budget, stop_reason} |
| GET /dashboard, GET /planner, POST /quiz/reset | Learner data. The planner runs the Planner Agent with a deterministic fallback |
| GET /evaluation | Requires the X-Benchmark-Password header. Returns the latest report or {"status":"no_data"}. 401 wrong password, 403 when BENCHMARK_PASSWORD is not set |
| GET /chat/history?session_id=&filename= | Stored messages, sources, title, summary |

Status codes: 400 validation, 401 API key or benchmark password, 403 benchmark locked, 404 unindexed document, 413 too large, 422 schema, 429, 502, 503 provider.

The quiz reply markdown format is parsed by the frontend (lib/parseQuiz.js) and must be preserved. All other reply text is markdown that the frontend renders with react-markdown (no raw HTML).

---

10. GUARDRAILS

| Layer | Where | Checks |
|---|---|---|
| Identity | guardrails/input.py | Session id matches ^[A-Za-z0-9_-]{1,64}$, file name up to 255 with no slashes or control characters |
| Input | guardrails/input.py | Empty, control characters, over 4000 characters, injection patterns, system prompt extraction |
| Evidence | Evaluator and route_after_evidence | Sufficiency, coverage 0.6 or more when out of attempts, standard refusal |
| Output | Critic and guardrails/output.py | Grounded, relevant, complete, non-empty, up to 8000 characters, no instruction leakage, cited chunks were retrieved |
| Quiz | quiz_service, guardrails/output.py | Schema, 4 distinct options, index range, difficulty equals phase, duplicates, verbatim source quote |
| Planner | planner_service | Topics, priorities, minutes 5 to 60, numbers within recorded data |
| Memory | agents/memory.py | Summary rejected if it trips the input guardrail |
| Benchmark | api/security.py | Constant-time password check on GET /evaluation |

---

11. OBSERVABILITY (LangSmith)

* Root run agent_request, then agent_workflow, then nodes named after agents, then <agent>.<step> LLM runs and named tool runs. Routing functions appear as route_after_* runs.
* Tags: ai-tutor-guide, workflow:{qa, guide-mode, quiz, study-plan, other}, intent:*, rag, retrieval, revision, quiz, study-planner, memory, fallback, error, budget-exceeded, llm-error, critic-unavailable.
* Metadata: hashed session_id, document_id, workflow_type, intent, decision_source, retrieval_attempt, revision_attempt, evidence_coverage, evidence_action, critic_action, quiz_phase, difficulty, stop_reason. Sensitive-looking keys are stripped and values truncated to 200 characters.
* configure_tracing() maps legacy LANGCHAIN_* names, defaults the project to ai-tutor-guide, and disables tracing with a warning if no key is set. TUTOR_DISABLE_TRACING=1 forces it off (tests).
* The request root is an explicit @traceable whose handle is stored in a ContextVar, so the Supervisor can add intent and workflow tags after deciding.

---

12. EVALUATION ARCHITECTURE

```text
build_golden (LLM-drafted from indexed chunks, code-verified)
   ↓
dataset.verify_item / split_verified
   ↓
EvaluationService runs baseline_rag (1 search, 1 call) and agentic_rag (full graph) on the same items
   ↓
evaluators (recall, precision, keyword coverage, similarity, lexical groundedness, LLM-judge faithfulness and relevancy, workflow counters)
   ↓
aggregate, compare, build_report → save_report and/or LangSmith (upload_to_langsmith, run_experiments)
```

Provider failures and time-budget stops are retried, then marked errored and excluded. LangSmith evaluators return None ("not evaluated") for errored runs.

---

13. CONFIGURATION

| Setting | Where | Default |
|---|---|---|
| GEMINI_API_KEY, API_KEY | .env | required, empty |
| BENCHMARK_PASSWORD | .env | empty (benchmark locked) |
| LANGSMITH_TRACING, LANGSMITH_API_KEY, LANGSMITH_PROJECT | .env | off, none, ai-tutor-guide |
| ANSWER_MODEL | env | gemini-flash-lite-latest |
| TUTOR_DB_PATH | env | ./data/tutor.db |
| Limits (MAX_*, chunk sizes, thresholds) | backend/config.py | see section 5 |
| CORS origins | backend/main.py | localhost:5173, 127.0.0.1:5173 |

---

14. KEY DECISIONS

| Decision | Why | Trade-off |
|---|---|---|
| LangGraph for the workflow | Real loops and branches, and each node is a named LangSmith run | Extra dependency |
| Routing in Python, not by the LLM | Bounded, testable, auditable | Less autonomy by design |
| Pydantic and Gemini response_schema | No free-text parsing | Schema must stay Gemini-compatible |
| SQLite for chat | No setup, transactional, portable | Single node. Swap to Postgres later |
| Learner state stays in JSON files | Existing, tested engine | Not yet in the database (see Tasks.md) |
| Hash the session id in traces | It works like a credential | Cannot search traces by raw id |
| Verify-first evaluation | An earlier report measured an empty index | Smaller, slower dataset creation |
| Server-side benchmark password | A browser-only check protects nothing | One shared password, no lockout |
| Quiz and plan rules live in backend/domain/ | Existing, correct, tested. Kept separate from the AI code | Agents and services import them by full path |
| All local data lives in data/ | One folder to back up or git-ignore. Path is anchored to the project, so it works from any folder | Set TUTOR_DATA_DIR to move it |

---

15. EXTENSION POINTS

* New agent: add a class in agents/, a Pydantic schema in agents/schemas.py, an allow-listed tool subset, a node in graph/nodes.py, and routing in graph/workflow.py.
* New tool: ToolArgs (extra forbidden) plus a function returning ToolResult in tools/, register it in tools/__init__.py, and add it to exactly the agents that need it.
* New store or database: implement it behind a services/ class and keep Scope(session, document) mandatory on every method.
* Different model: implement the LLM protocol (text, structured). Tests already do.

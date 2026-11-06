TASKS: AI TUTOR GUIDE

Status of work as of 2026-09-20.
Legend: ✅ done · 🟡 partial · ⬜ not started
Priority: P0 now, P1 next, P2 later
Related: [PRD](PRD.md) · [Architecture](Architecture.md) · [Rules](Rules.md) · [Design](Design.md) · [Memory](../docs/Memory.md)

---

1. IMMEDIATE (P0)

| # | Task | Status | Notes |
|---|---|---|---|
| P0-1 | Revoke the LangSmith API key | ⬜ | LangSmith is no longer used, but the key once sat in .env.example, a shareable file. Revoke it in LangSmith and delete it from .env |
| P0-2 | Finish the full-app audit | 🟡 | Non-AI parts done 2026-09-20 (see findings in F-8 to F-12 and S-7 to S-8). Still to run once the Gemini daily quota resets: real answers, follow-ups, off-topic and injection questions, quick actions, the quiz flow, and the pages with real quiz data |
| P0-3 | Verify markdown rendering in the browser | ✅ | Bold, italic, nested and numbered lists render correctly, and raw HTML and javascript: links are not rendered |

---

2. PRODUCT AND QUALITY (P1)

| # | Task | Status | Notes |
|---|---|---|---|
| P1-1 | Tune the Evidence Evaluator to reduce over-refusal | ⬜ | Measured 1/10 false refusals (the milk question, coverage stuck at 0.2). Ideas: accept passages that state the answer at the level asked, add few-shot examples, ease answer_not_supported, then re-measure |
| P1-2 | Bigger, human-reviewed golden set (50 or more questions, 3 or more documents) | ⬜ | Use build_golden, then a person reviews (review_status needs_human_review) |
| P1-3 | Independent, stronger LLM judge | ⬜ | The current judge is the same model family and scores near the ceiling |
| P1-4 | Re-index chem.pdf to get page numbers and regenerate the golden set with source_page | ⬜ | The legacy index has no pages |
| P1-5 | Latency work: skip the critic when evidence coverage is high and the draft cites correctly | ⬜ | Measure quality impact first |
| P1-6 | Consider a paid Gemini tier or a request queue | ⬜ | The free tier of 15 requests per minute drives latency and evaluation time |
| P1-7 | Move quiz progress into SQLite | ⬜ | Keep backend/domain/quiz_engine.py rules, migrate storage only, add a migration for legacy JSON |

---

3. FRONTEND (P1 to P2)

| # | Task | Status | Notes |
|---|---|---|---|
| F-1 | Restore chat from GET /chat/history on load | ✅ | The UI keeps its own localStorage cache today |
| F-2 | Show the agent trace (decisions, tool calls, budget) in a collapsible panel | ⬜ | agent_trace is already returned by /agent |
| F-3 | Benchmark: show baseline vs agentic comparison and "Not evaluated yet" | ⬜ | /evaluation already returns arms and comparison |
| F-4 | Show a Refused badge for abstained benchmark rows | ✅ | Done |
| F-5 | Show page numbers on source pills for new uploads | ⬜ | Chunk pages are in stored sources |
| F-6 | Frontend tests (components and the quiz parser) | ⬜ | None yet |
| F-8 | Set a different page title per route | ✅ | Every route shows "AI Tutor Guide" |
| F-10 | Show elapsed time, a "taking longer" note, and a Retry button while the tutor is thinking | ✅ | A failing request can leave "Thinking..." for about 30 seconds |
| F-11 | Let learners open a source pill to read the excerpt | ✅ | Pills only say Source 1, Source 2 |
| F-12 | Round benchmark values (Avg Latency shows 10.115) and enlarge the mobile Close navigation button | ✅ | |
| F-7 | Evaluation trend view (accuracy over time, answers with explanations) | ⬜ | Needs the per-answer history exposed by the backend |

---

4. SECURITY AND OPERATIONS (P1 to P2)

| # | Task | Status | Notes |
|---|---|---|---|
| S-1 | Real authentication (accounts) and per-user authorisation | ⬜ | The session id is the credential today |
| S-2 | Rate limiting and lockout, including wrong benchmark password attempts | ⬜ | Also protect /agent and /upload |
| S-3 | CORS origins from the environment | ⬜ | Hard-coded localhost:5173 today |
| S-4 | Postgres option for chat and learner data, plus a deployment guide | ⬜ | Chroma files and SQLite are single-node |
| S-7 | Fail fast on the Gemini per-day quota error | ⬜ | A per-day 429 is retried for about 32 seconds before failing. Detect GenerateRequestsPerDay and return "daily free limit reached, try tomorrow" immediately |
| S-8 | Delete the leftover fixtest/_smoke2.pdf chunk in data/chroma_db | ⬜ | Left by an early smoke test |
| S-6 | Health and readiness endpoint reporting model and database status | ⬜ | |

---

5. CODE HEALTH (P2)

| # | Task | Status | Notes |
|---|---|---|---|
| C-2 | Decouple agents.retrieval from quiz_service.normalize | ⬜ | Move text utilities to a shared module |
| C-3 | Give the Guide Agent real decisions or rename it to a service | ⬜ | Mostly a validated pipeline today |
| C-4 | Add type checking and linting to CI | ⬜ | |
| C-5 | Add a CI job for offline tests and a docs link check | ⬜ | |

---

6. COMPLETED ✅

Frontend

* ✅ React, Vite, and Tailwind app on the Playful Geometric design system (5 pages, shell, components, empty states, accessibility, reduced motion)
* ✅ Evaluation page reworked to learner risk analysis, and no longer repeats Dashboard numbers
* ✅ Dashboard trimmed to raw numbers (Weak and Strong topic chips removed) and retitled "Welcome Aboard to Your Learning Forum"
* ✅ Markdown rendering in chat (bold, italic, nested lists) with react-markdown, no raw HTML
* ✅ System Benchmark unlocked by a server-checked password
* ✅ Eyebrow labels, circles, and triangles removed. Streamlit UI removed

Backend architecture

* ✅ Audit and redesign into backend/ (api, agents, tools, graph, services, guardrails, evaluation, observability), with the app.py shim
* ✅ Supervisor, Retrieval Agent and Evidence Evaluator, Tutor, Critic, Quiz Agent, Guide Agent
* ✅ LangGraph workflow with bounded loops and a per-request Budget (12, 6, 3, 2, 45 s)
* ✅ Typed, allow-listed, traced tool layer with isolation in one place
* ✅ Guardrails: identity, input, evidence, output, quiz
* ✅ Chat history in SQLite with a recent window and a rolling summary
* ✅ Learner state per session and document. Legacy files still read
* ✅ Quiz: no answer leak, duplicate and difficulty checks, quote grounding, reload-safe
* ✅ Page-aware PDF ingestion for new uploads
* ✅ GET /evaluation protected by BENCHMARK_PASSWORD

Observability and evaluation

* ✅ agent_trace returned with every answer: steps, decisions, budget used, stop reason
* ✅ Verified golden-set builder and the chem.pdf set (10 of 10 verified, 4/3/3 difficulty)
* ✅ Baseline vs agentic evaluation with LLM-judge metrics, errored rows excluded, retries, report schema v2
* ✅ Live smoke tests (found and fixed follow-up misrouting)

Quality, docs, hygiene

* ✅ Folder tidy-up: runtime data in data/, quiz and plan rules in backend/domain/, project documents in project-docs/, run scripts in scripts/, root guardrails.py shim removed
* ✅ Chat page: restores from the server history, shows a "taking longer" note after 15 s, has a Retry button and a 100 s timeout, and source pills open the excerpt (server history now includes excerpt text)
* ✅ Fixed: follow-up chat questions failed with a 422 error after any reply that had sources (frontend now sends only role and content, backend ignores extra fields, errors show readable text)
* ✅ 214 offline tests
* ✅ Plain-language docs (docs/01 to 12), README, and this document set, all rewritten in a plain readable format
* ✅ .env.example restored to placeholders, key moved to .env, .gitignore extended
* ✅ Cleanup of leftovers (old chat JSONs, stray logs, old sample project, old docx, old golden set)

---

7. KNOWN ISSUES

| Issue | Impact | Plan |
|---|---|---|
| Agentic over-refusal on debatable questions (1/10) | Occasional "couldn't find..." for answerable questions | P1-1 |
| Free-tier rate limit | Slow answers and long evaluations | P1-6. Pacing and backoff already in place |
| Legacy chem.pdf index has no page numbers | Sources show chunk ids only | P1-4 |
| No authentication | The session id is the credential | S-1 |
| Benchmark password has no lockout | Guessable if exposed | S-2 |
| Benchmark password is short | Easy to guess | Use a longer one before any deployment |

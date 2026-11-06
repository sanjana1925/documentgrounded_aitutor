PRD: AI TUTOR GUIDE

Product: a document-grounded, adaptive AI tutor
Status: backend redesign complete and tested, frontend implemented, evaluation run once on a small sample
Last updated: 2026-09-20
Related: [Architecture](Architecture.md) · [Rules](Rules.md) · [Design](Design.md) · [Tasks](Tasks.md) · [Memory](../docs/Memory.md)

---

1. SUMMARY

AI Tutor Guide lets a learner upload a study PDF and then:

* ask questions answered only from that document
* get summaries, key points, simple explanations, and glossaries
* take an adaptive quiz that moves from Simple to Medium to High
* see a dashboard built from real quiz results

The difference is trust. Answers are grounded and cited, refusals are honest, quiz scoring is exact, limits are enforced, and every decision can be inspected in the `agent_trace` returned with each answer.

> Agents decide what to do. Deterministic code enforces what must never go wrong.

---

2. PROBLEM

| Pain | Why existing tools fail |
|---|---|
| Generic chatbots have not read the learner's material | They answer from memory, may invent facts, and give no source |
| Learners cannot tell if an answer is supported | No citations and no "I don't know" behaviour |
| Quizzes are not tied to the learner's document or level | Fixed difficulty, no progression |
| Learners do not know what to revise | No link between quiz results and next steps |
| AI systems are opaque | Hard to debug wrong answers or prove improvements |

---

3. GOALS AND NON-GOALS

Goals

1. Grounded answers: every document answer is supported by retrieved passages, cites them, and is reviewed by an independent critic. Unsupported questions get a standard refusal.
2. Adaptive practice: 15-question Simple phase (70% to advance), then Medium (checked every 5, 70%), then High. Weak-topic targeting and no repeated questions.
3. Honest analytics: the dashboard uses only recorded performance. The AI may not invent numbers.
4. Bounded and safe: 12 model calls, 6 tool calls, 3 searches, 2 revisions, 45 seconds per request. Session and document isolation. Input, evidence, and output guardrails.
5. Explainable and measurable: a per-request `agent_trace`, a verified golden dataset, and baseline vs agentic evaluation where unrun metrics read "Not evaluated yet".
6. Cheap context: the model sees the last 6 messages plus a rolling summary, never the full history.

Non-goals (this release)

* User accounts and login (the session id is the credential)
* Non-PDF sources
* Questions across several documents
* Real-time collaboration, mobile apps, payments
* Fine-tuning or hosting our own models

---

4. USERS

| Who | Need | Success looks like |
|---|---|---|
| Student (primary) | Understand a chapter, get tested, know what to revise | Asks a question, gets a cited answer in seconds, sees weak topics improve |
| Self-learner or professional | Learn from papers or manuals without made-up answers | Trusts the refusals and uses summaries and glossary |
| Developer | Change the system safely and prove it works | Reads a trace, runs tests offline, compares agentic vs baseline |

---

5. USER STORIES AND ACCEPTANCE CRITERIA

5.1 Documents

* I can upload a PDF and see it indexed. Criteria: PDF only, 25 MB max, chunks keep page numbers, re-uploading the same file changes nothing, unreadable PDFs give a clear 400.
* I can delete a document. Criteria: chunks, quiz progress, and chat history for that session and document are removed.
* My documents are private. Criteria: the same filename in two sessions never mixes, covered by automated tests.

5.2 Ask questions

* I get an answer from my document with its sources. Criteria: the reply cites chunks that were really retrieved. A typical request uses 4 model calls and 2 tool calls.
* If the document lacks the answer, I am told so. Criteria: the exact message "I couldn't find enough information about that in the uploaded document."
* Follow-ups work. Criteria: "explain that in simple words" stays a grounded question in simple style.
* Quick modes work. Criteria: Summary, Key points, Explain simply, and Glossary need no AI routing call.
* The reply is readable. Criteria: markdown (bold, lists, nested lists) is shown as formatting, never as raw ** and * symbols.

5.3 Adaptive quiz

* I get questions at my level. Criteria: phase, scoring, progression, and accuracy are computed in Python. The AI only proposes questions.
* Questions are valid and fresh. Criteria: four distinct options, difficulty matches the phase, a word-for-word supporting quote, duplicates rejected, at most 3 attempts then a fallback question.
* I cannot peek at answers. Criteria: the correct index and explanation never reach the browser before I answer.
* Reloading is safe. Criteria: a non-answer message re-shows the pending question without grading it.

5.4 Dashboard and evaluation

* The Dashboard shows raw numbers: accuracy, per-phase accuracy, and a topic table with status.
* The Evaluation page shows which topics are at risk (below 60%, at least 2 answers) and how far below the threshold. It does not repeat Dashboard numbers.
* The System Benchmark on the Evaluation page is behind a password checked on the server.

5.5 Trust, safety, and operations

* Attacks are blocked. Criteria: empty, oversized, or malformed input, prompt injection, and prompt extraction return guardrail_blocked with no model call.
* Nothing runs away. Criteria: every loop-back consumes a bounded counter and time is checked at every step.
* I can inspect any request. Criteria: an `agent_trace` in the response with named agent steps, tool calls, evidence, critic verdict, budget used and stop reason. No secrets in it.

5.6 Evaluation

* I can measure quality honestly. Criteria: only verified examples are scored, provider errors are retried then excluded, unrun metrics are "Not evaluated yet" and both arms use the same questions.

---

6. SCOPE

| Area | Included |
|---|---|
| Intents | qa, summary, key_points, eli5, glossary, quiz, other |
| Agents | Supervisor, Retrieval Agent, Evidence Evaluator, Tutor, Critic, Quiz Agent, Guide Agent, plus a conversation memory step |
| Storage | ChromaDB (chunks), SQLite (chat), JSON files (quiz progress) |
| API | /, /upload, /documents/{filename}, /agent, /dashboard, /evaluation, /quiz/reset, /chat/history |
| UI | Dashboard, AI Tutor, Adaptive Quiz, Evaluation (React and Tailwind) |

---

7. NON-FUNCTIONAL REQUIREMENTS

| Category | Requirement | Status |
|---|---|---|
| Latency | Typical answer within about 10 seconds | Measured average 10.1 s (median 7.3 s) including rate-limit waits. Baseline 2.5 s |
| Cost | Bounded per request | Typical 4 model calls, hard cap 12 |
| Reliability | Failures give an honest fallback, never a crash or made-up answer | Enforced and tested |
| Privacy | Session and document isolation, no secrets or raw session ids in traces | Enforced and tested |
| Compatibility | Existing API shapes preserved | Preserved |
| Accessibility | Visible focus, keyboard use, reduced motion, status never by colour alone | Implemented, see Design.md |

---

8. SUCCESS METRICS

Measured on 2026-09-19 with 10 verified questions from one chemistry chapter. This is a direction, not proof.

| Metric | Baseline RAG | Agentic RAG | Target |
|---|---|---|---|
| Recall@4 (first search) | 0.90 | 0.90 | 0.90 or more |
| Recall over all searches | 0.90 | 1.00 | 0.95 or more |
| Answer similarity (same 9 answers) | 0.847 | 0.922 | 0.85 or more |
| Lexical groundedness (same 9) | 0.486 | 0.837 | 0.75 or more |
| Faithfulness (LLM judge) | 1.00 | 0.98 | 0.95 or more |
| Refused an answerable question | 0/10 | 1/10 | 5% or less (needs a larger set) |
| Model calls per question | 1.0 | 4.6 | 5 or fewer typical |
| Latency per question | 2.5 s | 10.1 s | 8 s or less typical |

Reading: the agentic design gave closer, better-grounded answers and rescued one missed search, at about 4 to 5 times the calls and latency, with one over-refusal and no measurable faithfulness gain. Saying it is better needs a larger, human-reviewed dataset. Full analysis: [09-evaluation.md](../docs/09-evaluation.md).

---

9. ASSUMPTIONS AND CONSTRAINTS

* Gemini gemini-flash-lite-latest on a free tier limited to 15 requests per minute. Agentic questions use 4 to 6 requests, so latency and evaluation runs are rate-limit bound.
* Single-machine deployment (ChromaDB files and a SQLite file). No horizontal scaling.
* No login. Identity is the browser session id plus an optional shared API_KEY.
* The System Benchmark uses one shared BENCHMARK_PASSWORD, with no lockout on wrong guesses.
* The frontend contract (request and response shapes, the quiz reply markdown format) must not break.

---

10. RISKS

| Risk | Impact | Mitigation |
|---|---|---|
| Over-refusal (evaluator too strict) | Learner frustration | Measured at 1/10. Tune the evaluator and track the safe-fallback rate |
| Provider rate limits or outages | Slow or failed answers | Retry with backoff, bounded time, honest fallback, consider a paid tier |
| Session id is the credential | Data exposure if leaked | Documented, hashed in traces, add real auth before a public launch |
| Judge and generator share a model family | Optimistic quality scores | Report with a caveat, add an independent judge |
| Small AI-drafted golden set | Weak evidence for claims | Human review, grow to several documents |
| Secret hygiene (an API key once sat in .env.example) | Key exposure | Moved to .env. Revoke the old key (see Tasks.md) |
| Weak benchmark password | Benchmark data exposed | Use a longer password, add rate limiting before deployment |

---

11. MILESTONES

| Milestone | Status |
|---|---|
| React frontend on the design system | Done |
| Agentic backend (supervisor, retrieval loop, critic, quiz, guide) | Done |
| Guardrails, budgets, isolation | Done |
| Chat history and rolling summary (SQLite) | Done |
| Per-request agent_trace in the API response | Done |
| Verified golden set and baseline vs agentic evaluation | Done (n=10) |
| Markdown rendering in chat | Done |
| Password-protected System Benchmark | Done |
| Full-app audit, authentication, larger eval set, evaluator tuning | Backlog (see Tasks.md) |

---

12. OPEN QUESTIONS

1. Should refusal strictness be tunable per document type (textbook vs research paper)?
2. Is about 10 s typical latency acceptable, or should the retrieval loop be shortened?
3. When should accounts be introduced, and should quiz records move into the database first?
4. Which independent judge model should replace same-family judging?

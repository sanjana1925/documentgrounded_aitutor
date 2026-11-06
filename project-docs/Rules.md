RULES: AI TUTOR GUIDE

The rules every contributor (human or AI assistant) follows in this repository. Each rule has a reason. If a rule blocks you, change the rule deliberately instead of working around it.
Related: [PRD](PRD.md) · [Architecture](Architecture.md) · [Design](Design.md) · [Tasks](Tasks.md) · [Memory](../docs/Memory.md)

---

1. THE PRIME RULE

> Agents decide what to do. Python enforces what must never go wrong.

| An LLM may decide | Python must always control |
|---|---|
| User intent, learning goal, response style | Session and document isolation, session validation |
| Retrieval strategy and query rewrites | Retry limits, max tool calls, max execution time |
| Whether evidence is sufficient | Quiz scoring, progression, accuracy, duplicate prevention |
| Whether an answer needs revision | Schema validation, safety constraints |
| Quiz question wording | Database operations, persistence, dashboard metrics |

Never use an LLM for quiz scoring, security decisions, isolation filters, counters and limits, or computing statistics.

---

2. AGENT RULES

1. An agent must make a real decision: choose an action or tool, observe the result, then continue, revise, or stop. A function that wraps one llm.text() call is a step or service, not an agent. Do not name it one.
2. The Supervisor never writes the final answer.
3. Structured output only. Every decision has a Pydantic schema in agents/schemas.py and is parsed with llm.structured(...). Treat None as "no valid decision" and fall back safely. No regex parsing of free text for decisions.
4. Python normalises decisions so contradictory fields cannot pass (for example intent and next_action).
5. Every agent has a fallback. A failing agent gives the safe fallback, never an unhandled exception or a made-up answer. Provider errors (LLMError) are the only failures passed to the client, with the same HTTP status.
6. Do not add agents for show. Add one only if it makes meaningful decisions. Prefer plain Python where it is enough.
7. Tutor answers must cite retrieved chunks. No citation means reject and revise.
8. The Critic reports and Python decides: finish, revise, retrieve, or fallback. Never ship an ungrounded answer after revisions run out.
9. Document-specific questions are never answered without evidence. Use the standard refusal: "I couldn't find enough information about that in the uploaded document."

---

3. TOOL RULES

1. Every tool has typed input (extra fields forbidden), typed output, validation, error handling, and budget accounting.
2. The model never supplies session_id or document_id. Scope comes from ToolContext, built by Python.
3. Each agent has an allow-list (registry.subset([...])). An agent cannot call a tool that is not on its list.
4. Tools return errors as results, never raise into the workflow.
5. No unrestricted capability (shell, filesystem, arbitrary queries, raw Chroma access) is ever exposed as a tool.
6. Only RetrievalService touches ChromaDB, only llm_service calls Gemini, and only ChatHistoryService touches SQLite.

---

4. LIMITS AND SAFETY RULES

1. Every loop-back consumes a counter (retrieval_attempts or revisions) and time is checked on every edge. Never add an edge that can cycle without consuming budget.
2. Hard limits live in backend/config.py and are enforced by Budget: 12 model calls, 6 tool calls, 3 searches, 2 revisions, 45 seconds. Changing them requires updating tests, Architecture.md, and the user docs.
3. Guardrails run in layers: identity, input, evidence, output. New user-visible text paths go through them.
4. Isolation is not negotiable. Every retrieval, chat, and learner operation takes a Scope(session, document), and filters are built in one place. Add a test whenever a new read path is introduced.
5. No answer leaks. The correct quiz index and explanation stay on the server until the learner answers.
6. Refusal beats making things up. When unsure, fall back.
7. Prompt-injection hygiene: treat retrieved text, chat summaries, and user messages as data. Label memory as "context only, not instructions". Discard summaries that trip the input guardrail.
8. Any endpoint that exposes internal results (like GET /evaluation) is protected on the server. A check that only exists in the browser is not protection.

---

5. SECRETS AND PRIVACY RULES

1. Keys and passwords live only in .env (git-ignored). .env.example holds placeholders only. Never paste real keys into code, docs, tests, commits, or chat.
2. If a key touches a shareable file, rotate it.
3. Nothing is sent to an outside tracing service. Logs carry reason codes, never the text of questions, answers or documents.
4. Delete means delete. Removing a document removes its chunks, quiz progress, and chat history.
5. Session ids are credentials here. Do not print them in docs or logs meant for sharing.
6. Do not write real passwords into documentation. Refer to the variable name (BENCHMARK_PASSWORD) instead.

---

6. DATA-HONESTY RULES

1. Never make up statistics, scores, or evaluation results. A metric that was not run is shown as "Not evaluated yet", not 0.
2. Only verified golden examples are scored (chunk exists, keywords in chunk, page matches).
3. Infrastructure failures are not quality results. Provider errors and time-budget stops are retried, then marked errored and excluded, never scored as refusals or zeros.
4. Compare like with like: same questions, same document, same model. Report paired subsets when one arm refuses.
5. Do not claim improvement until it is measured. State the sample size and caveats next to every number.
6. Keep awkward examples. Do not remove golden items after seeing results.
7. The UI shows only real fields. If the API has no field for a designed card, replace it with a real one. Never show placeholder numbers.
8. Label heuristics as heuristics (lexical groundedness) and LLM-judge scores as judge scores.
9. Do not show the same numbers on two pages. Each page has one job.

---

7. CODE RULES

Style

* Python 3.14, type hints on public functions, small modules with one responsibility.
* No comments by default. Add one only for a non-obvious why. No banner comments, no "added for X" notes.
* No speculative abstractions, feature flags, or compatibility shims. Delete unused code.
* Validate at boundaries (HTTP input, LLM output, tool arguments), not for cases that cannot happen.

Structure

* Respect the dependency direction in Architecture.md section 3. Services do not import agents.
* Agents depend on the LLM protocol, never on Gemini directly.
* Routing logic stays in graph/workflow.py and nodes stay thin.
* Names: agent nodes use agent names, LLM calls are <agent>.<step>, tools are named exactly as registered.

Compatibility

* Do not break the API contract (endpoints, fields, status codes). New fields must be optional. The quiz reply markdown format is parsed by the frontend, so change it only with a matching frontend change and a test.
* app.py remains the uvicorn app:app entry point and re-exports what evaluate.py imports.

---

9. EVALUATION AND OBSERVABILITY RULES

1. Every request records its steps in the state's `trace` list, returned as `agent_trace`. Recording must never break a request.
2. Add events to `trace`; do not invent a second logging path inside agents.
3. Report token counts only when the provider returns them. Never estimate tokens or cost.
4. Evaluation runs must pace requests for the free-tier limit (15 per minute) and use retries with backoff.
5. New metrics need a definition in metric_notes and a "not evaluated" path.

---

10. FRONTEND RULES (details in Design.md)

1. Follow the design tokens in the Tailwind config. No ad-hoc colours, shadows, or radii.
2. Accessibility is required: visible focus, keyboard support, 48 px touch targets on mobile, status never by colour alone, reduced motion respected.
3. Decorative shapes are aria-hidden and pointer-events-none and never cover content.
4. Every page has a designed empty state. Never fake data.
5. The frontend is presentation only. Business logic belongs to the backend.
6. Render model text as markdown through the shared Markdown component. Never render raw HTML from model output.

---

11. REPOSITORY AND PROCESS RULES

1. Ask before destructive actions (deleting files, resetting a learner's progress, force operations). Delete only what was explicitly approved and check what exists first.
2. Do not reset real learner data during testing. Use throwaway sessions and clean them up with DELETE /documents/.... A test once wiped a real session's quiz state through /quiz/reset and it had to be restored.
3. Local data is git-ignored: .env and everything in data/ (chroma_db, tutor.db, learner_states, evaluation_report.json), plus frontend/dist, frontend/node_modules, __pycache__.
4. Update docs and tests with the code. If limits, endpoints, or metrics change, update Architecture.md, the docs/ pages, and README.md.
5. Keep requirements.txt accurate for every imported third-party package, and keep frontend/package.json accurate for the frontend.
6. Do not add frameworks or replace ChromaDB or LangGraph without a concrete, documented reason.
7. Documentation format: plain CAPS section titles, no markdown heading marks (#), no bold, short lines, and short vertical flows instead of large diagrams.

---

12. DEFINITION OF DONE

A change is done when:

* API compatibility is preserved.
* Guardrails and isolation are unaffected or extended with tests.
* A real-model smoke test was run for prompt or routing changes.
* Traces still show named runs, tags, and metadata.
* No secrets, made-up numbers, or placeholder stats were introduced.
* Docs (docs/, README.md, and these project documents) reflect the change.

# EVALUATION: WHAT IS MEASURED, WHERE, HOW AND WHY

This page explains every quality measure in the project, so each one can be explained and defended.
Related: [Architecture](Architecture.md) · [Rules](Rules.md) · [PRD](PRD.md)

---

## 1. TWO DIFFERENT THINGS

The project uses quality checks in two completely separate places. Mixing them up is the most common source of confusion.

| | Live safeguards | Offline benchmark |
|---|---|---|
| **When** | On every chat request | Only when someone runs `python evaluate.py` |
| **Purpose** | Stop or fix a bad answer before the learner sees it | Measure how good the system is, over many questions |
| **Output** | A decision (answer, revise, search again, fall back) | Numbers saved to `data/evaluation_report.json` |
| **Uses a golden dataset** | No | Yes |
| **Where** | `backend/agents/`, `backend/graph/`, `backend/guardrails/` | `backend/evaluation/`, `backend/services/evaluation_service.py`, `evaluate.py` |

The benchmark does not tune the live system. It measures it. Thresholds such as the 0.6 coverage cut-off are set by hand in `backend/config.py`.

---

## 2. LIVE SAFEGUARDS (run on every request)

| Check | Question it answers | Where | What happens on failure |
|---|---|---|---|
| Input guardrail | Is the message empty, oversized, or a prompt-injection attempt? | `guardrails/input.py`, called in `api/routes/agent.py` | Request blocked, no model call |
| Evidence evaluator | Is the retrieved text relevant and sufficient? Returns `coverage` from 0 to 1 | `agents/retrieval.py` (`EvidenceEvaluator`) | Search again with a different strategy (max 3 searches) |
| Coverage threshold | When searches run out, is the evidence still good enough to answer? | `config.MIN_COVERAGE_AT_LIMIT = 0.6`, used in `graph/workflow.py` | Answer from it, or fall back |
| Critic | Is every claim supported by the evidence? Any contradictions? | `agents/critic.py` | Revise (max 2), search again, or fall back |
| Output guardrail | Is the answer non-empty, free of leaked instructions, and does it only cite chunks that were actually retrieved? | `guardrails/output.py`, called in `graph/nodes.py` | Fall back to a safe message |
| Quiz validation | 4 distinct options, valid answer, right difficulty, not a repeat, quote really in the text | `services/quiz_service.py` | Retry, then a fallback question |
| Budget | Too many model calls, tool calls, searches, revisions, or seconds? | `budget.py` | Stop and fall back |

The critic's verdict and the evaluator's coverage are recorded in `agent_trace` in every API response. They are logging only and never change an answer (section 8).

---

## 3. OFFLINE BENCHMARK METRICS

Every metric below is computed per question in `EvaluationService.score()` (`backend/services/evaluation_service.py`), using the formulas in `backend/evaluation/evaluators.py`, then averaged in `aggregate()`.

| Metric | Question it answers | How it is computed | Inputs | Shown on the page |
|---|---|---|---|---|
| **Recall@k** | Did the first search find the right chunk? | 1 if the verified gold source chunk is in the first search's top k, else 0 | First search results, gold chunk | Retrieval card, table |
| **Precision@k** | How much of the top k is relevant? | Share of top k chunks that are the gold chunk or contain at least half of the expected keywords | First search results, keywords | Retrieval card |
| **Answer similarity** | Does the answer mean the same as the reference answer? | Cosine similarity of MiniLM embeddings | Answer, reference answer | Generation card, table |
| **Groundedness** | Does the answer stay inside the evidence? | Share of the answer's content words that appear in the evidence (a heuristic) | Answer, the evidence the system used | Generation card, table |
| **Groundedness (equal evidence)** | Same, but fair between systems | Same heuristic, scored against the standard top-k retrieval of the raw question for every system | Answer, shared top-k chunks | Generation card |
| **Faithfulness (LLM judge)** | Is every claim supported? | A model scores 0 to 1. Only computed with `--judge` | Question, answer, evidence | Generation card |
| **Faithfulness (equal evidence)** | Same, on equal evidence | Judge run again on the shared top-k when it differs from the system's own evidence | Question, answer, shared chunks | Saved in the report |
| **Answer relevancy (LLM judge)** | Does it address the question? | A model scores 0 to 1. Only with `--judge` | Question, answer, evidence | Saved in the report |
| **Latency, calls** | How slow and how costly? | Wall-clock seconds; counts of LLM calls, tool calls, searches, revisions | Run trace and budget | Latency on the page |
| **Completion / decline rate** | How often does it answer versus refuse? | Share of runs that finished; share that fell back or abstained | Run result | Declined on the page |

### Why each metric exists
- **Recall and precision** isolate search quality from answer quality. If recall is low, no amount of prompting fixes the answers.
- **Answer similarity** is a cheap, deterministic check that needs no extra model call.
- **Groundedness** is a cheap, deterministic proxy for "no invention".
- **Faithfulness** is the stronger check on invention, at the cost of extra model calls, so it is opt-in.
- **Equal-evidence versions** exist because the agentic system can gather up to 8 chunks while the baseline sees 4. More text to match makes a system look more grounded for the wrong reason.

---

## 4. HOW A BENCHMARK RUN WORKS

```
python evaluate.py --dataset <file> --session <id> --document <name>.pdf --arm both [--judge] [--judge-model <model>]

1. dataset.split_verified   keep only questions that check out against the indexed PDF
                            (source chunk exists, 60%+ of keywords appear in it, page number matches)
2. for each question, each arm (baseline RAG, agentic RAG):
       run it, score it (section 3), retry provider failures with backoff
3. aggregate()              average over non-errored rows; averages for similarity, groundedness and
                            faithfulness cover answered questions only (num_answered says how many)
4. build_report / save_report   write data/evaluation_report.json (schema version 2)
5. GET /evaluation (password) → Evaluation page reads the saved report
```
Building a dataset from your own document: `python -m backend.evaluation.build_golden --session <id> --document <name>.pdf --n 30 --out <file>`. The model drafts questions, Python verifies them, and every item is marked `needs_human_review`.

Options: `--judge` adds the LLM-judge metrics. `--judge-model` picks a different model for the judge.

---

## 5. RULES THAT KEEP THE NUMBERS HONEST

1. Only verified questions are scored. Unverified ones are listed in the report and never counted.
2. A metric that was not run is shown as "not evaluated", never as 0.
3. A provider failure (rate limit, outage) is retried, and if it persists the row is excluded. An outage is never counted as the tutor declining.
4. Declined questions are left out of the similarity, groundedness and faithfulness averages. The page shows Answered and Declined next to them so this cannot hide.
5. Both systems are compared on the same questions and the same document.
6. Reports from before schema version 2 are ignored.

---

## 6. LIMITS (say these before someone else does)

- **Groundedness is word overlap.** A faithful answer with an analogy can score lower, and a wrong claim that reuses document words can score higher. Use it as a trend, not a verdict.
- **Answer similarity is closeness to one reference answer.** It is not a correctness test, and scores are naturally high for any on-topic text.
- **The faithfulness judge can be the same model that wrote the answer.** That tends to flatter it. Use `--judge-model` with a different model, and the run prints which judge was used.
- **Recall uses one gold chunk per question.** A question whose answer spans two chunks is judged against one.
- **Questions are model-drafted.** They are verified programmatically but a person should still read them.
- **Small question counts are noisy.** With 10 questions one question moves an average by 10 points. The page warns when fewer than 20 were scored.
- **The live critic and the offline faithfulness judge are both model judgements.** Agreement between them is not independent evidence.

---

## 7. QUICK ANSWERS

- **Are these metrics computed while a student chats?** No. Only the live safeguards in section 2 run then.
- **Where are the numbers stored?** `data/evaluation_report.json`, written by `evaluate.py`. It is git-ignored.
- **Which metric should I trust most?** Recall@k. It is a direct, deterministic hit rate.
- **Why are there two groundedness numbers?** One uses the evidence each system gathered, the other uses the same evidence for every system. The second is the fair comparison.
- **Why is faithfulness sometimes missing?** It needs `--judge` and extra model calls, and is shown as N/A otherwise.

---

## 8. OBSERVABILITY: THE agent_trace

There is no external tracing service. Instead, every chat response includes an `agent_trace` that a developer can read directly, and the benchmark reads the same data.

| What is in it | Where it comes from |
|---|---|
| `events`: one entry per step, in order. Supervisor decision and its source; each retrieval attempt with its strategy and the chunks returned; the evidence evaluator's coverage and action; the tutor's action; the critic's verdict (grounded, complete, unsupported claims); the output guardrail result; any fallback reason | the `trace` list in `graph/state.py`, filled by `graph/nodes.py` |
| `budget`: model calls, tool calls, searches, revisions and seconds used, with the limits | `budget.py` |
| `stop_reason`: why a request ended early, if it did | `graph/nodes.py` |

### Why this is enough
It answers the questions that matter when an answer looks wrong: which step decided what, how many searches and revisions ran, which guardrail fired, and whether a limit was reached. Provider errors and retries are in the server log.

### Rules
1. Recording a step must never break a request.
2. Question text, answer text and document excerpts are not logged by the guardrails, only reason codes.
3. Nothing is sent to an outside service. `config.disable_third_party_tracing()` removes the usual hosted-tracing variables so libraries cannot do it on their own.

### Not included
LangSmith tracing, automatic answer scores, learner thumbs up/down, a live-quality summary and hosted dataset experiments were built and then removed to keep the project simple. The local benchmark (`evaluate.py`, sections 3 and 4) covers the measurement side.

---

## 9. LATEST RESULTS

Run on 2026-11-06 with `python evaluate.py --arm both --judge --judge-model gemini-3.5-flash-lite`.

| | Baseline RAG | Agentic RAG |
|---|---:|---:|
| Questions scored / answered | 21 / 21 | 21 / 21 |
| Recall@4 | 1.000 | 1.000 |
| Precision@4 | 0.405 | 0.405 |
| Answer similarity | 0.752 | 0.777 |
| Groundedness (own evidence) | 0.575 | 0.650 |
| Groundedness (equal evidence) | 0.575 | 0.650 |
| Faithfulness (LLM judge, 21 judged each) | 1.000 | 0.955 |
| Chunks the answer was written from | 4.0 | 4.0 |
| Model calls per question | 1.0 | 4.4 |
| Tool calls per question | 1.0 | 2.0 |
| Median / mean time per question | 1.5 s / 6.0 s | 7.2 s / 10.9 s |
| Declined to answer | 0 | 0 |

### How to read it
- **The agent is a little better on similarity (+0.025) and groundedness (+0.075) and a little worse on faithfulness (-0.045).** With 21 questions, one answer moves a faithfulness average by about 0.05, so none of these differences is clear evidence either way.
- **It costs about 4.4 times the model calls and about 5 times the median time.** Whether that is worth it depends on how much the critic's checks matter to you.
- **Recall is 1.0 for both because each question was written from one passage**, which is the easiest case for retrieval. Precision (0.405) is the same for both systems because both run the same first search.
- **Equal-evidence and own-evidence groundedness are identical here** because both systems were given the same 4 chunks. They would differ if the agent gathered more.
- **Judge:** faithfulness was scored by a different model from the one that wrote the answers, which avoids self-judging, but it is still a model's opinion.

### One adjustment, stated openly
During the agent's question 21 the computer went into standby, so the timer read 3,214 seconds and the answer fell back. That row was replaced by a re-run of that single question (19 seconds, answered normally), and every total was recomputed. The report records this under `dataset.adjustments`. Without the replacement the agent's mean time would read 163 seconds and its faithfulness 0.953.

### What would make this stronger
More questions (this document only supports about 21 independent ones), questions about more than one document, questions whose answers span several passages, and a human reading the question set, which is still marked `needs_human_review`.

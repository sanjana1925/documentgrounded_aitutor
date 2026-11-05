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

Nothing in the benchmark feeds back into the live system. It measures the pipeline; it does not tune it. Thresholds such as the 0.6 coverage cut-off are set by hand in `backend/config.py`.

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

The critic's verdict and the evaluator's coverage are written into the trace metadata of every request (LangSmith, and `agent_trace` in the API response). The fields are `evidence_coverage`, `evidence_action`, `critic_action`, `critic_grounded`, `critic_complete` and `critic_unsupported_claims`. They are recorded so the live checks can be compared with the offline scores later. They are logging only and never change an answer.

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

Options: `--judge` adds the LLM-judge metrics. `--judge-model` picks a different model for the judge. `--langsmith` also records the experiment in LangSmith.

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

AI TUTOR GUIDE

A document-grounded AI tutor that helps students learn from their own PDF study materials.

Upload a PDF, ask questions, get simple explanations, take adaptive quizzes, and track performance.

The project uses AI agents for flexible decision-making, while Python handles the important rules: validation, scoring, limits, privacy, and data storage.

Tech Stack: FastAPI · LangGraph · Google Gemini · ChromaDB · SQLite · Pydantic · LangSmith · React · Vite · Tailwind CSS

---

HOW TO RUN

You need Python 3.10+, Node.js 18+, and a Gemini API key.

Step 1: Create the virtual environment and install the backend

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On macOS / Linux use `source .venv/bin/activate` instead of the second line.

Step 2: Create your `.env` file

```bash
copy .env.example .env
```

Open `.env` and fill in your keys (see ENVIRONMENT VARIABLES below).

Step 3: Start the backend (terminal 1)

```bash
python -m uvicorn app:app --reload
```

Backend: http://localhost:8000
API docs: http://localhost:8000/docs

Step 4: Start the frontend (terminal 2)

```bash
cd frontend
npm install
npm run dev
```

Frontend: http://localhost:5173

Step 5: Open http://localhost:5173, upload a PDF, and start learning.

Every day after that, you only need Step 3 and Step 4.

Shortcut on Windows: double-click scripts/start-backend.bat and scripts/start-frontend.bat. They use the .venv in this folder automatically.

---

ENVIRONMENT VARIABLES

```env
GEMINI_API_KEY=<your-key>
API_KEY=
BENCHMARK_PASSWORD=<choose-a-password>

LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<your-key>
LANGSMITH_PROJECT=ai-tutor-guide
```

What each one does:

* GEMINI_API_KEY: required. Lets the tutor use Gemini.
* API_KEY: optional. If set, the backend requires an X-API-Key header on upload, chat and document calls.
* BENCHMARK_PASSWORD: password for the System Benchmark on the Evaluation page. The benchmark stays locked while this is empty.
* LANGSMITH_*: optional. Turns on tracing.

Never commit real keys to GitHub. `.env` is git-ignored.

---

📄 PDF-BASED LEARNING

Upload a PDF and it becomes the tutor's only knowledge source.

```text
PDF → Extract Text → Chunks → Embeddings → ChromaDB
```

---

💬 DOCUMENT-GROUNDED CHAT

Ask questions about the uploaded document.

```text
Question → Supervisor → Retrieval → Evidence Check → Tutor → Critic → Answer
```

If the document does not contain enough information, the tutor says so instead of making something up.

---

🧠 CHAT MEMORY

Chat history is stored in SQLite. The model sees:

* The last 6 messages
* A rolling summary of the conversation

This allows follow-up questions without sending the whole conversation every time.

---

📚 STUDY GUIDES

The tutor can generate a summary, key points, simple explanations, and a glossary.

---

📝 ADAPTIVE QUIZZES

The AI writes questions from the document.

```text
Simple (15 questions) → 70% or more → Medium → High
```

Python handles answer checking, scoring, progression, duplicate prevention, and saving. Correct answers are never sent to the browser early.

---

📊 LEARNING DASHBOARD

Shows overall accuracy, accuracy per difficulty, a topic table, and the current phase. Every number is calculated from recorded quiz answers.

---

🎯 EVALUATION PAGE

Shows which topics are at risk (below 60% accuracy) and how far below the threshold they are.

The System Benchmark (RAG evaluation) is on this page too, and it is password protected.

---

AI AGENTS

Each agent has one clear job.

* Supervisor: understands what the user wants and picks the path. It never writes the final answer.
* Retrieval Agent: chooses how to search the document and can try again if the first search is weak.
* Evidence Evaluator: checks if the retrieved text is enough to answer.
* Tutor Agent: writes the explanation from the evidence.
* Critic Agent: reviews the answer for grounding and unsupported claims.
* Quiz Agent: writes quiz questions with options, topic, and explanation.
* Guide Agent: writes summaries, key points, and glossaries.

---

CONTROLLED AGENTIC WORKFLOW

The main design rule:

> Agents decide what to do. Python decides what is allowed.

Agents handle flexible work: understanding intent, choosing searches, judging evidence, writing content.

Python handles fixed rules: validation, quiz scoring, performance maths, saving data, limits, and stopping.

Every request is limited to:

* 12 model calls
* 6 tool calls
* 3 search attempts
* 2 revisions
* 45 seconds

These limits stop agents from looping forever.

---

GUARDRAILS

Input checks: empty, oversized, or malformed requests, prompt injection, prompt extraction.

Retrieval checks: is the found text relevant, and is it enough?

Output checks: grounding, citations, unsupported claims, leaks, and format.

Guardrails reduce bad behavior. They cannot guarantee every answer is correct.

---

LANGSMITH

LangSmith records every request as a trace, so you can see each agent decision, tool call, retrieved evidence, revision, fallback, and the time taken.

Tracing is skipped if no LangSmith key is set.

---

PROJECT STRUCTURE

```text
app.py            start-up file (uvicorn app:app)
evaluate.py       evaluation runner
requirements.txt  Python packages
.env              your keys (git-ignored)
.venv/            Python virtual environment
backend/          all backend code
frontend/         React app
scripts/          start-backend.bat, start-frontend.bat
data/             your local data: indexed documents, chat database, quiz progress, evaluation report (git-ignored)
project-docs/     PRD, Architecture, Design, Rules, Tasks
```

Main folders inside backend/:

* api/: FastAPI endpoints
* domain/: quiz rules (plain Python, no AI)
* agents/: agent logic
* tools/: tools agents can use
* graph/: LangGraph workflow
* services/: retrieval, Gemini, quiz, memory, storage
* guardrails/: input, retrieval, and output checks
* evaluation/: golden dataset and scoring
* observability/: LangSmith setup

---

API ENDPOINTS

```text
GET     /
POST    /upload
DELETE  /documents/{filename}
POST    /agent
GET     /dashboard
GET     /evaluation        (needs the benchmark password)
POST    /quiz/reset
GET     /chat/history
```

POST /agent is the main endpoint for talking to the tutor.

---

TESTING

```bash
python -m unittest discover tests
```

There are 213 automated tests. They run offline and need no real API keys.

They cover the agent workflow, retrieval, quiz logic, guardrails, validation, API behavior, and the workflow limits.

---

EVALUATION

The project compares two approaches on a verified golden dataset:

```text
Baseline RAG   VS   Agentic RAG
```

Build the golden dataset:

```bash
python -m backend.evaluation.build_golden --session <session_id> --document chem.pdf --n 10 --out data/golden_dataset_chem.json
```

Run the evaluation:

```bash
python evaluate.py --dataset data/golden_dataset_chem.json --session <session_id> --document chem.pdf --arm both --judge --langsmith
```

Results from 10 verified questions from one chapter of chem.pdf (September 19, 2026):

| Metric                       | Baseline RAG | Agentic RAG |
| ---------------------------- | -----------: | ----------: |
| Recall@4                     |         0.90 |        0.90 |
| Recall across searches       |         0.90 |        1.00 |
| Answer similarity            |        0.847 |       0.922 |
| Lexical groundedness         |        0.486 |       0.837 |
| Faithfulness                 |         1.00 |        0.98 |
| Refused answerable questions |         0/10 |        1/10 |
| AI calls per question        |          1.0 |         4.6 |
| Latency per question         |         2.5s |       10.1s |

This is a small test. Read it as a direction, not proof. Agentic RAG gave closer and better-grounded answers, but used about 4 to 5 times more calls and time, and refused one answerable question.

---

WHY THESE TECHNOLOGIES

* LangGraph: shared state, routing, retrieval loops, revision loops, and controlled stopping.
* ChromaDB: stores embeddings and does similarity search with filters.
* SQLite: stores chat history.
* FastAPI: the backend API.
* React: the interactive frontend.
* LangSmith: tracing, debugging, and evaluation.

---

LIMITATIONS

* RAG does not guarantee correct answers.
* Answer quality depends on the PDF and how it is chunked.
* The evaluation set is small.
* Agentic workflows use more model calls and are slower.
* The Gemini free tier allows about 15 requests per minute, so heavy use can be rate limited.
* Prompt-injection protection is not perfect.
* There is no full login system.
* Scanned PDFs may need OCR.
* Quiz progress is still stored in local JSON files.

---

FUTURE IMPROVEMENTS

* Hybrid search and reranking
* OCR for scanned PDFs
* Larger, human-reviewed evaluation sets
* Stronger authentication
* Streaming responses
* Production database and cloud deployment
* Multilingual documents

---

DATA AND PRIVACY

These local files are git-ignored and should never be committed:

```text
.env
data/chroma_db/
data/tutor.db
data/learner_states/
data/evaluation_report.json
```

There is no login system, so the browser's session id works like a private link. Keep it private. LangSmith only receives a one-way fingerprint of it.

---

Built by Sanjana

AI Tutor Guide explores RAG, controlled AI agents, LangGraph workflows, learning analytics, and reliable AI application development.

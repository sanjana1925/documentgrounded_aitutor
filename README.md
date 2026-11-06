<div align="center">

# 🧠 Document Grounded AI Tutor Guide

*A document-grounded AI tutor for learning from your own PDFs.*

</div>

### ✨ Features
- 📄 PDF-based RAG learning
- 💬 Grounded AI tutoring with memory
- 📝 Adaptive quizzes and scoring
- 📊 Performance tracking
- 🤖 Controlled multi-agent workflow
<br>

### 🏗️ Architecture

<p align="center">
  <img src="project-docs/ai-tutor.png" alt="AI Tutor Guide Architecture" width="850">
</p>

<br>

### 🛡️ Guardrails

Input validation · Prompt-injection checks (structure, grammar and meaning, in several languages, also on uploaded documents; see [project-docs/Guardrails.md](project-docs/Guardrails.md)) · Evidence validation · Output grounding · Citation checks · Workflow limits

<br>

### 📈 Evaluation

Measured offline with `python evaluate.py`; see [project-docs/Evaluation.md](project-docs/Evaluation.md) for exactly what each metric is, where it is computed, and its limits.

| Metric | Baseline RAG | Agentic RAG |
|---|---:|---:|
| Recall@4 | 1.00 | 1.00 |
| Answer Similarity | 0.752 | 0.777 |
| Groundedness | 0.575 | 0.650 |
| Faithfulness | 1.00 | 0.955 |
| Model calls per question | 1.0 | 4.4 |
| Median time per question | 1.5 s | 7.2 s |

*Measured on 2026-11-06 with 21 questions drafted from one 7-page PDF and checked against it. Answers by `gemini-flash-lite-latest`; faithfulness judged by `gemini-3.5-flash-lite`. It is a small sample, so differences of a few hundredths are noise. Recall is 1.00 for both because every question was written from a single passage. Details and limits: [project-docs/Evaluation.md](project-docs/Evaluation.md).*

<br>

### 🔍 Observability
Every answer returns an `agent_trace`: each agent step and decision, the tools used, how many model calls and seconds were spent, and why a request stopped. Nothing is sent to an outside tracing service.

<br>

### 🚀 Run it

You need Python 3.10+, Node 18+ and a [Gemini API key](https://aistudio.google.com/apikey).

```bash
# backend (http://localhost:8000)
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env, then set GEMINI_API_KEY
uvicorn app:app --port 8000

# frontend (http://localhost:5173), in a second terminal
cd frontend
copy .env.example .env            # macOS/Linux: cp .env.example .env
npm install
npm run dev
```

On Windows, `scripts/start-backend.bat` and `scripts/start-frontend.bat` start each side.
Documents, chat history and quiz progress are stored locally in `data/`, which is created on first run.

<br>

### 🛠️ Tech Stack
`FastAPI` · `LangGraph` · `Gemini` · `ChromaDB` · `SQLite` · `React` · `Vite` · `Tailwind`

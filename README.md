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

Input validation · Prompt-injection checks · Evidence validation · Output grounding · Citation checks · Workflow limits

<br>

### 📈 Evaluation

| Metric | Baseline RAG | Agentic RAG |
|---|---:|---:|
| Recall@4 | 0.90 | 0.90 |
| Answer Similarity | 0.847 | 0.922 |
| Groundedness | 0.486 | 0.837 |
| Faithfulness | 1.00 | 0.98 |

<br>

### 🔍 Observability
**LangSmith** traces agent decisions, retrieval, revisions, latency, and model calls.

<br>

### 🚀 Run it

You need Python 3.10+, Node 18+ and a [Gemini API key](https://aistudio.google.com/apikey).

```bash
# backend (http://localhost:8000)
python -m venv .venv
.venv\Scriptsctivate            # macOS/Linux: source .venv/bin/activate
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
`FastAPI` · `LangGraph` · `Gemini` · `ChromaDB` · `SQLite` · `LangSmith` · `React` · `Vite` · `Tailwind`

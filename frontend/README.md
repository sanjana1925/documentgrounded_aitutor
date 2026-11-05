# AI Tutor Guide — Frontend

React + Tailwind implementation of the "Playful Geometric" design system, talking to the
existing FastAPI backend (`app.py`) in the parent directory. No backend/RAG/quiz logic
lives here — this is presentation only.

## Setup

```bash
cd frontend
npm install
cp .env.example .env   # adjust VITE_API_URL / VITE_API_KEY if needed
npm run dev
```

Then, in the parent directory, run the FastAPI backend as usual:

```bash
uvicorn app:app --reload
```

The dev server runs at `http://localhost:5173` and calls the API at `http://localhost:8000`
(CORS for this origin is already enabled in `app.py`).

## Structure

- `src/lib/api.js` — typed fetch wrappers for every backend endpoint (`/upload`, `/agent`,
  `/dashboard`, `/evaluation`, `/quiz/reset`, document delete).
- `src/lib/parseQuiz.js` — frontend-only parsing of the quiz endpoint's markdown `reply`
  field into structured feedback (correct/incorrect, explanation, phase-transition banner).
  The question itself comes from the already-structured `quiz_details.question_dict`.
- `src/store.jsx` — session id + per-document chat history, persisted to `localStorage`
  (mirrors what the old Streamlit app kept in `chat_history_*.json`).
- `src/components/` — design-system primitives (buttons, sticker cards, badges, decorative
  shapes, nav, chat bubbles, progress bars).
- `src/pages/` — the four views: Dashboard, AI Tutor, Adaptive Quiz, Evaluation.

## Notes on data fidelity

Every number shown is read directly from the backend's existing responses. Where the design
spec asked for a metric the API doesn't track (e.g. "Study Time" on the dashboard, or a
"Quiz" evaluation group), it was swapped for a real field instead of a fabricated one.

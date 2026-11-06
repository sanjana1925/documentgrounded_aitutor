"""FastAPI application entry point (`uvicorn app:app` or `uvicorn backend.main:app`)."""
import logging
from contextlib import asynccontextmanager
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(override=True)

from backend import config  # noqa: E402
from backend.api.routes import agent as agent_routes  # noqa: E402
from backend.api.routes import chat as chat_routes  # noqa: E402
from backend.api.routes import documents as document_routes  # noqa: E402
from backend.api.routes import learner as learner_routes  # noqa: E402
from backend.container import get_container  # noqa: E402
from backend.guardrails.injection import warm_up as warm_up_injection_check  # noqa: E402
from backend.services.evaluation_service import baseline_generate_answer  # noqa: E402
from backend.services.retrieval_service import Scope  # noqa: E402

logging.basicConfig(level=logging.INFO)

EMBEDDING_MODEL_NAME = config.EMBEDDING_MODEL_NAME


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_container()  # build the vector store / model clients once, at startup
    await run_in_threadpool(warm_up_injection_check)  # load the sentence model so the first message is not slow
    yield


app = FastAPI(title="AI Tutor Guide API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(document_routes.router)
app.include_router(agent_routes.router)
app.include_router(chat_routes.router)
app.include_router(learner_routes.router)


# --- Baseline (non-agentic) RAG, kept as plain functions ---------------------------------------
# evaluate.py uses these as the "baseline RAG" arm to compare against the agentic workflow.
def retrieve_relevant_chunks(question: str, top_k: int, filename: str, session_id: str = "default") -> List[str]:
    chunks = get_container().retrieval.search(Scope(session_id, filename), question, top_k)
    return [c["text"] for c in chunks]


def generate_answer(question: str, context_chunks: List[str], feedback: str = "") -> str:
    return baseline_generate_answer(get_container().llm, question, context_chunks, feedback)

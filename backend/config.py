"""Central configuration. Every limit that bounds agent behaviour lives here, in Python."""
import os
from pathlib import Path

ANSWER_MODEL = os.environ.get("ANSWER_MODEL", "gemini-flash-lite-latest")
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("TUTOR_DATA_DIR", PROJECT_ROOT / "data"))
CHROMA_PATH = str(DATA_DIR / "chroma_db")
COLLECTION_NAME = "pdf_chunks"

CHUNK_SIZE = 800
CHUNK_OVERLAP = 150

# Prompt-injection analysis (guardrails/injection.py). The semantic layer compares each sentence with known attack
# phrasings and with ordinary study phrasings, using a local multilingual sentence-embedding model (no API call).
# "ATTACK" thresholds are cosine similarity to the nearest attack phrasing; "MARGIN" is how much closer that is than
# the nearest ordinary phrasing. Tuned on labelled attack / benign text (see project-docs/Guardrails.md).
INJECTION_EMBEDDING_MODEL = os.environ.get("INJECTION_EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
INJECTION_SEMANTIC_FLAG = float(os.environ.get("INJECTION_SEMANTIC_FLAG", "0.62"))
INJECTION_SEMANTIC_BLOCK = float(os.environ.get("INJECTION_SEMANTIC_BLOCK", "0.68"))
INJECTION_MARGIN_FLAG = float(os.environ.get("INJECTION_MARGIN_FLAG", "-0.05"))
INJECTION_MARGIN_BLOCK = float(os.environ.get("INJECTION_MARGIN_BLOCK", "0.0"))

# Leak check (guardrails/leak.py): how many answer sentences must read like the assistant reciting its own rules before the
# answer is blocked. A single borderline sentence is only logged unless it is a very strong match.
LEAK_PARAPHRASE_MIN_SENTENCES = int(os.environ.get("LEAK_PARAPHRASE_MIN_SENTENCES", "1"))
LEAK_STRONG_SELF_SIM = float(os.environ.get("LEAK_STRONG_SELF_SIM", "0.70"))
LEAK_STRONG_RULE_SIM = float(os.environ.get("LEAK_STRONG_RULE_SIM", "0.55"))

QA_TOP_K = 4
MAX_EVIDENCE_CHUNKS = 8

# Hard per-request budgets. The LLM can never raise these; Python enforces them.
MAX_LLM_CALLS = 12
MAX_TOOL_CALLS = 6
MAX_RETRIEVAL_ATTEMPTS = 3
MAX_REVISIONS = 2
MAX_SECONDS = 45.0
GRAPH_RECURSION_LIMIT = 30

# Evidence acceptance when no retrieval attempts remain.
MIN_COVERAGE_AT_LIMIT = 0.6

QUIZ_DUPLICATE_SIMILARITY = 0.85
QUIZ_MAX_GENERATION_ATTEMPTS = 3
GUIDE_MAX_GROUPS = 8

SESSION_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
MAX_FILENAME_LENGTH = 255

# Chat memory: the LLM sees the recent window + a rolling summary, never the whole history.
DB_PATH = os.environ.get("TUTOR_DB_PATH", str(DATA_DIR / "tutor.db"))
CHAT_RECENT_MESSAGES = 6
SUMMARY_TRIGGER_MESSAGES = 4  # summarise once this many older, unsummarised messages exist
SUMMARY_MAX_CHARS = 800
MAX_STORED_MESSAGE_CHARS = 20000


def disable_third_party_tracing() -> None:
    """
    This app does not send traces anywhere. LangGraph and LangChain would still send them to a hosted tracing service on
    their own if the usual tracing variables were set (for example left over in .env), so those variables are removed.
    Call it right after the .env file is loaded.
    """
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_ENDPOINT", "LANGSMITH_PROJECT"):
        os.environ.pop(name, None)

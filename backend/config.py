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

PLANNER_MIN_MINUTES = 5
PLANNER_MAX_MINUTES = 60
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

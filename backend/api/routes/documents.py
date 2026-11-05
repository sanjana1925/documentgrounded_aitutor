import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from backend.api.schemas import IngestResponse
from backend.api.security import require_api_key
from backend.container import Container, get_container
from backend.ingestion import IngestionError
from backend.guardrails.input import validate_request_identity
from backend.services.retrieval_service import Scope

router = APIRouter()

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@router.get("/")
def home(c: Container = Depends(get_container)):
    return {"message": "Generative AI PDF RAG Chatbot Running", "documents_indexed": c.retrieval.total_chunks()}


@router.post("/upload", response_model=IngestResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    session_id: str = Form("default"),
    _: None = Depends(require_api_key),
    c: Container = Depends(get_container),
):
    name = file.filename or ""
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    ok, err = validate_request_identity(session_id, name)
    if not ok:
        raise HTTPException(status_code=400, detail=err)

    pdf_bytes = await file.read(MAX_UPLOAD_BYTES + 1)  # never buffer more than one byte past the limit
    if len(pdf_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="PDF is too large (25 MB limit)")

    scope = Scope(session_id, name)
    content_hash = hashlib.sha256(pdf_bytes).hexdigest()
    existing, existing_hash = c.retrieval.get_records(scope)
    has_pages = any(ch["page"] is not None for ch in existing)
    if existing and existing_hash == content_hash and has_pages:
        return IngestResponse(filename=name, chunks_added=len(existing))
    # A changed file, or an older index without page numbers, is re-indexed; index_pdf replaces the old copy.
    try:
        added = c.retrieval.index_pdf(scope, pdf_bytes, content_hash)
    except IngestionError as exc:  # not a PDF, encrypted, or no extractable text: a client error with a clear reason
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - any other failure while reading a corrupt PDF is also a client error
        raise HTTPException(status_code=400, detail="Could not read this PDF") from exc
    return IngestResponse(filename=name, chunks_added=added)


@router.delete("/documents/{filename}")
def delete_document(filename: str, session_id: str = "default", _: None = Depends(require_api_key), c: Container = Depends(get_container)):
    ok, err = validate_request_identity(session_id, filename)
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    scope = Scope(session_id, filename)
    c.retrieval.delete(scope)
    c.learner.reset(scope)
    c.chat.delete_for_document(session_id, filename)
    return {"filename": filename, "deleted": True}

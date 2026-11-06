"""
Golden-dataset handling. An example only counts as VERIFIED if it can be checked against the actual
indexed document: the source chunk exists, the expected keywords really appear in it, and (when the
index has page numbers) the recorded page matches. Unverified examples are never scored.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.services.retrieval_service import RetrievalService, Scope

MIN_KEYWORD_SUPPORT = 0.6


def load_dataset(path: Path) -> List[Dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def verify_item(retrieval: RetrievalService, scope: Scope, item: Dict[str, Any]) -> Dict[str, Any]:
    """Returns {"verified": bool, "reasons": [...]} - reasons explain every failed check."""
    reasons: List[str] = []
    if item.get("source_document") != scope.document_id:
        reasons.append(f"example is for '{item.get('source_document')}', not '{scope.document_id}'")
    if retrieval.count(scope) == 0:
        reasons.append(f"document '{scope.document_id}' is not indexed in this session")
        return {"verified": False, "reasons": reasons}

    chunk_id = item.get("source_chunk")
    chunks = retrieval.get_by_indices(scope, [chunk_id]) if isinstance(chunk_id, int) else []
    if not chunks:
        reasons.append(f"source_chunk {chunk_id!r} does not exist in the index")
    else:
        chunk = chunks[0]
        keywords = [k.lower() for k in item.get("expected_keywords", [])]
        text = chunk["text"].lower()
        supported = sum(1 for k in keywords if k in text)
        if not keywords or supported / len(keywords) < MIN_KEYWORD_SUPPORT:
            reasons.append(f"only {supported}/{len(keywords)} expected keywords appear in the source chunk")
        page = item.get("source_page")
        if page is not None and chunk["page"] is not None and chunk["page"] != page:
            reasons.append(f"source_page {page} does not match the chunk's page {chunk['page']}")
    return {"verified": not reasons, "reasons": reasons}


def split_verified(retrieval: RetrievalService, scope: Scope, items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    verified, rejected = [], []
    for item in items:
        result = verify_item(retrieval, scope, item)
        (verified if result["verified"] else rejected).append({**item, "verification": result})
    return verified, rejected

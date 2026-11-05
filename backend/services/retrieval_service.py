"""
ChromaDB access. This is the ONLY module that touches the vector store, and every method
requires a `Scope` (session + document). Isolation filters are built here, in Python - the LLM
never supplies or influences them.
"""
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from backend.ingestion import chunk_pdf

Chunk = Dict[str, Any]  # {"chunk_index": int, "text": str, "page": Optional[int], "distance": Optional[float]}


@dataclass(frozen=True)
class Scope:
    session_id: str
    document_id: str

    def __post_init__(self):
        if not self.session_id or not self.document_id:
            raise ValueError("Scope requires both a session_id and a document_id")


class RetrievalService:
    def __init__(self, collection, splitter):
        self._collection = collection
        self._splitter = splitter

    # ---- isolation ------------------------------------------------------
    @staticmethod
    def _where(scope: Scope, *extra: Dict[str, Any]) -> Dict[str, Any]:
        clauses = [{"source": scope.document_id}, {"session_id": scope.session_id}, *extra]
        return {"$and": clauses}

    @staticmethod
    def _to_chunks(documents, metadatas, distances=None) -> List[Chunk]:
        chunks: List[Chunk] = []
        for i, (doc, meta) in enumerate(zip(documents or [], metadatas or [])):
            page = meta.get("page")
            chunks.append(
                {
                    "chunk_index": int(meta.get("chunk_index", -1)),
                    "text": doc,
                    "page": int(page) if page is not None else None,
                    "distance": float(distances[i]) if distances is not None else None,
                }
            )
        return chunks

    # ---- reads ----------------------------------------------------------
    def get_records(self, scope: Scope) -> Tuple[List[Chunk], Optional[str]]:
        data = self._collection.get(where=self._where(scope), include=["documents", "metadatas"])
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []
        if not docs:
            return [], None
        chunks = sorted(self._to_chunks(docs, metas), key=lambda c: c["chunk_index"])
        content_hash = metas[0].get("content_hash")
        return chunks, content_hash

    def find_by_hash(self, session_id: str, content_hash: str) -> Optional[str]:
        """Name of a document in this session whose file content is identical, else None."""
        data = self._collection.get(
            where={"$and": [{"session_id": session_id}, {"content_hash": content_hash}]}, include=["metadatas"], limit=1
        )
        metas = data.get("metadatas") or []
        return metas[0]["source"] if metas else None

    def list_documents(self, session_id: str) -> List[Dict[str, Any]]:
        """Every indexed document in this session (the browser reconciles its own list against this)."""
        metas = self._collection.get(where={"session_id": session_id}, include=["metadatas"]).get("metadatas") or []
        docs: Dict[str, Dict[str, Any]] = {}
        for m in metas:
            d = docs.setdefault(m["source"], {"filename": m["source"], "num_chunks": 0, "num_pages": None})
            d["num_chunks"] += 1
            if m.get("page") is not None:
                d["num_pages"] = max(d["num_pages"] or 0, int(m["page"]))
        return sorted(docs.values(), key=lambda d: d["filename"].lower())

    def get_texts(self, scope: Scope) -> List[str]:
        chunks, _ = self.get_records(scope)
        return [c["text"] for c in chunks]

    def total_chunks(self) -> int:
        return self._collection.count()

    def count(self, scope: Scope) -> int:
        return len(self._collection.get(where=self._where(scope), include=[]).get("ids") or [])

    def metadata(self, scope: Scope) -> Dict[str, Any]:
        chunks, content_hash = self.get_records(scope)
        pages = [c["page"] for c in chunks if c["page"] is not None]
        return {
            "document_id": scope.document_id,
            "num_chunks": len(chunks),
            "has_page_metadata": bool(pages),
            "num_pages": max(pages) if pages else None,
            "indexed": bool(chunks),
            "content_hash": content_hash,
        }

    def search(self, scope: Scope, query: str, top_k: int = 4, exclude_index: Optional[int] = None) -> List[Chunk]:
        total = self.count(scope)
        if total == 0:
            return []
        n = min(top_k + (1 if exclude_index is not None else 0), total)
        res = self._collection.query(
            query_texts=[query], n_results=n, where=self._where(scope), include=["documents", "metadatas", "distances"]
        )
        if not res["documents"]:
            return []
        chunks = self._to_chunks(res["documents"][0], res["metadatas"][0], res["distances"][0])
        if exclude_index is not None:
            chunks = [c for c in chunks if c["chunk_index"] != exclude_index]
        return chunks[:top_k]

    def get_by_indices(self, scope: Scope, indices: List[int]) -> List[Chunk]:
        if not indices:
            return []
        data = self._collection.get(
            where=self._where(scope, {"chunk_index": {"$in": [int(i) for i in indices]}}),
            include=["documents", "metadatas"],
        )
        return sorted(self._to_chunks(data.get("documents"), data.get("metadatas")), key=lambda c: c["chunk_index"])

    def neighbors(self, scope: Scope, chunk_index: int, window: int = 1) -> List[Chunk]:
        wanted = [i for i in range(chunk_index - window, chunk_index + window + 1) if i >= 0 and i != chunk_index]
        return self.get_by_indices(scope, wanted)

    def by_page(self, scope: Scope, page: int) -> List[Chunk]:
        data = self._collection.get(where=self._where(scope, {"page": int(page)}), include=["documents", "metadatas"])
        return sorted(self._to_chunks(data.get("documents"), data.get("metadatas")), key=lambda c: c["chunk_index"])

    # ---- writes ---------------------------------------------------------
    def delete(self, scope: Scope) -> None:
        self._collection.delete(where=self._where(scope))

    def index_pdf(self, scope: Scope, pdf_bytes: bytes, content_hash: str) -> int:
        """Chunk page by page (every chunk keeps its page number) and index, replacing any earlier copy. Raises IngestionError
        when the PDF is unreadable, encrypted, or has no extractable text. Returns chunks added."""
        chunks = chunk_pdf(pdf_bytes, self._splitter)  # a bad PDF raises here, before anything is touched
        old_ids = self._collection.get(where=self._where(scope), include=[]).get("ids") or []
        self._collection.add(
            documents=[c.text for c in chunks],
            ids=[str(uuid.uuid4()) for _ in chunks],
            metadatas=[
                {
                    "source": scope.document_id,
                    "session_id": scope.session_id,
                    "chunk_index": c.index,
                    "content_hash": content_hash,
                    "page": c.page,
                }
                for c in chunks
            ],
        )
        if old_ids:  # replace only after the new copy is stored, so a failed add keeps the old one
            self._collection.delete(ids=old_ids)
        return len(chunks)

import pytest

from backend.ingestion import IngestionError, chunk_pdf
from tests.pdf_util import make_pdf


def test_chunks_keep_page_numbers_and_never_straddle_pages():
    chunks = chunk_pdf(make_pdf(["Alpha page one text.", "Beta page two text."]))
    assert [c.page for c in chunks] == [1, 2]
    assert [c.index for c in chunks] == [0, 1]


def test_rejects_non_pdf_bytes():
    with pytest.raises(IngestionError, match="not a valid PDF"):
        chunk_pdf(b"hello world")


def test_rejects_pdf_without_extractable_text():
    with pytest.raises(IngestionError, match="No readable text"):
        chunk_pdf(make_pdf([""]))


def test_reupload_replaces_old_chunks_and_failed_reupload_keeps_them(tmp_path):
    import chromadb
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    from backend.services.retrieval_service import RetrievalService, Scope
    from tests.helpers import HashEmbedding

    coll = chromadb.PersistentClient(path=str(tmp_path)).get_or_create_collection("test_chunks", embedding_function=HashEmbedding())
    svc = RetrievalService(coll, RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=150))
    scope = Scope("s1", "a.pdf")
    svc.index_pdf(scope, make_pdf(["one", "two"]), "h1")
    svc.index_pdf(scope, make_pdf(["only"]), "h2")
    assert svc.count(scope) == 1
    with pytest.raises(IngestionError):
        svc.index_pdf(scope, b"not a pdf", "h3")
    assert svc.count(scope) == 1

"""PDF bytes -> list of chunks. Each chunk keeps its page number so answers can cite it later."""
import io
from dataclasses import dataclass
from typing import List

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from backend import config


class IngestionError(ValueError):
    """The upload cannot be turned into chunks (not a PDF, encrypted, or no extractable text)."""


@dataclass(frozen=True)
class Chunk:
    index: int
    page: int
    text: str


_default_splitter = RecursiveCharacterTextSplitter(chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP)


def extract_pages(pdf_bytes: bytes) -> List[str]:
    if not pdf_bytes.startswith(b"%PDF"):
        raise IngestionError("That file is not a valid PDF.")
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted:
            raise IngestionError("This PDF is password protected.")
        return [page.extract_text() or "" for page in reader.pages]
    except PyPdfError as exc:
        raise IngestionError("Could not read this PDF.") from exc


def chunk_pdf(pdf_bytes: bytes, splitter=None) -> List[Chunk]:
    """Split page by page so a chunk never straddles two pages."""
    splitter = splitter or _default_splitter
    chunks: List[Chunk] = []
    for page_number, page_text in enumerate(extract_pages(pdf_bytes), start=1):
        if not page_text.strip():
            continue
        for piece in splitter.split_text(page_text):
            chunks.append(Chunk(index=len(chunks), page=page_number, text=piece))
    if not chunks:
        raise IngestionError("No readable text found. Scanned or image-only PDFs are not supported.")
    return chunks

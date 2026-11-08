"""Approved company-knowledge document ingestion.

Uploads are company knowledge only — never visitor documents. Supports
PDF, DOCX and TXT; enforces type/size limits; extracts text, chunks it with
source metadata, versions it, and feeds the shared retriever. Visitor
attachments are handled separately and are never indexed here.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .rag import KnowledgeChunk, SourceReference

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}
_CHUNK_SIZE = 1200
_CHUNK_OVERLAP = 150


class DocumentIngestionError(RuntimeError):
    pass


@dataclass
class DocumentRecord:
    document_id: str
    filename: str
    title: str
    version: str
    status: str  # uploaded | processing | indexed | failed
    chunk_count: int = 0
    error: str | None = None
    uploaded_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    sha256: str | None = None


def _extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".txt":
            return data.decode("utf-8", errors="replace")
        if ext == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        if ext == ".docx":
            import docx

            doc = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as exc:
        raise DocumentIngestionError(f"Could not extract text: {exc}") from exc
    raise DocumentIngestionError(f"Unsupported file type '{ext}'.")


def _chunk_text(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + _CHUNK_SIZE, len(text))
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = end - _CHUNK_OVERLAP
    return [c for c in chunks if c]


class KnowledgeStore:
    """Filesystem-backed approved-knowledge index (JSON metadata + chunks)."""

    def __init__(self, root: str | Path = "data/knowledge") -> None:
        self.root = Path(root)
        self.docs_dir = self.root / "documents"
        self.index_path = self.root / "index.json"
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        # Index read-modify-write must be atomic across concurrent uploads.
        self._lock = threading.Lock()

    def _load_index(self) -> dict[str, Any]:
        if self.index_path.exists():
            try:
                return json.loads(self.index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {"documents": {}}

    def _save_index(self, index: dict[str, Any]) -> None:
        self.index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")

    def list_documents(self) -> list[DocumentRecord]:
        index = self._load_index()
        records = []
        for doc_id, meta in index.get("documents", {}).items():
            records.append(DocumentRecord(
                document_id=doc_id,
                filename=meta.get("filename", ""),
                title=meta.get("title", ""),
                version=meta.get("version", "1"),
                status=meta.get("status", "uploaded"),
                chunk_count=meta.get("chunk_count", 0),
                error=meta.get("error"),
                uploaded_at=meta.get("uploaded_at", ""),
                sha256=meta.get("sha256"),
            ))
        return records

    def ingest(
        self,
        filename: str,
        data: bytes,
        *,
        max_bytes: int,
        title: str | None = None,
    ) -> tuple[DocumentRecord, list[KnowledgeChunk]]:
        """Validate, store, extract and chunk one approved knowledge document."""
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise DocumentIngestionError(
                f"File type '{ext or 'unknown'}' is not allowed. Accepted: PDF, DOCX, TXT."
            )
        if not data:
            raise DocumentIngestionError("Empty file.")
        if len(data) > max_bytes:
            raise DocumentIngestionError(
                f"File exceeds the {max_bytes // (1024 * 1024)} MB limit."
            )

        digest = hashlib.sha256(data).hexdigest()
        doc_title = (title or Path(filename).stem).strip()[:200] or Path(filename).stem
        index = self._load_index()

        # Re-ingesting identical content reuses the document id (re-index path).
        existing_id = next(
            (d for d, m in index["documents"].items() if m.get("sha256") == digest), None
        )
        doc_id = existing_id or f"doc-{uuid4().hex[:12]}"
        version = "1"
        if existing_id:
            version = str(int(index["documents"][existing_id].get("version", "1")) + 1)

        record = DocumentRecord(
            document_id=doc_id,
            filename=Path(filename).name[:200],
            title=doc_title,
            version=version,
            status="processing",
            sha256=digest,
        )
        with self._lock:
            index = self._load_index()
            index["documents"][doc_id] = {
                "filename": record.filename,
                "title": doc_title,
                "version": version,
                "status": "processing",
                "chunk_count": 0,
                "uploaded_at": record.uploaded_at,
                "sha256": digest,
            }
            self._save_index(index)

        try:
            text = _extract_text(filename, data)
            pieces = _chunk_text(text)
            if not pieces:
                raise DocumentIngestionError("Document contained no extractable text.")
        except DocumentIngestionError as exc:
            with self._lock:
                index = self._load_index()
                index["documents"][doc_id].update({"status": "failed", "error": str(exc)})
                self._save_index(index)
            record.status = "failed"
            record.error = str(exc)
            return record, []

        (self.docs_dir / f"{doc_id}-v{version}.txt").write_text(text, encoding="utf-8")

        source = SourceReference(document_id=doc_id, title=doc_title, version=version)
        chunks = [KnowledgeChunk(text=p, source=source, approved=True) for p in pieces]

        with self._lock:
            index = self._load_index()
            index["documents"][doc_id].update({
                "status": "indexed",
                "chunk_count": len(chunks),
                "error": None,
            })
            self._save_index(index)
        record.status = "indexed"
        record.chunk_count = len(chunks)
        return record, chunks

    def remove(self, document_id: str) -> bool:
        """Remove a document and all its stored versions from the index.

        Returns True if the document existed. Caller is responsible for
        re-syncing the retriever afterwards."""
        with self._lock:
            index = self._load_index()
            if document_id not in index.get("documents", {}):
                return False
            del index["documents"][document_id]
            self._save_index(index)
        for f in self.docs_dir.glob(f"{document_id}-v*.txt"):
            try:
                f.unlink()
            except OSError:
                pass
        return True

    def indexed_chunks(self) -> list[KnowledgeChunk]:
        """Rebuild retrievable chunks for all indexed documents (startup reload)."""
        chunks: list[KnowledgeChunk] = []
        index = self._load_index()
        for doc_id, meta in index.get("documents", {}).items():
            if meta.get("status") != "indexed":
                continue
            version = meta.get("version", "1")
            text_file = self.docs_dir / f"{doc_id}-v{version}.txt"
            if not text_file.exists():
                continue
            source = SourceReference(
                document_id=doc_id,
                title=meta.get("title", doc_id),
                version=version,
            )
            for piece in _chunk_text(text_file.read_text(encoding="utf-8")):
                chunks.append(KnowledgeChunk(text=piece, source=source, approved=True))
        return chunks

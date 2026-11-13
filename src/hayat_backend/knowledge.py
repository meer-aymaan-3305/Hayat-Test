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
import logging
import os
import re
import tempfile
import threading
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .rag import KnowledgeChunk, SourceReference

logger = logging.getLogger("hayat.knowledge")

# File type is decided by extension (browsers report inconsistent content types for
# DOCX/TXT), and the parser then rejects anything that is not really that format.
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
_CHUNK_SIZE = 1200
_CHUNK_OVERLAP = 150

# Limits that stop a small upload from expanding into an event-loop or memory bomb.
_MAX_PDF_PAGES = 300
_MAX_TEXT_CHARS = 5_000_000
_MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
_MAX_DOCX_ENTRIES = 2_000
_MAX_DOCX_RATIO = 100
_RATIO_CHECK_FLOOR_BYTES = 1024 * 1024
_UNREADABLE_FILE = "Could not read this file."


class DocumentIngestionError(RuntimeError):
    pass


class DocumentNotFoundError(DocumentIngestionError):
    pass


class KnowledgeStoreError(RuntimeError):
    """The knowledge store is unusable (unwritable folder or damaged index)."""


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


def _check_docx_archive(data: bytes) -> None:
    """Reject zip bombs before python-docx unpacks the archive.

    Declared sizes are trustworthy upper bounds: zipfile never reads past them."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise DocumentIngestionError(_UNREADABLE_FILE) from exc
    total = sum(entry.file_size for entry in entries)
    if (
        len(entries) > _MAX_DOCX_ENTRIES
        or total > _MAX_DOCX_UNCOMPRESSED_BYTES
        or (total > _RATIO_CHECK_FLOOR_BYTES and total / max(len(data), 1) > _MAX_DOCX_RATIO)
    ):
        raise DocumentIngestionError("This document is too large or too compressed to process.")


def _extract_text(filename: str, data: bytes) -> str:
    """Blocking and CPU-heavy: callers on the event loop must run it in a thread."""
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".txt":
            text = data.decode("utf-8", errors="replace")
        elif ext == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            if len(reader.pages) > _MAX_PDF_PAGES:
                raise DocumentIngestionError(
                    f"PDF has too many pages (limit {_MAX_PDF_PAGES})."
                )
            parts: list[str] = []
            total = 0
            for page in reader.pages:
                page_text = page.extract_text() or ""
                total += len(page_text)
                if total > _MAX_TEXT_CHARS:
                    raise DocumentIngestionError("Document contains too much text.")
                parts.append(page_text)
            text = "\n".join(parts)
        elif ext == ".docx":
            import docx

            _check_docx_archive(data)
            doc = docx.Document(io.BytesIO(data))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        else:
            raise DocumentIngestionError(f"Unsupported file type '{ext}'.")
    except DocumentIngestionError:
        raise
    except Exception as exc:
        # Parser messages can echo file content or internals: log, never return.
        logger.warning("Could not extract text from %s upload: %s", ext, exc)
        raise DocumentIngestionError(_UNREADABLE_FILE) from exc
    if len(text) > _MAX_TEXT_CHARS:
        raise DocumentIngestionError("Document contains too much text.")
    return text


def _chunk_text(text: str) -> list[str]:
    """Passages that never start or end mid sentence (IMPLEMENTATION.md, phase 4). Paragraphs
    and sentences are packed up to the chunk size; the last sentence of one passage opens the
    next, so a fact that sits on a boundary is still found whole."""
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n+", text)]
    sentences: list[str] = []
    for paragraph in paragraphs:
        if not paragraph:
            continue
        parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", paragraph) if s.strip()]
        for part in parts:
            # A single very long sentence is still split, at word boundaries.
            while len(part) > _CHUNK_SIZE:
                cut = part.rfind(" ", 0, _CHUNK_SIZE)
                cut = cut if cut > _CHUNK_SIZE // 2 else _CHUNK_SIZE
                sentences.append(part[:cut].strip())
                part = part[cut:].strip()
            if part:
                sentences.append(part)
    chunks: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        if current and len(" ".join(current + [sentence])) > _CHUNK_SIZE:
            chunks.append(" ".join(current))
            overlap = current[-1] if len(current[-1]) <= _CHUNK_OVERLAP * 2 else ""
            current = [overlap] if overlap else []
        current.append(sentence)
    if current:
        chunks.append(" ".join(current))
    return [c for c in chunks if c]


class KnowledgeStore:
    """Filesystem-backed approved-knowledge index (JSON metadata + chunks)."""

    def __init__(self, root: str | Path = "data/knowledge") -> None:
        self.root = Path(root)
        self.docs_dir = self.root / "documents"
        self.index_path = self.root / "index.json"
        # Index read-modify-write must be atomic across concurrent uploads.
        self._lock = threading.Lock()
        # An unwritable folder must not stop Hayat from starting: uploads are
        # switched off and every knowledge call reports the store as unavailable.
        self.available = True
        try:
            self.docs_dir.mkdir(parents=True, exist_ok=True)
            if not os.access(self.docs_dir, os.W_OK | os.X_OK):
                raise PermissionError(f"{self.docs_dir} is not writable")
        except OSError as exc:
            self.available = False
            logger.error(
                "Knowledge folder %s is unusable, knowledge uploads are disabled: %s",
                self.root, exc,
            )

    def _load_index(self) -> dict[str, Any]:
        if not self.available:
            raise KnowledgeStoreError("Knowledge store is unavailable.")
        if not self.index_path.exists():
            return {"documents": {}}  # clean first run
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            # Never fall back to an empty index: the next save would overwrite
            # every approved document's record.
            logger.error("Knowledge index %s is unreadable: %s", self.index_path, exc)
            raise KnowledgeStoreError("Knowledge index is unreadable.") from exc

    def _save_index(self, index: dict[str, Any]) -> None:
        """Write atomically: temp file in the same folder, fsync, then rename."""
        payload = json.dumps(index, indent=2, ensure_ascii=False)
        fd, tmp_name = tempfile.mkstemp(dir=self.root, prefix="index.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.index_path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        try:
            dir_fd = os.open(self.root, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)

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

    def update(
        self,
        document_id: str,
        filename: str,
        data: bytes,
        *,
        max_bytes: int,
        title: str | None = None,
    ) -> tuple[DocumentRecord, list[KnowledgeChunk]]:
        """Update an existing document in place: same document_id, version+1.

        Content is validated and extracted BEFORE the index is touched, so a
        failed update never disturbs the previously active version. Prior
        version files remain on disk for audit; only the active version is
        indexed for retrieval."""
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

        index = self._load_index()
        meta = index.get("documents", {}).get(document_id)
        if meta is None:
            raise DocumentNotFoundError("Document not found.")

        # Extract first — a failure here leaves the active version untouched.
        try:
            text = _extract_text(filename, data)
            pieces = _chunk_text(text)
            if not pieces:
                raise DocumentIngestionError("Document contained no extractable text.")
        except DocumentIngestionError:
            raise

        digest = hashlib.sha256(data).hexdigest()
        doc_title = (title or meta.get("title") or Path(filename).stem).strip()[:200]

        with self._lock:
            index = self._load_index()
            meta = index["documents"][document_id]
            version = str(int(meta.get("version", "1")) + 1)
            (self.docs_dir / f"{document_id}-v{version}.txt").write_text(text, encoding="utf-8")
            index["documents"][document_id].update({
                "filename": Path(filename).name[:200],
                "title": doc_title,
                "version": version,
                "status": "indexed",
                "chunk_count": len(pieces),
                "error": None,
                "sha256": digest,
                "uploaded_at": meta.get("uploaded_at"),
            })
            self._save_index(index)

        record = DocumentRecord(
            document_id=document_id,
            filename=Path(filename).name[:200],
            title=doc_title,
            version=version,
            status="indexed",
            chunk_count=len(pieces),
            sha256=digest,
        )
        source = SourceReference(document_id=document_id, title=doc_title, version=version)
        chunks = [KnowledgeChunk(text=p, source=source, approved=True) for p in pieces]
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

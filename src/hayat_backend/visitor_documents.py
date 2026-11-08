"""Visitor-uploaded medical document support.

Visitor documents are strictly separate from the admin knowledge base:
they are stored per guest session on the local filesystem (private
``attachments_dir``), never indexed as company knowledge, never sent to
the CRM, and never used for model training. Access is enforced at the API
layer through session authorization plus per-document ownership checks.

Processing is fail-closed: extraction problems produce ``failed`` or
``needs_clearer_upload`` status — a document is never reported as reviewed
unless extraction actually succeeded.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger("hayat_backend.visitor_documents")

# Consent type recorded through the existing consent_records mechanism.
DOCUMENT_CONSENT_TYPE = "visitor_document_processing"
DOCUMENT_CONSENT_VERSION = "visitor-docs-v1"

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".png", ".jpg", ".jpeg"}
MAX_PAGES = 20
MAX_OCR_PAGES = 5
MIN_EXTRACTED_CHARS = 40
LOW_CONFIDENCE_CHARS = 200
MAX_DOC_CHARS = 6000
MAX_TOTAL_CONTEXT_CHARS = 12000

STATUS_UPLOADED = "uploaded"
STATUS_PROCESSED = "processed"
STATUS_NEEDS_CLEARER = "needs_clearer_upload"
STATUS_FAILED = "failed"
STATUS_DELETED = "deleted"


@dataclass
class VisitorDocument:
    """Metadata + processing state for one visitor-uploaded document."""

    id: UUID
    session_id: UUID
    conversation_id: UUID
    filename: str
    media_type: str
    size_bytes: int
    status: str = STATUS_UPLOADED
    extraction_method: str | None = None  # "text" | "ocr" | "mixed" | None
    page_count: int | None = None
    confidence: str | None = None  # "high" | "low" | None
    extracted_chars: int = 0
    extracted_text: str | None = None
    storage_path: str | None = None
    consent_version: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    processed_at: datetime | None = None
    deleted_at: datetime | None = None

    def public_dict(self, include_text: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "document_id": str(self.id),
            "conversation_id": str(self.conversation_id),
            "filename": self.filename,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "status": self.status,
            "extraction_method": self.extraction_method,
            "page_count": self.page_count,
            "confidence": self.confidence,
            "extracted_chars": self.extracted_chars,
            "consent_version": self.consent_version,
            "created_at": self.created_at.isoformat(),
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
        }
        if include_text:
            data["extracted_text"] = self.extracted_text
        return data


def validate_upload(data: bytes, ext: str) -> str | None:
    """Validate extension + magic bytes. Returns error string or None."""
    if ext not in ALLOWED_EXTENSIONS:
        return "unsupported_type"
    if not data:
        return "empty_file"
    head = data[:8]
    checks = {
        ".pdf": head.startswith(b"%PDF-"),
        ".docx": head.startswith(b"PK\x03\x04"),
        ".png": head.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": head.startswith(b"\xff\xd8\xff"),
        ".jpeg": head.startswith(b"\xff\xd8\xff"),
    }
    if not checks.get(ext, False):
        return "content_mismatch"
    # Reject embedded active-content signatures commonly found in malicious
    # documents (JavaScript / launch actions). This is a basic filter — full
    # malware scanning requires infrastructure-level AV and is documented
    # as an outstanding operational dependency.
    if re.search(rb"/JavaScript|/JS\b|/Launch\b|/EmbeddedFile", data[:65536]):
        return "unsafe_content"
    return None


def _ocr_image(image_bytes: bytes, langs: str = "eng") -> tuple[str, float | None]:
    """OCR one image; returns (text, mean_confidence 0-100 or None)."""
    import pytesseract
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes))
    text = pytesseract.image_to_string(image, lang=langs)
    conf = None
    try:
        data = pytesseract.image_to_data(image, lang=langs, output_type=pytesseract.Output.DICT)
        vals = [c for c in data.get("conf", []) if isinstance(c, (int, float)) and c >= 0]
        if vals:
            conf = sum(vals) / len(vals)
    except Exception:  # noqa: BLE001 — confidence is best-effort
        conf = None
    return text or "", conf


def extract_document_text(data: bytes, ext: str) -> tuple[str, dict[str, Any]]:
    """Extract text with per-page markers. Returns (text, metadata).

    Never raises for content problems — failures are reported via metadata
    so callers can mark the document failed/needs-clearer instead of
    pretending it was reviewed.
    """
    meta: dict[str, Any] = {"method": None, "pages": None, "confidence": None}
    try:
        if ext == ".pdf":
            return _extract_pdf(data, meta)
        if ext == ".docx":
            return _extract_docx(data, meta)
        if ext in {".png", ".jpg", ".jpeg"}:
            return _extract_image(data, meta)
    except Exception as exc:  # noqa: BLE001 — extraction must fail closed
        logger.warning("Document extraction failed for %s: %s", ext, exc)
        meta["error"] = type(exc).__name__
    return "", meta


def _extract_pdf(data: bytes, meta: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return _pdf_text_and_ocr(data, meta)


def _pdf_text_and_ocr(data: bytes, meta: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Second pass kept simple: re-open and emit pages in order."""
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    meta["pages"] = len(doc)
    parts: list[str] = []
    used_ocr = False
    used_text = False
    confs: list[float] = []
    for i, page in enumerate(doc):
        if i >= MAX_PAGES:
            parts.append(f"## Page {i + 1}\n[additional pages not processed]")
            continue
        text = (page.get_text("text") or "").strip()
        if len(text) >= MIN_EXTRACTED_CHARS:
            used_text = True
            parts.append(f"## Page {i + 1}\n{text}")
            continue
        try:
            pix = page.get_pixmap(dpi=200)
            ocr_text, conf = _ocr_image(pix.tobytes("png"))
        except Exception:  # noqa: BLE001
            ocr_text, conf = "", None
        if ocr_text.strip():
            used_ocr = True
            if conf is not None:
                confs.append(conf)
            parts.append(f"## Page {i + 1}\n{ocr_text.strip()}")
        else:
            parts.append(f"## Page {i + 1}\n[no readable text]")
    doc.close()
    meta["method"] = "mixed" if used_text and used_ocr else ("ocr" if used_ocr else "text")
    if confs:
        meta["confidence"] = "low" if (sum(confs) / len(confs)) < 60 else "high"
    return "\n\n".join(parts), meta


def _extract_docx(data: bytes, meta: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    import docx

    document = docx.Document(io.BytesIO(data))
    parts: list[str] = []
    for para in document.paragraphs:
        if para.text.strip():
            parts.append(para.text.strip())
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    meta["method"] = "text"
    meta["pages"] = None
    text = "\n".join(parts)
    meta["confidence"] = "high" if len(text) >= LOW_CONFIDENCE_CHARS else "low"
    return text, meta


def _extract_image(data: bytes, meta: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    text, conf = _ocr_image(data)
    meta["method"] = "ocr"
    meta["pages"] = 1
    meta["confidence"] = "low" if (conf is not None and conf < 60) or len(text.strip()) < LOW_CONFIDENCE_CHARS else "high"
    return text.strip(), meta


def classify_extraction(text: str, meta: dict[str, Any]) -> str:
    """Map extraction output to a document status."""
    if meta.get("error"):
        return STATUS_FAILED
    if len(text.strip()) < MIN_EXTRACTED_CHARS:
        return STATUS_NEEDS_CLEARER
    return STATUS_PROCESSED


def build_document_context(
    documents: list[VisitorDocument],
    max_total_chars: int = MAX_TOTAL_CONTEXT_CHARS,
) -> str:
    """Build the untrusted-data prompt block for ChatService.

    Only ``processed`` documents with extracted text are included. Output is
    truncated deterministically; page markers from extraction are preserved
    so the model can cite document + page.
    """
    blocks: list[str] = []
    remaining = max_total_chars
    for doc in documents:
        if doc.status != STATUS_PROCESSED or not doc.extracted_text:
            continue
        header = (
            f"### Document: {doc.filename} "
            f"(document_id={doc.id}, uploaded {doc.created_at.date().isoformat()})"
        )
        body = doc.extracted_text[: min(MAX_DOC_CHARS, remaining)]
        if not body:
            break
        blocks.append(f"{header}\n{body}")
        remaining -= len(body)
        if remaining <= 0:
            break
    return "\n\n".join(blocks)

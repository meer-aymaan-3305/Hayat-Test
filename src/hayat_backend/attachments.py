"""Visitor file attachments: private storage, intake validation and retention.

Files are kept exactly as received and are never parsed, summarised, indexed as
company knowledge or sent to the CRM or an AI provider. Each conversation gets
its own folder holding the files (generated names only) and a small
`index.json` with the display metadata.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger("hayat.attachments")

MAX_FILES_PER_CONVERSATION = 5
ALLOWED_EXTENSIONS = (".pdf", ".docx", ".txt")
# Fixed per extension: the visitor's own content type is never echoed back.
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain; charset=utf-8",
}
_MAGIC_PREFIX = {".pdf": b"%PDF", ".docx": b"PK"}
_ATTACHMENT_ID = re.compile(r"^[0-9a-f]{32}$")
_MAX_NAME_CHARS = 120

ACKNOWLEDGEMENTS = {
    "en": {
        "user": "Attached file: {filename}",
        "reply": "I've saved your file with this conversation. I can't read or review documents myself.",
    },
    "ar": {
        "user": "تم إرفاق ملف: {filename}",
        "reply": "حفظتُ ملفك ضمن هذه المحادثة. لا أستطيع قراءة المستندات أو مراجعتها بنفسي.",
    },
}


class AttachmentError(Exception):
    """The file was refused; the message is safe to show the visitor."""


class AttachmentStoreError(Exception):
    """The attachment index could not be read or written."""


def is_attachment_id(value: str) -> bool:
    return bool(_ATTACHMENT_ID.fullmatch(value))


def safe_display_name(filename: str | None) -> str:
    """A filename for display only: no path, no control characters, bounded length."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    if len(name) > _MAX_NAME_CHARS:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: _MAX_NAME_CHARS - len(ext) - 1] + "." + ext) if dot else name[:_MAX_NAME_CHARS]
    return name or "file"


def validate_upload(filename: str | None, data: bytes, max_bytes: int) -> str:
    """Return the lower-case extension, or raise AttachmentError."""
    ext = Path(safe_display_name(filename)).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise AttachmentError("Only PDF, DOCX and TXT files can be attached.")
    if not data:
        raise AttachmentError("The file is empty.")
    if len(data) > max_bytes:
        raise AttachmentError(f"The file is too large (limit {max_bytes // (1024 * 1024)} MB).")
    if ext == ".txt":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AttachmentError("The file content does not match its type.") from exc
        if b"\x00" in data:
            raise AttachmentError("The file content does not match its type.")
    elif not data.startswith(_MAGIC_PREFIX[ext]):
        raise AttachmentError("The file content does not match its type.")
    return ext


class AttachmentStore:
    def __init__(self, root: str | Path, retention_days: int = 0) -> None:
        self.root = Path(root)
        self.retention_days = retention_days
        self._lock = threading.Lock()

    def save(self, conversation_id: str, filename: str | None, data: bytes, ext: str) -> dict[str, Any]:
        directory = self.root / str(conversation_id)
        with self._lock:
            entries = self._read(directory)
            if len(entries) >= MAX_FILES_PER_CONVERSATION:
                raise AttachmentError(
                    f"You can attach up to {MAX_FILES_PER_CONVERSATION} files to one conversation."
                )
            attachment_id = uuid4().hex
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{attachment_id}{ext}").write_bytes(data)
            entry = {
                "id": attachment_id,
                "filename": safe_display_name(filename),
                "extension": ext,
                "size": len(data),
                "uploaded_at": datetime.now(UTC).isoformat(),
            }
            try:
                self._write(directory, entries + [entry])
            except BaseException:
                (directory / f"{attachment_id}{ext}").unlink(missing_ok=True)
                raise
        return entry

    def list_for(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return self._read(self.root / str(conversation_id))

    def find(self, attachment_id: str) -> tuple[dict[str, Any], Path] | None:
        """Locate a file by id across conversations; None when unknown or malformed."""
        if not is_attachment_id(attachment_id) or not self.root.is_dir():
            return None
        with self._lock:
            for directory in self.root.iterdir():
                for entry in self._read(directory):
                    if entry["id"] == attachment_id:
                        return entry, directory / f"{attachment_id}{entry['extension']}"
        return None

    def purge_expired(self, now: datetime | None = None) -> int:
        """Delete files and index entries older than the retention period."""
        if self.retention_days <= 0 or not self.root.is_dir():
            return 0
        cutoff = (now or datetime.now(UTC)) - timedelta(days=self.retention_days)
        removed = 0
        with self._lock:
            for directory in self.root.iterdir():
                entries = self._read(directory)
                keep = [e for e in entries if datetime.fromisoformat(e["uploaded_at"]) >= cutoff]
                if len(keep) == len(entries):
                    continue
                for entry in entries:
                    if entry not in keep:
                        (directory / f"{entry['id']}{entry['extension']}").unlink(missing_ok=True)
                if keep:
                    self._write(directory, keep)
                else:
                    (directory / "index.json").unlink(missing_ok=True)
                    try:
                        directory.rmdir()
                    except OSError:
                        pass  # a stray file is left for an operator to look at
                removed += len(entries) - len(keep)
        return removed

    # -- index file ---------------------------------------------------------

    @staticmethod
    def _read(directory: Path) -> list[dict[str, Any]]:
        index_path = directory / "index.json"
        if not index_path.exists():
            return []
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))["attachments"]
        except (json.JSONDecodeError, UnicodeDecodeError, OSError, KeyError, TypeError) as exc:
            # Never treat a damaged index as empty: the next save would overwrite it.
            logger.error("Attachment index %s is unreadable: %s", index_path, exc)
            raise AttachmentStoreError("Attachment index is unreadable.") from exc

    @staticmethod
    def _write(directory: Path, entries: list[dict[str, Any]]) -> None:
        """Atomic: temp file in the same folder, fsync, then rename."""
        payload = json.dumps({"attachments": entries}, indent=2, ensure_ascii=False)
        fd, tmp_name = tempfile.mkstemp(dir=directory, prefix="index.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, directory / "index.json")
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

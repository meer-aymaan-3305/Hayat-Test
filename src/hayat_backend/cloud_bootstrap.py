"""Run Hayat inside a single Streamlit process, for team testing on Streamlit Cloud.

Streamlit Community Cloud only runs the Streamlit app, so the FastAPI backend is started
in a background thread of the same process and the UI talks to it over localhost.

This is a test deployment, not production:
- conversations are kept in memory (lost on restart) unless USE_SUPABASE=true;
- the OTP is the local test code 123456 unless a real provider is configured;
- everything is controlled by Streamlit secrets, which are exposed as environment variables.
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import socket
import tempfile
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("hayat.cloud")

# Applied only when the secrets do not set them. These match the guided-intake build.
TEST_DEFAULTS = {
    "APP_ENV": "test",
    "EXTENDED_INTAKE": "true",
    "COLLECT_DIAGNOSIS": "true",
    "DEV_FAKE_OTP": "true",
    "MEDICAL_AI_REPLIES": "true",
    "VISITOR_ATTACHMENTS_ENABLED": "false",
}


def apply_secrets(streamlit_secrets: Mapping[str, Any] | None) -> None:
    """Expose Streamlit secrets as environment variables, then fill test defaults."""
    try:
        items = list((streamlit_secrets or {}).items())
    except Exception:  # no secrets configured at all
        items = []
    for key, value in items:
        if isinstance(value, (str, int, float, bool)) and key not in os.environ:
            os.environ[str(key)] = str(value)
    for key, value in TEST_DEFAULTS.items():
        os.environ.setdefault(key, value)
    # Make sure nothing loaded before this point keeps stale settings.
    from .config import get_settings

    get_settings.cache_clear()


def password_ok(entered: str, expected: str) -> bool:
    return bool(expected) and hmac.compare_digest(entered.encode(), expected.encode())


def _seed_knowledge(seed_dir: Path, knowledge_dir: Path) -> int:
    """Index the approved company documents shipped with the app."""
    from .knowledge import KnowledgeStore

    store = KnowledgeStore(knowledge_dir)
    if not store.available or not seed_dir.is_dir():
        return 0
    count = 0
    for path in sorted(seed_dir.iterdir()):
        if path.suffix.lower() not in {".docx", ".pdf", ".txt"}:
            continue
        try:
            store.ingest(
                path.name, path.read_bytes(), max_bytes=10 * 1024 * 1024,
                title=path.stem.replace("_", " "),
            )
            count += 1
        except Exception:
            logger.exception("could not index %s", path.name)
    return count


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_embedded_backend(app_root: Path) -> str:
    """Start the API in a daemon thread and return its base URL. Call once per process."""
    import uvicorn

    from .config import get_settings
    from .main import create_app
    from .memory_store import MemoryStore

    work_dir = Path(tempfile.mkdtemp(prefix="hayat-cloud-"))
    os.environ["KNOWLEDGE_DIR"] = str(work_dir / "knowledge")
    os.environ["ATTACHMENTS_DIR"] = str(work_dir / "attachments")
    # The Streamlit client signs its calls with this; generate one if none was supplied.
    os.environ.setdefault("JWT_SYSTEM_SECRET", secrets.token_urlsafe(32))
    use_supabase = os.environ.get("USE_SUPABASE", "false").lower() in {"1", "true", "yes"}
    if not use_supabase:
        # Keep test conversations out of the real database.
        os.environ["SUPABASE_URL"] = ""
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""
    get_settings.cache_clear()

    indexed = _seed_knowledge(app_root / "knowledge_seed", work_dir / "knowledge")
    logger.info("indexed %d knowledge document(s)", indexed)

    api = create_app(store=None if use_supabase else MemoryStore())
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(api, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, name="hayat-api", daemon=True).start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            if httpx.get(f"{base_url}/health", timeout=1).status_code == 200:
                return base_url
        except httpx.HTTPError:
            time.sleep(0.3)
    raise RuntimeError("The embedded Hayat API did not start in time.")

"""Streamlit Community Cloud entrypoint for Hayat (team testing).

Main file path to enter when deploying:  hayat-backend/cloud_app.py
(or just cloud_app.py if hayat-backend is the repository root).
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import hashlib  # noqa: E402

import streamlit as st  # noqa: E402


def _code_version() -> str:
    """A short fingerprint of the backend code and knowledge shipped with this deploy."""
    digest = hashlib.sha1()
    for folder in (ROOT / "src" / "hayat_backend", ROOT / "knowledge_seed"):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".docx", ".txt", ".json"}:
                digest.update(path.name.encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


VERSION = _code_version()
# A redeploy can land in a process that is already running. If the code changed, drop the
# old backend modules and the cached old backend, so fixes always take effect.
if getattr(sys, "_hayat_code_version", VERSION) != VERSION:
    for name in [m for m in sys.modules if m == "hayat_backend" or m.startswith("hayat_backend.")]:
        del sys.modules[name]
    st.cache_resource.clear()
sys._hayat_code_version = VERSION
os.environ["HAYAT_CODE_VERSION"] = VERSION

from hayat_backend.cloud_bootstrap import (  # noqa: E402
    apply_secrets,
    start_embedded_backend,
)

apply_secrets(st.secrets)


@st.cache_resource(show_spinner="Starting Hayat…")
def _backend_url(version: str) -> str:
    return start_embedded_backend(ROOT)


os.environ["HAYAT_CLOUD"] = "1"
os.environ["HAYAT_API_URL"] = _backend_url(VERSION)
runpy.run_path(str(ROOT / "streamlit_app.py"), run_name="__main__")

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

import streamlit as st  # noqa: E402

from hayat_backend.cloud_bootstrap import (  # noqa: E402
    apply_secrets,
    password_ok,
    start_embedded_backend,
)

apply_secrets(st.secrets)


@st.cache_resource(show_spinner="Starting Hayat…")
def _backend_url() -> str:
    return start_embedded_backend(ROOT)


# Shared password for the team. Set APP_PASSWORD in the app secrets.
expected_password = os.environ.get("APP_PASSWORD", "")
if expected_password and not st.session_state.get("team_access_ok"):
    st.title("Hayat team test")
    with st.form("team_login"):
        entered = st.text_input("Team password", type="password")
        if st.form_submit_button("Enter") and password_ok(entered, expected_password):
            st.session_state.team_access_ok = True
            st.rerun()
    st.caption("Ask the project owner for the team password.")
    st.stop()

os.environ["HAYAT_API_URL"] = _backend_url()
runpy.run_path(str(ROOT / "streamlit_app.py"), run_name="__main__")

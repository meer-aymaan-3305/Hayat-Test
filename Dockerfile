# syntax=docker/dockerfile:1
#
# trawellcare-hayat (FastAPI). Build:  docker build -t trawellcare-hayat .
#
# RUN AS A SINGLE INSTANCE. Hayat keeps chats in memory until Supabase is connected,
# so a second copy (or uvicorn --workers) would give visitors a different, empty
# conversation depending on which one answered. No settings are baked in; they come
# from the environment at start.
#
# The Python version comes from .python-version (3.14) and pyproject.toml; if
# python:3.14-slim ever stops being available, change it here on purpose rather than silently.

# uv is only needed to install packages, so it is taken from its own image and never
# ends up in the final one. 0.12 matches the uv_build range in pyproject.toml.
FROM ghcr.io/astral-sh/uv:0.12 AS uv

# build: install the locked, non-development packages into /app/.venv.
FROM python:3.14-slim AS build
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
# Use the Python already in this image, never download another one.
# Compile .pyc files now so the first request is not slower.
# "copy" because uv's cache is a mounted folder that does not exist in the final image.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
# Step 1: packages only. This layer is reused as long as uv.lock does not change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,id=uv-hayat,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
# Step 2: the Hayat code itself, installed as a normal package (not editable), so the
# final image does not need the src folder. README.md is required by pyproject.toml.
COPY README.md ./
COPY src ./src
RUN --mount=type=cache,id=uv-hayat,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# runtime: same Python base, plus the finished virtual environment. No uv, no compiler.
FROM python:3.14-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
# An ordinary user with no login shell, instead of root.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin hayat
# Uploaded knowledge documents and attachments live here. Mount a volume on
# /app/data so they survive a redeploy (Hayat runs as exactly one container).
RUN mkdir -p /app/data/knowledge /app/data/attachments && chown -R hayat /app/data
ENV KNOWLEDGE_DIR=/app/data/knowledge \
    ATTACHMENTS_DIR=/app/data/attachments
VOLUME /app/data
USER hayat
EXPOSE 2005
# /health is open (no service token needed) and does not call Groq or Supabase.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:2005/health', timeout=4).status == 200 else 1)"]
# Deliberately no --workers: exactly one process (see top of file).
# Python runs as PID 1 through uvicorn, which shuts down cleanly on SIGTERM.
CMD ["uvicorn", "hayat_backend.main:app", "--host", "0.0.0.0", "--port", "2005"]

# syntax=docker/dockerfile:1

FROM python:3.11-slim

# --- System libraries required at runtime by opencv-python-headless / mediapipe ---
# (libgl1/libglib etc. cover the shared objects these wheels dlopen even
# though we use the "headless" opencv build; libgomp1 is needed by numpy/mediapipe's
# OpenMP-linked native code.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# --- uv: the package manager this project already uses (pyproject.toml / uv.lock) ---
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /usr/local/bin/

WORKDIR /app

# Install dependencies first so this layer is cached unless pyproject/uv.lock change
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

# Now copy the rest of the source (routes, detectors, engines, .task model files)
COPY . .

RUN uv sync --locked --no-dev
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    libgles2 \
    libegl1 \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# `uv run` resolves the venv itself, so this works regardless of how PATH
# ends up looking at container-start time (more reliable than depending on
# the ENV PATH prepend above to have taken effect for the exec-form CMD).
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
# AgentForge runtime image. Used by:
#   - docker-compose.local.yml (local L1 gate; both API + UI services share this image)
#   - Railway build (one service per dockerfile path; CMD overridden per service)
#
# Mirrors EMR-SO/openemr/agent/copilot-api/Dockerfile pattern: python:slim base,
# install deps from the pyproject.toml, copy source, EXPOSE one port, default CMD.
# Difference: Poetry (this project) vs pip (copilot-api).
#
# Decision: AgDR-0014 dockerize-agentforge-for-railway. Rationale documented in
# agentdocs/decisions/AgDR-0014-*.md; reverses earlier plan to use Nixpacks.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# OS deps. Rarely changes; cache lives long.
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
      build-essential \
    && rm -rf /var/lib/apt/lists/*

# Poetry pinned to match local toolchain.
RUN pip install --upgrade pip && pip install poetry==2.4.1

# Dependency layer. Re-runs only when pyproject.toml or poetry.lock changes.
# --without dev keeps the image lean; tests run native via Poetry, not in-container.
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --without dev

# Application layer. Re-runs on every source edit.
COPY agentforge ./agentforge
COPY config ./config
COPY evals ./evals
COPY scripts ./scripts
COPY reports ./reports
COPY alembic.ini ./
# README.md is referenced by pyproject.toml as the package long_description;
# Poetry --only-root will fail without it. .dockerignore whitelists it.
COPY README.md ./

# Install the agentforge package itself (so `tb` CLI + module imports work).
RUN poetry install --only-root

# Default service is the API. UI service overrides via Compose `command:`.
EXPOSE 8100

CMD ["uvicorn", "agentforge.api.main:app", "--host", "0.0.0.0", "--port", "8100"]

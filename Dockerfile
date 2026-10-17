FROM python:3.12-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libseccomp2 postgresql-client-17 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app app
COPY migrations migrations
COPY alembic.ini ./
RUN useradd --uid 10001 --create-home assuredesk && mkdir data && chown assuredesk:assuredesk data
USER assuredesk
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "app.web:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

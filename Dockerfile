FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv
WORKDIR /workspace
COPY pyproject.toml uv.lock ./
COPY app ./app
RUN uv sync --frozen --no-dev
COPY scripts ./scripts
COPY data ./data
RUN useradd --uid 10001 --create-home appuser && mkdir -p var /home/appuser/.cache/fastembed && chown -R appuser:appuser var /home/appuser/.cache
USER appuser
ENV PATH="/workspace/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]

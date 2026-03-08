FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY src/ src/
COPY alembic/ alembic/

HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
    CMD python -c "print('ok')" || exit 1

CMD ["python", "-m", "src.main"]

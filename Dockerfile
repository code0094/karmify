FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cache-friendly layer)
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

# Copy remaining files
COPY alembic/ alembic/
COPY alembic.ini .

CMD ["python", "-m", "src.main"]

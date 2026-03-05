FROM python:3.11-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir poetry==1.7.1 && \
    poetry config virtualenvs.create false

COPY pyproject.toml ./
RUN poetry install --no-dev --no-interaction --no-ansi

FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY app/ ./app/

EXPOSE 8002

ENV ENVIRONMENT=production
ENV LOG_LEVEL=INFO

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]

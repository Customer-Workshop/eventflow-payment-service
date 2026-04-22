# EventFlow Payment Service

**System 2** in the EventFlow event-driven architecture demo.

A FastAPI service that consumes `OrderCreated` events from Azure Service Bus and processes payments. This service contains a known bug with zero-decimal currencies (JPY, KRW) that demonstrates the demo's incident response narrative.

## Architecture Role

```
Azure Service Bus → [Payment Service] → Payment Processing
                          ↓
                   Application Insights
                          ↓
                   Alert Rule (on error spike)
                          ↓
                   Devin API (investigate + fix)
```

## Features

- Azure Service Bus consumer for `OrderCreated` events
- Payment processing with currency conversion
- Health check and readiness endpoints
- Structured logging with correlation IDs
- OpenTelemetry instrumentation for Azure Monitor

## The Bug (Demo Narrative)

The payment processor converts amounts from smallest currency unit to display amounts by dividing by 100 (assuming all currencies have two decimal places). This works for USD, EUR, GBP but **fails for zero-decimal currencies** like JPY and KRW where the amount is already in the base unit.

When a JPY order arrives:
- Amount `15800` (yen) gets divided by 100 → `158.00`
- Validation expects amount ≥ smallest billable unit in display currency
- The converted amount fails a downstream consistency check → **unhandled exception**

This bug is intentionally present on the `main` branch to demonstrate:
1. CI tests passing (they only cover USD/EUR)
2. Production crash on JPY input
3. Devin AI investigating logs and opening a fix PR

## Tech Stack

- Python 3.11+
- FastAPI
- Azure Service Bus SDK
- OpenTelemetry + Azure Monitor
- Pydantic v2

## Local Development

```bash
pip install poetry
poetry install

cp .env.example .env
# Edit .env with your values

# Run the service
poetry run uvicorn app.main:app --reload --port 8002

# Run tests
poetry run pytest -v
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `AZURE_SERVICEBUS_CONNECTION_STRING` | Service Bus connection string | *(required)* |
| `AZURE_SERVICEBUS_QUEUE_NAME` | Queue name for order events | `order-events` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights connection string | *(optional)* |
| `LOG_LEVEL` | Logging level | `INFO` |
| `ENVIRONMENT` | Deployment environment | `development` |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/ready` | Readiness check |
| `GET` | `/api/payments` | List processed payments |
| `GET` | `/api/payments/{payment_id}` | Get payment by ID |

## Test Coverage

55 tests across 6 test files covering all application modules:

| Test File | Module | Tests | Coverage |
|---|---|---|---|
| `test_processor.py` | `app/processor.py` | 21 | Currency conversion (USD/EUR/GBP/JPY/KRW), validation thresholds, gateway processing, full payment flow, gateway failure mock |
| `test_consumer.py` | `app/consumer.py` | 7 | Message parsing (valid/invalid JSON, ValueError re-raise), order status callback (no URL, success, HTTP failure, non-200) |
| `test_main.py` | `app/main.py` | 3 | Payment 404, list with limit param, descending sort order |
| `test_models.py` | `app/models.py` | 8 | PaymentStatus enum values, PaymentRecord defaults, OrderCreatedEvent deserialization, OrderEventData field access |
| `test_config.py` | `app/config.py` | 8 | Default values for all Settings fields |
| `test_processor.py` | Health endpoints | 3 | Health check, readiness (no Service Bus), empty payments list |

**Known bug tests:** Several tests in `test_processor.py` document the intentional JPY/KRW zero-decimal currency bug. These tests assert the *incorrect* behavior (e.g., `convert_to_display_amount(15800, "JPY") == 158.0`) and will intentionally break when the bug is fixed.

```bash
# Run tests
poetry run pytest -v --tb=short

# Lint
poetry run ruff check app/ tests/
```

## Docker

```bash
docker build -t eventflow-payment-service .
docker run -p 8002:8002 --env-file .env eventflow-payment-service
```

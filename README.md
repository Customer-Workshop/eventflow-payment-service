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
- Processing fee line (25 bps, rounded to the cent) on every completed payment via the shared `demo-ledger-service` library
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
- [`demo-ledger-service`](https://github.com/Cognition-Partner-Workshops/demo-ledger-service) (`ledger.fees`), pinned to a Git tag in `pyproject.toml`

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

## Processing fee

Completed payments carry `processing_fee` and `processing_fee_bps` in the
`PaymentRecord` returned by `/api/payments`. The fee is
`ledger.fees.management_fee(Decimal(amount_display), 25 bps)` from
`demo-ledger-service`, so it is a `Decimal` rounded to the cent and serialises
as a string in JSON (for example `"0.27"` on a `109.97` USD payment).

## Shared library dependency

`demo-ledger-service` is installed straight from GitHub at a pinned tag (no
package registry):

```toml
demo-ledger-service = { git = "https://github.com/Cognition-Partner-Workshops/demo-ledger-service.git", tag = "v0.4.0" }
```

To pick up a new library release, bump the `tag`, run `poetry lock` (Poetry
1.7.1, matching CI and the Dockerfile) and commit the updated `poetry.lock`.
CI fails if `poetry.lock` is out of date with `pyproject.toml`. The Docker
image installs `git` in the builder stage so Poetry can fetch it.

## Docker

```bash
docker build -t eventflow-payment-service .
docker run -p 8002:8002 --env-file .env eventflow-payment-service
```

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

## Design

### Dual-Plane Architecture

The service operates on two concurrent planes:

- **HTTP API plane** — FastAPI runs on the main async event loop (via uvicorn) and serves health probes and payment retrieval endpoints.
- **Event consumer plane** — A background daemon thread polls the Azure Service Bus `order-events` queue for `OrderCreated` messages, processes payments through a simulated gateway, and stores the results in memory.

This separation ensures that long-running message consumption does not block the ASGI event loop.

### Lifespan Management

The application uses FastAPI's `lifespan` async context manager (replacing the deprecated `on_event` hooks) to coordinate startup and shutdown:

1. **Startup** — Spawns the Service Bus consumer thread which connects to the queue and begins polling.
2. **Shutdown** — Signals the consumer thread to stop and joins it with a 15-second timeout, allowing in-flight messages to complete or be abandoned gracefully.

### In-Memory Storage

Payment records are stored in a plain Python `dict` keyed by payment ID. This is intentional for demo/prototype purposes and is **not** production-ready — records are lost on restart.

### Health Probes

| Endpoint | Probe Type | Checks |
|---|---|---|
| `GET /health` | Kubernetes **liveness** | Process is alive, no dependency checks |
| `GET /ready` | Kubernetes **readiness** | Azure Service Bus connectivity |

The readiness probe reports `"degraded"` when Service Bus is unreachable, signalling the orchestrator to stop routing traffic to this instance.

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

## Docker

```bash
docker build -t eventflow-payment-service .
docker run -p 8002:8002 --env-file .env eventflow-payment-service
```

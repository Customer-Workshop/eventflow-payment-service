"""Payment processing logic.

This module converts order amounts from minor units (cents/smallest denomination)
to display amounts and validates the payment.

For most currencies the minor unit is 1/100 of the base unit (e.g. cents → dollars).
Zero-decimal currencies like JPY and KRW have no minor unit subdivision, so the
amount value already represents the base unit and must not be divided.
"""

import logging
from dataclasses import dataclass

from app.models import OrderEventData, PaymentRecord, PaymentStatus

logger = logging.getLogger(__name__)

# Minimum transaction thresholds in display currency units
# These represent the minimum billable amount for each currency
MINIMUM_TRANSACTION_THRESHOLDS: dict[str, float] = {
    "USD": 0.50,
    "EUR": 0.50,
    "GBP": 0.30,
    "JPY": 500.0,
    "KRW": 500.0,
    "CHF": 0.50,
    "CAD": 0.50,
    "AUD": 0.50,
    "CNY": 3.00,
    "INR": 50.0,
}


@dataclass
class GatewayResponse:
    """Simulated payment gateway response."""

    success: bool
    transaction_id: str | None = None
    error: str | None = None


# Zero-decimal currencies where the minor unit equals the base unit
ZERO_DECIMAL_CURRENCIES: set[str] = {"JPY", "KRW", "VND", "CLP", "PYG", "UGX", "RWF", "XOF", "XAF"}


def convert_to_display_amount(amount_minor: int, currency: str) -> float:
    """Convert an amount from minor units to display format.

    Args:
        amount_minor: Amount in the smallest currency unit (e.g., cents).
        currency: ISO 4217 currency code.

    Returns:
        The amount in display format (e.g., dollars).

    For most currencies (USD, EUR, GBP, etc.) the minor unit is 1/100
    of the base unit, so we divide by 100. For zero-decimal currencies
    like JPY and KRW, the amount is already in the base unit.
    """
    if currency.upper() in ZERO_DECIMAL_CURRENCIES:
        return float(amount_minor)
    return amount_minor / 100


def validate_payment_amount(display_amount: float, currency: str) -> None:
    """Validate that the payment amount meets minimum thresholds.

    Args:
        display_amount: Amount in display format.
        currency: ISO 4217 currency code.

    Raises:
        ValueError: If the amount is below the minimum threshold.
    """
    threshold = MINIMUM_TRANSACTION_THRESHOLDS.get(currency, 0.50)
    if display_amount < threshold:
        raise ValueError(
            f"Amount {display_amount} {currency} is below minimum threshold {threshold} {currency}"
        )


def process_payment_through_gateway(
    display_amount: float,
    currency: str,
    order_id: str,
) -> GatewayResponse:
    """Simulate processing a payment through an external gateway.

    In a real system this would call Stripe, Adyen, etc.
    For the demo, it validates the amount and returns a simulated response.

    Args:
        display_amount: Amount in display format.
        currency: ISO 4217 currency code.
        order_id: The order being paid for.

    Returns:
        A GatewayResponse indicating success or failure.
    """
    # Validate minimum amount
    validate_payment_amount(display_amount, currency)

    # Simulate successful gateway response
    import uuid

    return GatewayResponse(
        success=True,
        transaction_id=f"txn-{uuid.uuid4().hex[:12]}",
    )


def process_order_payment(event_data: OrderEventData) -> PaymentRecord:
    """Process a payment for an incoming order event.

    This is the main entry point called by the Service Bus consumer.

    Args:
        event_data: The order event data from Service Bus.

    Returns:
        A PaymentRecord with the processing result.
    """
    logger.info(
        "Processing payment for order %s: %s %d",
        event_data.order_id,
        event_data.currency,
        event_data.amount,
    )

    # Convert from minor units to display amount
    display_amount = convert_to_display_amount(event_data.amount, event_data.currency)

    logger.info(
        "Converted amount: %s %s (minor: %d)",
        display_amount,
        event_data.currency,
        event_data.amount,
    )

    # Process through the payment gateway
    gateway_response = process_payment_through_gateway(
        display_amount=display_amount,
        currency=event_data.currency,
        order_id=event_data.order_id,
    )

    if gateway_response.success:
        logger.info(
            "Payment completed for order %s (txn: %s)",
            event_data.order_id,
            gateway_response.transaction_id,
        )
        return PaymentRecord(
            order_id=event_data.order_id,
            customer_id=event_data.customer_id,
            currency=event_data.currency,
            amount_minor=event_data.amount,
            amount_display=display_amount,
            status=PaymentStatus.COMPLETED,
        )

    logger.error(
        "Payment failed for order %s: %s",
        event_data.order_id,
        gateway_response.error,
    )
    return PaymentRecord(
        order_id=event_data.order_id,
        customer_id=event_data.customer_id,
        currency=event_data.currency,
        amount_minor=event_data.amount,
        amount_display=display_amount,
        status=PaymentStatus.FAILED,
        error_message=gateway_response.error,
    )

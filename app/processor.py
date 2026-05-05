"""Payment processing logic.

This module converts order amounts from minor units (smallest denomination)
to display amounts using ISO 4217 currency exponents and validates the payment.

Each currency has a defined minor-unit exponent (e.g. USD=2, JPY=0, BHD=3).
The conversion divides the minor-unit amount by ``10 ** exponent`` to produce
the display amount. Unknown currencies default to exponent 2.
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
    "BHD": 0.100,
    "KWD": 0.100,
    "OMR": 0.100,
}

# ISO 4217 minor-unit exponents.
# Exponent 0 → amount is already in the base unit (e.g. 1 JPY = 1 minor unit).
# Exponent 2 → 100 minor units per base unit (e.g. 100 cents = 1 USD).
# Exponent 3 → 1000 minor units per base unit (e.g. 1000 fils = 1 BHD).
CURRENCY_EXPONENTS: dict[str, int] = {
    # Zero-decimal currencies (exponent 0)
    "JPY": 0,
    "KRW": 0,
    "VND": 0,
    "CLP": 0,
    "UGX": 0,
    "ISK": 0,
    "HUF": 0,
    "RWF": 0,
    "PYG": 0,
    "XOF": 0,
    "XAF": 0,
    # Standard two-decimal currencies (exponent 2)
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "CHF": 2,
    "CAD": 2,
    "AUD": 2,
    "CNY": 2,
    "INR": 2,
    # Three-decimal currencies (exponent 3)
    "BHD": 3,
    "KWD": 3,
    "OMR": 3,
}


@dataclass
class GatewayResponse:
    """Simulated payment gateway response."""

    success: bool
    transaction_id: str | None = None
    error: str | None = None


def convert_to_display_amount(amount_minor: int, currency: str) -> float:
    """Convert an amount from minor units to display format.

    Uses the ISO 4217 exponent for the given currency to determine
    the divisor.  Currencies not listed in ``CURRENCY_EXPONENTS``
    default to exponent 2 (i.e. divide by 100).

    Args:
        amount_minor: Amount in the smallest currency unit (e.g., cents for USD,
            yen for JPY, fils for BHD).
        currency: ISO 4217 currency code.

    Returns:
        The amount in display format (e.g., dollars, yen, dinars).
    """
    exponent = CURRENCY_EXPONENTS.get(currency, 2)
    return amount_minor / (10 ** exponent)


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

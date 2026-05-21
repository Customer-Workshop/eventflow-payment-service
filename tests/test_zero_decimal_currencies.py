"""Tests for zero-decimal currency handling (JPY, KRW).

These tests expose the KNOWN BUG in the payment processor where all
currency amounts are divided by 100 for display, which is incorrect
for zero-decimal currencies like JPY and KRW.

Expected behavior:
  - JPY 15800 should display as 15800 (no division)
  - KRW 50000 should display as 50000 (no division)

Actual (buggy) behavior:
  - JPY 15800 / 100 = 158.00 → below 500 JPY threshold → ValueError
  - KRW 50000 / 100 = 500.00 → meets threshold but display amount is wrong

All tests are marked xfail because the application has a known bug that
divides ALL currency amounts by 100, regardless of whether the currency
uses decimal places. These tests document the CORRECT behavior.
"""

import pytest

from app.models import OrderEventData, PaymentStatus
from app.processor import convert_to_display_amount, process_order_payment

ZERO_DECIMAL_BUG = pytest.mark.xfail(
    reason="Known bug: all amounts divided by 100, incorrect for JPY/KRW",
    strict=True,
)


class TestConvertToDisplayAmountZeroDecimal:
    """Tests for convert_to_display_amount with zero-decimal currencies."""

    @ZERO_DECIMAL_BUG
    def test_convert_jpy_amount(self):
        """JPY amounts should NOT be divided by 100 (zero-decimal currency).

        BUG: The processor incorrectly divides by 100.
        Expected: 15800, Actual: 158.00
        """
        result = convert_to_display_amount(15800, "JPY")
        assert result == 15800

    @ZERO_DECIMAL_BUG
    def test_convert_krw_amount(self):
        """KRW amounts should NOT be divided by 100 (zero-decimal currency).

        BUG: The processor incorrectly divides by 100.
        Expected: 50000, Actual: 500.00
        """
        result = convert_to_display_amount(50000, "KRW")
        assert result == 50000

    @ZERO_DECIMAL_BUG
    def test_convert_jpy_small_amount(self):
        """Small JPY amounts should remain unchanged.

        BUG: 1000 JPY becomes 10.00 after incorrect division.
        """
        result = convert_to_display_amount(1000, "JPY")
        assert result == 1000

    @ZERO_DECIMAL_BUG
    def test_convert_krw_large_amount(self):
        """Large KRW amounts should remain unchanged.

        BUG: 1500000 KRW becomes 15000.00 after incorrect division.
        """
        result = convert_to_display_amount(1500000, "KRW")
        assert result == 1500000


class TestProcessOrderPaymentZeroDecimal:
    """Tests for process_order_payment with zero-decimal currencies."""

    @ZERO_DECIMAL_BUG
    def test_process_jpy_order(self):
        """JPY order should process successfully with correct display amount.

        BUG: The incorrect conversion causes the display_amount to fall
        below the 500 JPY minimum threshold, raising a ValueError.
        """
        event_data = OrderEventData(
            order_id="order-jpy-001",
            customer_id="cust-jp-001",
            currency="JPY",
            amount=15800,
            items=[
                {
                    "product_id": "prod-jp-101",
                    "name": "Japanese Keyboard",
                    "quantity": 1,
                    "unit_price": 15800,
                }
            ],
        )
        payment = process_order_payment(event_data)

        assert payment.status == PaymentStatus.COMPLETED
        assert payment.order_id == "order-jpy-001"
        assert payment.currency == "JPY"
        assert payment.amount_minor == 15800
        assert payment.amount_display == 15800

    @ZERO_DECIMAL_BUG
    def test_process_krw_order(self):
        """KRW order should process successfully with correct display amount.

        BUG: The incorrect conversion produces a wrong display_amount (500.00
        instead of 50000). While this may pass the threshold check for large
        enough inputs, the display_amount is still wrong.
        """
        event_data = OrderEventData(
            order_id="order-krw-001",
            customer_id="cust-kr-001",
            currency="KRW",
            amount=50000,
            items=[
                {
                    "product_id": "prod-kr-101",
                    "name": "Korean Snack Box",
                    "quantity": 1,
                    "unit_price": 50000,
                }
            ],
        )
        payment = process_order_payment(event_data)

        assert payment.status == PaymentStatus.COMPLETED
        assert payment.order_id == "order-krw-001"
        assert payment.currency == "KRW"
        assert payment.amount_minor == 50000
        assert payment.amount_display == 50000

    @ZERO_DECIMAL_BUG
    def test_process_jpy_order_below_threshold(self):
        """JPY order with amount below threshold after buggy conversion should fail.

        With the bug: 800 JPY / 100 = 8.00, which is below the 500 JPY threshold.
        Correct behavior: 800 JPY is above the 500 JPY threshold and should succeed.
        """
        event_data = OrderEventData(
            order_id="order-jpy-002",
            customer_id="cust-jp-002",
            currency="JPY",
            amount=800,
            items=[
                {
                    "product_id": "prod-jp-102",
                    "name": "Candy",
                    "quantity": 1,
                    "unit_price": 800,
                }
            ],
        )
        payment = process_order_payment(event_data)
        assert payment.status == PaymentStatus.COMPLETED

    @ZERO_DECIMAL_BUG
    def test_process_krw_small_order(self):
        """KRW order with amount that fails after buggy conversion.

        With the bug: 1000 KRW / 100 = 10.00, which is below 500 KRW threshold.
        Correct behavior: 1000 KRW is above threshold and should succeed.
        """
        event_data = OrderEventData(
            order_id="order-krw-002",
            customer_id="cust-kr-002",
            currency="KRW",
            amount=1000,
            items=[
                {
                    "product_id": "prod-kr-102",
                    "name": "Gum",
                    "quantity": 1,
                    "unit_price": 1000,
                }
            ],
        )
        payment = process_order_payment(event_data)
        assert payment.status == PaymentStatus.COMPLETED

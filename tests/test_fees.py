"""Tests for the processing fee computed via demo-ledger-service."""

from decimal import Decimal

from app.fees import PROCESSING_FEE_BPS, processing_fee
from app.models import OrderEventData, PaymentStatus
from app.processor import process_order_payment


class TestProcessingFee:
    def test_rate_is_25_bps(self):
        assert PROCESSING_FEE_BPS == Decimal("25")

    def test_fee_is_rounded_to_the_cent(self):
        # 109.97 * 25 / 10000 = 0.274925
        assert processing_fee(109.97) == Decimal("0.27")

    def test_fee_on_round_amount(self):
        assert processing_fee(10000.00) == Decimal("25.00")

    def test_fee_on_zero_amount(self):
        assert processing_fee(0.0) == Decimal("0.00")


class TestPaymentRecordCarriesFee:
    def test_completed_usd_payment_has_fee(self, usd_order_event_data: OrderEventData):
        payment = process_order_payment(usd_order_event_data)

        assert payment.status == PaymentStatus.COMPLETED
        assert payment.processing_fee == Decimal("0.27")
        assert payment.processing_fee_bps == 25

    def test_completed_eur_payment_has_fee(self, eur_order_event_data: OrderEventData):
        payment = process_order_payment(eur_order_event_data)

        # 89.99 * 25 / 10000 = 0.224975
        assert payment.processing_fee == Decimal("0.22")

    def test_fee_serialises_as_string_in_json(self, usd_order_event_data: OrderEventData):
        payment = process_order_payment(usd_order_event_data)
        dumped = payment.model_dump(mode="json")
        assert dumped["processing_fee"] == "0.27"

"""Processing fee for completed payments, via the shared ledger library."""

from decimal import Decimal

from ledger.fees import management_fee

# Flat processing fee charged on every completed payment, in basis points.
PROCESSING_FEE_BPS = Decimal("25")


def processing_fee(display_amount: float) -> Decimal:
    """Fee on ``display_amount`` (display currency units), rounded to the cent.

    Delegates to ``ledger.fees.management_fee`` so rounding follows the
    ``demo-ledger-service`` accounting conventions.
    """
    return management_fee(Decimal(str(display_amount)), PROCESSING_FEE_BPS)

# packages/ingest/tests/test_voucher_parse.py
import sys
from datetime import date
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from munim_ingest.voucher_parse import (
    parse_gyftr, parse_amazonpay, parse_swiggy, parse_instamart,
    UnrecognizedGyftrBrand,
)


def _msg(subject, from_addr, date_header, body) -> bytes:
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["Date"] = date_header
    return msg.as_bytes()


GYFTR_BODY = """Dear Customer,
Congratulations! Thank you for buying Gift Voucher from Gyftr via HDFC Bank PayZapp Shop e-Vouchers. Please find your instant voucher details.

Swiggy Money Voucher
Swiggy Money Voucher

E-Gift Card Code
VGHDR7VACB6SD15E

Value
2000
PIN
525269

Valid Till
06 Mar 2027

To Redeem your Gift Voucher: Click Here.
"""


def test_parse_gyftr_extracts_brand_value_code_and_date():
    raw = _msg(
        "Confidential - Your Gift Voucher details from GyFTR via HDFC Bank PayZapp Shop e-Vouchers",
        "GyFTR <gifts@gyftr.com>", "Mon, 14 Sep 2026 14:09:00 +0530", GYFTR_BODY)
    record = parse_gyftr(raw)
    assert record == {
        "kind": "purchase", "brand": "swiggy", "value": 2000.0,
        "code": "VGHDR7VACB6SD15E", "purchased_at": date(2026, 9, 14),
    }


def test_parse_gyftr_raises_for_unrecognized_brand():
    # A genuine GYFTR purchase-confirmation email (has both Value and
    # E-Gift Card Code) but a product line not in GYFTR_BRAND_MAP must
    # be distinguishable from "not a GYFTR email at all" -- silently
    # returning None here would make it indistinguishable from that case
    # and this brand would be dropped with zero user-visible signal.
    raw = _msg("Your Gift Voucher", "GyFTR <gifts@gyftr.com>",
               "Mon, 14 Sep 2026 14:09:00 +0530",
               GYFTR_BODY.replace("Swiggy Money Voucher", "Bata Voucher"))
    with pytest.raises(UnrecognizedGyftrBrand) as exc_info:
        parse_gyftr(raw)
    assert "Bata Voucher" in exc_info.value.product_text


AMAZONPAY_BODY = """Hi Tony,
Thank you for using Amazon Pay Balance. Your payment was successful.
Paid on	Amount
Amazon.in	Rs132.00
To report any unauthorised transaction, please click here
Order ID	171-9035274-8173116
Order Date	01 September 2026
Updated Amazon Pay Balance	Rs5938.58
Wallet	Rs1285.76
Gift Cards	Rs4652.82
Vouchers	Rs0.00
"""


def test_parse_amazonpay_extracts_amount_merchant_order_id_and_date():
    raw = _msg("Rs 132.00 was paid on Amazon.in",
               "Amazon Pay India <no-reply@amazonpay.in>",
               "Tue, 1 Sep 2026 00:15:00 +0530", AMAZONPAY_BODY)
    record = parse_amazonpay(raw)
    assert record == {
        "kind": "spend", "brand": "amazonpay", "source": "amazonpay",
        "amount": 132.0, "merchant": "Amazon.in",
        "order_id": "171-9035274-8173116", "order_date": date(2026, 9, 1),
        "paid_via": None,
    }


SWIGGY_BODY = """Order summary banner
Delivery in 25 mins!
Rs192 saved on this order
ORDER JOURNEY
Restaurant icon
Restaurant icon
Cafe Iftar
No.58/8A Jnr Complex Ground Floor Gubbi Cross Kothanur Post, Bangalore
Aug 28, 10:52 PM
Order ID: 246907327135063
BILL DETAILS
Arabian Pulpy Grap x1		Rs95
Peri Peri Alfaham x1		Rs380
Paid Via Credit/Debit card		Rs391
"""


def test_parse_swiggy_extracts_restaurant_amount_order_id_and_paid_via():
    raw = _msg("Your order from Cafe Iftar", "Swiggy <noreply@swiggy.in>",
               "Wed, 28 Aug 2024 23:17:00 +0530", SWIGGY_BODY)
    record = parse_swiggy(raw)
    assert record == {
        "kind": "spend", "brand": "swiggy", "source": "swiggy_order",
        "amount": 391.0, "merchant": "Cafe Iftar",
        "order_id": "246907327135063", "order_date": date(2024, 8, 28),
        "paid_via": "Credit/Debit card",
    }


INSTAMART_BODY = """Greetings from Instamart
Your Instamart order id: 248336149154232 was successfully delivered.
Order Items
1 x Yelakki Banana (Baalehannu)	Rs70.00
Order Summary
Item Bill	Rs348.00
Handling Fee	Rs12.00
Delivery Partner Fee	Rs35.40
Grand Total	Rs395.00
"""


def test_parse_instamart_extracts_amount_order_id_and_no_paid_via():
    raw = _msg("Your Instamart order is delivered!",
               "noreply@instamart.in", "Mon, 14 Sep 2026 12:09:00 +0530",
               INSTAMART_BODY)
    record = parse_instamart(raw)
    assert record == {
        "kind": "spend", "brand": "swiggy", "source": "instamart_order",
        "amount": 395.0, "merchant": "Instamart",
        "order_id": "248336149154232", "order_date": date(2026, 9, 14),
        "paid_via": None,
    }


def test_parsers_return_none_for_unrelated_email():
    raw = _msg("Hello", "someone@example.com",
               "Mon, 14 Sep 2026 12:09:00 +0530", "Not a voucher email.")
    assert parse_gyftr(raw) is None
    assert parse_amazonpay(raw) is None
    assert parse_swiggy(raw) is None
    assert parse_instamart(raw) is None

# packages/ingest/tests/test_voucher_parse.py
import sys
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim_ingest.voucher_parse import (
    parse_gyftr, parse_amazonpay, parse_swiggy, parse_instamart,
)


def _msg(subject, from_addr, date_header, body) -> bytes:
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["Date"] = date_header
    return msg.as_bytes()


def _multipart_msg(subject, from_addr, date_header, plain_body, html_body) -> bytes:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["Date"] = date_header
    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
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
    records, unrecognized = parse_gyftr(raw)
    assert records == [{
        "kind": "purchase", "brand": "gyftr", "value": 2000.0,
        "code": "VGHDR7VACB6SD15E", "purchased_at": date(2026, 9, 14),
    }]
    assert unrecognized == []


def test_parse_gyftr_reports_unrecognized_brand_without_raising():
    # A genuine GYFTR purchase-confirmation email (has both Value and
    # E-Gift Card Code) but a product line not in GYFTR_BRAND_MAP must
    # be distinguishable from "not a GYFTR email at all" -- silently
    # returning nothing here would make it indistinguishable from that
    # case and this brand would be dropped with zero user-visible signal.
    raw = _msg("Your Gift Voucher", "GyFTR <gifts@gyftr.com>",
               "Mon, 14 Sep 2026 14:09:00 +0530",
               GYFTR_BODY.replace("Swiggy Money Voucher", "Croma Voucher"))
    records, unrecognized = parse_gyftr(raw)
    assert records == []
    assert unrecognized == ["Croma Voucher"]


GYFTR_MULTI_ZEPTO_BODY = """Dear Customer,
Congratulations! Thank you for buying Gift Voucher from Gyftr via HDFC Bank PayZapp Shop e-Vouchers. Please find your instant voucher details.

Zepto

E-Gift Card Code
6009750167418156

Value
1000
PIN
174657

Valid Till
31 Jul 2027

Zepto

E-Gift Card Code
6009750167153158

Value
1000
PIN
185809

Valid Till
31 Jul 2027

To Redeem your Gift Voucher: Click Here.
"""


def test_parse_gyftr_extracts_every_voucher_from_a_multi_item_email():
    # A single GYFTR email can bundle more than one purchased voucher
    # (e.g. buying two Zepto vouchers in one checkout) -- both must be
    # extracted, not just the first.
    raw = _msg("Your Gift Vouchers", "GyFTR <gifts@gyftr.com>",
               "Mon, 14 Sep 2026 14:09:00 +0530", GYFTR_MULTI_ZEPTO_BODY)
    records, unrecognized = parse_gyftr(raw)
    assert records == [
        {"kind": "purchase", "brand": "gyftr", "value": 1000.0,
         "code": "6009750167418156", "purchased_at": date(2026, 9, 14)},
        {"kind": "purchase", "brand": "gyftr", "value": 1000.0,
         "code": "6009750167153158", "purchased_at": date(2026, 9, 14)},
    ]
    assert unrecognized == []


GYFTR_PROMO_PLUS_VOUCHER_BODY = """Dear Customer,
Congratulations! Thank you for buying Gift Voucher from Gyftr via HDFC Bank PayZapp Shop e-Vouchers. Please find your instant voucher details.

Barbeque Nation Promo Code

Promo Code
XZJM7RZTYO3I4X4

Valid Till
12 Dec 2026

Promo Code Details
INR 1000 OFF on minimum booking of 8 pax or more

Swiggy Instamart

E-Gift Card Code
VOGRRS01K7PFC93A

Value
5000
PIN
995645

Valid Till
04 Sep 2026

To Redeem your Gift Voucher: Click Here.
"""


def test_parse_gyftr_ignores_a_promo_code_bundled_with_a_real_voucher():
    # GYFTR emails sometimes bundle an unrelated marketing promo code
    # (no E-Gift Card Code, no money spent) alongside a real purchased
    # voucher -- the promo must never be treated as a voucher, and must
    # not be reported as an unrecognized brand either.
    raw = _msg("Your Gift Voucher", "GyFTR <gifts@gyftr.com>",
               "Mon, 14 Sep 2026 14:09:00 +0530", GYFTR_PROMO_PLUS_VOUCHER_BODY)
    records, unrecognized = parse_gyftr(raw)
    assert records == [{
        "kind": "purchase", "brand": "gyftr", "value": 5000.0,
        "code": "VOGRRS01K7PFC93A", "purchased_at": date(2026, 9, 14),
    }]
    assert unrecognized == []


GYFTR_MIXED_RECOGNIZED_UNRECOGNIZED_BODY = """Dear Customer,
Congratulations! Thank you for buying Gift Voucher from Gyftr via HDFC Bank PayZapp Shop e-Vouchers. Please find your instant voucher details.

Zepto

E-Gift Card Code
6009750167588875

Value
2000
PIN
253456

Valid Till
05 Nov 2026

Croma

E-Gift Card Code
CRVG01I8YY1NWTQA

Value
1500
PIN
998877

Valid Till
31 Dec 2026

To Redeem your Gift Voucher: Click Here.
"""


def test_parse_gyftr_reports_both_recognized_and_unrecognized_from_one_email():
    raw = _msg("Your Gift Vouchers", "GyFTR <gifts@gyftr.com>",
               "Mon, 14 Sep 2026 14:09:00 +0530", GYFTR_MIXED_RECOGNIZED_UNRECOGNIZED_BODY)
    records, unrecognized = parse_gyftr(raw)
    assert records == [{
        "kind": "purchase", "brand": "gyftr", "value": 2000.0,
        "code": "6009750167588875", "purchased_at": date(2026, 9, 14),
    }]
    assert unrecognized == ["Croma"]


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
        "kind": "spend", "brand": "gyftr", "source": "amazonpay",
        "amount": 132.0, "merchant": "Amazon.in",
        "order_id": "171-9035274-8173116", "order_date": date(2026, 9, 1),
        "paid_via": None,
    }


# A real fetched Amazon Pay email (confirmed via --dump-unparsed): the
# text/plain alternative is a short stub with none of the order detail,
# and the actual Order ID/Order Date/amount live only in the HTML
# alternative -- with a <style> block ahead of the body, and the Order
# ID wrapped in an <a href=...> tracking link, exactly like this.
AMAZONPAY_PLAIN_STUB = "Hi Tony,\r\nThanks for using Amazon Pay Balance. Your payment was successful.\r\n"
AMAZONPAY_REAL_HTML = """<html>
<head>
<style>
  #amount {
    padding-right: 17px;
    font-size: 24px;
  }
  .paymentDetailsHeading {
    font-size: 13px;
  }
</style>
</head><body>
<table><tr><td id="greetings">Hi Tony,</td></tr></table>
<table><tr>
<td id="paymentHighlightsHeading1">Paid on</td>
<td id="paymentHighlightsHeading2">Amount</td>
</tr><tr>
<td id="bankName"><b>Amazon.in</b></td>
<td id="amount"><b>&#8377;109.00</b></td>
</tr></table>
<table id="paymentDetails">
<tr><td class="paymentDetailsHeading">Order ID</td>
<td class="paymentDetailsContent"><a href="https://track.example.com/L0/very-long-tracking-url">406-7409280-4736312</a></td></tr>
<tr><td class="paymentDetailsHeading">Order Date</td>
<td class="paymentDetailsContent">01 May 2025</td></tr>
</table>
</body></html>"""


def test_parse_amazonpay_falls_back_to_html_when_plain_text_is_a_stub():
    raw = _multipart_msg(
        "Rs 109.00 was paid on Amazon.in",
        "Amazon Pay India <no-reply@amazonpay.in>",
        "Thu, 1 May 2025 04:39:45 +0000",
        AMAZONPAY_PLAIN_STUB, AMAZONPAY_REAL_HTML)
    record = parse_amazonpay(raw)
    assert record == {
        "kind": "spend", "brand": "gyftr", "source": "amazonpay",
        "amount": 109.0, "merchant": "Amazon.in",
        "order_id": "406-7409280-4736312", "order_date": date(2025, 5, 1),
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
        "kind": "spend", "brand": "gyftr", "source": "swiggy_order",
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
        "kind": "spend", "brand": "gyftr", "source": "instamart_order",
        "amount": 395.0, "merchant": "Instamart",
        "order_id": "248336149154232", "order_date": date(2026, 9, 14),
        "paid_via": None,
    }


def test_parsers_return_none_for_unrelated_email():
    raw = _msg("Hello", "someone@example.com",
               "Mon, 14 Sep 2026 12:09:00 +0530", "Not a voucher email.")
    assert parse_gyftr(raw) == ([], [])
    assert parse_amazonpay(raw) is None
    assert parse_swiggy(raw) is None
    assert parse_instamart(raw) is None

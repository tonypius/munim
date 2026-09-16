# packages/ingest/munim_ingest/voucher_parse.py
"""Body-only parsers for voucher purchase/redemption emails (GYFTR,
Amazon Pay, Swiggy, Instamart) -- none of these send an attachment, so
this is a parallel path to attachments.py, extracting structured
records straight from the message body/subject/headers instead.

Every parse_* function returns None (never raises) when the message
doesn't match its expected template, so a caller can safely try each
parser against every fetched message without needing to pre-classify
by sender first.
"""
from __future__ import annotations

import email
import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime

from .voucher_packs import brand_for_gyftr_product


class UnrecognizedGyftrBrand(Exception):
    """Raised by parse_gyftr when a message is a genuine GYFTR
    purchase-confirmation email (it has both a "Value" and an "E-Gift
    Card Code" -- the two fields every real GYFTR voucher purchase
    carries) but its product-line text doesn't match any entry in
    voucher_packs.GYFTR_BRAND_MAP. This is deliberately distinct from
    parse_gyftr returning None, which means "not a GYFTR voucher-purchase
    email at all" (wrong sender, or missing the fields above). The
    design spec requires an unrecognized brand be "skipped and logged
    rather than silently creating a wrongly-named account" -- collapsing
    both cases into a bare `None` would make that impossible to tell
    apart from the caller, so the caller (gmail fetch-vouchers) catches
    this specifically to print a warning naming the unmatched product
    line."""

    def __init__(self, product_text: str):
        self.product_text = product_text
        super().__init__(f"Unrecognized GYFTR product line: {product_text!r}")


def _text_body(msg) -> str:
    """Best-effort plain-text body: prefers a text/plain part, falls
    back to stripping tags from text/html if that's all there is."""
    if msg.is_multipart():
        plain = html = None
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain" and plain is None:
                plain = part.get_payload(decode=True)
            elif ctype == "text/html" and html is None:
                html = part.get_payload(decode=True)
        payload = plain if plain is not None else html
    else:
        payload = msg.get_payload(decode=True)
    if payload is None:
        return ""
    charset = msg.get_content_charset() or "utf-8"
    text = payload.decode(charset, errors="replace")
    if msg.get_content_type() == "text/html" or (msg.is_multipart() and plain is None):
        text = re.sub(r"<[^>]+>", "\n", text)
    return text


def _header_date(msg) -> date | None:
    """Parse the message's Date header, returning None (never raising)
    if it's missing or malformed -- callers must check for None before
    building a record, since a matching sender/body with no usable
    Date header should still fall through to "no match" rather than
    blow up the caller."""
    header = msg["Date"]
    if not header:
        return None
    try:
        return parsedate_to_datetime(header).date()
    except (TypeError, ValueError):
        return None


def _amount(text: str, label: str) -> float | None:
    m = re.search(rf"{label}\s*\n?\s*\t?\s*(?:Rs|₹)?\s*([\d,]+(?:\.\d+)?)", text)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def parse_gyftr(raw_email: bytes) -> dict | None:
    """Returns a purchase record, or None if this isn't a GYFTR
    voucher-purchase email at all (wrong sender, or missing the Value/
    E-Gift Card Code/Date fields every real one carries). Raises
    UnrecognizedGyftrBrand -- distinct from returning None -- if it IS a
    genuine GYFTR purchase-confirmation email but its product-line text
    doesn't match any brand in GYFTR_BRAND_MAP."""
    msg = email.message_from_bytes(raw_email)
    if "gyftr" not in (msg["From"] or "").lower():
        return None
    text = _text_body(msg)
    value = _amount(text, "Value")
    code_match = re.search(r"E-Gift Card Code\s*\n\s*(\S+)", text)
    purchased_at = _header_date(msg)
    if value is None or not code_match or purchased_at is None:
        return None

    brand = brand_for_gyftr_product(text)
    if brand is None:
        # Best-effort extraction of the repeated product-line text (it
        # appears twice in a row directly above "E-Gift Card Code" in
        # every real sample seen) to name in the warning; falls back to
        # the whole body if that shape doesn't match either, so the
        # warning is never silently empty.
        product_match = re.search(r"\n([^\n]+)\n\1\n+E-Gift Card Code", text)
        product_text = product_match.group(1).strip() if product_match else text.strip()
        raise UnrecognizedGyftrBrand(product_text)

    return {
        "kind": "purchase", "brand": brand, "value": value,
        "code": code_match.group(1), "purchased_at": purchased_at,
    }


def parse_amazonpay(raw_email: bytes) -> dict | None:
    msg = email.message_from_bytes(raw_email)
    if "amazonpay.in" not in (msg["From"] or "").lower():
        return None
    subject = msg["Subject"] or ""
    subj_match = re.match(
        r"Rs\s*([\d,]+(?:\.\d+)?)\s+was paid on\s+(.+)", subject.strip())
    if not subj_match:
        return None
    text = _text_body(msg)
    order_id_match = re.search(r"Order ID\s*\n?\s*\t?\s*([\w-]+)", text)
    order_date_match = re.search(
        r"Order Date\s*\n?\s*\t?\s*(\d{1,2} \w+ \d{4})", text)
    if not order_id_match or not order_date_match:
        return None
    order_date = datetime.strptime(
        order_date_match.group(1), "%d %B %Y").date()
    return {
        "kind": "spend", "brand": "amazonpay", "source": "amazonpay",
        "amount": float(subj_match.group(1).replace(",", "")),
        "merchant": subj_match.group(2).strip(),
        "order_id": order_id_match.group(1), "order_date": order_date,
        "paid_via": None,
    }


def parse_swiggy(raw_email: bytes) -> dict | None:
    msg = email.message_from_bytes(raw_email)
    if "swiggy.in" not in (msg["From"] or "").lower():
        return None
    text = _text_body(msg)
    order_id_match = re.search(r"Order ID:\s*(\d+)", text)
    restaurant_match = re.search(
        r"Restaurant icon\s*\n\s*Restaurant icon\s*\n+([^\n]+)", text)
    paid_via_match = re.search(
        r"Paid Via\s+([^\t\n₹]+?)\s*\t*\s*(?:Rs|₹)?\s*([\d,]+(?:\.\d+)?)", text)
    order_date = _header_date(msg)
    if not (order_id_match and restaurant_match and paid_via_match) or order_date is None:
        return None
    return {
        "kind": "spend", "brand": "swiggy", "source": "swiggy_order",
        "amount": float(paid_via_match.group(2).replace(",", "")),
        "merchant": restaurant_match.group(1).strip(),
        "order_id": order_id_match.group(1), "order_date": order_date,
        "paid_via": paid_via_match.group(1).strip(),
    }


def parse_instamart(raw_email: bytes) -> dict | None:
    msg = email.message_from_bytes(raw_email)
    if "instamart.in" not in (msg["From"] or "").lower():
        return None
    text = _text_body(msg)
    order_id_match = re.search(r"order id:\s*(\d+)", text, re.I)
    grand_total = _amount(text, "Grand Total")
    order_date = _header_date(msg)
    if not order_id_match or grand_total is None or order_date is None:
        return None
    return {
        "kind": "spend", "brand": "swiggy", "source": "instamart_order",
        "amount": grand_total, "merchant": "Instamart",
        "order_id": order_id_match.group(1), "order_date": order_date,
        "paid_via": None,
    }

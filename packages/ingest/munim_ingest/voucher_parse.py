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
import html as html_lib
import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime

from .voucher_packs import brand_for_gyftr_product


def _text_body(msg) -> str:
    """Best-effort plain-text body. Real senders sometimes ship a
    text/plain alternative that's a short stub ("Thanks for your
    payment.") with the actual order/amount detail living only in the
    HTML alternative (confirmed via a real Amazon Pay email dumped with
    --dump-unparsed) -- preferring "plain if present" would then
    silently return incomplete text forever. Decodes both alternatives
    and returns whichever has more actual content."""
    plain_payload = html_payload = None
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain" and plain_payload is None:
                plain_payload = part.get_payload(decode=True)
            elif ctype == "text/html" and html_payload is None:
                html_payload = part.get_payload(decode=True)
    elif msg.get_content_type() == "text/html":
        html_payload = msg.get_payload(decode=True)
    else:
        plain_payload = msg.get_payload(decode=True)

    charset = msg.get_content_charset() or "utf-8"
    plain_text = plain_payload.decode(charset, errors="replace") if plain_payload else ""
    html_text = ""
    if html_payload:
        html_text = html_payload.decode(charset, errors="replace")
        # Strip style/script blocks WITH their content first -- the
        # generic tag-stripping below only removes the tags themselves,
        # which would otherwise leave raw CSS/JS text inline and could
        # confuse a field regex or bloat the search space.
        html_text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ",
                           html_text, flags=re.I | re.S)
        html_text = re.sub(r"<[^>]+>", "\n", html_text)
        html_text = html_lib.unescape(html_text)

    return html_text if len(html_text) > len(plain_text) else plain_text


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


def _last_nonempty_line(text: str, max_len: int = 120) -> str:
    """Best-effort guess at "the product name" for an unrecognized-brand
    warning: the last non-blank line before whatever follows (in
    practice, the line immediately above "E-Gift Card Code"). Real GYFTR
    emails don't reliably repeat the product line twice in a row (some
    samples do, some don't), so this doesn't assume that shape -- it
    just takes the nearest non-empty text, which matches every real
    sample seen."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if lines:
        return lines[-1][:max_len]
    return text.strip()[:max_len]


def parse_gyftr(raw_email: bytes) -> tuple[list[dict], list[str]]:
    """Returns (records, unrecognized_product_lines) for a GYFTR
    voucher-purchase email. A single email can bundle more than one
    purchased voucher (e.g. two Zepto vouchers bought together), and can
    also bundle unrelated marketing promo-code blocks (no "E-Gift Card
    Code", no money spent) alongside real vouchers -- those are silently
    skipped, never counted as vouchers or as unrecognized brands.

    Both lists are empty if this isn't a GYFTR voucher-purchase email at
    all (wrong sender, or no real voucher block found). A brand not in
    voucher_packs.GYFTR_BRAND_MAP contributes its product-line text to
    `unrecognized_product_lines` instead of a record, so the design's
    "skipped and logged, never guessed" requirement holds even when
    other vouchers in the same email ARE recognized.
    """
    msg = email.message_from_bytes(raw_email)
    if "gyftr" not in (msg["From"] or "").lower():
        return [], []
    text = _text_body(msg)
    purchased_at = _header_date(msg)
    if purchased_at is None:
        return [], []

    # Splitting on the "E-Gift Card Code" label anchors each voucher
    # block: parts[i] ends with this block's product-name line (and, for
    # i>0, may also contain the PREVIOUS block's trailing Valid-Till/promo
    # text -- harmless, since brand lookup only cares about a substring
    # match), and parts[i+1] starts with this block's code/value/pin.
    # A promo-code block has no "E-Gift Card Code" at all, so it never
    # creates a split point and is never mistaken for a voucher.
    parts = re.split(r"E-Gift Card Code", text)
    if len(parts) < 2:
        return [], []

    records: list[dict] = []
    unrecognized: list[str] = []
    for i in range(len(parts) - 1):
        brand_chunk = parts[i]
        data_chunk = parts[i + 1]

        code_match = re.match(r"\s*(\S+)", data_chunk)
        value = _amount(data_chunk, "Value")
        if not code_match or value is None:
            continue

        brand = brand_for_gyftr_product(brand_chunk)
        if brand is None:
            unrecognized.append(_last_nonempty_line(brand_chunk))
            continue

        records.append({
            "kind": "purchase", "brand": brand, "value": value,
            "code": code_match.group(1), "purchased_at": purchased_at,
        })

    return records, unrecognized


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
        "kind": "spend", "brand": "gyftr", "source": "amazonpay",
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
        "kind": "spend", "brand": "gyftr", "source": "swiggy_order",
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
        "kind": "spend", "brand": "gyftr", "source": "instamart_order",
        "amount": grand_total, "merchant": "Instamart",
        "order_id": order_id_match.group(1), "order_date": order_date,
        "paid_via": None,
    }

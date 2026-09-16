# Voucher Redemption Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull GYFTR voucher purchases and their real-world redemptions
(Amazon Pay spend, Swiggy orders, Instamart orders) out of Gmail and
represent them in munim as a virtual-wallet-account so Groceries/Dining
spend reporting stops undercounting purchases routed through vouchers.

**Architecture:** A new body-only email-parsing path in
`packages/ingest` (parallel to the existing attachment-only `BankPack`
path) produces plain record dicts; a new `voucher_wallet` module in
`packages/classify` turns those records into real `Transaction` rows on
auto-created `voucher-<brand>` virtual `Assets` accounts, linked to their
funding bank transaction via the existing `transfer_links` mechanism.

**Tech Stack:** Python stdlib `email`/`imaplib` (matching the existing
ingest package — no new dependencies), the existing `Store`/`Pipeline`/
`Transaction` classes in `packages/classify`.

## Global Constraints

- Gmail fetching is a user-run terminal command only — the app password
  must never be read, logged, or handled by any code path the assistant
  runs on the user's behalf. `fetch-vouchers` must follow the exact same
  password handling as the existing `gmail fetch` command
  (`MUNIM_GMAIL_APP_PASSWORD` env var, else `getpass.getpass`, never
  written to disk, never in a traceback — see `ImapConfig`'s
  `repr=False` password field and `pretty_exceptions_show_locals=False`
  on every Typer app in `packages/ingest/munim_ingest/cli.py`).
- GYFTR voucher face value ("Value" field) equals the amount actually
  paid — confirmed with the user, no discount reconciliation needed.
- No Wallet/Gift-Card/Voucher balance-bucket tracking for Amazon Pay —
  every top-up (GYFTR or otherwise) lands in one shared `voucher-<brand>`
  account; every spend is a debit from that same pool regardless of
  which literal top-up funded it.
- The redemption-vs-already-real-spend decision for Swiggy/Instamart is:
  a known real payment rail (card/UPI/netbanking) named directly →
  already real, skip; otherwise → search real bank transactions for a
  matching debit (±2 day window) — found → skip, not found → voucher
  redemption. This is the single mechanism (`_has_matching_bank_txn`)
  used by both the initial import and `recheck`.
- Every synthetic transaction id is derived from a natural, guaranteed-
  unique identifier from its source email (GYFTR's E-Gift Card Code;
  Order ID for Amazon Pay/Swiggy/Instamart) — never munim's normal
  content-hash — so re-running fetch/import is idempotent by
  construction (`upsert_transactions` skips on primary-key collision).
- Full spec: `docs/superpowers/specs/2026-09-16-voucher-redemption-tracking-design.md`.

---

### Task 1: Voucher sender/brand config

**Files:**
- Create: `packages/ingest/munim_ingest/voucher_packs.py`
- Test: `packages/ingest/tests/test_voucher_packs.py`

**Interfaces:**
- Produces: `GYFTR_FROM: str`, `AMAZONPAY_FROM: str`, `SWIGGY_FROM: str`,
  `INSTAMART_FROM: str` (sender-domain substrings, for IMAP search).
  `GYFTR_BRAND_MAP: dict[str, str]` mapping a lowercase GYFTR product-line
  substring to the wallet account's brand slug.
  `brand_for_gyftr_product(product_text: str) -> str | None` — looks up
  `product_text` (any case) against `GYFTR_BRAND_MAP` by substring match,
  returns the slug or `None` if unrecognized.

- [ ] **Step 1: Write the failing tests**

```python
# packages/ingest/tests/test_voucher_packs.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim_ingest.voucher_packs import (
    GYFTR_FROM, AMAZONPAY_FROM, SWIGGY_FROM, INSTAMART_FROM,
    brand_for_gyftr_product,
)


def test_sender_domains_are_bare_domains():
    # bare domain substrings, matching how BankPack.from_domains is used
    # elsewhere (imap_client.build_from_query wraps them in FROM search
    # terms) -- no "@" prefix, no full email address.
    assert GYFTR_FROM == "gyftr.com"
    assert AMAZONPAY_FROM == "amazonpay.in"
    assert SWIGGY_FROM == "swiggy.in"
    assert INSTAMART_FROM == "instamart.in"


def test_brand_for_gyftr_product_recognizes_swiggy_money_voucher():
    assert brand_for_gyftr_product("Swiggy Money Voucher") == "swiggy"


def test_brand_for_gyftr_product_is_case_insensitive():
    assert brand_for_gyftr_product("SWIGGY MONEY VOUCHER") == "swiggy"


def test_brand_for_gyftr_product_returns_none_for_unknown_brand():
    assert brand_for_gyftr_product("Bata Voucher") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/ingest && ../../.venv/bin/pytest tests/test_voucher_packs.py -v`
Expected: FAIL with "No module named 'munim_ingest.voucher_packs'"

- [ ] **Step 3: Write the implementation**

```python
# packages/ingest/munim_ingest/voucher_packs.py
"""Sender domains and GYFTR product->wallet-brand mapping for the
voucher-redemption email-body parsing path (see voucher_parse.py). This
is a parallel, smaller cousin of packs.py's BankPack -- these four
senders never send an attachment, so there's no attachment_extensions
concept here, only enough config to drive IMAP search and brand lookup.
"""
from __future__ import annotations

GYFTR_FROM = "gyftr.com"
AMAZONPAY_FROM = "amazonpay.in"
SWIGGY_FROM = "swiggy.in"
INSTAMART_FROM = "instamart.in"

# GYFTR's purchase-confirmation email repeats a product-line string (e.g.
# "Swiggy Money Voucher") whose exact wording per brand is otherwise
# unconfirmed -- rather than guess a slug from free text, add one line
# here the first time a new brand's real wording is seen. Keys are
# matched case-insensitively as a substring of the email body.
GYFTR_BRAND_MAP: dict[str, str] = {
    "swiggy money voucher": "swiggy",
}


def brand_for_gyftr_product(product_text: str) -> str | None:
    """Look up product_text against GYFTR_BRAND_MAP by case-insensitive
    substring match. Returns the wallet-account brand slug, or None if
    this product line doesn't match any known brand."""
    lowered = product_text.lower()
    for label, slug in GYFTR_BRAND_MAP.items():
        if label in lowered:
            return slug
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/ingest && ../../.venv/bin/pytest tests/test_voucher_packs.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add packages/ingest/munim_ingest/voucher_packs.py packages/ingest/tests/test_voucher_packs.py
git commit -m "Add voucher sender domains and GYFTR brand mapping"
```

---

### Task 2: Voucher email body parsers

**Files:**
- Create: `packages/ingest/munim_ingest/voucher_parse.py`
- Test: `packages/ingest/tests/test_voucher_parse.py`

**Interfaces:**
- Consumes: `brand_for_gyftr_product` from Task 1 (`voucher_packs.py`).
- Produces: four functions, each `(raw_email: bytes) -> dict | None`:
  - `parse_gyftr(raw_email) -> {"kind": "purchase", "brand": str, "value": float, "code": str, "purchased_at": date} | None`
  - `parse_amazonpay(raw_email) -> {"kind": "spend", "brand": "amazonpay", "source": "amazonpay", "amount": float, "merchant": str, "order_id": str, "order_date": date, "paid_via": None} | None`
  - `parse_swiggy(raw_email) -> {"kind": "spend", "brand": "swiggy", "source": "swiggy_order", "amount": float, "merchant": str, "order_id": str, "order_date": date, "paid_via": str} | None`
  - `parse_instamart(raw_email) -> {"kind": "spend", "brand": "swiggy", "source": "instamart_order", "amount": float, "merchant": "Instamart", "order_id": str, "order_date": date, "paid_via": None} | None`
  - Every function returns `None` (never raises) when the email doesn't
    match its expected template — later tasks rely on `None` meaning
    "skip, don't create anything."
  - `order_date`/`purchased_at` for Swiggy and Instamart come from the
    email's own `Date` header (the visible body timestamps have no
    year); Amazon Pay's `order_date` is parsed from the body's `Order
    Date` field (which does include a year); GYFTR's `purchased_at`
    also comes from the `Date` header (the body only has an expiry
    date, not a purchase date).

**Note for the implementer:** these regexes are built against the exact
sample emails the user pasted into the design conversation (reproduced
in the tests below verbatim, as MIME text/plain bodies). Real fetched
emails may render slightly differently (HTML-to-text conversion
artifacts, extra whitespace) — if `munim-ingest gmail fetch-vouchers`
later shows 0 matches against real mail despite senders matching,
that's expected follow-up tuning, not a sign this task was done wrong.

- [ ] **Step 1: Write the failing tests**

```python
# packages/ingest/tests/test_voucher_parse.py
import sys
from datetime import date
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


def test_parse_gyftr_returns_none_for_unrecognized_brand():
    raw = _msg("Your Gift Voucher", "GyFTR <gifts@gyftr.com>",
               "Mon, 14 Sep 2026 14:09:00 +0530",
               GYFTR_BODY.replace("Swiggy Money Voucher", "Bata Voucher"))
    assert parse_gyftr(raw) is None


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/ingest && ../../.venv/bin/pytest tests/test_voucher_parse.py -v`
Expected: FAIL with "No module named 'munim_ingest.voucher_parse'"

- [ ] **Step 3: Write the implementation**

```python
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


def _header_date(msg) -> date:
    return parsedate_to_datetime(msg["Date"]).date()


def _amount(text: str, label: str) -> float | None:
    m = re.search(rf"{label}\s*\n?\s*\t?\s*(?:Rs|₹)?\s*([\d,]+(?:\.\d+)?)", text)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def parse_gyftr(raw_email: bytes) -> dict | None:
    msg = email.message_from_bytes(raw_email)
    if "gyftr" not in (msg["From"] or "").lower():
        return None
    text = _text_body(msg)
    brand = brand_for_gyftr_product(text)
    if brand is None:
        return None
    value = _amount(text, "Value")
    code_match = re.search(r"E-Gift Card Code\s*\n\s*(\S+)", text)
    if value is None or not code_match:
        return None
    return {
        "kind": "purchase", "brand": brand, "value": value,
        "code": code_match.group(1), "purchased_at": _header_date(msg),
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
    if not (order_id_match and restaurant_match and paid_via_match):
        return None
    return {
        "kind": "spend", "brand": "swiggy", "source": "swiggy_order",
        "amount": float(paid_via_match.group(2).replace(",", "")),
        "merchant": restaurant_match.group(1).strip(),
        "order_id": order_id_match.group(1), "order_date": _header_date(msg),
        "paid_via": paid_via_match.group(1).strip(),
    }


def parse_instamart(raw_email: bytes) -> dict | None:
    msg = email.message_from_bytes(raw_email)
    if "instamart.in" not in (msg["From"] or "").lower():
        return None
    text = _text_body(msg)
    order_id_match = re.search(r"order id:\s*(\d+)", text, re.I)
    grand_total = _amount(text, "Grand Total")
    if not order_id_match or grand_total is None:
        return None
    return {
        "kind": "spend", "brand": "swiggy", "source": "instamart_order",
        "amount": grand_total, "merchant": "Instamart",
        "order_id": order_id_match.group(1), "order_date": _header_date(msg),
        "paid_via": None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/ingest && ../../.venv/bin/pytest tests/test_voucher_parse.py -v`
Expected: PASS (7 tests). If a regex doesn't match the sample text
exactly as transcribed, adjust the regex (not the test) — the test
bodies are the ground truth, transcribed directly from the user's real
emails.

- [ ] **Step 5: Commit**

```bash
git add packages/ingest/munim_ingest/voucher_parse.py packages/ingest/tests/test_voucher_parse.py
git commit -m "Add body-only parsers for GYFTR/Amazon Pay/Swiggy/Instamart emails"
```

---

### Task 3: `gmail fetch-vouchers` CLI command

**Files:**
- Modify: `packages/ingest/munim_ingest/cli.py`
- Test: `packages/ingest/tests/test_cli_gmail_vouchers.py`

**Interfaces:**
- Consumes: `GYFTR_FROM`, `AMAZONPAY_FROM`, `SWIGGY_FROM`,
  `INSTAMART_FROM` (Task 1); `parse_gyftr`, `parse_amazonpay`,
  `parse_swiggy`, `parse_instamart` (Task 2); `ImapConfig`, `connect`,
  `search_uids` (existing, `imap_client.py`).
- Produces: `gmail_app.command("fetch-vouchers")` — writes one JSON
  object per line (JSONL) to the output file, one line per successfully
  parsed record. Dates are serialized as ISO strings (`"2026-09-14"`)
  since JSON has no native date type — Task 7 parses them back.

- [ ] **Step 1: Write the failing tests**

```python
# packages/ingest/tests/test_cli_gmail_vouchers.py
import json
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from munim_ingest.cli import app

runner = CliRunner()


def _msg(subject, from_addr, date_header, body) -> bytes:
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["Date"] = date_header
    return msg.as_bytes()


GYFTR_BODY = """Please find your instant voucher details.

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
"""


def test_fetch_vouchers_writes_jsonl_records(tmp_path, monkeypatch):
    monkeypatch.delenv("MUNIM_GMAIL_APP_PASSWORD", raising=False)
    fake_conn = MagicMock()
    gyftr_raw = _msg(
        "Your Gift Voucher", "GyFTR <gifts@gyftr.com>",
        "Mon, 14 Sep 2026 14:09:00 +0530", GYFTR_BODY)

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1"]), \
         patch("munim_ingest.cli.getpass.getpass", return_value="fake-app-password"):
        fake_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", gyftr_raw)])
        out_file = tmp_path / "vouchers.jsonl"
        result = runner.invoke(
            app, ["gmail", "fetch-vouchers", "--email", "me@example.com",
                  "--out", str(out_file)])

    assert result.exit_code == 0, result.output
    lines = out_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == "purchase"
    assert record["brand"] == "swiggy"
    assert record["value"] == 2000.0
    assert record["purchased_at"] == "2026-09-14"


def test_fetch_vouchers_skips_unparseable_messages(tmp_path, monkeypatch):
    monkeypatch.delenv("MUNIM_GMAIL_APP_PASSWORD", raising=False)
    fake_conn = MagicMock()
    unrelated_raw = _msg("Hello", "someone@example.com",
                         "Mon, 14 Sep 2026 12:09:00 +0530", "Not a voucher.")

    with patch("munim_ingest.cli.connect", return_value=fake_conn), \
         patch("munim_ingest.cli.search_uids", return_value=[b"1"]), \
         patch("munim_ingest.cli.getpass.getpass", return_value="fake-app-password"):
        fake_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {123}", unrelated_raw)])
        out_file = tmp_path / "vouchers.jsonl"
        result = runner.invoke(
            app, ["gmail", "fetch-vouchers", "--email", "me@example.com",
                  "--out", str(out_file)])

    assert result.exit_code == 0, result.output
    assert "0" in result.output
    assert not out_file.exists() or out_file.read_text().strip() == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/ingest && ../../.venv/bin/pytest tests/test_cli_gmail_vouchers.py -v`
Expected: FAIL with "No such command 'fetch-vouchers'"

- [ ] **Step 3: Write the implementation**

Add these imports near the top of `packages/ingest/munim_ingest/cli.py`,
alongside the existing `from .imap_client import ...` line:

```python
import json as json_module
from .voucher_packs import GYFTR_FROM, AMAZONPAY_FROM, SWIGGY_FROM, INSTAMART_FROM
from .voucher_parse import parse_gyftr, parse_amazonpay, parse_swiggy, parse_instamart
```

Add this command in the `gmail_app` section, after `gmail_fetch`:

```python
_VOUCHER_SENDERS = [
    (GYFTR_FROM, parse_gyftr),
    (AMAZONPAY_FROM, parse_amazonpay),
    (SWIGGY_FROM, parse_swiggy),
    (INSTAMART_FROM, parse_instamart),
]


def _json_default(value):
    # date objects (purchased_at / order_date) have no native JSON
    # representation -- serialize as ISO strings, matching how Task 7's
    # `munim vouchers import` parses them back with date.fromisoformat.
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {value!r}")


@gmail_app.command("fetch-vouchers")
def gmail_fetch_vouchers(
    email: str = typer.Option(..., prompt=True, help="Your Gmail address"),
    out: Path = typer.Option(None, help="Output JSONL file (default: ~/.munim-ingest/vouchers.jsonl)"),
    mailbox: str = typer.Option("INBOX", help="IMAP mailbox to search"),
    imap_host: str = typer.Option("imap.gmail.com"),
    imap_port: int = typer.Option(993),
    since: str = typer.Option(
        None, "--since",
        help="Only messages on/after this date (YYYY-MM-DD)."),
):
    """Search Gmail for GYFTR/Amazon Pay/Swiggy/Instamart emails and
    write one parsed voucher record per line to a JSONL file for
    `munim vouchers import`. No attachments involved -- these senders
    put the spend detail directly in the email body. Same password
    handling as `gmail fetch`: the app password is read from
    MUNIM_GMAIL_APP_PASSWORD if set, otherwise prompted, never written
    to disk.
    """
    since_date = None
    if since is not None:
        try:
            since_date = datetime.strptime(since, "%Y-%m-%d").date()
        except ValueError:
            console.print(f"[red]--since must be YYYY-MM-DD, got {escape(since)}[/red]")
            raise typer.Exit(1)

    password = os.environ.get("MUNIM_GMAIL_APP_PASSWORD") or getpass.getpass(
        f"App password for {email} (never stored): ")

    config = ImapConfig(host=imap_host, port=imap_port, email=email, password=password)
    try:
        conn = connect(config)
    except Exception as e:
        console.print(f"[red]Could not connect or log in: {escape(str(e))}[/red]")
        raise typer.Exit(1)

    out_file = out or (DEFAULT_HOME / "vouchers.jsonl")
    records = []
    try:
        all_domains = [d for d, _ in _VOUCHER_SENDERS]
        uids = search_uids(conn, mailbox, all_domains, since=since_date)
        console.print(f"Found {len(uids)} candidate message(s) in {escape(mailbox)}.")

        consecutive_failures = 0
        for uid in uids:
            try:
                status, data = conn.fetch(uid, "(RFC822)")
                if status != "OK" or not data or not data[0]:
                    continue
                item = data[0]
                if not isinstance(item, tuple) or len(item) < 2:
                    continue
                raw = item[1]
                for _domain, parser in _VOUCHER_SENDERS:
                    record = parser(raw)
                    if record is not None:
                        records.append(record)
                        break
            except Exception as e:
                consecutive_failures += 1
                console.print(
                    f"[yellow]Skipping message {escape(str(uid))}: {escape(str(e))}[/yellow]")
                if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                    console.print(
                        f"[red]Stopping after {consecutive_failures} consecutive failures.[/red]")
                    break
                continue
            else:
                consecutive_failures = 0
    finally:
        conn.logout()

    if records:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json_module.dumps(record, default=_json_default) + "\n")
        console.print(f"[green]{len(records)}[/green] voucher record(s) written to {escape(str(out_file))}.")
    else:
        console.print("[bold]0[/bold] voucher record(s) found.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/ingest && ../../.venv/bin/pytest tests/test_cli_gmail_vouchers.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full ingest test suite to check for regressions**

Run: `cd packages/ingest && ../../.venv/bin/pytest tests/ -q`
Expected: all tests pass, no regressions in existing `gmail fetch` tests

- [ ] **Step 6: Commit**

```bash
git add packages/ingest/munim_ingest/cli.py packages/ingest/tests/test_cli_gmail_vouchers.py
git commit -m "Add gmail fetch-vouchers command for voucher email bodies"
```

---

### Task 4: `Store.delete_transaction()`

**Files:**
- Modify: `packages/classify/munim/store.py`
- Test: `packages/classify/tests/test_store_delete_transaction.py`

**Interfaces:**
- Produces: `Store.delete_transaction(txn_id: str) -> None` — removes
  the transaction row and any `tags`/`transfer_links` rows referencing
  it, so no orphaned references remain. Idempotent: deleting an id that
  doesn't exist is a no-op, not an error. Needed by Task 8's `recheck`.

- [ ] **Step 1: Write the failing test**

```python
# packages/classify/tests/test_store_delete_transaction.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction


def _txn(id_, amount=100.0, direction=Direction.DEBIT):
    return Transaction(id=id_, date="2026-06-01", amount=amount,
                       direction=direction, description_raw="X",
                       account="cc", category="Shopping")


def test_delete_transaction_removes_the_row(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([_txn("t1")])
    assert store.get_transaction("t1") is not None

    store.delete_transaction("t1")

    assert store.get_transaction("t1") is None


def test_delete_transaction_removes_tags_and_transfer_links(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([
        _txn("t1", direction=Direction.DEBIT),
        _txn("t2", direction=Direction.CREDIT),
    ])
    store.set_tags("t1", ["business"])
    store.link_transfer("t1", "t2")

    store.delete_transaction("t1")

    assert store.tags_for("t1") == []
    assert store.linked_counterpart("t2") is None


def test_delete_transaction_on_unknown_id_is_a_noop(tmp_path):
    store = Store(home=tmp_path)
    store.delete_transaction("does-not-exist")  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/classify && ../../.venv/bin/pytest tests/test_store_delete_transaction.py -v`
Expected: FAIL with "'Store' object has no attribute 'delete_transaction'"

- [ ] **Step 3: Write the implementation**

Add this method to `Store` in `packages/classify/munim/store.py`,
directly after `update_transaction` (around line 161):

```python
    def delete_transaction(self, txn_id: str) -> None:
        """Removes a transaction and any tags/transfer_links rows that
        reference it, so no orphaned references remain. A no-op if
        txn_id doesn't exist. Used by the voucher-wallet recheck pass to
        safely regenerate synthetic redemption transactions."""
        self.db.execute("DELETE FROM transactions WHERE id=?", (txn_id,))
        self.db.execute("DELETE FROM tags WHERE txn_id=?", (txn_id,))
        self.db.execute(
            "DELETE FROM transfer_links WHERE txn_id_a=? OR txn_id_b=?",
            (txn_id, txn_id))
        self.db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/classify && ../../.venv/bin/pytest tests/test_store_delete_transaction.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add packages/classify/munim/store.py packages/classify/tests/test_store_delete_transaction.py
git commit -m "Add Store.delete_transaction for voucher-wallet recheck support"
```

---

### Task 5: Voucher wallet — purchase import

**Files:**
- Create: `packages/classify/munim/voucher_wallet.py`
- Test: `packages/classify/tests/test_voucher_wallet_purchase.py`

**Interfaces:**
- Consumes: `Store` (`upsert_transactions`, `all_transactions`,
  `get_config`/`set_config`, `link_transfer`, `transfer_link_map`) and
  `Transaction`/`Direction`/`Stage`/`Status` from `schema.py`.
- Produces: `import_purchase(store: Store, record: dict) -> str` where
  `record` is a GYFTR purchase dict shaped exactly as Task 2's
  `parse_gyftr` produces it (with `purchased_at` already a `date`
  object, not a string — the caller, Task 7, is responsible for that
  conversion). Returns the created/updated transaction's id. Later
  tasks (6, 8) call this directly.

- [ ] **Step 1: Write the failing tests**

```python
# packages/classify/tests/test_voucher_wallet_purchase.py
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction
from munim.voucher_wallet import import_purchase


def _card_debit(id_, amount, d):
    return Transaction(id=id_, date=d, amount=amount, direction=Direction.DEBIT,
                       description_raw="GYFTR SWIGGY VOUCHER", account="cc",
                       category="Transfers")


PURCHASE_RECORD = {
    "kind": "purchase", "brand": "swiggy", "value": 2000.0,
    "code": "VGHDR7VACB6SD15E", "purchased_at": date(2026, 9, 14),
}


def test_import_purchase_creates_credit_on_voucher_account(tmp_path):
    store = Store(home=tmp_path)
    txn_id = import_purchase(store, PURCHASE_RECORD)

    txn = store.get_transaction(txn_id)
    assert txn.account == "voucher-swiggy"
    assert txn.direction == Direction.CREDIT
    assert txn.amount == 2000.0
    assert txn.category == "Transfers"
    assert txn.date.isoformat() == "2026-09-14"


def test_import_purchase_registers_account_as_assets(tmp_path):
    store = Store(home=tmp_path)
    import_purchase(store, PURCHASE_RECORD)

    types = store.get_config("account_types", {})
    assert types["voucher-swiggy"] == "Assets"


def test_import_purchase_links_to_unique_matching_card_debit(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([_card_debit("card1", 2000.0, "2026-09-14")])

    txn_id = import_purchase(store, PURCHASE_RECORD)

    assert store.linked_counterpart("card1") == txn_id


def test_import_purchase_does_not_link_when_multiple_candidates(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([
        _card_debit("card1", 2000.0, "2026-09-13"),
        _card_debit("card2", 2000.0, "2026-09-15"),
    ])

    txn_id = import_purchase(store, PURCHASE_RECORD)

    assert store.linked_counterpart("card1") is None
    assert store.linked_counterpart("card2") is None
    assert store.linked_counterpart(txn_id) is None


def test_import_purchase_is_idempotent_on_rerun(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([_card_debit("card1", 2000.0, "2026-09-14")])

    first_id = import_purchase(store, PURCHASE_RECORD)
    second_id = import_purchase(store, PURCHASE_RECORD)

    assert first_id == second_id
    assert len(store.all_transactions()) == 2  # card1 + the one voucher credit
    assert store.linked_counterpart("card1") == first_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/classify && ../../.venv/bin/pytest tests/test_voucher_wallet_purchase.py -v`
Expected: FAIL with "No module named 'munim.voucher_wallet'"

- [ ] **Step 3: Write the implementation**

```python
# packages/classify/munim/voucher_wallet.py
"""Turns parsed voucher-purchase/redemption records (from
munim_ingest.voucher_parse) into real Transaction rows on auto-created
voucher-<brand> virtual Assets accounts -- the same double-entry
pattern already used for house-sgs. See
docs/superpowers/specs/2026-09-16-voucher-redemption-tracking-design.md.
"""
from __future__ import annotations

from datetime import date

from .schema import Direction, Stage, Status, Transaction
from .store import Store

# How many days apart a voucher purchase's card debit can be from the
# GYFTR purchase-confirmation email's own date and still be considered
# the same real-world event -- covers card-network posting lag.
LINK_WINDOW_DAYS = 5


def import_purchase(store: Store, record: dict) -> str:
    """record: {"kind": "purchase", "brand": str, "value": float,
    "code": str, "purchased_at": date}. Creates (or, on rerun,
    idempotently finds) a credit transaction on voucher-<brand> for the
    voucher's face value, links it to the one unambiguous matching real
    card debit if exactly one exists, and returns the transaction id."""
    brand = record["brand"]
    account = f"voucher-{brand}"

    account_types = store.get_config("account_types", {}) or {}
    if account not in account_types:
        account_types[account] = "Assets"
        store.set_config("account_types", account_types)

    txn = Transaction(
        id=f"voucher-purchase-{record['code']}",
        date=record["purchased_at"],
        amount=record["value"],
        direction=Direction.CREDIT,
        description_raw=f"GYFTR voucher purchase - {brand}",
        account=account,
        category="Transfers",
        stage=Stage.STRUCTURAL,
        confidence=1.0,
        status=Status.PROVISIONAL,
    )
    store.upsert_transactions([txn])

    linked = set(store.transfer_link_map().keys())
    candidates = [
        t for t in store.all_transactions()
        if t.direction == Direction.DEBIT
        and not t.account.startswith("voucher-")
        and t.id not in linked
        and abs(t.amount - record["value"]) < 0.01
        and abs((t.date - record["purchased_at"]).days) <= LINK_WINDOW_DAYS
    ]
    if len(candidates) == 1:
        store.link_transfer(candidates[0].id, txn.id, confidence="auto")

    return txn.id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/classify && ../../.venv/bin/pytest tests/test_voucher_wallet_purchase.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add packages/classify/munim/voucher_wallet.py packages/classify/tests/test_voucher_wallet_purchase.py
git commit -m "Add voucher_wallet.import_purchase with auto transfer-linking"
```

---

### Task 6: Voucher wallet — spend import

**Files:**
- Modify: `packages/classify/munim/voucher_wallet.py`
- Test: `packages/classify/tests/test_voucher_wallet_spend.py`

**Interfaces:**
- Consumes: everything from Task 5, plus `Pipeline` from `pipeline.py`
  (`Pipeline(store).run([txn])` classifies `txn.category`/`stage`/
  `status`/`confidence` in place).
- Produces: `import_spend(store: Store, record: dict) -> str | None`
  where `record` is an Amazon Pay/Swiggy/Instamart spend dict shaped
  exactly as Task 2's parsers produce them (with `order_date` already a
  `date` object). Returns the created transaction's id, or `None` if
  the spend was skipped as already-real (a real payment rail was named,
  or a matching bank transaction was found). Also produces
  `_has_matching_bank_txn(store, amount, when, window_days=2) -> bool`,
  reused by Task 8's `recheck`.

- [ ] **Step 1: Write the failing tests**

```python
# packages/classify/tests/test_voucher_wallet_spend.py
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction
from munim.voucher_wallet import import_spend


def _real_debit(id_, amount, d, account="cc"):
    return Transaction(id=id_, date=d, amount=amount, direction=Direction.DEBIT,
                       description_raw="ZOMATO", account=account,
                       category="Dining")


AMAZONPAY_RECORD = {
    "kind": "spend", "brand": "amazonpay", "source": "amazonpay",
    "amount": 132.0, "merchant": "Zomato", "order_id": "171-9035274-8173116",
    "order_date": date(2026, 9, 1), "paid_via": None,
}

SWIGGY_CARD_RECORD = {
    "kind": "spend", "brand": "swiggy", "source": "swiggy_order",
    "amount": 391.0, "merchant": "Cafe Iftar", "order_id": "246907327135063",
    "order_date": date(2024, 8, 28), "paid_via": "Credit/Debit card",
}

INSTAMART_RECORD = {
    "kind": "spend", "brand": "swiggy", "source": "instamart_order",
    "amount": 395.0, "merchant": "Instamart", "order_id": "248336149154232",
    "order_date": date(2026, 9, 14), "paid_via": None,
}


def test_import_spend_skips_when_paid_via_names_a_real_rail(tmp_path):
    store = Store(home=tmp_path)
    txn_id = import_spend(store, SWIGGY_CARD_RECORD)
    assert txn_id is None
    assert store.all_transactions() == []


def test_import_spend_skips_when_matching_bank_txn_exists(tmp_path):
    store = Store(home=tmp_path)
    store.upsert_transactions([_real_debit("card1", 395.0, "2026-09-14")])

    txn_id = import_spend(store, INSTAMART_RECORD)

    assert txn_id is None
    # only the pre-existing real transaction, nothing created
    assert len(store.all_transactions()) == 1


def test_import_spend_creates_redemption_when_no_bank_match(tmp_path):
    store = Store(home=tmp_path)

    txn_id = import_spend(store, INSTAMART_RECORD)

    txn = store.get_transaction(txn_id)
    assert txn.account == "voucher-swiggy"
    assert txn.direction == Direction.DEBIT
    assert txn.amount == 395.0
    assert txn.category == "Groceries"


def test_import_spend_swiggy_order_category_is_dining(tmp_path):
    store = Store(home=tmp_path)
    record = {**SWIGGY_CARD_RECORD, "paid_via": "Swiggy Money"}

    txn_id = import_spend(store, record)

    txn = store.get_transaction(txn_id)
    assert txn.account == "voucher-swiggy"
    assert txn.category == "Dining"


def test_import_spend_amazonpay_uses_pipeline_classification(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("categories", ["Dining", "Groceries"])
    from munim.memory import MemoryMatcher
    store.remember("ZOMATO", "Dining", kind="merchant")

    txn_id = import_spend(store, AMAZONPAY_RECORD)

    txn = store.get_transaction(txn_id)
    assert txn.account == "voucher-amazonpay"
    assert txn.category == "Dining"


def test_import_spend_is_idempotent_on_rerun(tmp_path):
    store = Store(home=tmp_path)
    first_id = import_spend(store, INSTAMART_RECORD)
    second_id = import_spend(store, INSTAMART_RECORD)
    assert first_id == second_id
    assert len(store.all_transactions()) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/classify && ../../.venv/bin/pytest tests/test_voucher_wallet_spend.py -v`
Expected: FAIL with "cannot import name 'import_spend'"

- [ ] **Step 3: Write the implementation**

Append to `packages/classify/munim/voucher_wallet.py`:

```python
# Payment-rail strings confirmed to mean "a real bank transaction already
# covers this" -- matched case-insensitively against a spend record's
# paid_via. Anything else (a voucher/wallet-branded value, or None) falls
# through to the bank cross-check below, which is the authoritative
# signal either way (per the user: "there will be an HDFC transaction if
# paid by card, else it'll be using GYFTR coupons").
KNOWN_REAL_PAYMENT_RAILS = {"credit/debit card", "credit card", "debit card",
                            "upi", "netbanking"}

# category is deterministic for these two sources -- Swiggy/Instamart
# order emails don't carry enough merchant detail for the normal
# classification pipeline to do better than guess. Amazon Pay's merchant
# varies too widely for a fixed category, so it goes through Pipeline
# instead (see import_spend).
FIXED_CATEGORY_BY_SOURCE = {"swiggy_order": "Dining", "instamart_order": "Groceries"}

# Date-window for deciding a spend record already has a matching real
# bank transaction -- covers order-date vs. settlement-date lag.
BANK_MATCH_WINDOW_DAYS = 2


def _has_matching_bank_txn(store: Store, amount: float, when: date,
                           window_days: int = BANK_MATCH_WINDOW_DAYS) -> bool:
    return any(
        t.direction == Direction.DEBIT
        and not t.account.startswith("voucher-")
        and abs(t.amount - amount) < 0.01
        and abs((t.date - when).days) <= window_days
        for t in store.all_transactions()
    )


def import_spend(store: Store, record: dict) -> str | None:
    """record: {"kind": "spend", "brand": str, "source": str,
    "amount": float, "merchant": str, "order_id": str, "order_date":
    date, "paid_via": str | None}. Returns the created transaction id,
    or None if this spend is already covered by a real bank transaction
    (skipped, nothing created)."""
    paid_via = (record.get("paid_via") or "").strip().lower()
    if paid_via in KNOWN_REAL_PAYMENT_RAILS:
        return None
    if _has_matching_bank_txn(store, record["amount"], record["order_date"]):
        return None

    account = f"voucher-{record['brand']}"
    txn = Transaction(
        id=f"voucher-redemption-{record['order_id']}",
        date=record["order_date"],
        amount=record["amount"],
        direction=Direction.DEBIT,
        # description_raw is the bare merchant name, not an annotated
        # string like "Zomato (via ... voucher)" -- for the Amazon Pay
        # case this text goes straight through Pipeline/Normalizer, which
        # expects real-narration-shaped input, and annotation text risks
        # polluting the extracted merchant_norm so an existing "ZOMATO"
        # memory rule no longer matches. The voucher-<brand> account
        # already conveys "this was a voucher redemption" on its own.
        description_raw=record["merchant"],
        account=account,
    )

    fixed_category = FIXED_CATEGORY_BY_SOURCE.get(record["source"])
    if fixed_category:
        txn.category = fixed_category
        txn.stage = Stage.STRUCTURAL
        txn.confidence = 1.0
        txn.status = Status.PROVISIONAL
    else:
        from .pipeline import Pipeline
        Pipeline(store).run([txn])

    store.upsert_transactions([txn])
    return txn.id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/classify && ../../.venv/bin/pytest tests/test_voucher_wallet_spend.py -v`
Expected: PASS (7 tests). If `test_import_spend_amazonpay_uses_pipeline_classification`
fails because `store.remember` has a different signature, check
`packages/classify/munim/store.py` for the real method name/signature
used to seed a memory rule (see other tests in
`packages/classify/tests/` that call it, e.g. `test_pipeline.py`) and
adjust the test to match — the implementation code above does not
depend on this detail.

- [ ] **Step 5: Commit**

```bash
git add packages/classify/munim/voucher_wallet.py packages/classify/tests/test_voucher_wallet_spend.py
git commit -m "Add voucher_wallet.import_spend with bank cross-check"
```

---

### Task 7: `munim vouchers import` CLI command

**Files:**
- Modify: `packages/classify/munim/cli.py`
- Test: `packages/classify/tests/test_cli_vouchers_import.py`

**Interfaces:**
- Consumes: `import_purchase`, `import_spend` (Tasks 5/6).
- Produces: a new `vouchers_app` Typer sub-app (`munim vouchers ...`,
  registered the same way `gmail_app` is registered in
  `packages/ingest/munim_ingest/cli.py` — via `app.add_typer`), with an
  `import` command: `munim vouchers import <file>` reads the JSONL file
  produced by Task 3, converts each record's date string back to a
  `date` via `date.fromisoformat`, dispatches to `import_purchase`/
  `import_spend` by `record["kind"]`, and **appends every record** (with
  dates still as ISO strings) to a new `voucher_records` config list —
  the durable source of truth Task 8's `recheck` replays from. Prints a
  summary: vouchers purchased, redemptions created, redemptions skipped
  as already-real.

- [ ] **Step 1: Write the failing test**

```python
# packages/classify/tests/test_cli_vouchers_import.py
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store


def test_vouchers_import_creates_transactions_and_persists_records(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))

    records = [
        {"kind": "purchase", "brand": "swiggy", "value": 2000.0,
         "code": "VGHDR7VACB6SD15E", "purchased_at": "2026-09-14"},
        {"kind": "spend", "brand": "swiggy", "source": "instamart_order",
         "amount": 395.0, "merchant": "Instamart",
         "order_id": "248336149154232", "order_date": "2026-09-14",
         "paid_via": None},
    ]
    jsonl_file = tmp_path / "vouchers.jsonl"
    with open(jsonl_file, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["vouchers", "import", str(jsonl_file)])
    assert result.exit_code == 0, result.output

    store = Store(home=tmp_path)
    accounts = {t.account for t in store.all_transactions()}
    assert accounts == {"voucher-swiggy"}
    assert len(store.all_transactions()) == 2

    stored_records = store.get_config("voucher_records", [])
    assert len(stored_records) == 2


def test_vouchers_import_is_safe_to_rerun_without_duplicating(tmp_path, monkeypatch):
    monkeypatch.setattr("munim.cli._store", lambda: Store(home=tmp_path))

    records = [
        {"kind": "purchase", "brand": "swiggy", "value": 2000.0,
         "code": "VGHDR7VACB6SD15E", "purchased_at": "2026-09-14"},
    ]
    jsonl_file = tmp_path / "vouchers.jsonl"
    with open(jsonl_file, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    from typer.testing import CliRunner
    from munim.cli import app
    runner = CliRunner()
    runner.invoke(app, ["vouchers", "import", str(jsonl_file)])
    runner.invoke(app, ["vouchers", "import", str(jsonl_file)])

    store = Store(home=tmp_path)
    assert len(store.all_transactions()) == 1
    # the record log should not grow unboundedly on repeated imports of
    # the exact same source file
    assert len(store.get_config("voucher_records", [])) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/classify && ../../.venv/bin/pytest tests/test_cli_vouchers_import.py -v`
Expected: FAIL with "No such command 'vouchers'"

- [ ] **Step 3: Write the implementation**

Add near the top of `packages/classify/munim/cli.py`, alongside the
other feature imports:

```python
from .voucher_wallet import import_purchase, import_spend
```

Add this new sub-app and command, following the same registration
pattern as any other `typer.Typer()` + `app.add_typer` pair already in
this file (e.g. search for how `tag_app` is wired):

```python
vouchers_app = typer.Typer(help="Import voucher purchase/redemption records fetched via munim-ingest gmail fetch-vouchers.")
app.add_typer(vouchers_app, name="vouchers")


def _record_key(record: dict) -> str:
    """The natural identifier a record log entry is deduplicated by --
    matches the id scheme import_purchase/import_spend use, so a record
    already present in voucher_records (by this key) is never appended
    twice even if the same source file is imported again."""
    if record["kind"] == "purchase":
        return f"purchase-{record['code']}"
    return f"spend-{record['order_id']}"


@vouchers_app.command("import")
def vouchers_import(file: Path = typer.Argument(..., exists=True,
        help="JSONL file from munim-ingest gmail fetch-vouchers")):
    """Turn fetched voucher records into transactions on voucher-<brand>
    virtual accounts, linking purchases to their funding card debit and
    creating redemption debits for spend not already covered by a real
    bank transaction."""
    from datetime import date as date_cls
    store = _store()
    existing_records = store.get_config("voucher_records", []) or []
    existing_keys = {_record_key(r) for r in existing_records}

    purchased = created = skipped = 0
    new_records = []
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        if record["kind"] == "purchase":
            live_record = {**record, "purchased_at": date_cls.fromisoformat(record["purchased_at"])}
            import_purchase(store, live_record)
            purchased += 1
        else:
            live_record = {**record, "order_date": date_cls.fromisoformat(record["order_date"])}
            if import_spend(store, live_record) is not None:
                created += 1
            else:
                skipped += 1
        if _record_key(record) not in existing_keys:
            new_records.append(record)
            existing_keys.add(_record_key(record))

    if new_records:
        store.set_config("voucher_records", existing_records + new_records)

    console.print(f"[green]{purchased}[/green] voucher purchase(s) recorded, "
                  f"[green]{created}[/green] redemption(s) created, "
                  f"[dim]{skipped}[/dim] already covered by a real transaction.")
```

`json` is already imported at the top of `packages/classify/munim/cli.py`
(line 7, `import json`) — no new import needed for it. `vouchers_app` and
`app.add_typer(vouchers_app, name="vouchers")` follow the exact same
registration pattern already used for `tag_app` (`cli.py:1039-1040`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/classify && ../../.venv/bin/pytest tests/test_cli_vouchers_import.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full classify test suite to check for regressions**

Run: `cd packages/classify && ../../.venv/bin/pytest tests/ -q`
Expected: all tests pass, no regressions

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/cli.py packages/classify/tests/test_cli_vouchers_import.py
git commit -m "Add munim vouchers import command"
```

---

### Task 8: Recheck — regenerate redemptions against current bank data

**Files:**
- Modify: `packages/classify/munim/voucher_wallet.py`
- Modify: `packages/classify/munim/cli.py`
- Test: `packages/classify/tests/test_voucher_wallet_recheck.py`

**Interfaces:**
- Consumes: `_has_matching_bank_txn`, `import_purchase`, `import_spend`
  (all from Tasks 5/6, already in `voucher_wallet.py`); `Store.
  delete_transaction` (Task 4); the `voucher_records` config list
  persisted by Task 7.
- Produces: `recheck(store: Store) -> dict` with keys `{"checked": int,
  "removed_existing": int, "created": int}`; and `munim vouchers
  recheck` CLI command.

- [ ] **Step 1: Write the failing tests**

```python
# packages/classify/tests/test_voucher_wallet_recheck.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from munim.store import Store
from munim.schema import Transaction, Direction
from munim.voucher_wallet import import_spend, recheck


def _real_debit(id_, amount, d):
    return Transaction(id=id_, date=d, amount=amount, direction=Direction.DEBIT,
                       description_raw="INSTAMART", account="cc",
                       category="Groceries")


INSTAMART_RECORD = {
    "kind": "spend", "brand": "swiggy", "source": "instamart_order",
    "amount": 395.0, "merchant": "Instamart", "order_id": "248336149154232",
    "order_date": "2026-09-14", "paid_via": None,
}


def test_recheck_removes_redemption_once_real_bank_txn_appears(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("voucher_records", [INSTAMART_RECORD])
    from datetime import date
    import_spend(store, {**INSTAMART_RECORD, "order_date": date(2026, 9, 14)})
    assert len(store.all_transactions()) == 1  # the redemption

    # the corresponding bank statement is imported later, revealing this
    # was actually card-paid all along
    store.upsert_transactions([_real_debit("card1", 395.0, "2026-09-14")])

    result = recheck(store)

    remaining = [t for t in store.all_transactions() if t.account.startswith("voucher-")]
    assert remaining == []
    assert result["removed_existing"] >= 1


def test_recheck_recreates_redemption_still_correctly_missing(tmp_path):
    store = Store(home=tmp_path)
    store.set_config("voucher_records", [INSTAMART_RECORD])
    from datetime import date
    original_id = import_spend(store, {**INSTAMART_RECORD, "order_date": date(2026, 9, 14)})

    result = recheck(store)

    remaining_ids = {t.id for t in store.all_transactions() if t.account.startswith("voucher-")}
    assert remaining_ids == {original_id}
    assert result["created"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd packages/classify && ../../.venv/bin/pytest tests/test_voucher_wallet_recheck.py -v`
Expected: FAIL with "cannot import name 'recheck'"

- [ ] **Step 3: Write the implementation**

Append to `packages/classify/munim/voucher_wallet.py`:

```python
def recheck(store: Store) -> dict:
    """Deletes every existing synthetic transaction on voucher-<brand>
    accounts, then replays the full voucher_records log (persisted by
    `munim vouchers import`) from scratch against the CURRENT set of
    real bank transactions. Safe to run any time -- corrects any earlier
    "no matching bank transaction, must be voucher-funded" guess that
    was only true because that period's bank statement hadn't been
    imported yet when the guess was originally made.

    Returns {"checked": len(voucher_records), "removed_existing": N,
    "created": N} -- created counts new/recreated transactions across
    both purchases and non-skipped redemptions."""
    removed_existing = 0
    for t in store.all_transactions():
        if t.account.startswith("voucher-"):
            store.delete_transaction(t.id)
            removed_existing += 1

    records = store.get_config("voucher_records", []) or []
    created = 0
    for record in records:
        if record["kind"] == "purchase":
            live_record = {**record, "purchased_at": date.fromisoformat(record["purchased_at"])}
            import_purchase(store, live_record)
            created += 1
        else:
            live_record = {**record, "order_date": date.fromisoformat(record["order_date"])}
            if import_spend(store, live_record) is not None:
                created += 1

    return {"checked": len(records), "removed_existing": removed_existing, "created": created}
```

`from datetime import date` is already at the top of
`packages/classify/munim/voucher_wallet.py` from Task 5 — no new import
needed for `recheck`.

Add this command to `packages/classify/munim/cli.py`, after
`vouchers_import`:

```python
@vouchers_app.command("recheck")
def vouchers_recheck():
    """Re-evaluate every voucher redemption against current bank data,
    removing any that a later-imported bank statement now shows was
    actually card-paid all along."""
    from .voucher_wallet import recheck as recheck_wallet
    store = _store()
    result = recheck_wallet(store)
    console.print(f"[green]{result['checked']}[/green] record(s) replayed, "
                  f"[yellow]{result['removed_existing']}[/yellow] prior "
                  f"synthetic transaction(s) cleared, "
                  f"[green]{result['created']}[/green] recreated as still-genuine.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/classify && ../../.venv/bin/pytest tests/test_voucher_wallet_recheck.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full classify test suite one more time**

Run: `cd packages/classify && ../../.venv/bin/pytest tests/ -q`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add packages/classify/munim/voucher_wallet.py packages/classify/munim/cli.py packages/classify/tests/test_voucher_wallet_recheck.py
git commit -m "Add voucher recheck: safely regenerate redemptions against current bank data"
```

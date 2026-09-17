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
    # These two have real, working redemption-email tracking of their
    # own (Swiggy/Instamart order emails; Amazon Pay spend emails), so
    # each keeps its own wallet account rather than joining the
    # catch-all below -- consolidating them would mean either losing
    # that tracking or redirecting it to a different account.
    "swiggy money voucher": "swiggy",
    "swiggy instamart": "swiggy",
    "amazon shopping voucher": "amazonpay",
    "amazon": "amazonpay",
    # Everything else is a single-use, store-specific voucher with no
    # redemption-email parser built (no sample email seen yet for any
    # of these) -- rather than a proliferation of never-redeemed
    # per-brand accounts, they share one generic GYFTR wallet until a
    # real redemption source is found for a given brand.
    "lenskart": "gyftr",
    "bata": "gyftr",
    "zepto": "gyftr",
    "westside": "gyftr",
    "max": "gyftr",
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

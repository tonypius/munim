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

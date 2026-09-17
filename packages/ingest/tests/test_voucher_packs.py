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
    assert brand_for_gyftr_product("Croma Voucher") is None


def test_brand_for_gyftr_product_recognizes_amazon_variants():
    assert brand_for_gyftr_product("Amazon") == "amazonpay"
    assert brand_for_gyftr_product("Amazon Shopping Voucher") == "amazonpay"


def test_brand_for_gyftr_product_recognizes_swiggy_instamart():
    assert brand_for_gyftr_product("Swiggy Instamart") == "swiggy"


def test_brand_for_gyftr_product_recognizes_other_known_brands():
    assert brand_for_gyftr_product("LENSKART") == "lenskart"
    assert brand_for_gyftr_product("Bata") == "bata"
    assert brand_for_gyftr_product("Zepto") == "zepto"
    assert brand_for_gyftr_product("Westside") == "westside"
    assert brand_for_gyftr_product("MAX") == "max"

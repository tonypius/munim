import pytest

from munim_ingest.packs import PackNotFoundError, list_packs, load_pack


def test_load_hdfc_pack():
    pack = load_pack("hdfc")
    assert pack.bank == "hdfc"
    assert "hdfcbank.net" in pack.from_domains
    assert ".csv" in pack.attachment_extensions
    assert ".pdf" in pack.attachment_extensions


def test_load_sib_pack():
    pack = load_pack("sib")
    assert pack.bank == "sib"
    assert len(pack.from_domains) > 0


def test_load_sbi_pack():
    pack = load_pack("sbi")
    assert pack.bank == "sbi"
    assert len(pack.from_domains) > 0


def test_load_unknown_bank_raises_with_available_list():
    with pytest.raises(PackNotFoundError) as exc_info:
        load_pack("nonexistent_bank_xyz")
    assert "hdfc" in str(exc_info.value)


def test_list_packs_includes_all_three():
    packs = list_packs()
    assert {"hdfc", "sib", "sbi"}.issubset(set(packs))

import pytest

from munim_ingest.packs import PackNotFoundError, list_packs, load_pack


def test_load_hdfc_pack():
    pack = load_pack("hdfc")
    assert pack.bank == "hdfc"
    assert "hdfcbank.net" in pack.from_domains
    assert ".csv" in pack.attachment_extensions
    assert ".pdf" in pack.attachment_extensions
    # Sender-domain search alone matches years of non-statement mail
    # (alerts, OTPs, offers) from a bank's domain — subject_keywords narrows
    # it to the statement emails specifically. Confirmed against a real
    # subject line: "Your HDFC Bank - Regalia Gold Credit Card Statement -
    # August-2026" — the card name and month vary, "Credit Card Statement"
    # doesn't.
    assert "Credit Card Statement" in pack.subject_keywords


def test_load_pack_defaults_subject_keywords_to_empty_list():
    """A pack file with no subject_keywords key (like sib/sbi today) must
    not filter by subject at all — empty list, not a crash."""
    pack = load_pack("sib")
    assert pack.subject_keywords == []


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

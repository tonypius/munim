from unittest.mock import MagicMock

import pytest

from munim_ingest.imap_client import ImapConfig, build_from_query, search_uids

FAKE_PASSWORD = "hunter2-totally-distinctive-app-password"


def test_imap_config_repr_never_contains_the_password():
    """The app password must not appear in the dataclass repr — otherwise
    any traceback, log line or error message that renders an ImapConfig
    leaks the user's Gmail app password in plaintext."""
    config = ImapConfig(
        host="imap.gmail.com", port=993, email="me@example.com", password=FAKE_PASSWORD,
    )

    assert FAKE_PASSWORD not in repr(config)
    assert FAKE_PASSWORD not in str(config)
    assert FAKE_PASSWORD not in f"{config}"
    # ...but the object is otherwise unchanged and still usable.
    assert config.password == FAKE_PASSWORD
    assert config.host == "imap.gmail.com"
    assert config.port == 993
    assert config.email == "me@example.com"
    assert repr(config) == (
        "ImapConfig(host='imap.gmail.com', port=993, email='me@example.com')"
    )


def test_imap_config_accepts_positional_construction():
    """field(repr=False) is not a default value, so positional
    construction and field ordering must be unaffected."""
    config = ImapConfig("imap.gmail.com", 993, "me@example.com", FAKE_PASSWORD)
    assert config.password == FAKE_PASSWORD
    with pytest.raises(TypeError):
        ImapConfig("imap.gmail.com", 993, "me@example.com")  # password is required


def test_build_from_query_single_domain():
    assert build_from_query(["hdfcbank.net"]) == b'(FROM "hdfcbank.net")'


def test_build_from_query_two_domains_ors_them():
    query = build_from_query(["hdfcbank.net", "hdfcbank.com"])
    assert query == b'(OR (FROM "hdfcbank.net") (FROM "hdfcbank.com"))'


def test_build_from_query_three_domains_nests_or():
    query = build_from_query(["a.com", "b.com", "c.com"])
    assert query == b'(OR (FROM "a.com") (OR (FROM "b.com") (FROM "c.com")))'


def test_build_from_query_empty_raises():
    with pytest.raises(ValueError):
        build_from_query([])


def test_search_uids_selects_mailbox_readonly_and_searches():
    conn = MagicMock()
    conn.select.return_value = ("OK", [b"1"])
    conn.search.return_value = ("OK", [b"12 13 14"])

    uids = search_uids(conn, "INBOX", ["hdfcbank.net"])

    conn.select.assert_called_once_with("INBOX", readonly=True)
    conn.search.assert_called_once()
    assert uids == [b"12", b"13", b"14"]


def test_search_uids_empty_results():
    conn = MagicMock()
    conn.select.return_value = ("OK", [b"1"])
    conn.search.return_value = ("OK", [b""])

    uids = search_uids(conn, "INBOX", ["hdfcbank.net"])

    assert uids == []


def test_search_uids_raises_on_search_failure():
    conn = MagicMock()
    conn.select.return_value = ("OK", [b"1"])
    conn.search.return_value = ("NO", [None])

    with pytest.raises(RuntimeError):
        search_uids(conn, "INBOX", ["hdfcbank.net"])

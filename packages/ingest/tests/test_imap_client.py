from unittest.mock import MagicMock

import pytest

from munim_ingest.imap_client import build_from_query, search_uids


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

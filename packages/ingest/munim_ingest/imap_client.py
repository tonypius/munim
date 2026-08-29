"""IMAP connection and search for bank statement emails. Standard library
only (imaplib) — no OAuth, no external API, just IMAP + an app password.
"""
from __future__ import annotations

import imaplib
from dataclasses import dataclass, field
from datetime import date


@dataclass
class ImapConfig:
    host: str
    port: int
    email: str
    # repr=False keeps the app password out of the auto-generated __repr__,
    # so it can never be rendered into a traceback, log line or error
    # message that happens to include an ImapConfig. It is not a default
    # value, so it does not affect dataclass field ordering.
    password: str = field(repr=False)


def connect(config: ImapConfig) -> imaplib.IMAP4_SSL:
    conn = imaplib.IMAP4_SSL(config.host, config.port)
    conn.login(config.email, config.password)
    return conn


def build_from_query(from_domains: list[str]) -> bytes:
    """Build an IMAP SEARCH criteria string matching any of the given
    sender domains. A single domain is `(FROM "domain")`; more are OR'd:
    `(OR (FROM "a") (OR (FROM "b") (FROM "c")))`.
    """
    if not from_domains:
        raise ValueError("from_domains must be non-empty")
    terms = [f'(FROM "{d}")' for d in from_domains]
    query = terms[-1]
    for term in reversed(terms[:-1]):
        query = f"(OR {term} {query})"
    return query.encode()


def build_since_criterion(since: date) -> bytes:
    """IMAP's SINCE search key wants DD-Mon-YYYY (e.g. 01-Jan-2024), not
    ISO format."""
    return f'(SINCE "{since.strftime("%d-%b-%Y")}")'.encode()


def search_uids(conn: imaplib.IMAP4_SSL, mailbox: str, from_domains: list[str],
                 since: date | None = None) -> list[bytes]:
    """Search for messages from any of from_domains, optionally narrowed to
    only messages received on/after `since`. IMAP SEARCH ANDs multiple
    criteria passed as separate arguments — without `since`, this is
    unfiltered by date exactly as before, which can match years of
    unrelated mail (alerts, OTPs, promos) from a long-lived bank sender,
    not just statements. Narrowing with `since` also matters in practice:
    fetching thousands of messages over one IMAP connection can exhaust
    Gmail's per-connection limits and drop the connection.
    """
    conn.select(mailbox, readonly=True)
    criteria = [build_from_query(from_domains)]
    if since is not None:
        criteria.append(build_since_criterion(since))
    status, data = conn.search(None, *criteria)
    if status != "OK":
        raise RuntimeError(f"IMAP search failed: {status}")
    if not data or not data[0]:
        return []
    return data[0].split()

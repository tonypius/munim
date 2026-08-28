"""IMAP connection and search for bank statement emails. Standard library
only (imaplib) — no OAuth, no external API, just IMAP + an app password.
"""
from __future__ import annotations

import imaplib
from dataclasses import dataclass, field


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


def search_uids(conn: imaplib.IMAP4_SSL, mailbox: str, from_domains: list[str]) -> list[bytes]:
    conn.select(mailbox, readonly=True)
    query = build_from_query(from_domains)
    status, data = conn.search(None, query)
    if status != "OK":
        raise RuntimeError(f"IMAP search failed: {status}")
    if not data or not data[0]:
        return []
    return data[0].split()

"""Extract matching attachments from a raw RFC822 email message and save
them safely to a local folder.
"""
from __future__ import annotations

import email
from pathlib import Path


def extract_attachments(raw_message: bytes, extensions: list[str]) -> list[tuple[str, bytes]]:
    """Returns [(filename, content_bytes), ...] for every attachment whose
    filename ends with one of the given extensions (case-insensitive).
    """
    msg = email.message_from_bytes(raw_message)
    found = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        if not filename:
            continue
        if any(filename.lower().endswith(ext.lower()) for ext in extensions):
            payload = part.get_payload(decode=True)
            if payload:
                found.append((filename, payload))
    return found


def _pick_dest(out_dir: Path, safe_name: str, content: bytes, used: set[str]) -> Path:
    """Choose a destination path for `content` that will not clobber a
    different file, trying "Statement.csv", "Statement (2).csv", ... in
    turn.

    A candidate is rejected if it was already claimed earlier in this call,
    or if a *different* file already sits there on disk. A file already on
    disk with byte-identical content is accepted: that is the same
    attachment from an earlier run, so re-fetching stays idempotent rather
    than piling up endless copies.

    In-call keys are compared case-insensitively so two attachments
    differing only in case cannot clobber each other on a case-insensitive
    filesystem (macOS, Windows).
    """
    stem = Path(safe_name).stem
    suffix = Path(safe_name).suffix
    counter = 1
    while True:
        candidate = safe_name if counter == 1 else f"{stem} ({counter}){suffix}"
        key = candidate.casefold()
        counter += 1
        if key in used:
            continue
        dest = out_dir / candidate
        if dest.exists() and not (dest.is_file() and dest.read_bytes() == content):
            continue
        used.add(key)
        return dest


def save_attachments(attachments: list[tuple[str, bytes]], out_dir: Path) -> list[Path]:
    """Saves each attachment into out_dir, stripping any path components
    from the filename first — an email attachment's filename is untrusted
    input and must never be used to write outside out_dir.

    Attachments that would share a destination filename are disambiguated
    ("Statement.csv", "Statement (2).csv", ...) rather than silently
    overwriting one another; bank statements very commonly all carry the
    same name, and the caller invokes this once per message, so collisions
    are resolved against what is already on disk as well as against names
    claimed within this call.

    The returned list is the real set of files written, so callers can use
    len() of it as an accurate "downloaded" count.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    used: set[str] = set()
    for filename, content in attachments:
        safe_name = Path(filename).name
        # Skip attachments whose filename sanitizes to nothing usable or to ".."
        if not safe_name or safe_name in (".", ".."):
            continue
        dest = _pick_dest(out_dir, safe_name, content, used)
        dest.write_bytes(content)
        saved.append(dest)
    return saved

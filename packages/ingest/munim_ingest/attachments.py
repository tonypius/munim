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


def save_attachments(attachments: list[tuple[str, bytes]], out_dir: Path) -> list[Path]:
    """Saves each attachment into out_dir, stripping any path components
    from the filename first — an email attachment's filename is untrusted
    input and must never be used to write outside out_dir.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for filename, content in attachments:
        safe_name = Path(filename).name
        # Skip attachments whose filename sanitizes to nothing usable or to ".."
        if not safe_name or safe_name in (".", ".."):
            continue
        dest = out_dir / safe_name
        dest.write_bytes(content)
        saved.append(dest)
    return saved

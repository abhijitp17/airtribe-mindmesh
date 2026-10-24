"""Upload safety checks beyond the magic-byte type check in the routers.

* content_disposition: a header-safe filename (RFC 6266/5987). Raw names broke the
  download for any non-Latin-1 filename (500) and let a quote end the parameter.
* check_zip_container: DOCX files are zips; refuse archives that would expand past
  sane limits before python-docx loads every part into memory. PDFs are covered by
  pypdf's own 75 MB decompression cap and MAX_PAGES.
* scan: optional malware scanning through a ClamAV daemon (UPLOAD_SCAN=clamd). When
  configured it fails closed: if clamd can't be reached, the upload is refused.

No FastAPI/SQLAlchemy imports, so it is unit-testable on its own.
"""
from __future__ import annotations

import io
import os
import socket
import struct
import unicodedata
import zipfile
from dataclasses import dataclass
from urllib.parse import quote

MAX_ZIP_ENTRIES = 2_000
MAX_ZIP_UNCOMPRESSED = 50 * 1024 * 1024  # a long resume DOCX is well under 5 MB expanded


@dataclass
class UploadRejected(Exception):
    status: int  # HTTP status the router should return
    message: str  # user-facing

    def __str__(self) -> str:
        return self.message


def content_disposition(filename: str, disposition: str = "inline") -> str:
    """`inline; filename="ascii fallback"; filename*=UTF-8''percent-encoded` for any filename."""
    name = (filename or "document.pdf").replace("\r", " ").replace("\n", " ")
    fallback = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    fallback = "".join(c for c in fallback if c.isprintable() and c not in '"\\').strip() or "document.pdf"
    if "." not in fallback and "." in name:
        fallback += "." + name.rsplit(".", 1)[1].encode("ascii", "ignore").decode("ascii")
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


def check_zip_container(data: bytes, max_entries: int = MAX_ZIP_ENTRIES, max_total: int = MAX_ZIP_UNCOMPRESSED) -> None:
    """Refuse zip bombs. Declared sizes bound what zipfile will actually read."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise UploadRejected(422, "Could not read this file. Re-save it from Word or paste the text instead.") from exc
    if len(infos) > max_entries or sum(i.file_size for i in infos) > max_total:
        raise UploadRejected(422, "This file is too large once unpacked. Re-save it from Word or paste the text instead.")


# ---------------------------------------------------------------- malware scanning

def scan(data: bytes) -> None:
    """Raise UploadRejected if the configured scanner flags the file or can't be reached."""
    mode = os.getenv("UPLOAD_SCAN", "off").strip().lower()
    if mode in ("", "off", "none"):
        return
    if mode != "clamd":
        raise UploadRejected(503, "File scanning is misconfigured, so uploads are paused. Please try again later.")
    host = os.getenv("CLAMD_HOST", "localhost")
    port = int(os.getenv("CLAMD_PORT", "3310"))
    try:
        verdict = clamd_instream(data, host, port, timeout=float(os.getenv("CLAMD_TIMEOUT", "30")))
    except OSError as exc:
        raise UploadRejected(503, "We couldn't check this file for viruses right now. Please try again in a few minutes.") from exc
    if verdict.endswith("FOUND"):
        raise UploadRejected(422, "This file was flagged by our virus scanner, so we didn't keep it.")
    if not verdict.endswith("OK"):
        raise UploadRejected(503, "We couldn't check this file for viruses right now. Please try again in a few minutes.")


def clamd_instream(data: bytes, host: str, port: int, timeout: float = 30.0, chunk: int = 64 * 1024) -> str:
    """ClamAV INSTREAM protocol: returns clamd's reply, e.g. 'stream: OK' or 'stream: Eicar-Signature FOUND'."""
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(b"zINSTREAM\0")
        for i in range(0, len(data), chunk):
            part = data[i:i + chunk]
            s.sendall(struct.pack("!L", len(part)) + part)
        s.sendall(struct.pack("!L", 0))
        reply = b""
        while not reply.endswith(b"\0"):
            got = s.recv(4096)
            if not got:
                break
            reply += got
    return reply.rstrip(b"\0").decode("utf-8", "replace").strip()

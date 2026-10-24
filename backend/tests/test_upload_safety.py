"""Upload hardening (app/core/upload_safety.py and the upload routes)."""
import io
import os
import socket
import struct
import tempfile
import threading
import zipfile

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{tmp}/test_uploads.db",
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.upload_safety import UploadRejected, check_zip_container, content_disposition, scan  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _signup(client, email):
    r = client.post("/api/auth/signup", json={"email": email, "password": "correct-horse-1"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ---------------------------------------------------------------- filenames

@pytest.mark.parametrize("name", ["इतिहास.pdf", "履歴書.pdf", 'a"; filename="evil.exe.pdf', "line\r\nX-Injected: 1.pdf", "résumé.pdf"])
def test_content_disposition_is_header_safe(name):
    value = content_disposition(name)
    value.encode("latin-1")  # must not raise
    assert "\r" not in value and "\n" not in value
    assert value.startswith('inline; filename="') and "filename*=UTF-8''" in value
    fallback = value.split('filename="', 1)[1].split('"', 1)[0]
    assert '"' not in fallback and fallback.endswith(".pdf")


def test_original_pdf_download_works_for_non_latin_filenames(client, sample_pdf):
    """Regression: Content-Disposition used the raw name, so this returned 500."""
    h = _signup(client, "names@example.com")
    doc = client.post("/api/documents?rights_confirmed=true", headers=h,
                      files={"file": ("इतिहास.pdf", sample_pdf, "application/pdf")}).json()
    r = client.get(f"/api/documents/{doc['id']}/file", headers=h)
    assert r.status_code == 200 and r.content == sample_pdf
    assert "filename*=UTF-8''%E0%A4%87" in r.headers["content-disposition"]


# ---------------------------------------------------------------- zip bombs

def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_zip_limits():
    check_zip_container(_zip({"word/document.xml": b"<w/>" * 1000}))  # normal
    bomb = _zip({"word/document.xml": b"\0" * (60 * 1024 * 1024)})  # 60 MB of zeros compresses to ~60 KB
    assert len(bomb) < 200_000
    with pytest.raises(UploadRejected, match="too large once unpacked"):
        check_zip_container(bomb)
    with pytest.raises(UploadRejected, match="too large once unpacked"):
        check_zip_container(_zip({f"f{i}": b"" for i in range(2_001)}))
    with pytest.raises(UploadRejected, match="Could not read"):
        check_zip_container(b"PK\x03\x04 not really a zip")


def test_docx_resume_bomb_is_refused_before_parsing(client):
    h = _signup(client, "bomb@example.com")
    bomb = _zip({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"\0" * (60 * 1024 * 1024)})
    r = client.post("/api/interview/resumes", headers=h,
                    files={"file": ("cv.docx", bomb, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.status_code == 422 and "too large once unpacked" in r.text


# ---------------------------------------------------------------- malware scanning

class FakeClamd:
    """Speaks just enough of clamd's INSTREAM protocol; records what it received."""

    def __init__(self, reply: bytes):
        self.reply = reply
        self.received = b""
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _read(self, conn, n):
        buf = b""
        while len(buf) < n:
            buf += conn.recv(n - len(buf))
        return buf

    def _serve(self):
        conn, _ = self.sock.accept()
        with conn:
            assert self._read(conn, 10) == b"zINSTREAM\0"
            while True:
                (size,) = struct.unpack("!L", self._read(conn, 4))
                if size == 0:
                    break
                self.received += self._read(conn, size)
            conn.sendall(self.reply + b"\0")
        self.sock.close()


def test_scan_is_off_by_default(monkeypatch):
    monkeypatch.delenv("UPLOAD_SCAN", raising=False)
    scan(b"anything")


def test_scan_passes_clean_files_and_streams_all_bytes(monkeypatch):
    clamd = FakeClamd(b"stream: OK")
    monkeypatch.setenv("UPLOAD_SCAN", "clamd")
    monkeypatch.setenv("CLAMD_HOST", "127.0.0.1")
    monkeypatch.setenv("CLAMD_PORT", str(clamd.port))
    data = os.urandom(200_000)  # several 64 KB chunks
    scan(data)
    assert clamd.received == data


def test_infected_upload_is_refused_and_not_stored(client, sample_pdf, monkeypatch):
    clamd = FakeClamd(b"stream: Eicar-Test-Signature FOUND")
    monkeypatch.setenv("UPLOAD_SCAN", "clamd")
    monkeypatch.setenv("CLAMD_HOST", "127.0.0.1")
    monkeypatch.setenv("CLAMD_PORT", str(clamd.port))
    h = _signup(client, "virus@example.com")
    r = client.post("/api/documents?rights_confirmed=true", headers=h, files={"file": ("x.pdf", sample_pdf, "application/pdf")})
    assert r.status_code == 422 and "virus scanner" in r.text
    assert client.get("/api/documents", headers=h).json() == []


@pytest.mark.parametrize("mode", ["clamd", "sophos"])
def test_scan_fails_closed(monkeypatch, mode):
    monkeypatch.setenv("UPLOAD_SCAN", mode)
    monkeypatch.setenv("CLAMD_HOST", "127.0.0.1")
    monkeypatch.setenv("CLAMD_PORT", "1")  # nothing listens here
    with pytest.raises(UploadRejected) as e:
        scan(b"data")
    assert e.value.status == 503

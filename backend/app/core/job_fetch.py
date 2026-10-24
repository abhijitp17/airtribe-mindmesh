"""Fetch a job ad from a link and turn it into plain text (gap report "From a link").

The server fetches a URL the visitor typed, so this is an SSRF surface. Rules:
- http/https only, default ports only, no credentials in the URL.
- Every address the host resolves to must be public (no loopback, private, link-local,
  carrier-grade NAT, multicast or reserved ranges, including IPv4-mapped IPv6).
- The connection goes to the address we checked (the host name is kept for the Host header
  and TLS SNI/certificate checks), so DNS can't be swapped between the check and the fetch.
- Redirects are followed by hand, at most 3, and each hop is checked the same way.
- Small time and size limits; only HTML or plain text is read.

Job sites that need JavaScript or a sign-in return little text; the caller tells the user to
paste the ad instead. Structured data (schema.org JobPosting in JSON-LD) is preferred when present.
Nothing here logs the URL (it can carry tracking or personal query strings).
"""
from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable, Iterable
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
TIMEOUT = httpx.Timeout(6.0, connect=4.0)
MIN_CHARS, MAX_CHARS = 200, 20_000
MAX_URL_CHARS = 2048
USER_AGENT = "MindmeshJobImport/1.0 (+https://mindmesh.app; fetches one page a visitor asked for)"
_TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")

Resolver = Callable[[str, int], Iterable[str]]


class JobFetchError(Exception):
    """A user-safe message: shown as-is in the 422 response."""


@dataclass
class JobPage:
    text: str
    title: str | None = None
    company: str | None = None


# ---------------------------------------------------------------- address checks

def _default_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def is_public_address(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def check_url(url: str) -> tuple[str, str, int]:
    """(scheme, host, port) for an acceptable URL, else JobFetchError."""
    url = url.strip()
    if not url or len(url) > MAX_URL_CHARS:
        raise JobFetchError("That link doesn't look right. Paste the full address, starting with https://.")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        raise JobFetchError("That link doesn't look right. Paste the full address, starting with https://.")
    if parts.username or parts.password:
        raise JobFetchError("Links with a user name or password in them can't be imported.")
    try:
        port = parts.port
    except ValueError as exc:
        raise JobFetchError("That link doesn't look right. Paste the full address, starting with https://.") from exc
    default = 443 if scheme == "https" else 80
    if port not in (None, default):
        raise JobFetchError("We can only import from ordinary web addresses (no custom ports).")
    return scheme, parts.hostname.lower().rstrip("."), default


def _pick_address(host: str, port: int, resolve: Resolver) -> str:
    try:
        ipaddress.ip_address(host)
        addrs = [host]  # a literal address: still has to be public
    except ValueError:
        try:
            addrs = list(dict.fromkeys(resolve(host, port)))
        except (OSError, UnicodeError) as exc:
            raise JobFetchError("We couldn't find that website. Check the link, or paste the job ad instead.") from exc
    if not addrs or not all(is_public_address(a) for a in addrs):
        raise JobFetchError("That address can't be imported. Paste the job ad text instead.")
    return addrs[0]


# ---------------------------------------------------------------- fetching

def fetch_job_page(url: str, *, resolve: Resolver = _default_resolver,
                   transport: httpx.BaseTransport | None = None) -> JobPage:
    """Fetch and extract a job ad. Raises JobFetchError with a message fit for the user."""
    current = url.strip()
    with httpx.Client(transport=transport, timeout=TIMEOUT, follow_redirects=False, trust_env=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            scheme, host, port = check_url(current)
            addr = _pick_address(host, port, resolve)
            parts = urlsplit(current)
            netloc = f"[{addr}]" if ":" in addr else addr
            target = parts._replace(scheme=scheme, netloc=f"{netloc}:{port}", fragment="").geturl()
            headers = {"Host": host, "User-Agent": USER_AGENT,
                       "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8", "Accept-Language": "en"}
            try:
                with client.stream("GET", target, headers=headers, extensions={"sni_hostname": host}) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("location")
                        if not loc:
                            raise JobFetchError("That page didn't load. Paste the job ad text instead.")
                        current = urljoin(current, loc)
                        continue
                    if resp.status_code in (401, 403):
                        raise JobFetchError("That site needs you to sign in to see the job. Paste the job ad text instead.")
                    if resp.status_code == 404:
                        raise JobFetchError("That page wasn't found. The job may have closed; check the link.")
                    if resp.status_code >= 400:
                        raise JobFetchError("That page didn't load. Paste the job ad text instead.")
                    ctype = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if ctype and ctype not in _TEXT_TYPES:
                        raise JobFetchError("That link isn't a web page (it may be a PDF or a file). Paste the job ad text instead.")
                    body = _read_capped(resp)
                    charset = resp.charset_encoding or "utf-8"
            except httpx.TimeoutException as exc:
                raise JobFetchError("That site took too long to answer. Try again, or paste the job ad text.") from exc
            except httpx.HTTPError as exc:
                raise JobFetchError("We couldn't reach that site. Check the link, or paste the job ad text.") from exc
            try:
                raw = body.decode(charset, errors="replace")
            except LookupError:
                raw = body.decode("utf-8", errors="replace")
            page = extract_job(raw) if ctype != "text/plain" else JobPage(text=_tidy(raw))
            if len(page.text) < MIN_CHARS:
                raise JobFetchError("We couldn't read the job ad on that page (some sites need JavaScript or a sign-in). "
                                    "Paste the job ad text instead.")
            page.text = page.text[:MAX_CHARS]
            return page
    raise JobFetchError("That link redirected too many times. Paste the job ad text instead.")


def _read_capped(resp: httpx.Response) -> bytes:
    declared = resp.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        raise JobFetchError("That page is too large to import. Paste the job ad text instead.")
    buf = bytearray()
    for chunk in resp.iter_bytes():
        buf.extend(chunk)
        if len(buf) > MAX_BYTES:
            raise JobFetchError("That page is too large to import. Paste the job ad text instead.")
    return bytes(buf)


# ---------------------------------------------------------------- extraction

_SKIP = {"script", "style", "noscript", "svg", "template", "nav", "header", "footer", "form", "iframe", "button", "select"}
_BLOCK = {"p", "div", "section", "article", "main", "br", "tr", "table", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
          "dl", "dt", "dd", "blockquote", "pre", "hr", "aside"}
_VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source", "track", "wbr"}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.title: list[str] = []
        self.in_title = False
        self.in_ld = False
        self.ld: list[str] = []
        self.ld_blocks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type", "").lower() == "application/ld+json":
            self.in_ld, self.ld = True, []
            return
        if tag in _SKIP and tag not in _VOID:
            self.skip += 1
        elif tag == "title":
            self.in_title = True
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in _BLOCK:
            self.out.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in ("br", "hr"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag == "script" and self.in_ld:
            self.in_ld = False
            self.ld_blocks.append("".join(self.ld))
            return
        if tag in _SKIP and self.skip:
            self.skip -= 1
        elif tag == "title":
            self.in_title = False
        elif tag in _BLOCK or tag == "li":
            self.out.append("\n")

    def handle_data(self, data):
        if self.in_ld:
            self.ld.append(data)
        elif self.in_title:
            self.title.append(data)
        elif not self.skip:
            self.out.append(data)


def html_to_text(markup: str) -> str:
    p = _TextParser()
    p.feed(markup)
    p.close()
    return _tidy("".join(p.out))


def _tidy(text: str) -> str:
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.replace("\r", "").split("\n")]
    out: list[str] = []
    for ln in lines:
        if ln in ("", "-"):
            if out and out[-1] != "":
                out.append("")
            continue
        out.append(ln)
    return "\n".join(out).strip()


def _job_postings(node) -> Iterable[dict]:
    if isinstance(node, list):
        for item in node:
            yield from _job_postings(item)
    elif isinstance(node, dict):
        kind = node.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "JobPosting" in kinds:
            yield node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                yield from _job_postings(node[key])


def _name(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("name")
    if isinstance(value, str) and value.strip():
        return html.unescape(value.strip())[:200]
    return None


def extract_job(markup: str) -> JobPage:
    """Prefer schema.org JobPosting data; fall back to the page's visible text."""
    p = _TextParser()
    p.feed(markup)
    p.close()
    for block in p.ld_blocks:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for posting in _job_postings(data):
            desc = posting.get("description")
            if not isinstance(desc, str):
                continue
            body = html_to_text(html.unescape(desc) if "&lt;" in desc else desc)
            title, company = _name(posting.get("title")), _name(posting.get("hiringOrganization"))
            head = "\n".join(x for x in (title, f"Company: {company}" if company else None) if x)
            text = f"{head}\n\n{body}".strip() if head else body
            if len(text) >= MIN_CHARS:
                return JobPage(text=text, title=title, company=company)
    title = _name("".join(p.title))
    return JobPage(text=_tidy("".join(p.out)), title=title)

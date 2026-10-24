"""Job ad import from a link: SSRF rules, redirects, limits, extraction, and the public endpoint."""
import json
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update({
    "APP_ENV": "test",
    "DATABASE_URL": f"sqlite:///{tmp}/test_job_fetch.db",
    "STORAGE_DIR": f"{tmp}/uploads",
    "AI_PROVIDER": "mock",
})

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import job_fetch as jf  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import public as public_router  # noqa: E402
from app.services import public_report  # noqa: E402

PUBLIC_IP = "93.184.215.14"
REQS = ["Lead a team of four analysts and set analytics priorities with supply chain leadership.",
        "Build demand forecasting models that drive inventory decisions.",
        "5+ years of experience with SQL and Python; strong statistical modelling.",
        "Excellent stakeholder management and communication skills."]
PAGE = f"""<!doctype html><html><head><title>Analytics Manager | Fabrikam</title>
<style>.x{{color:red}}</style><script>var tracking = "secret";</script></head>
<body><nav>Home Jobs About</nav><header>Fabrikam careers</header>
<main><h1>Analytics Manager</h1><p>Fabrikam Foods is hiring.</p><ul>{''.join(f'<li>{r}</li>' for r in REQS)}</ul></main>
<footer>Cookie settings</footer></body></html>"""


def resolver(mapping):
    def resolve(host, port):
        if host not in mapping:
            raise OSError("no such host")
        return mapping[host]
    return resolve


def html_response(body=PAGE, status=200, ctype="text/html; charset=utf-8", headers=None):
    return httpx.Response(status, headers={"content-type": ctype, **(headers or {})}, content=body.encode())


# ---------------------------------------------------------------- URL and address rules

@pytest.mark.parametrize("url", ["ftp://jobs.example.com/1", "file:///etc/passwd", "jobs.example.com/1", "https://",
                                 "javascript:alert(1)", "https://user:pw@jobs.example.com/1",
                                 "https://jobs.example.com:8443/1", "http://jobs.example.com:22/"])
def test_bad_urls_are_refused(url):
    with pytest.raises(jf.JobFetchError):
        jf.check_url(url)


@pytest.mark.parametrize("addr", ["127.0.0.1", "10.0.0.5", "172.16.3.4", "192.168.1.1", "169.254.169.254", "100.64.0.1",
                                  "0.0.0.0", "224.0.0.1", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1",
                                  "::ffff:169.254.169.254", "not-an-ip"])
def test_non_public_addresses(addr):
    assert not jf.is_public_address(addr)


def test_public_addresses():
    assert jf.is_public_address(PUBLIC_IP)
    assert jf.is_public_address("2606:4700:4700::1111")


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/latest/meta-data/"])
def test_literal_private_addresses_never_fetched(url):
    def handler(request):  # pragma: no cover - must not be reached
        raise AssertionError("fetched a private address")
    with pytest.raises(jf.JobFetchError, match="can't be imported"):
        jf.fetch_job_page(url, resolve=resolver({}), transport=httpx.MockTransport(handler))


def test_host_resolving_to_any_private_address_is_refused():
    resolve = resolver({"jobs.example.com": [PUBLIC_IP, "10.1.2.3"]})
    with pytest.raises(jf.JobFetchError, match="can't be imported"):
        jf.fetch_job_page("https://jobs.example.com/1", resolve=resolve,
                          transport=httpx.MockTransport(lambda r: html_response()))


def test_unknown_host():
    with pytest.raises(jf.JobFetchError, match="couldn't find"):
        jf.fetch_job_page("https://nope.example.com/1", resolve=resolver({}),
                          transport=httpx.MockTransport(lambda r: html_response()))


def test_connects_to_checked_address_with_host_and_sni():
    seen = {}

    def handler(request):
        seen.update(host=request.url.host, scheme=request.url.scheme, port=request.url.port, header=request.headers["host"],
                    sni=request.extensions.get("sni_hostname"), path=request.url.raw_path)
        return html_response()

    page = jf.fetch_job_page("https://Jobs.Example.com/roles/42?ref=abc#apply",
                             resolve=resolver({"jobs.example.com": [PUBLIC_IP]}), transport=httpx.MockTransport(handler))
    # port None = the scheme default (443); httpx normalises it away
    assert seen == {"host": PUBLIC_IP, "scheme": "https", "port": None, "header": "jobs.example.com", "sni": "jobs.example.com",
                    "path": b"/roles/42?ref=abc"}
    assert "Analytics Manager" in page.text


# ---------------------------------------------------------------- redirects, status, limits

def test_redirect_to_private_address_is_refused():
    def handler(request):
        if request.headers["host"] == "jobs.example.com":
            return httpx.Response(302, headers={"location": "http://internal.example.com/admin"})
        raise AssertionError("followed a redirect to a private address")  # pragma: no cover
    resolve = resolver({"jobs.example.com": [PUBLIC_IP], "internal.example.com": ["10.0.0.7"]})
    with pytest.raises(jf.JobFetchError, match="can't be imported"):
        jf.fetch_job_page("https://jobs.example.com/1", resolve=resolve, transport=httpx.MockTransport(handler))


def test_relative_redirect_is_followed():
    def handler(request):
        if request.url.raw_path == b"/old":
            return httpx.Response(301, headers={"location": "/new"})
        return html_response()
    page = jf.fetch_job_page("https://jobs.example.com/old", resolve=resolver({"jobs.example.com": [PUBLIC_IP]}),
                             transport=httpx.MockTransport(handler))
    assert "demand forecasting" in page.text


def test_redirect_loop_stops():
    transport = httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": "/again"}))
    with pytest.raises(jf.JobFetchError, match="too many times"):
        jf.fetch_job_page("https://jobs.example.com/1", resolve=resolver({"jobs.example.com": [PUBLIC_IP]}),
                          transport=transport)


@pytest.mark.parametrize("status, msg", [(403, "sign in"), (401, "sign in"), (404, "wasn't found"), (500, "didn't load")])
def test_error_statuses(status, msg):
    transport = httpx.MockTransport(lambda r: html_response(status=status))
    with pytest.raises(jf.JobFetchError, match=msg):
        jf.fetch_job_page("https://jobs.example.com/1", resolve=resolver({"jobs.example.com": [PUBLIC_IP]}),
                          transport=transport)


def test_non_text_content_is_refused():
    transport = httpx.MockTransport(lambda r: html_response(ctype="application/pdf"))
    with pytest.raises(jf.JobFetchError, match="isn't a web page"):
        jf.fetch_job_page("https://jobs.example.com/1.pdf", resolve=resolver({"jobs.example.com": [PUBLIC_IP]}),
                          transport=transport)


def test_oversized_page_is_refused(monkeypatch):
    monkeypatch.setattr(jf, "MAX_BYTES", 1000)
    transport = httpx.MockTransport(lambda r: html_response(body="<p>" + "x" * 5000 + "</p>"))
    with pytest.raises(jf.JobFetchError, match="too large"):
        jf.fetch_job_page("https://jobs.example.com/1", resolve=resolver({"jobs.example.com": [PUBLIC_IP]}),
                          transport=transport)


def test_timeout_message():
    def handler(request):
        raise httpx.ConnectTimeout("slow", request=request)
    with pytest.raises(jf.JobFetchError, match="too long"):
        jf.fetch_job_page("https://jobs.example.com/1", resolve=resolver({"jobs.example.com": [PUBLIC_IP]}),
                          transport=httpx.MockTransport(handler))


def test_javascript_only_page_asks_for_paste():
    shell = "<html><body><div id=root></div><script>render()</script></body></html>"
    with pytest.raises(jf.JobFetchError, match="Paste the job ad text"):
        jf.fetch_job_page("https://jobs.example.com/1", resolve=resolver({"jobs.example.com": [PUBLIC_IP]}),
                          transport=httpx.MockTransport(lambda r: html_response(body=shell)))


# ---------------------------------------------------------------- extraction

def test_visible_text_skips_scripts_nav_and_footer():
    page = jf.extract_job(PAGE)
    assert page.title == "Analytics Manager | Fabrikam"
    assert "tracking" not in page.text and "Cookie settings" not in page.text and "Home Jobs" not in page.text
    assert "color:red" not in page.text
    for r in REQS:
        assert f"- {r}" in page.text


def test_json_ld_job_posting_is_preferred():
    posting = {"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, {
        "@type": "JobPosting", "title": "Analytics Manager - Supply Chain",
        "hiringOrganization": {"@type": "Organization", "name": "Fabrikam Foods"},
        "description": "&lt;p&gt;Responsibilities&lt;/p&gt;&lt;ul&gt;" + "".join(f"&lt;li&gt;{r}&lt;/li&gt;" for r in REQS) + "&lt;/ul&gt;"}]}
    markup = f'<html><head><script type="application/ld+json">{json.dumps(posting)}</script></head><body><p>Apply now</p></body></html>'
    page = jf.extract_job(markup)
    assert page.title == "Analytics Manager - Supply Chain" and page.company == "Fabrikam Foods"
    assert page.text.startswith("Analytics Manager - Supply Chain\nCompany: Fabrikam Foods")
    assert f"- {REQS[1]}" in page.text and "Apply now" not in page.text


def test_broken_json_ld_falls_back_to_page_text():
    markup = '<script type="application/ld+json">{not json</script>' + PAGE
    assert REQS[0] in jf.extract_job(markup).text


def test_plain_text_page():
    body = "\n".join(REQS) * 2
    page = jf.fetch_job_page("https://jobs.example.com/1.txt", resolve=resolver({"jobs.example.com": [PUBLIC_IP]}),
                             transport=httpx.MockTransport(lambda r: html_response(body=body, ctype="text/plain")))
    assert page.text.startswith(REQS[0])


def test_text_is_capped(monkeypatch):
    monkeypatch.setattr(jf, "MAX_CHARS", 300)
    page = jf.fetch_job_page("https://jobs.example.com/1", resolve=resolver({"jobs.example.com": [PUBLIC_IP]}),
                             transport=httpx.MockTransport(lambda r: html_response()))
    assert len(page.text) == 300


# ---------------------------------------------------------------- endpoint

@pytest.fixture
def client():
    public_report.job_url_limiter.reset()
    with TestClient(app) as c:
        yield c


def test_endpoint_returns_text(client, monkeypatch):
    monkeypatch.setattr(public_router, "fetch_job_page",
                        lambda url: jf.JobPage(text="x" * 250, title="Analytics Manager", company="Fabrikam"))
    r = client.post("/api/public/job-from-url", json={"url": "https://jobs.example.com/1"})
    assert r.status_code == 200
    assert r.json() == {"text": "x" * 250, "title": "Analytics Manager", "company": "Fabrikam"}


def test_endpoint_refusal_is_422_with_message(client):
    r = client.post("/api/public/job-from-url", json={"url": "http://127.0.0.1/admin"})
    assert r.status_code == 422
    assert "can't be imported" in r.json()["detail"]


def test_endpoint_rate_limited(client, monkeypatch):
    monkeypatch.setattr(public_router, "fetch_job_page", lambda url: jf.JobPage(text="x" * 250))
    codes = [client.post("/api/public/job-from-url", json={"url": "https://jobs.example.com/1"}).status_code
             for _ in range(public_report.JOB_URL_PER_IP_PER_HOUR + 1)]
    assert codes[:-1] == [200] * public_report.JOB_URL_PER_IP_PER_HOUR
    assert codes[-1] == 429

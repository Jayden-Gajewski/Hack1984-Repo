"""Reads a page straight from a website, for the browser extension's privacy-policy check.

No search API is involved. site_policy.py only fetches pages on the site the user is visiting,
and passes `stay_within` so a redirect can't take the request to another site either. Every hop
goes through outbound.request (service "website") and shows in the outbound log. No stored
cookies are sent.

The URLs come from web pages, so they're untrusted:
- Only https on a public hostname and the default port is fetched. No localhost, IP addresses,
  single-label, .local or reserved names (.test, .invalid), and no user:password@. An http link
  is upgraded to https. Hostnames aren't resolved here, so this relies on the certificate check
  to keep a hostile link off devices on the local network: they can't show a valid certificate
  for a public name.
- The query string and fragment are dropped: a policy doesn't need them, and a link on a
  logged-in page can carry an account id or an email address.
- Redirects are followed by hand, at most MAX_REDIRECTS, and each hop is checked again.
- Only HTML or plain text is read, at most MAX_BYTES of it, with TOTAL_SECONDS per hop and
  at most CONCURRENT fetches at once.
"""

import asyncio
import ipaddress
import re
from collections.abc import Callable
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from app.outbound import request

MAX_REDIRECTS = 4
MAX_BYTES = 2_000_000
TIMEOUT = 15.0  # seconds to connect, and between reads
TOTAL_SECONDS = 30.0  # per hop, start to finish, so a page that never ends can't hang the check
CONCURRENT = 4
_PRIVATE_SUFFIXES = (
    ".localhost", ".local", ".localdomain", ".internal", ".lan", ".home", ".home.arpa", ".corp",
    ".intranet", ".test", ".invalid",
)
_TLD = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}")  # "127.1" or "0x7f.1" are addresses, not names
_TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
_ACCEPT = "text/html,application/xhtml+xml;q=0.9,text/plain;q=0.8"
_slots: asyncio.Semaphore | None = None


class PageError(Exception):
    """The page couldn't be read. The message is shown to the user."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status  # the site's HTTP status, when it answered with an error


def public_host(host: str) -> bool:
    """True for a public website's hostname: not this machine, an IP address or a local name."""
    host = host.strip("[]").rstrip(".").lower()
    if "." not in host or host == "localhost" or host.endswith(_PRIVATE_SUFFIXES):
        return False
    try:
        ipaddress.ip_address(host)
        return False  # a bare IP address, not a website
    except ValueError:
        pass
    return bool(_TLD.fullmatch(host.rsplit(".", 1)[1]))


def public_https(url: str) -> str | None:
    """`url` as a clean https URL if it's safe to fetch (see the module docstring), else None."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname or "@" in parts.netloc:
        return None
    if port not in (None, {"http": 80, "https": 443}[parts.scheme]):
        return None
    if not public_host(parts.hostname):
        return None
    return urlunsplit(("https", parts.hostname.rstrip("."), parts.path or "/", "", ""))


class _TextParser(HTMLParser):
    """Visible text, one line per block element. Scripts, styles and the <title> are skipped.
    Line breaks in the HTML source are spaces, as in a browser (except in <pre>): many sites wrap
    their source mid-sentence, and keeping those breaks cut "We don't sell your data to third /
    parties" in two."""

    SKIP = {"script", "style", "noscript", "template", "svg", "title", "iframe", "canvas", "select", "textarea"}
    BLOCK = {
        "address", "article", "aside", "blockquote", "br", "caption", "dd", "details", "div", "dl",
        "dt", "figcaption", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr",
        "li", "main", "nav", "ol", "p", "pre", "section", "summary", "table", "td", "th", "tr", "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0
        self.pre = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.SKIP:
            self.skipping += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
            self.pre += tag == "pre"

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")
            if tag == "pre":
                self.pre = max(0, self.pre - 1)

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.parts.append(data if self.pre else re.sub(r"\s+", " ", data))


def html_to_text(html: str) -> str:
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def _concurrency() -> asyncio.Semaphore:
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(CONCURRENT)
    return _slots


async def read_page(
    url: str, *, purpose: str, stay_within: Callable[[str], bool] | None = None
) -> tuple[str, str]:
    """Return (final URL, readable text) for a page on a public site. Raises PageError.
    `stay_within(host)` must be true for every hop, redirects included, when it's given."""
    current = public_https(url)
    if current is None:
        raise PageError("That link isn't a public https page, so it wasn't opened.")
    async with _concurrency():
        for _ in range(MAX_REDIRECTS + 1):
            host = urlsplit(current).hostname or ""
            if stay_within and not stay_within(host):
                raise PageError(f"The policy is on another site ({host}), so it wasn't opened automatically.")
            try:
                res = await asyncio.wait_for(
                    request(
                        "website",
                        "GET",
                        current,
                        purpose=purpose,
                        headers={"Accept": _ACCEPT, "Accept-Language": "en"},
                        timeout=TIMEOUT,
                        send_cookies=False,
                        max_bytes=MAX_BYTES,
                    ),
                    TOTAL_SECONDS,
                )
            except TimeoutError:
                raise PageError(f"{host} took too long to answer.") from None
            except Exception as exc:
                raise PageError(f"{host} couldn't be reached ({type(exc).__name__}).") from None
            if res.is_redirect:
                following = public_https(urljoin(current, res.headers["location"]))
                if following is None:
                    raise PageError(f"{host} redirected to a page that isn't a public https page, so it wasn't followed.")
                current = following
                continue
            if res.status_code != 200:
                raise PageError(f"{host} answered HTTP {res.status_code}.", status=res.status_code)
            kind = res.headers.get("content-type", "").split(";")[0].strip().lower()
            if kind == "application/pdf":
                raise PageError(f"{host}'s policy is a PDF, which this check can't read.")
            if kind and kind not in _TEXT_TYPES:
                raise PageError(f"{host} sent {kind}, not a web page.")
            body = res.text
            text = body if kind == "text/plain" else await asyncio.to_thread(html_to_text, body)
            return current, text
    raise PageError(f"{urlsplit(url).hostname} redirected too many times.")

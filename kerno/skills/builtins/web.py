"""
Built-in web skills.

Designed to work without API keys where possible.
All functions return structured DataFrames, not raw HTML.
"""

_WEB_SKILLS_CODE = '''
import pandas as pd
import json
import re
from IPython.display import display as _display, HTML as _HTML


def fetch(url: str, timeout: int = 15) -> dict:
    """
    Fetch a URL and return structured content.
    Extracts: title, text content, links, meta description.

    Returns:
        dict: {url, title, text, links, status_code}
    """
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (kerno-agent/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw         = resp.read()
            status_code = resp.status
            charset     = resp.headers.get_content_charset() or "utf-8"
            html        = raw.decode(charset, errors="replace")

    except urllib.error.HTTPError as e:
        return {"url": url, "error": f"HTTP {e.code}", "status_code": e.code,
                "title": "", "text": "", "links": []}
    except Exception as e:
        return {"url": url, "error": str(e), "status_code": 0,
                "title": "", "text": "", "links": []}

    # Extract title
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title       = re.sub(r"\\s+", " ", title_match.group(1)).strip() if title_match else ""

    # Extract meta description
    desc_match  = re.search(
        r'<meta[^>]+name=["\\']description["\\'][^>]+content=["\\']([^"\\']*)["\\']',
        html, re.I
    )
    description = desc_match.group(1).strip() if desc_match else ""

    # Extract text (strip tags, collapse whitespace)
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>",   "", text,  flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\\s+", " ", text).strip()
    text = text[:5000]   # Cap at 5000 chars

    # Extract links
    links = [
        {"text": re.sub(r"<[^>]+>", "", a_tag).strip()[:100],
         "href": href}
        for a_tag, href in re.findall(
            r'(<a[^>]+href=["\\']([^"\\'#][^"\\']*)["\\'][^>]*>)',
            html, re.I
        )
        if href.startswith("http")
    ][0:20]

    result = {
        "url":         url,
        "title":       title,
        "description": description,
        "text":        text,
        "links":       links,
        "status_code": status_code,
    }

    _display(_HTML(
        f"<div style='font-family:monospace;font-size:12px;border:1px solid #ddd;padding:8px'>"
        f"<b>✓ Fetched:</b> {url}<br>"
        f"<b>Title:</b> {title}<br>"
        f"<b>Text length:</b> {len(text)} chars<br>"
        f"<b>Links found:</b> {len(links)}"
        f"</div>"
    ))
    return result


def fetch_json(url: str, timeout: int = 15, **params) -> dict | list:
    """
    Fetch a JSON API endpoint and return parsed data.

    Args:
        url:     API endpoint URL
        timeout: Request timeout in seconds
        params: Query string parameters

    Returns:
        Parsed JSON (dict or list)
    """
    import urllib.request
    import urllib.parse

    if params:
        url = url + "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "kerno-agent/1.0",
            "Accept":     "application/json",
        }
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def extract_tables(url: str) -> list:
    """
    Extract all HTML tables from a URL as DataFrames.
    Requires pandas (included in default environment).

    Returns:
        list of DataFrames, one per table found
    """
    page = fetch(url)
    if "error" in page:
        print(f"Error fetching {url}: {page['error']}")
        return []

    try:
        tables = pd.read_html(url)
        print(f"✓ Found {len(tables)} table(s) at {url}")
        for i, df in enumerate(tables):
            print(f"  Table {i}: {df.shape}")
            _display(df.head(3))
        return tables
    except Exception as e:
        print(f"No tables found: {e}")
        return []


def read_csv_url(url: str, **kwargs) -> pd.DataFrame:
    """
    Load a CSV directly from a URL into a DataFrame.

    Returns:
        DataFrame
    """
    df = pd.read_csv(url, **kwargs)
    print(f"✓ Loaded from URL: {df.shape}")
    _display(df.head(3))
    return df
'''


def get_code() -> str:
    return _WEB_SKILLS_CODE

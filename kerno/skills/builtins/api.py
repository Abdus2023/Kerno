# kerno/skills/builtins/api.py
"""
Built-in API and network skills.

These functions wrap REST calls, pagination, retries, and file downloads.
The ``requests`` package is imported lazily so kernels without network work
can still start.
"""

_API_SKILLS_CODE = r'''
import time as _time
from pathlib import Path as _Path

import pandas as pd
from IPython.display import display as _display


_API_CACHE = {}


def _requests():
    try:
        import requests
    except ImportError as exc:
        raise ImportError("requests is required. Install with: pip install requests") from exc
    return requests


def fetch_api(
    url: str,
    method: str = "GET",
    headers: dict = None,
    params: dict = None,
    json_body: dict = None,
    paginate: dict = None,
    max_pages: int = 10,
    delay: float = 0.5,
    timeout: int = 30,
    cache: bool = True,
):
    """
    Fetch JSON from a REST API, optionally paginating.

    paginate examples:
      {"type": "offset", "limit": 100, "param": "offset"}
      {"type": "cursor", "param": "cursor", "json_path": "next_cursor"}

    Returns a DataFrame when records are detected; otherwise returns parsed JSON.
    """
    requests = _requests()
    cache_key = f"{method.upper()}:{url}:{params}"
    if cache and method.upper() == "GET" and cache_key in _API_CACHE:
        print(f"✓ Using cached response for {url}")
        return _API_CACHE[cache_key]

    all_records = []
    current_params = dict(params or {})
    response_data = None

    for page in range(1, max_pages + 1):
        if page > 1 and delay:
            _time.sleep(delay)
        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                headers=headers,
                params=current_params,
                json=json_body,
                timeout=timeout,
            )
            response.raise_for_status()
            response_data = response.json()
        except Exception as exc:
            print(f"✗ API error on page {page}: {exc}")
            if page == 1:
                raise
            break

        if not paginate:
            result = _records_to_dataframe(response_data, url)
            if cache and method.upper() == "GET":
                _API_CACHE[cache_key] = result
            return result

        page_type = paginate.get("type", "offset")
        data_key = paginate.get("data_key", "results")
        records = response_data if isinstance(response_data, list) else response_data.get(data_key, [])
        all_records.extend(records)
        print(f"  Page {page}: {len(records)} records (total={len(all_records)})")

        if page_type == "offset":
            limit = paginate.get("limit", 100)
            if len(records) < limit:
                break
            current_params[paginate.get("param", "offset")] = page * limit
        elif page_type == "cursor":
            cursor = response_data.get(paginate.get("json_path", "next_cursor"))
            if not cursor:
                break
            current_params[paginate.get("param", "cursor")] = cursor
        else:
            break

    if all_records:
        df = pd.DataFrame(all_records)
        print(f"✓ Fetched {len(df)} records from {url}")
        if cache and method.upper() == "GET":
            _API_CACHE[cache_key] = df
        return df
    return response_data


def _records_to_dataframe(data, url):
    if isinstance(data, list):
        print(f"✓ {url} returned {len(data)} list records → DataFrame")
        return pd.DataFrame(data)
    if isinstance(data, dict):
        for key in ("results", "data", "items", "records"):
            value = data.get(key)
            if isinstance(value, list):
                print(f"✓ {url} returned dict['{key}'] with {len(value)} records → DataFrame")
                return pd.DataFrame(value)
    print(f"✓ {url} returned {type(data).__name__} JSON")
    return data


def download_file(url: str, filename: str = None, chunk_size: int = 8192) -> str:
    """
    Download a file with a progress indicator. Returns the local absolute path.
    """
    requests = _requests()
    filename = filename or url.split("/")[-1].split("?")[0] or "downloaded_file"
    path = _Path(filename)

    print(f"Downloading {url} → {path}")
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        downloaded = 0
        with open(path, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        print(f"\r  {downloaded / total:.1%}", end="", flush=True)
        if total:
            print()
    print(f"✓ Saved {path.resolve()} ({path.stat().st_size / 1024:.1f} KB)")
    return str(path.resolve())
'''


def get_code() -> str:
    return _API_SKILLS_CODE

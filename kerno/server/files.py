"""
File materialization: convert Open WebUI file attachments
into kernel-accessible objects.

Open WebUI sends files as:
  - Base64-encoded content in the message body
  - URL references to uploaded files
  - Multipart form data (for direct API calls)

Kerno materializes them into:
  - Files on disk (all types)
  - DataFrames in namespace (CSV, Excel, Parquet, JSON)
  - PIL Images in namespace (PNG, JPG, WebP)
  - Extracted text in namespace (PDF, DOCX, TXT)

Security boundary (F-001 / K-001):
  FileMaterializer NEVER owns a raw kernel. It receives a narrow
  MaterializationExecutor that exposes exactly one operation —
  execute_load_code() — which routes through the ExecutionEngine choke
  point (audit records, event stream, effects, budget, finalization).
  The loader code is server-generated template code (trusted host code,
  origin=ORIGIN_RUNTIME — the same trust class as skill bootstrap).

  URL ingestion (F-002) is policy-checked: http/https only, private /
  loopback / link-local / CGNAT addresses rejected (including every
  redirect target), download size capped while streaming, connect/read
  timeouts enforced. File materialization (F-003) is bounded: per-file,
  per-request count, and total-byte limits, with base64 size rejected
  BEFORE decode/allocation.
"""

from __future__ import annotations

import base64
import ipaddress
import shutil
import socket
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from kerno.execution.engine import ORIGIN_RUNTIME

# ── Materialization limits (F-003) ───────────────────────────────────────────

DEFAULT_MAX_FILE_BYTES            = 50 * 1024 * 1024    # 50 MB per file
DEFAULT_MAX_TOTAL_FILE_BYTES      = 100 * 1024 * 1024   # 100 MB per request
DEFAULT_MAX_FILES_PER_REQUEST     = 20
DEFAULT_MAX_URL_DOWNLOAD_BYTES    = 50 * 1024 * 1024    # 50 MB per URL fetch
DEFAULT_MAX_MATERIALIZATION_TIME  = 60.0                # seconds, overall
DEFAULT_URL_CONNECT_TIMEOUT       = 10.0                # seconds
DEFAULT_URL_READ_TIMEOUT          = 30.0                # seconds
DEFAULT_ALLOWED_URL_SCHEMES       = frozenset({"http", "https"})


@dataclass(frozen=True)
class MaterializationLimits:
    """
    Bounds for file materialization (F-003).

    The server measures ACTUAL bytes; the client-declared `size` field is
    never trusted.
    """

    max_file_bytes:           int = DEFAULT_MAX_FILE_BYTES
    max_total_file_bytes:     int = DEFAULT_MAX_TOTAL_FILE_BYTES
    max_files_per_request:    int = DEFAULT_MAX_FILES_PER_REQUEST
    max_url_download_bytes:   int = DEFAULT_MAX_URL_DOWNLOAD_BYTES
    max_materialization_time: float = DEFAULT_MAX_MATERIALIZATION_TIME
    url_connect_timeout:      float = DEFAULT_URL_CONNECT_TIMEOUT
    url_read_timeout:         float = DEFAULT_URL_READ_TIMEOUT
    allowed_url_schemes:      frozenset = field(default_factory=lambda: DEFAULT_ALLOWED_URL_SCHEMES)


def default_limits() -> MaterializationLimits:
    """Default materialization bounds (override per deployment as needed)."""
    return MaterializationLimits()


class MaterializationLimitError(Exception):
    """Raised when a materialization resource limit is exceeded (F-003)."""


class UrlPolicyError(Exception):
    """Raised when a download URL violates the outbound URL policy (F-002)."""


# ── Outbound URL policy (F-002) ──────────────────────────────────────────────

# Addresses that must never be reachable via server-side file materialization.
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),        # "this network" / invalid
    ipaddress.ip_network("10.0.0.0/8"),       # RFC 1918
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT (RFC 6598)
    ipaddress.ip_network("127.0.0.0/8"),      # loopback
    ipaddress.ip_network("169.254.0.0/16"),   # link-local
    ipaddress.ip_network("172.16.0.0/12"),    # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),   # RFC 1918
    ipaddress.ip_network("198.18.0.0/15"),    # benchmarking (RFC 2544)
    ipaddress.ip_network("224.0.0.0/4"),      # multicast
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
    ipaddress.ip_network("ff00::/8"),         # IPv6 multicast
]


def _is_private_address(ip: ipaddress._BaseAddress) -> bool:
    return any(ip in net for net in _PRIVATE_NETWORKS)


def validate_download_url(
    url: str,
    allowed_schemes: frozenset | None = None,
) -> urllib.parse.ParseResult:
    """
    Validate an outbound download URL against the F-002 policy.

    Rejects:
      - unsupported schemes (anything but http/https by default)
      - URLs embedding credentials (userinfo)
      - literal private / loopback / link-local / CGNAT IP addresses
      - hostnames that resolve (in whole or in part) to a non-public
        address (DNS-rebinding resistance: EVERY resolved address is
        checked, not just the first)

    Returns the parsed URL on success; raises UrlPolicyError otherwise.
    """
    schemes = allowed_schemes if allowed_schemes is not None else DEFAULT_ALLOWED_URL_SCHEMES

    if not url or not isinstance(url, str):
        raise UrlPolicyError("empty or invalid URL")

    parsed = urllib.parse.urlparse(url)

    if parsed.scheme.lower() not in schemes:
        raise UrlPolicyError(
            "scheme {!r} is not allowed (allowed: {})".format(
                parsed.scheme or "<none>", ", ".join(sorted(schemes))
            )
        )

    if parsed.username or parsed.password:
        raise UrlPolicyError("URLs with embedded credentials are not allowed")

    host = parsed.hostname
    if not host:
        raise UrlPolicyError("URL has no hostname")

    # Literal IP address → check directly.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if _is_private_address(ip):
            raise UrlPolicyError(f"URL targets a non-public address: {ip}")
        return parsed

    # Hostname → resolve and require ALL addresses to be public.
    try:
        infos = socket.getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as exc:
        raise UrlPolicyError(f"cannot resolve host: {host}") from exc
    if not infos:
        raise UrlPolicyError(f"host resolves to no addresses: {host}")

    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _is_private_address(addr):
            raise UrlPolicyError(
                f"host {host} resolves to a non-public address: {addr}"
            )
    return parsed


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """
    Re-validates EVERY redirect target against the F-002 URL policy.

    Without this, a public URL redirecting to http://127.0.0.1:8000/ would
    bypass the initial validation.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_download_opener() -> urllib.request.OpenerDirector:
    """Opener with redirect-revalidating handler (F-002)."""
    return urllib.request.build_opener(_ValidatingRedirectHandler())


def _download_to_file(
    url: str,
    dest: Path,
    *,
    max_bytes: int,
    connect_timeout: float,
    read_timeout: float,
    overall_timeout: float,
    opener: urllib.request.OpenerDirector | None = None,
) -> int:
    """
    Download `url` to `dest` enforcing scheme/IP policy, per-redirect
    validation, connect/read timeouts, and a streaming size cap.

    Returns the number of bytes written. Raises UrlPolicyError (policy),
    MaterializationLimitError (size/timeout), or the underlying error.
    """
    validate_download_url(url)
    opener = opener or _build_download_opener()
    deadline = time.monotonic() + overall_timeout

    try:
        resp = opener.open(url, timeout=connect_timeout)
    except UrlPolicyError:
        raise
    except TimeoutError as exc:
        raise MaterializationLimitError("URL download timed out (connect)") from exc

    with resp:
        # Reject on declared Content-Length before reading anything.
        declared = resp.headers.get("Content-Length")
        if declared:
            try:
                if int(declared) > max_bytes:
                    raise MaterializationLimitError(
                        f"URL download exceeds size limit (declared {declared} bytes, limit {max_bytes})"
                    )
            except ValueError:
                pass

        total = 0
        with open(dest, "wb") as f:
            while True:
                if time.monotonic() > deadline:
                    raise MaterializationLimitError(
                        f"URL download exceeded overall time limit ({round(overall_timeout, 1)}s)"
                    )
                try:
                    chunk = resp.read(64 * 1024)
                except TimeoutError as exc:
                    raise MaterializationLimitError(
                        "URL download timed out (read)"
                    ) from exc
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise MaterializationLimitError(
                        f"URL download exceeds size limit ({total} bytes, limit {max_bytes})"
                    )
                f.write(chunk)
    return total


def _estimate_base64_size(data_b64: str) -> int:
    """Upper-bound estimate of the decoded size WITHOUT decoding (F-003)."""
    compact = "".join(data_b64.split())
    padding = len(compact) - len(compact.rstrip("="))
    return max(0, (len(compact) * 3) // 4 - padding)


# ── Narrow execution authority (F-001) ───────────────────────────────────────

class MaterializationExecutor:
    """
    The ONLY execution authority available to FileMaterializer (F-001).

    Exposes exactly one operation — execute_load_code() — routed through
    the ExecutionEngine choke point. Loader code is server-generated
    template code, i.e. trusted host code, so it runs with
    origin=ORIGIN_RUNTIME (the same trust class as skill bootstrap); the
    engine still applies the transaction lifecycle: execution_id,
    sequence, audit records, event stream, effect declaration/
    observation, budget (when the engine is wrapped), cancellation, and
    guaranteed finalization.

    This class can never be used as a general-purpose executor, and the
    materializer can never reach the raw kernel.
    """

    def __init__(self, engine: object, *, capabilities: frozenset = frozenset()):
        if not hasattr(engine, "execute"):
            raise TypeError(
                "MaterializationExecutor requires an Executor-shaped object "
                f"(e.g. ExecutionEngine), got {type(engine).__name__!r}"
            )
        self._engine       = engine
        self._capabilities = frozenset(capabilities)

    def execute_load_code(
        self,
        code: str,
        *,
        timeout: float = 30.0,
        cancel_event: object | None = None,
    ):
        """Execute server-generated load code through the engine (F-001)."""
        return self._engine.execute(
            code,
            timeout       = timeout,
            origin        = ORIGIN_RUNTIME,
            capabilities  = self._capabilities,
            cancel_event  = cancel_event,
        )


@dataclass
class MaterializedFile:
    """
    A file that has been materialized for kernel access.
    """
    original_name: str
    local_path:    str
    mime_type:     str
    size_bytes:    int
    variable_name: str         # Name assigned in kernel namespace
    load_code:     str         # Python code to load into namespace


class FileMaterializer:
    """
    Handles file attachments from Open WebUI and makes them
    available inside the kernel.

    Usage:
        executor   = MaterializationExecutor(engine)   # engine = ExecutionEngine
        materializer = FileMaterializer(executor, upload_dir="/tmp/kerno_uploads")
        files = materializer.process(message_files)
        # files: list[MaterializedFile]
        # Each file is now accessible in the kernel namespace

    The constructor REQUIRES a MaterializationExecutor-shaped object
    (anything with execute_load_code()); a raw KernelRuntime or a
    general-purpose executor is rejected structurally — FileMaterializer
    cannot execute code outside the engine choke point (F-001).
    """

    SUPPORTED_TYPES = {
        # Data files → DataFrame
        "text/csv":                         "dataframe",
        "application/json":                 "dataframe",
        "application/vnd.ms-excel":         "dataframe",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
                                            "dataframe",
        "application/octet-stream":         "dataframe",  # Parquet

        # Images → PIL Image
        "image/png":    "image",
        "image/jpeg":   "image",
        "image/webp":   "image",
        "image/gif":    "image",

        # Documents → text
        "application/pdf":   "document",
        "text/plain":        "document",
        "text/markdown":     "document",
    }

    LOAD_TEMPLATES = {
        "dataframe": """
import pandas as _pd, pathlib as _pl
_path = {path!r}
_suffix = _pl.Path(_path).suffix.lower()
_loaders = {{
    '.csv':     lambda: _pd.read_csv(_path),
    '.json':    lambda: _pd.read_json(_path),
    '.xlsx':    lambda: _pd.read_excel(_path),
    '.xls':     lambda: _pd.read_excel(_path),
    '.parquet': lambda: _pd.read_parquet(_path),
}}
{varname} = _loaders.get(_suffix, lambda: _pd.read_csv(_path))()
print(f"✓ Loaded {{repr({varname!r})}}: {{{varname}.shape}}")
""",
        "image": """
try:
    from PIL import Image as _PILImage
    {varname} = _PILImage.open({path!r})
    print(f"✓ Loaded image {{repr({varname!r})}}: {{{varname}.size}}")
except ImportError:
    import matplotlib.pyplot as _plt
    import matplotlib.image as _mpimg
    {varname} = _mpimg.imread({path!r})
    print(f"✓ Loaded image {{repr({varname!r})}}: {{{varname}.shape}}")
""",
        "document": """
with open({path!r}, 'r', encoding='utf-8', errors='replace') as _f:
    {varname} = _f.read()
print(f"✓ Loaded document {{repr({varname!r})}}: {{len({varname})}} chars")
""",
        "pdf": """
try:
    import pdfplumber as _pdfplumber
    with _pdfplumber.open({path!r}) as _pdf:
        {varname} = '\\n'.join(
            page.extract_text() or '' for page in _pdf.pages
        )
    print(f"✓ Extracted PDF {{repr({varname!r})}}: {{len({varname})}} chars")
except ImportError:
    with open({path!r}, 'rb') as _f:
        {varname} = f"[PDF file at {path!r} — install pdfplumber to extract text]"
""",
    }

    def __init__(
        self,
        executor: object,
        upload_dir: str = "/tmp/kerno_uploads",
        limits: MaterializationLimits | None = None,
    ):
        if not hasattr(executor, "execute_load_code"):
            raise TypeError(
                "FileMaterializer requires a MaterializationExecutor (any object "
                "with execute_load_code()); raw kernels and general-purpose "
                "executors are not accepted — materialization must run through "
                "the ExecutionEngine choke point (F-001)."
            )
        self._executor    = executor
        self._limits      = limits or default_limits()
        self.upload_dir   = Path(upload_dir)
        # Per-instance (per-request) storage isolation (F-004): the original
        # filename is metadata, never the storage identity.
        self._session_dir = self.upload_dir / uuid.uuid4().hex
        self._session_dir.mkdir(parents=True, exist_ok=True)
        self._counter     = 0
        self._total_bytes = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def process(self, files: list[dict]) -> list[MaterializedFile]:
        """
        Process a list of file attachments from Open WebUI.

        Expected file format (Open WebUI):
            {
                "name":    "sales_data.csv",
                "type":    "text/csv",         # MIME type
                "data":    "base64...",         # base64-encoded content
                "url":     "http://...",        # OR a URL
                "size":    12345,
            }
        """
        if len(files) > self._limits.max_files_per_request:
            raise MaterializationLimitError(
                f"too many files in request ({len(files)} > limit {self._limits.max_files_per_request})"
            )
        materialized = []
        for file_info in files:
            result = self._process_one(file_info)
            if result:
                materialized.append(result)
        return materialized

    def process_from_context(self, body: dict) -> list[MaterializedFile]:
        """
        Extract and process files from an Open WebUI request body.
        Handles multiple attachment formats.
        """
        files = []

        # Format 1: files array
        if "files" in body:
            files.extend(body["files"])

        # Format 2: embedded in messages
        for msg in body.get("messages", []):
            if isinstance(msg.get("content"), list):
                for part in msg["content"]:
                    if part.get("type") in ("image_url", "file"):
                        files.append(self._normalize_content_part(part))

        return self.process([f for f in files if f])

    def build_context_message(self, files: list[MaterializedFile]) -> str:
        """
        Build a context message telling the LLM what files are available.
        Injected into the task description.
        """
        if not files:
            return ""

        lines = ["The following files have been loaded into the kernel namespace:"]
        for f in files:
            lines.append(
                f"  `{f.variable_name}` — {f.original_name} "
                f"({f.mime_type}, {f.size_bytes // 1024}KB)"
            )
        lines.append(
            "\nUse these variables directly in your code — they are already loaded."
        )
        return "\n".join(lines)

    def cleanup(self) -> None:
        """
        Remove this instance's storage directory (F-004 lifecycle).

        Guaranteed-cleanup is the caller's responsibility (try/finally);
        this removes the per-request directory so uploads cannot pile up
        in /tmp/kerno_uploads.
        """
        try:
            if self._session_dir.exists():
                shutil.rmtree(self._session_dir, ignore_errors=True)
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[kerno] FileMaterializer cleanup error: {exc}")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _process_one(self, file_info: dict) -> MaterializedFile | None:
        """Save one file to disk and inject it into the kernel."""
        if not isinstance(file_info, dict):
            return None

        name      = file_info.get("name", f"file_{self._counter}")
        mime      = file_info.get("type", "application/octet-stream")
        data_b64  = file_info.get("data", "")
        url       = file_info.get("url", "")
        size      = file_info.get("size", 0)

        # Write to disk (enforces F-002 URL policy + F-003 size limits)
        local_path = self._save_file(name, data_b64, url)
        if not local_path:
            return None

        # Determine variable name
        self._counter += 1
        varname = self._safe_varname(name)

        # Determine load strategy
        kind     = self._classify(mime, name)
        template = self.LOAD_TEMPLATES.get(kind, self.LOAD_TEMPLATES["document"])

        # Handle PDFs specially
        if mime == "application/pdf":
            template = self.LOAD_TEMPLATES["pdf"]

        load_code = template.format(path=local_path, varname=varname)

        # Execute through the engine choke point (F-001) — the raw kernel
        # is never reachable from here.
        output = self._executor.execute_load_code(load_code, timeout=30)
        if output.has_error:
            print(
                f"[kerno] File load warning: {name}: "
                f"{output.error.ename}: {output.error.evalue}"
            )
            return None

        return MaterializedFile(
            original_name = name,
            local_path    = local_path,
            mime_type     = mime,
            size_bytes    = size or Path(local_path).stat().st_size,
            variable_name = varname,
            load_code     = load_code,
        )

    def _save_file(self, name: str, data_b64: str, url: str) -> str | None:
        """Save file content to disk, from either base64 or URL."""
        safe_name = "".join(c for c in name if c.isalnum() or c in "._-") or f"file_{self._counter}"
        local_path = str(self._session_dir / safe_name)

        if data_b64:
            # F-003: reject before decode/allocation based on encoded size.
            estimated = _estimate_base64_size(data_b64)
            if estimated > self._limits.max_file_bytes:
                raise MaterializationLimitError(
                    f"base64 file exceeds size limit (estimated {estimated} bytes, limit {self._limits.max_file_bytes})"
                )
            try:
                content = base64.b64decode(data_b64)
            except Exception as e:
                print(f"[kerno] Base64 decode error for {name}: {e}")
                return None
            if len(content) > self._limits.max_file_bytes:  # defense in depth
                raise MaterializationLimitError(
                    f"base64 file exceeds size limit ({len(content)} bytes, limit {self._limits.max_file_bytes})"
                )
            with open(local_path, "wb") as f:
                f.write(content)

        elif url:
            # F-002: policy-checked, size-capped, timed download.
            _download_to_file(
                url,
                Path(local_path),
                max_bytes      = self._limits.max_url_download_bytes,
                connect_timeout = self._limits.url_connect_timeout,
                read_timeout   = self._limits.url_read_timeout,
                overall_timeout = self._limits.max_materialization_time,
            )

        else:
            return None

        size = Path(local_path).stat().st_size
        self._total_bytes += size
        if self._total_bytes > self._limits.max_total_file_bytes:
            raise MaterializationLimitError(
                f"total materialized size exceeds limit ({self._total_bytes} bytes, limit {self._limits.max_total_file_bytes})"
            )
        return local_path

    @staticmethod
    def _classify(mime: str, name: str) -> str:
        """Classify file type for load strategy selection."""
        if mime == "application/pdf" or name.endswith(".pdf"):
            return "pdf"
        if mime.startswith("image/"):
            return "image"
        if any(name.endswith(ext) for ext in [".csv", ".xlsx", ".xls", ".parquet", ".json"]):
            return "dataframe"
        return "document"

    @staticmethod
    def _safe_varname(filename: str) -> str:
        """Convert filename to a valid Python variable name."""
        import re
        stem = Path(filename).stem
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", stem)
        safe = re.sub(r"_+", "_", safe).strip("_")
        if safe and safe[0].isdigit():
            safe = f"file_{safe}"
        return safe or "uploaded_file"

    @staticmethod
    def _normalize_content_part(part: dict) -> dict | None:
        """Normalize a message content part into file_info format."""
        if part.get("type") == "image_url":
            url_data = part.get("image_url", {})
            url      = url_data.get("url", "")
            if url.startswith("data:"):
                # Data URL: data:image/png;base64,...
                try:
                    header, b64 = url.split(",", 1)
                    mime        = header.split(":")[1].split(";")[0]
                    return {"name": f"image.{mime.split('/')[1]}", "type": mime, "data": b64}
                except Exception:
                    return None
            return {"name": "image.jpg", "type": "image/jpeg", "url": url}
        return None

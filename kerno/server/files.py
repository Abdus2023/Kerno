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
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib     import Path
from typing      import Optional


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
        materializer = FileMaterializer(kernel, upload_dir="/tmp/kerno_uploads")
        files = materializer.process(message_files)
        # files: list[MaterializedFile]
        # Each file is now accessible in the kernel namespace
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
        kernel,
        upload_dir: str = "/tmp/kerno_uploads",
    ):
        self.kernel     = kernel
        self.upload_dir = Path(upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self._counter   = 0

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

    # ── Internal ──────────────────────────────────────────────────────────────

    def _process_one(self, file_info: dict) -> Optional[MaterializedFile]:
        """Save one file to disk and inject it into the kernel."""
        name      = file_info.get("name", f"file_{self._counter}")
        mime      = file_info.get("type", "application/octet-stream")
        data_b64  = file_info.get("data", "")
        url       = file_info.get("url", "")
        size      = file_info.get("size", 0)

        # Write to disk
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

        # Execute in kernel
        output = self.kernel.execute(load_code, timeout=30)
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

    def _save_file(self, name: str, data_b64: str, url: str) -> Optional[str]:
        """Save file content to disk, from either base64 or URL."""
        safe_name  = "".join(c for c in name if c.isalnum() or c in "._-")
        local_path = str(self.upload_dir / safe_name)

        if data_b64:
            # Decode base64
            try:
                content = base64.b64decode(data_b64)
                with open(local_path, "wb") as f:
                    f.write(content)
                return local_path
            except Exception as e:
                print(f"[kerno] Base64 decode error for {name}: {e}")
                return None

        elif url:
            # Download from URL
            try:
                import urllib.request
                urllib.request.urlretrieve(url, local_path)
                return local_path
            except Exception as e:
                print(f"[kerno] URL download error for {name}: {e}")
                return None

        return None

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
        if safe[0].isdigit():
            safe = f"file_{safe}"
        return safe or "uploaded_file"

    @staticmethod
    def _normalize_content_part(part: dict) -> Optional[dict]:
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

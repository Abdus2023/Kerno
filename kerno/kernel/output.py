# kerno/kernel/output.py
"""
OutputCollector: translates raw ZMQ messages into CellOutput.
This is the sensory layer — everything the kernel says, we hear here.
"""

import queue
import re
import time
from typing import Iterator

from kerno.types import CellError, CellOutput


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[mK]")


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE.sub("", text)


def collect(
    kc,
    msg_id: str,
    timeout: float = 120.0,
    on_timeout: "callable | None" = None,
) -> CellOutput:
    """
    Collect all ZMQ messages for a given execution request.
    Blocks until kernel signals idle or timeout expires.

    Args:
        kc:         KernelClient (already connected)
        msg_id:     The message ID returned by kc.execute()
        timeout:    Wall-clock timeout in seconds
        on_timeout: Optional zero-argument callback invoked when the deadline
                    expires. Typically used to interrupt the kernel via its
                    KernelManager (KernelClient has no interrupt method).

    Returns:
        Fully populated CellOutput
    """
    output   = CellOutput()
    deadline = time.monotonic() + timeout

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if on_timeout is not None:
                try:
                    on_timeout()
                except Exception as exc:           # pragma: no cover
                    import sys
                    print(f"Timeout interrupt failed: {exc}", file=sys.stderr)
            output.error = CellError(
                ename="TimeoutError",
                evalue=f"Cell execution exceeded {timeout}s limit"
            )
            break

        try:
            msg = kc.get_iopub_msg(timeout=min(remaining, 1.0))
        except queue.Empty:
            continue

        msg_type = msg["msg_type"]
        content  = msg["content"]

        match msg_type:

            case "stream":
                text = content.get("text", "")
                if content.get("name") == "stdout":
                    output.stdout += text
                else:
                    output.stderr += text

            case "display_data" | "execute_result":
                data = content.get("data", {})

                if "image/png" in data:
                    output.images.append(data["image/png"])

                if "text/html" in data:
                    output.displays.append({"html": data["text/html"]})

                if "application/json" in data:
                    output.displays.append({"json": data["application/json"]})

                if "text/plain" in data and msg_type == "execute_result":
                    output.result = data["text/plain"]

            case "error":
                tb = "\n".join(
                    _strip_ansi(line)
                    for line in content.get("traceback", [])
                )
                output.error = CellError(
                    ename=content.get("ename", "Error"),
                    evalue=content.get("evalue", ""),
                    traceback=tb,
                )

            case "status":
                if content.get("execution_state") == "idle":
                    break

            # clear_output, comm_msg, etc. — ignored for now
            case _:
                pass

    return output


def stream(
    kc,
    msg_id: str,
    timeout: float = 120.0,
    on_timeout: "callable | None" = None,
) -> Iterator[tuple[str, str]]:
    """
    Generator variant: yields (msg_type, text) as messages arrive.
    Useful for long-running cells where you want to read output in real time.

    Yields:
        ("stdout", text) | ("stderr", text) | ("error", "ename: evalue") | ("done", "")
    """
    deadline = time.monotonic() + timeout

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if on_timeout is not None:
                on_timeout()
            yield ("error", "TimeoutError: execution limit exceeded")
            return

        try:
            msg = kc.get_iopub_msg(timeout=min(remaining, 0.5))
        except queue.Empty:
            continue

        msg_type = msg["msg_type"]
        content  = msg["content"]

        match msg_type:
            case "stream":
                name = "stdout" if content.get("name") == "stdout" else "stderr"
                yield (name, content.get("text", ""))

            case "error":
                ename  = content.get("ename", "Error")
                evalue = content.get("evalue", "")
                yield ("error", f"{ename}: {evalue}")

            case "status":
                if content.get("execution_state") == "idle":
                    yield ("done", "")
                    return

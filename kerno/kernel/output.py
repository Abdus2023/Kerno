# kerno/kernel/output.py
"""
OutputCollector: translates raw ZMQ messages into CellOutput.
This is the sensory layer — everything the kernel says, we hear here.
"""

import queue
import re
import threading
import time
from typing import Iterator, Optional

from kerno.types import CellError, CellOutput


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[mK]")


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE.sub("", text)


# ── Single-reader coordination ────────────────────────────────────────────────
# The IOPUB socket has ONE consumer. If a background listener (e.g. KernoComm)
# reads from it concurrently with collect(), messages — including the
# terminal "idle" status — are randomly distributed between the readers and
# cells hang until timeout. All iopub readers must therefore share this lock.

IOPUB_LOCK = threading.RLock()

# Optional comm_msg dispatcher, installed by KernoComm. Called inline while
# collecting a cell, so comm messages are delivered without a competing
# reader thread.
_comm_handler: Optional["callable"] = None


def set_comm_handler(handler: Optional["callable"]) -> None:
    """Install (or remove, with None) the comm_msg dispatcher."""
    global _comm_handler
    _comm_handler = handler


def get_comm_handler() -> Optional["callable"]:
    return _comm_handler



def collect(
    kc,
    msg_id: str,
    timeout: float = 120.0,
    on_timeout: "callable | None" = None,
    cancel_event: "object | None" = None,
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

    # Hold the single-reader lock for the whole collection so no background
    # listener can steal messages (including the terminal "idle").
    with IOPUB_LOCK:
        while True:
            # Audit #83: cancellation propagates MID-CELL — interrupt the
            # kernel (like a timeout) and terminate the execution cleanly.
            if cancel_event is not None and cancel_event.is_set():
                if on_timeout is not None:
                    try:
                        on_timeout()
                    except Exception as exc:           # pragma: no cover
                        import sys
                        print(f"Cancel interrupt failed: {exc}", file=sys.stderr)
                output.error = CellError(
                    ename  = "KernelInterrupted",
                    evalue = "execution cancelled by CancellationToken",
                )
                break

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

                case "comm_msg":
                    handler = _comm_handler
                    if handler is not None:
                        try:
                            handler(msg)
                        except Exception as exc:
                            import sys
                            print(
                                f"Comm handler error: {exc}", file=sys.stderr
                            )

                # clear_output, etc. — ignored for now
                case _:
                    pass

    return output


def stream(
    kc,
    msg_id: str,
    timeout: float = 120.0,
    on_timeout: "callable | None" = None,
    cancel_event: "object | None" = None,
) -> Iterator[tuple[str, str]]:
    """
    Generator variant: yields (msg_type, text) as messages arrive.
    Useful for long-running cells where you want to read output in real time.

    Yields:
        ("stdout", text) | ("stderr", text) | ("error", "ename: evalue") | ("done", "")
    """
    deadline = time.monotonic() + timeout

    with IOPUB_LOCK:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                if on_timeout is not None:
                    on_timeout()
                yield ("error", "KernelInterrupted: execution cancelled")
                return

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

                case "comm_msg":
                    handler = _comm_handler
                    if handler is not None:
                        try:
                            handler(msg)
                        except Exception as exc:
                            import sys
                            print(
                                f"Comm handler error: {exc}", file=sys.stderr
                            )

                case "status":
                    if content.get("execution_state") == "idle":
                        yield ("done", "")
                        return

# kerno/dev/reload.py
"""
HotReloader: reload skills and configuration without restarting the kernel.

The kernel process stays alive — only the skill code is re-injected.
This makes the development loop fast:

  1. Edit skill code
  2. Call reload()
  3. New skill immediately available in the running kernel

No restart. No state loss.
"""

from __future__ import annotations

import hashlib
import time
import threading
from pathlib import Path
from typing  import Callable, Optional


class HotReloader:
    """
    Watches skill files and reloads them in a running kernel on change.

    Usage:
        kernel = KernelRuntime().start()

        reloader = HotReloader(kernel)
        reloader.watch("skills/my_skills.py")
        reloader.watch("skills/domain.py")
        reloader.start()   # Background watching

        # Edit skills/my_skills.py ...
        # Reloader detects change and reloads automatically

        reloader.stop()
    """

    def __init__(
        self,
        kernel,
        on_reload: Optional[Callable[[str], None]] = None,
        interval:  float = 1.0,
    ):
        self.kernel    = kernel
        self.on_reload = on_reload
        self.interval  = interval

        self._watched:  dict[str, str]         = {}   # path → last_hash
        self._thread:   Optional[threading.Thread] = None
        self._running:  bool                   = False

    def watch(self, path: str) -> "HotReloader":
        """Add a file to watch. Returns self for chaining."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError("Not found: {}".format(path))

        self._watched[str(p.resolve())] = self._hash(p)
        return self

    def watch_directory(self, directory: str, pattern: str = "*.py") -> "HotReloader":
        """Watch all matching files in a directory."""
        for path in Path(directory).glob(pattern):
            self.watch(str(path))
        return self

    def start(self) -> "HotReloader":
        """Start background watching. Returns self."""
        self._running = True
        self._thread  = threading.Thread(
            target = self._watch_loop,
            daemon = True,
            name   = "kerno-hot-reloader",
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stop background watching."""
        self._running = False

    def reload_all(self) -> list[str]:
        """Force reload all watched files. Returns list of reloaded paths."""
        reloaded = []
        for path in list(self._watched.keys()):
            self._reload(path)
            reloaded.append(path)
        return reloaded

    def reload(self, path: str) -> None:
        """Force reload a specific file."""
        self._reload(str(Path(path).resolve()))

    # ── Internals ─────────────────────────────────────────────────────────────

    def _watch_loop(self) -> None:
        while self._running:
            for path, last_hash in list(self._watched.items()):
                try:
                    current_hash = self._hash(Path(path))
                    if current_hash != last_hash:
                        self._watched[path] = current_hash
                        self._reload(path)
                except FileNotFoundError:
                    pass   # File was deleted — stop watching it
            time.sleep(self.interval)

    def _reload(self, path: str) -> None:
        """Reload a skill file into the kernel."""
        p    = Path(path)
        code = p.read_text()

        output = self.kernel.execute(code, silent=False, timeout=30)

        if output.has_error:
            print(
                "[hot-reload] ✗ {}: "
                "{}: {}".format(p.name, output.error.ename, output.error.evalue)
            )
        else:
            print("[hot-reload] ✓ {}".format(p.name))
            if self.on_reload:
                self.on_reload(path)

    @staticmethod
    def _hash(path: Path) -> str:
        return hashlib.md5(path.read_bytes()).hexdigest()


class SkillDevelopmentSession:
    """
    An interactive skill development session.
    Combines a kernel, hot reloader, and immediate feedback.

    Usage:
        with SkillDevelopmentSession("skills/my_skill.py") as dev:
            dev.test("Use my_skill() to process the data")
            dev.inspect("my_skill")
            dev.namespace()
            # Edit my_skill.py — auto-reloaded
            dev.test("Use my_skill() again with the fix")
    """

    def __init__(self, *skill_paths: str):
        from kerno.kernel.runtime import KernelRuntime
        from kerno.skills.bootstrap import bootstrap

        self.kernel   = KernelRuntime()
        self.reloader = HotReloader(self.kernel)
        for path in skill_paths:
            self.reloader.watch(path)

    def __enter__(self) -> "SkillDevelopmentSession":
        self.kernel.start()
        from kerno.skills.bootstrap import bootstrap
        bootstrap(self.kernel)
        self.reloader.reload_all()
        self.reloader.start()
        return self

    def __exit__(self, *args) -> None:
        self.reloader.stop()
        self.kernel.shutdown()

    def test(self, task: str, llm=None) -> None:
        """Run a quick test task in the current kernel state."""
        if llm is None:
            print("[dev] No LLM provided — skipping test run")
            return

        from kerno.steps.generate import GenerateCodeStep
        from kerno.steps.execute  import ExecuteStep
        from kerno.steps.compress import CompletionCheckStep
        from kerno.pipeline       import Pipeline, LoopStep
        from kerno.interfaces     import AgentState

        pipe = LoopStep(
            Pipeline([
                GenerateCodeStep(llm),
                ExecuteStep(self.kernel),
                CompletionCheckStep(),
            ]),
            done           = lambda s: s.complete,
            max_iterations = 10,
        )
        state = AgentState(task=task)
        final = pipe.run(state)
        print("\n[dev] {} ({})".format(
            "Complete" if final.complete else "Incomplete",
            len(final.history)
        ))

    def inspect(self, name: str) -> dict:
        """Inspect a named object in the kernel namespace."""
        return self.kernel.inspect(name)

    def namespace(self) -> str:
        """Print the current kernel namespace."""
        ns = self.kernel.namespace
        print("Namespace:\n{}".format(ns))
        return ns

    def execute(self, code: str) -> None:
        """Execute code directly in the development kernel."""
        output = self.kernel.execute(code)
        if output.stdout:
            print(output.stdout)
        if output.has_error:
            print("Error: {}: {}".format(output.error.ename, output.error.evalue))

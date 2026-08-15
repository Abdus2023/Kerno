"""State checkpoint plugin using the live kernel namespace."""

from __future__ import annotations

from dataclasses import dataclass

from kerno.plugins.registry import BasePlugin


@dataclass
class CheckpointRecord:
    cell: int
    directory: str
    output: str


class CheckpointPlugin(BasePlugin):
    """
    Periodically checkpoint DataFrames and fitted models from the kernel.

    The plugin is used like other lifecycle plugins but needs access to the
    kernel in order to serialize live objects. Attach it explicitly after
    construction:

        plugin = CheckpointPlugin(directory="_checkpoints/run").attach(kernel)
        registry.register(plugin)
    """

    name = "checkpoint"

    _CHECKPOINT_CODE = '''
import joblib as _joblib
import pathlib as _pathlib
import pandas as _pd

_root = _pathlib.Path(_checkpoint_directory)
_root.mkdir(parents=True, exist_ok=True)
_saved = []
for _name, _obj in list(globals().items()):
    if _name.startswith("_"):
        continue
    try:
        if isinstance(_obj, _pd.DataFrame):
            _obj.to_parquet(_root / f"{_name}.parquet")
            _saved.append(_name)
        elif hasattr(_obj, "fit") and hasattr(_obj, "predict"):
            _joblib.dump(_obj, _root / f"{_name}.joblib")
            _saved.append(_name)
    except Exception:
        pass
print(f"[checkpoint] saved {len(_saved)} object(s) to {_root.resolve()}")
'''

    def __init__(
        self,
        every: int = 10,
        directory: str = "_checkpoints/session",
        on_complete: bool = True,
    ):
        self.every = max(1, every)
        self.directory = directory
        self.on_complete = on_complete
        self._kernel = None
        self.records: list[CheckpointRecord] = []

    def attach(self, kernel) -> "CheckpointPlugin":
        """Bind this plugin to the kernel whose namespace should be saved."""
        self._kernel = kernel
        return self

    def on_cell_complete(self, cell) -> None:
        if cell.cell_num and cell.cell_num % self.every == 0:
            self._checkpoint(cell.cell_num)

    # Current BaseLoop/PluginRegistry calls on_cell_complete, not on_cell_complete.
    on_cell_complete = on_cell_complete

    def on_session_complete(self, result) -> None:
        if self.on_complete:
            last_num = result.cells[-1].cell_num if result.cells else 0
            self._checkpoint(last_num)

    def _checkpoint(self, cell_num: int) -> None:
        if self._kernel is None:
            print("[checkpoint] kernel not attached; skipping checkpoint", flush=True)
            return
        code = (
            f"_checkpoint_directory = {self.directory!r}\n"
            + self._CHECKPOINT_CODE
        )
        output = self._kernel.execute(code, silent=True, timeout=30)
        self.records.append(CheckpointRecord(
            cell=cell_num,
            directory=self.directory,
            output=output.stdout.strip(),
        ))
        if output.stdout.strip():
            print(output.stdout.strip(), flush=True)
        if output.has_error:
            print(f"[checkpoint] warning: {output.error.ename}: {output.error.evalue}", flush=True)

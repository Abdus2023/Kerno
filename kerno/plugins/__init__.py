# kerno/plugins/__init__.py
"""
kerno plugin system.

A plugin is any Python object with a `name` attribute
and optional lifecycle hooks.

Built-in plugin points:
  - on_session_start(task, session_id)
  - on_cell_complete(cell)
  - on_error(cell, classified_error)
  - on_session_complete(result)
  - on_skill_load(skill_name)

Usage:
    from kerno.plugins import PluginRegistry, BasePlugin

    class MyPlugin(BasePlugin):
        name = "my_logger"

        def on_cell_complete(self, cell):
            print("Cell {}: {}".format(cell.cell_num, cell.output.as_text(50)))

    registry = PluginRegistry()
    registry.register(MyPlugin())

    # Pass to loop
    loop = ReactiveLoop(kernel=kernel, llm=llm, plugins=registry)
"""

from kerno.plugins.registry import PluginRegistry, BasePlugin

__all__ = ["PluginRegistry", "BasePlugin"]

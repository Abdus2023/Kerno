"""Unit tests for the Plugin system."""

import pytest
from kerno.plugins.registry import (
    BasePlugin, PluginRegistry,
    TimingPlugin, CostEstimatorPlugin, NotebookPlugin,
)


class TestBasePlugin:
    """Tests for the BasePlugin ABC."""

    def test_default_name(self):
        p = BasePlugin()
        assert p.name == "unnamed_plugin"

    def test_all_hooks_are_noop(self):
        p = BasePlugin()
        # All hooks should not raise
        p.on_session_start("test task", "sid-123")
        p.on_cell_complete(None)
        p.on_error(None, None)
        p.on_session_complete(None)
        p.on_skill_load("data_skills")

    def test_custom_name(self):
        class MyPlugin(BasePlugin):
            name = "my_plugin"
        p = MyPlugin()
        assert p.name == "my_plugin"


class TestPluginRegistry:
    """Tests for the PluginRegistry."""

    def test_register_and_len(self):
        reg = PluginRegistry()
        assert len(reg) == 0
        p1 = BasePlugin()
        p1.name = "plugin_a"
        result = reg.register(p1)
        assert len(reg) == 1
        assert result is reg  # chaining

    def test_register_multiple(self):
        reg = PluginRegistry()
        p1 = BasePlugin()
        p1.name = "a"
        p2 = BasePlugin()
        p2.name = "b"
        reg.register(p1).register(p2)
        assert len(reg) == 2

    def test_unregister_existing(self):
        reg = PluginRegistry()
        p = BasePlugin()
        p.name = "removable"
        reg.register(p)
        assert reg.unregister("removable") is True
        assert len(reg) == 0

    def test_unregister_nonexistent(self):
        reg = PluginRegistry()
        assert reg.unregister("ghost") is False

    def test_dispatch_calls_hooks(self):
        called = []

        class Tracker(BasePlugin):
            name = "tracker"
            def on_session_start(self, task, session_id):
                called.append(("start", task, session_id))
            def on_cell_complete(self, cell):
                called.append(("cell", cell))
            def on_session_complete(self, result):
                called.append(("complete", result))
            def on_skill_load(self, skill_name):
                called.append(("skill", skill_name))

        reg = PluginRegistry()
        reg.register(Tracker())

        reg.on_session_start("test task", "sid-1")
        reg.on_cell_complete("cell_obj")
        reg.on_session_complete("result_obj")
        reg.on_skill_load("ml_skills")

        assert len(called) == 4
        assert called[0] == ("start", "test task", "sid-1")
        assert called[1] == ("cell", "cell_obj")
        assert called[2] == ("complete", "result_obj")
        assert called[3] == ("skill", "ml_skills")

    def test_dispatch_catches_plugin_errors(self):
        """Plugin errors must not interrupt the session."""
        class BadPlugin(BasePlugin):
            name = "bad"
            def on_session_start(self, task, session_id):
                raise RuntimeError("boom")

        class GoodPlugin(BasePlugin):
            name = "good"
            def on_session_start(self, task, session_id):
                pass

        reg = PluginRegistry()
        reg.register(BadPlugin())
        reg.register(GoodPlugin())

        # Should not raise — bad plugin error is caught and logged
        reg.on_session_start("test", "sid")

    def test_dispatch_error_hook(self):
        called = []

        class Tracker(BasePlugin):
            name = "tracker"
            def on_error(self, cell, classified_error):
                called.append(("error", cell, classified_error))

        reg = PluginRegistry()
        reg.register(Tracker())
        reg.on_error("cell_obj", "classified_obj")
        assert called[0] == ("error", "cell_obj", "classified_obj")


class TestTimingPlugin:
    """Tests for the TimingPlugin."""

    def test_name(self):
        p = TimingPlugin()
        assert p.name == "timing"

    def test_on_session_start(self):
        p = TimingPlugin()
        p.on_session_start("task", "sid")
        assert p._session_start > 0


class TestCostEstimatorPlugin:
    """Tests for the CostEstimatorPlugin."""

    def test_name(self):
        p = CostEstimatorPlugin()
        assert p.name == "cost_estimator"

    def test_custom_model(self):
        p = CostEstimatorPlugin(model="gpt-4o")
        assert p.model == "gpt-4o"

    def test_costs_dict(self):
        p = CostEstimatorPlugin()
        assert "claude-opus-4-5" in p.COSTS
        assert "gpt-4o" in p.COSTS


class TestNotebookPlugin:
    """Tests for the NotebookPlugin."""

    def test_name(self):
        p = NotebookPlugin()
        assert p.name == "notebook_writer"

    def test_custom_path(self):
        p = NotebookPlugin(path="custom/path.ipynb")
        assert p._path == "custom/path.ipynb"


class TestPluginImports:
    """Verify plugin imports from expected places."""

    def test_import_from_kerno_init(self):
        from kerno import PluginRegistry, BasePlugin
        assert PluginRegistry is not None
        assert BasePlugin is not None

    def test_import_builtins_from_kerno_init(self):
        from kerno import TimingPlugin, CostEstimatorPlugin, NotebookPlugin
        assert TimingPlugin is not None
        assert CostEstimatorPlugin is not None
        assert NotebookPlugin is not None

    def test_import_from_plugins_init(self):
        from kerno.plugins import PluginRegistry, BasePlugin
        assert PluginRegistry is not None
        assert BasePlugin is not None

"""
Unit tests for the provenance graph (audit #39, K-006):

    "Where did this artifact come from?"
    artifact → execution → action → task
"""

import pytest

from kerno.execution.engine import ExecutionEngine
from kerno.provenance import (
    KIND_ACTION, KIND_ARTIFACT, KIND_CODE, KIND_EXECUTION, KIND_TASK,
    ProvenanceGraph, ProvenanceGraphError,
)
from kerno.types import CellOutput


class FakeKernel:
    def __init__(self):
        self.calls = []

    def execute(self, code, timeout=120.0, silent=False):
        self.calls.append(code)
        return CellOutput(stdout="ok")

    def execute_silent(self, code, timeout=15.0):
        return "ok"

    @property
    def namespace(self):
        return "{}"

    @property
    def is_alive(self):
        return True


class TestGraphBasics:

    def test_add_node_and_retrieve(self):
        g = ProvenanceGraph()
        node = g.add_node("task-1", KIND_TASK, attrs={"task": "build model"})
        assert g.node("task-1") is node
        assert node.kind == KIND_TASK

    def test_duplicate_node_rejected(self):
        g = ProvenanceGraph()
        g.add_node("task-1", KIND_TASK)
        with pytest.raises(ProvenanceGraphError):
            g.add_node("task-1", KIND_TASK)

    def test_edge_requires_known_nodes(self):
        g = ProvenanceGraph()
        g.add_node("a", KIND_TASK)
        with pytest.raises(ProvenanceGraphError):
            g.add_edge("a", "missing")
        with pytest.raises(ProvenanceGraphError):
            g.add_edge("missing", "a")

    def test_parents_and_children(self):
        g = ProvenanceGraph()
        g.add_node("task", KIND_TASK)
        g.add_node("action", KIND_ACTION)
        g.add_edge("action", "task")
        assert g.parents("action") == ["task"]
        assert g.children("task") == ["action"]


class TestTrace:
    """K-006: every artifact traces back to the execution that created it."""

    def _build_report_chain(self):
        g = ProvenanceGraph()
        g.add_node("task-abc123", KIND_TASK, attrs={"task": "analyze sales"})
        g.add_node("act-0047", KIND_ACTION, attrs={"action_id": "act_0047"})
        g.add_edge("act-0047", "task-abc123")
        g.add_node("code-1", KIND_CODE, attrs={"code_hash": "abc..."})
        g.add_edge("code-1", "act-0047")
        g.add_node("exec_00000042", KIND_EXECUTION,
                   attrs={"execution_id": "exec_00000042"})
        g.add_edge("exec_00000042", "code-1")
        g.add_node("report.pdf", KIND_ARTIFACT, attrs={"sha256": "f00d"})
        g.add_edge("report.pdf", "exec_00000042")
        return g

    def test_artifact_traces_to_task(self):
        g = self._build_report_chain()
        chain = g.trace("report.pdf")
        assert [c["kind"] for c in chain] == [
            KIND_ARTIFACT, KIND_EXECUTION, KIND_CODE, KIND_ACTION, KIND_TASK,
        ]
        assert chain[-1]["node_id"] == "task-abc123"

    def test_lineage_kinds(self):
        g = self._build_report_chain()
        assert g.lineage("report.pdf") == [
            KIND_TASK, KIND_ACTION, KIND_CODE, KIND_EXECUTION, KIND_ARTIFACT,
        ]

    def test_unknown_node_trace_is_empty(self):
        g = ProvenanceGraph()
        assert g.trace("ghost") == []


class TestCycleGuard:
    """The graph must stay a DAG."""

    def test_cycle_rejected(self):
        g = ProvenanceGraph()
        g.add_node("a", KIND_TASK)
        g.add_node("b", KIND_ACTION)
        g.add_edge("a", "b")
        with pytest.raises(ProvenanceGraphError, match="cycle"):
            g.add_edge("b", "a")  # would close the loop

    def test_self_loop_rejected(self):
        g = ProvenanceGraph()
        g.add_node("a", KIND_TASK)
        with pytest.raises(ProvenanceGraphError):
            g.add_edge("a", "a")

    def test_deeper_cycle_rejected(self):
        g = ProvenanceGraph()
        for nid in ("a", "b", "c"):
            g.add_node(nid, KIND_TASK)
        g.add_edge("b", "a")
        g.add_edge("c", "b")
        with pytest.raises(ProvenanceGraphError):
            g.add_edge("a", "c")  # a → c → b → a


class TestSerialization:

    def test_round_trip(self):
        g = ProvenanceGraph()
        g.add_node("task", KIND_TASK, attrs={"task": "t"})
        g.add_node("exec", KIND_EXECUTION)
        g.add_edge("exec", "task")

        g2 = ProvenanceGraph.from_dict(g.to_dict())

        assert g2.node("task").attrs == {"task": "t"}
        assert g2.parents("exec") == ["task"]
        # The chain still works after a round trip
        assert g2.trace("exec")[1]["node_id"] == "task"


class TestEngineIntegration:
    """ExecutionEngine records execution nodes when a graph is attached."""

    def test_engine_records_execution_nodes(self):
        graph  = ProvenanceGraph()
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel, provenance=graph)

        engine.execute("x = 1", capabilities=frozenset())
        engine.execute("y = 2", capabilities=frozenset())

        exec_nodes = [
            n for n in graph.nodes if n.kind == KIND_EXECUTION
        ]
        assert len(exec_nodes) == 2
        assert exec_nodes[0].node_id == "exec_00000001"
        assert exec_nodes[0].attrs["origin"] == "agent"
        assert len(exec_nodes[0].attrs["code_hash"]) == 16

    def test_engine_trace_links_artifact_to_execution(self):
        graph  = ProvenanceGraph()
        kernel = FakeKernel()
        engine = ExecutionEngine(kernel, provenance=graph)

        graph.add_node("task-1", KIND_TASK, attrs={"task": "report"})
        graph.add_node("act-1", KIND_ACTION, attrs={"action_id": "act_1"})
        graph.add_edge("act-1", "task-1")

        engine.execute("df = load_data()", capabilities=frozenset())
        exec_id = "exec_00000001"

        graph.add_edge(exec_id, "act-1")
        graph.add_node("report.csv", KIND_ARTIFACT, attrs={"sha256": "x"})
        graph.add_edge("report.csv", exec_id)

        chain = graph.trace("report.csv")
        kinds = [c["kind"] for c in chain]
        assert kinds == [
            KIND_ARTIFACT, KIND_EXECUTION, KIND_ACTION, KIND_TASK,
        ]
        # The execution node is exactly the one the engine recorded
        assert chain[1]["node_id"] == exec_id

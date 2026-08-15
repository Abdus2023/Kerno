# kerno/graph.py
"""
Pipeline visualization: inspect and render pipeline structure.

Before running a pipeline, you can visualize its graph —
see which steps connect, detect missing execute steps,
and export for Mermaid or ASCII rendering.

Usage:
    from kerno.graph import PipelineGraph

    graph = PipelineGraph.from_pipeline(my_pipeline)
    print(graph.ascii())
    print(graph.mermaid())
    graph.validate()  # Raises if no execute step found
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from kerno.interfaces import AgentState, Step
from kerno.pipeline import Pipeline, LoopStep, ConditionalStep, RetryStep


# ── GraphNode ─────────────────────────────────────────────────────────────────

@dataclass
class GraphNode:
    """A node in the pipeline graph."""
    name:      str
    kind:      str      # "step", "pipeline", "loop", "conditional", "retry"
    children:  list[GraphNode] = field(default_factory=list)
    metadata:  dict            = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to a nested dict for JSON serialization."""
        result = {
            "name": self.name,
            "kind": self.kind,
        }
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        if self.children:
            result["children"] = [c.to_dict() for c in self.children]
        return result


# ── PipelineGraph ─────────────────────────────────────────────────────────────

class PipelineGraph:
    """
    Build and render the graph of a Pipeline's step structure.

    Supports:
      - ASCII rendering (terminal-friendly)
      - Mermaid rendering (markdown-friendly)
      - Dict export (JSON-friendly)
      - Validation (warns if no execute step)
    """

    def __init__(self, root: GraphNode):
        self.root = root

    @classmethod
    def from_pipeline(cls, pipeline: Pipeline) -> "PipelineGraph":
        """Build a graph from a Pipeline object."""
        children = []
        for step in pipeline.steps:
            children.append(cls._build_node(step))
        root = GraphNode(
            name="pipeline",
            kind="pipeline",
            children=children,
        )
        return cls(root)

    @classmethod
    def _build_node(cls, step: Step) -> GraphNode:
        """Recursively build a GraphNode from a Step."""
        name = type(step).__name__

        if isinstance(step, Pipeline):
            children = [cls._build_node(s) for s in step.steps]
            return GraphNode(
                name=name,
                kind="pipeline",
                children=children,
                metadata={"n_steps": len(step.steps)},
            )

        if isinstance(step, LoopStep):
            inner = cls._build_node(step.step)
            return GraphNode(
                name=name,
                kind="loop",
                children=[inner],
                metadata={
                    "max_iterations": step.max_iterations,
                },
            )

        if isinstance(step, ConditionalStep):
            true_node  = cls._build_node(step.if_true)
            false_node = cls._build_node(step.if_false)
            return GraphNode(
                name=name,
                kind="conditional",
                children=[true_node, false_node],
            )

        if isinstance(step, RetryStep):
            inner = cls._build_node(step.step)
            return GraphNode(
                name=name,
                kind="retry",
                children=[inner],
                metadata={"max_retries": step.max_retries},
            )

        # Regular step
        return GraphNode(
            name=name,
            kind="step",
        )

    # ── Rendering ─────────────────────────────────────────────────────────────

    def ascii(self) -> str:
        """Render the pipeline as an ASCII tree."""
        lines = []
        self._ascii_node(self.root, lines, prefix="", is_last=True)
        return "\n".join(lines)

    def _ascii_node(
        self,
        node:   GraphNode,
        lines:  list[str],
        prefix: str,
        is_last: bool,
    ) -> None:
        connector = "└── " if is_last else "├── "
        child_prefix = "    " if is_last else "│   "

        label = node.name
        if node.kind == "loop":
            label += " (max={})".format(
                node.metadata.get("max_iterations", "?")
            )
        elif node.kind == "retry":
            label += " (retries={})".format(
                node.metadata.get("max_retries", "?")
            )
        elif node.kind == "conditional":
            label += " (if/else)"

        lines.append("{}{}{}".format(prefix, connector, label))

        # Render children with if/else labels for conditionals
        for i, child in enumerate(node.children):
            last = i == len(node.children) - 1
            child_line_prefix = prefix + child_prefix

            if node.kind == "conditional":
                branch_label = "if_true" if i == 0 else "if_false"
                lines.append("{}{}{}".format(
                    child_line_prefix,
                    "└── " if last else "├── ",
                    branch_label,
                ))
                inner_prefix = child_line_prefix + ("    " if last else "│   ")
                self._ascii_node(child, lines, inner_prefix, is_last=True)
            else:
                self._ascii_node(child, lines, child_line_prefix, is_last=last)

    def mermaid(self) -> str:
        """Render the pipeline as a Mermaid flowchart."""
        lines = ["flowchart TD"]
        self._mermaid_node(self.root, lines, parent_id=None)
        return "\n".join(lines)

    def _mermaid_node(
        self,
        node:      GraphNode,
        lines:     list[str],
        parent_id: Optional[str],
    ) -> str:
        node_id = "N{}_{}".format(
            abs(hash(node.name)) % 10000,
            node.kind,
        )

        # Shape by kind
        shapes = {
            "step":       ("[", "]"),
            "pipeline":   ("{{", "}}"),
            "loop":       ("[[", "]]"),
            "conditional":("{", "}"),
            "retry":      ("[[", "]]"),
        }
        left, right = shapes.get(node.kind, ("[", "]"))

        label = node.name
        if node.kind == "loop":
            label += "\\nmax={}".format(node.metadata.get("max_iterations", "?"))
        elif node.kind == "retry":
            label += "\\nretries={}".format(node.metadata.get("max_retries", "?"))

        lines.append("    {}{}{}{}{}".format(node_id, left, label, right, node_id))

        if parent_id:
            lines.append("    {} --> {}".format(parent_id, node_id))

        if node.kind == "conditional" and len(node.children) == 2:
            true_id = self._mermaid_node(node.children[0], lines, node_id)
            false_id = self._mermaid_node(node.children[1], lines, node_id)
            lines.append("    {} -- if_true --> {}".format(node_id, true_id))
            lines.append("    {} -- if_false --> {}".format(node_id, false_id))
        else:
            for child in node.children:
                self._mermaid_node(child, lines, node_id)

        return node_id

    # ── Export ─────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Export the graph as a nested dict."""
        return self.root.to_dict()

    # ── Validation ─────────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """
        Validate the pipeline graph.
        Returns a list of warning messages (empty if valid).
        """
        warnings = []
        step_names = self._collect_step_names(self.root)

        # Check: must have an execute step
        has_execute = any("Execute" in name for name in step_names)
        if not has_execute:
            warnings.append(
                "Pipeline has no ExecuteStep — generated code will not be run"
            )

        # Check: must have a generate step
        has_generate = any("Generate" in name or "Reflect" in name for name in step_names)
        if not has_generate:
            warnings.append(
                "Pipeline has no code generation step — no code will be produced"
            )

        return warnings

    def _collect_step_names(self, node: GraphNode) -> list[str]:
        """Collect all step names from the graph."""
        names = []
        if node.kind == "step":
            names.append(node.name)
        for child in node.children:
            names.extend(self._collect_step_names(child))
        return names

    # ── Summary ────────────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """Return a summary of the pipeline structure."""
        counts = self._count_by_kind(self.root)
        return {
            "total_steps": sum(counts.values()),
            "step_types": counts,
            "has_execute": any("Execute" in n for n in self._collect_step_names(self.root)),
            "has_generate": any(
                "Generate" in n or "Reflect" in n
                for n in self._collect_step_names(self.root)
            ),
        }

    def _count_by_kind(self, node: GraphNode) -> dict[str, int]:
        """Count nodes by kind."""
        counts = {}
        if node.kind != "pipeline":
            counts[node.kind] = 1
        for child in node.children:
            for k, v in self._count_by_kind(child).items():
                counts[k] = counts.get(k, 0) + v
        return counts

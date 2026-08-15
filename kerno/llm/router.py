"""
TaskAwareRouter: route requests to models based on task analysis.

Routing rules:
  - Code generation tasks  → models strong at coding
  - Statistical analysis   → models with math strength
  - Document summarization → fast/cheap models sufficient
  - Planning               → reasoning-strong models
  - Unknown/simple         → cheapest available

Replaces the simple ModelRouter (which routes on message length)
with semantic task analysis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing      import Callable, Optional

from kerno.types import Message


@dataclass
class RoutingRule:
    """A rule that maps task patterns to a model."""
    name:       str
    patterns:   list[str]     # Regex patterns to match against task
    model:      str           # OpenRouter model ID to use
    reason:     str           # Human-readable explanation
    priority:   int = 0       # Higher = checked first


class TaskAwareRouter:
    """
    Routes LLM calls to appropriate models based on task content.

    Works seamlessly as a drop-in LLM callable.
    Logs routing decisions for debugging.

    Usage:
        router = TaskAwareRouter(
            default_model    = "anthropic/claude-opus-4-5",
            cheap_model      = "meta-llama/llama-3.1-8b-instruct",
            api_key          = os.environ["OPENROUTER_API_KEY"],
        )
        result = run("Analyze sales data", llm=router)
    """

    DEFAULT_RULES = [
        RoutingRule(
            name     = "complex_ml",
            patterns = [
                r"train.*model", r"neural.network", r"deep.learning",
                r"backprop", r"gradient.descent", r"architecture",
            ],
            model    = "anthropic/claude-opus-4-5",
            reason   = "ML tasks need strong reasoning",
            priority = 10,
        ),
        RoutingRule(
            name     = "statistical_analysis",
            patterns = [
                r"hypothesis.test", r"p.value", r"confidence.interval",
                r"bayesian", r"regression.*coefficient", r"anova",
            ],
            model    = "anthropic/claude-opus-4-5",
            reason   = "Statistical tasks need mathematical precision",
            priority = 9,
        ),
        RoutingRule(
            name     = "planning",
            patterns = [
                r"^plan\b", r"decompose", r"strategy", r"architecture",
                r"design.*system", r"how.*should.*approach",
            ],
            model    = "anthropic/claude-opus-4-5",
            reason   = "Planning tasks need strategic thinking",
            priority = 8,
        ),
        RoutingRule(
            name     = "code_generation",
            patterns = [
                r"write.*function", r"implement.*class", r"create.*script",
                r"refactor", r"debug.*code",
            ],
            model    = "openai/gpt-4o",
            reason   = "Code generation — GPT-4o is strong here",
            priority = 7,
        ),
        RoutingRule(
            name     = "data_profiling",
            patterns = [
                r"profile.*data", r"describe.*dataframe", r"show.*columns",
                r"head\(\)", r"shape\b",
            ],
            model    = "meta-llama/llama-3.1-70b-instruct",
            reason   = "Simple data inspection — cheaper model sufficient",
            priority = 5,
        ),
        RoutingRule(
            name     = "summarization",
            patterns = [
                r"summarize", r"tldr", r"brief.*overview",
                r"what.*key.*finding", r"main.*point",
            ],
            model    = "meta-llama/llama-3.1-70b-instruct",
            reason   = "Summarization — cheaper model sufficient",
            priority = 4,
        ),
        RoutingRule(
            name     = "visualization",
            patterns = [
                r"plot\b", r"chart\b", r"visualize", r"histogram",
                r"scatter", r"heatmap",
            ],
            model    = "anthropic/claude-haiku-4-5",
            reason   = "Plotting code — haiku is fast and sufficient",
            priority = 3,
        ),
    ]

    def __init__(
        self,
        default_model:    str,
        api_key:          Optional[str] = None,
        cheap_model:      Optional[str] = None,
        custom_rules:     list[RoutingRule] = None,
        verbose:          bool = False,
    ):
        self.default_model = default_model
        self.cheap_model   = cheap_model or "meta-llama/llama-3.1-8b-instruct:free"
        self.api_key       = api_key
        self.verbose       = verbose
        self._rules        = sorted(
            (custom_rules or []) + self.DEFAULT_RULES,
            key=lambda r: r.priority,
            reverse=True,
        )
        self._llm_cache:   dict[str, Callable] = {}
        self._routing_log: list[dict]          = []

    def __call__(self, messages: list[Message]) -> str:
        """Route and call. Acts as a standard LLM callable."""
        model, reason = self._route(messages)
        llm           = self._get_llm(model)

        if self.verbose:
            task_preview = messages[-1].content[:60] if messages else ""
            print(f"[router] {model} ← {reason} | {task_preview}")

        self._routing_log.append({
            "model":    model,
            "reason":   reason,
            "task_len": len(messages[-1].content) if messages else 0,
        })

        return llm(messages)

    @property
    def routing_stats(self) -> dict:
        """Summary of routing decisions made so far."""
        from collections import Counter
        models = Counter(r["model"] for r in self._routing_log)
        return {
            "total_calls": len(self._routing_log),
            "by_model":    dict(models),
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _route(self, messages: list[Message]) -> tuple[str, str]:
        """Determine which model to use for these messages."""
        # Use last few messages for routing analysis
        text = " ".join(
            m.content[:500]
            for m in messages[-3:]
            if m.role != "system"
        ).lower()

        for rule in self._rules:
            if any(re.search(p, text, re.I) for p in rule.patterns):
                return rule.model, rule.reason

        return self.default_model, "default"

    def _get_llm(self, model: str) -> Callable:
        """Get or create a cached LLM for a model."""
        if model not in self._llm_cache:
            from kerno.llm.openrouter import openrouter_llm
            self._llm_cache[model] = openrouter_llm(
                model   = model,
                api_key = self.api_key,
            )
        return self._llm_cache[model]


class CostTrackingRouter:
    """
    Wraps any LLM and tracks estimated cost per call.
    Useful for production cost monitoring.
    """

    # Approximate cost per 1M tokens (input/output) as of 2024
    PRICING = {
        "anthropic/claude-opus-4-5":       {"in": 15.00, "out": 75.00},
        "anthropic/claude-sonnet-4-5":     {"in": 3.00,  "out": 15.00},
        "anthropic/claude-haiku-4-5":      {"in": 0.25,  "out": 1.25},
        "openai/gpt-4o":                   {"in": 5.00,  "out": 15.00},
        "openai/gpt-4o-mini":              {"in": 0.15,  "out": 0.60},
        "meta-llama/llama-3.1-70b-instruct":{"in": 0.59,  "out": 0.79},
        "meta-llama/llama-3.1-8b-instruct": {"in": 0.07,  "out": 0.07},
        "meta-llama/llama-3-8b-instruct:free": {"in": 0.0, "out": 0.0},
    }

    def __init__(self, llm: Callable, model: str = "unknown"):
        self.llm            = llm
        self.model          = model
        self.total_cost     = 0.0
        self.total_calls    = 0
        self.total_in_toks  = 0
        self.total_out_toks = 0

    def __call__(self, messages: list[Message]) -> str:
        response = self.llm(messages)

        # Estimate tokens (rough: 1 token ≈ 4 chars)
        in_toks  = sum(len(m.content) // 4 for m in messages)
        out_toks = len(response) // 4

        pricing = self.PRICING.get(self.model, {"in": 10.0, "out": 30.0})
        cost    = (
            in_toks  / 1_000_000 * pricing["in"] +
            out_toks / 1_000_000 * pricing["out"]
        )

        self.total_cost     += cost
        self.total_calls    += 1
        self.total_in_toks  += in_toks
        self.total_out_toks += out_toks

        return response

    def cost_report(self) -> str:
        return (
            f"Cost report — {self.model}\n"
            f"  Calls:        {self.total_calls}\n"
            f"  Input tokens: {self.total_in_toks:,}\n"
            f"  Output tokens:{self.total_out_toks:,}\n"
            f"  Total cost:   ${self.total_cost:.4f}"
        )

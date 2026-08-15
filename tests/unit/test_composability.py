"""Unit tests for the composability redesign modules."""

import pytest
import copy


# ── interfaces.py ──────────────────────────────────────────────────────────────

class TestAgentState:
    """Tests for the AgentState dataclass."""

    def test_default_values(self):
        from kerno.interfaces import AgentState
        state = AgentState(task="test")
        assert state.task == "test"
        assert state.history == []
        assert state.namespace == "{}"
        assert state.summary == ""
        assert state.session_id == ""
        assert state.complete is False
        assert state.error is None
        assert state.metadata == {}

    def test_custom_values(self):
        from kerno.interfaces import AgentState
        state = AgentState(
            task="my task",
            history=[1, 2, 3],
            namespace="{x: 1}",
            summary="done",
            session_id="sid-1",
            complete=True,
        )
        assert state.task == "my task"
        assert state.history == [1, 2, 3]
        assert state.complete is True

    def test_metadata_is_mutable(self):
        from kerno.interfaces import AgentState
        state = AgentState(task="test")
        state.metadata["last_code"] = "x = 1"
        assert state.metadata["last_code"] == "x = 1"

    def test_two_states_independent(self):
        from kerno.interfaces import AgentState
        s1 = AgentState(task="a")
        s2 = AgentState(task="b")
        s1.metadata["key"] = "val"
        assert "key" not in s2.metadata


class TestTransformContext:
    """Tests for the TransformContext dataclass."""

    def test_creation(self):
        from kerno.interfaces import TransformContext
        ctx = TransformContext(
            cell_num=1,
            session_id="sid",
            namespace="{}",
            history=[],
            task="test",
        )
        assert ctx.cell_num == 1
        assert ctx.session_id == "sid"


class TestProtocolInterfaces:
    """Tests for runtime-checkable Protocol interfaces."""

    def test_llm_protocol(self):
        from kerno.interfaces import LLM
        class MyLLM:
            def __call__(self, messages):
                return "hello"
        assert isinstance(MyLLM(), LLM)

    def test_executor_protocol(self):
        from kerno.interfaces import Executor
        class MyExecutor:
            def execute(self, code, **kwargs):
                return None
            def execute_silent(self, code, **kwargs):
                return ""
            @property
            def namespace(self):
                return "{}"
            @property
            def is_alive(self):
                return True
        assert isinstance(MyExecutor(), Executor)

    def test_step_protocol(self):
        from kerno.interfaces import Step
        class MyStep:
            def run(self, state):
                return state
        assert isinstance(MyStep(), Step)

    def test_cell_transformer_protocol(self):
        from kerno.interfaces import CellTransformer
        class MyTransformer:
            def transform(self, code, context):
                return code
        assert isinstance(MyTransformer(), CellTransformer)

    def test_output_formatter_protocol(self):
        from kerno.interfaces import OutputFormatter
        class MyFormatter:
            def format(self, output, **kwargs):
                return "formatted"
        assert isinstance(MyFormatter(), OutputFormatter)

    def test_skill_protocol(self):
        from kerno.interfaces import Skill
        class MySkill:
            @property
            def name(self):
                return "test"
            @property
            def code(self):
                return "x = 1"
            @property
            def dependencies(self):
                return []
        assert isinstance(MySkill(), Skill)

    def test_context_strategy_protocol(self):
        from kerno.interfaces import ContextStrategy
        class MyStrategy:
            def build(self, task, history, namespace, summary):
                return []
        assert isinstance(MyStrategy(), ContextStrategy)

    def test_memory_protocol(self):
        from kerno.interfaces import Memory
        class MyMemory:
            def store(self, entry):
                return "id"
            def retrieve(self, query, k, **kwargs):
                return []
        assert isinstance(MyMemory(), Memory)


# ── pipeline.py ────────────────────────────────────────────────────────────────

class TestPipeline:
    """Tests for Pipeline composition."""

    def test_empty_pipeline(self):
        from kerno.pipeline import Pipeline
        from kerno.interfaces import AgentState
        state = AgentState(task="test")
        result = Pipeline([]).run(state)
        assert result.task == "test"

    def test_single_step(self):
        from kerno.pipeline import Pipeline
        from kerno.interfaces import AgentState

        class MarkStep:
            def run(self, state):
                state.metadata["mark"] = True
                return state

        state = AgentState(task="test")
        result = Pipeline([MarkStep()]).run(state)
        assert result.metadata["mark"] is True

    def test_multi_step_pipeline(self):
        from kerno.pipeline import Pipeline
        from kerno.interfaces import AgentState

        class CounterStep:
            def __init__(self, key):
                self.key = key
            def run(self, state):
                state.metadata[self.key] = state.metadata.get("count", 0)
                state.metadata["count"] = state.metadata.get("count", 0) + 1
                return state

        state = AgentState(task="test")
        result = Pipeline([
            CounterStep("a"), CounterStep("b"), CounterStep("c")
        ]).run(state)
        assert result.metadata["a"] == 0
        assert result.metadata["b"] == 1
        assert result.metadata["c"] == 2
        assert result.metadata["count"] == 3

    def test_pipeline_stops_on_complete(self):
        from kerno.pipeline import Pipeline
        from kerno.interfaces import AgentState

        class CompleteStep:
            def run(self, state):
                state.complete = True
                return state

        class NeverReachedStep:
            def run(self, state):
                state.metadata["reached"] = True
                return state

        state = AgentState(task="test")
        result = Pipeline([CompleteStep(), NeverReachedStep()]).run(state)
        assert result.complete is True
        assert "reached" not in result.metadata

    def test_pipeline_stops_on_error(self):
        from kerno.pipeline import Pipeline
        from kerno.interfaces import AgentState

        class ErrorStep:
            def run(self, state):
                state.error = "boom"
                return state

        class NeverReachedStep:
            def run(self, state):
                state.metadata["reached"] = True
                return state

        state = AgentState(task="test")
        result = Pipeline([ErrorStep(), NeverReachedStep()]).run(state)
        assert result.error == "boom"
        assert "reached" not in result.metadata

    def test_then_method(self):
        from kerno.pipeline import Pipeline, IdentityStep
        p1 = Pipeline([IdentityStep()])
        p2 = p1.then(IdentityStep())
        assert len(p2.steps) == 2

    def test_or_operator(self):
        from kerno.pipeline import Pipeline, IdentityStep
        p1 = Pipeline([IdentityStep()])
        p2 = p1 | IdentityStep()
        assert len(p2.steps) == 2

    def test_repr(self):
        from kerno.pipeline import Pipeline, IdentityStep
        p = Pipeline([IdentityStep()])
        assert "IdentityStep" in repr(p)


class TestIdentityStep:
    """Tests for IdentityStep."""

    def test_pass_through(self):
        from kerno.pipeline import IdentityStep
        from kerno.interfaces import AgentState
        state = AgentState(task="test")
        result = IdentityStep().run(state)
        assert result.task == "test"
        assert result is state


class TestConditionalStep:
    """Tests for ConditionalStep."""

    def test_if_true(self):
        from kerno.pipeline import ConditionalStep
        from kerno.interfaces import AgentState

        class MarkStep:
            def run(self, state):
                state.metadata["branch"] = "true"
                return state

        state = AgentState(task="test")
        result = ConditionalStep(
            condition=lambda s: True,
            if_true=MarkStep(),
        ).run(state)
        assert result.metadata["branch"] == "true"

    def test_if_false(self):
        from kerno.pipeline import ConditionalStep
        from kerno.interfaces import AgentState

        class MarkStep:
            def run(self, state):
                state.metadata["branch"] = "false"
                return state

        state = AgentState(task="test")
        result = ConditionalStep(
            condition=lambda s: False,
            if_true=MarkStep(),
            if_false=MarkStep(),
        ).run(state)
        assert result.metadata["branch"] == "false"

    def test_default_false_branch_is_identity(self):
        from kerno.pipeline import ConditionalStep, IdentityStep
        from kerno.interfaces import AgentState
        state = AgentState(task="test")
        result = ConditionalStep(
            condition=lambda s: False,
            if_true=IdentityStep(),
        ).run(state)
        assert result.task == "test"


class TestLoopStep:
    """Tests for LoopStep."""

    def test_loop_completes(self):
        from kerno.pipeline import LoopStep
        from kerno.interfaces import AgentState

        class CounterStep:
            def run(self, state):
                state.metadata["count"] = state.metadata.get("count", 0) + 1
                if state.metadata["count"] >= 3:
                    state.complete = True
                return state

        state = AgentState(task="test")
        result = LoopStep(
            CounterStep(),
            done=lambda s: s.complete,
            max_iterations=10,
        ).run(state)
        assert result.metadata["count"] == 3
        assert result.complete is True

    def test_loop_respects_max_iterations(self):
        from kerno.pipeline import LoopStep
        from kerno.interfaces import AgentState

        class NeverCompleteStep:
            def run(self, state):
                state.metadata["count"] = state.metadata.get("count", 0) + 1
                return state

        state = AgentState(task="test")
        result = LoopStep(
            NeverCompleteStep(),
            done=lambda s: s.complete,
            max_iterations=5,
        ).run(state)
        assert result.metadata["count"] == 5


class TestRetryStep:
    """Tests for RetryStep."""

    def test_retry_succeeds(self):
        from kerno.pipeline import RetryStep
        from kerno.interfaces import AgentState

        class EventuallySucceeds:
            def __init__(self):
                self.attempts = 0
            def run(self, state):
                self.attempts += 1
                if self.attempts >= 2:
                    state.metadata["success"] = True
                    state.error = None
                else:
                    state.error = "fail"
                return state

        step = EventuallySucceeds()
        state = AgentState(task="test")
        result = RetryStep(step, max_retries=3).run(state)
        assert result.metadata.get("success") is True
        assert step.attempts == 2


# ── steps/ ──────────────────────────────────────────────────────────────────────

class TestTransformCodeStep:
    """Tests for TransformCodeStep and built-in transformers."""

    def test_normalization_removes_fences(self):
        from kerno.steps.transform import NormalizationTransformer
        from kerno.interfaces import TransformContext
        t = NormalizationTransformer()
        code = "```python\nx = 1\n```"
        result = t.transform(code, TransformContext(
            cell_num=1, session_id="s", namespace="{}",
            history=[], task="test"
        ))
        assert result == "x = 1"

    def test_normalization_no_fences(self):
        from kerno.steps.transform import NormalizationTransformer
        from kerno.interfaces import TransformContext
        t = NormalizationTransformer()
        code = "x = 1"
        result = t.transform(code, TransformContext(
            cell_num=1, session_id="s", namespace="{}",
            history=[], task="test"
        ))
        assert result == "x = 1"

    def test_transform_code_step_chaining(self):
        from kerno.steps.transform import TransformCodeStep, NormalizationTransformer
        from kerno.interfaces import AgentState

        class DoubleTransformer:
            def transform(self, code, ctx):
                return code + "\ny = 2"

        state = AgentState(task="test")
        state.metadata["last_code"] = "x = 1"
        result = TransformCodeStep([
            NormalizationTransformer(),
            DoubleTransformer(),
        ]).run(state)
        assert "x = 1" in result.metadata["last_code"]
        assert "y = 2" in result.metadata["last_code"]

    def test_auto_checkpoint_adds_for_fit(self):
        from kerno.steps.transform import AutoCheckpointTransformer
        from kerno.interfaces import TransformContext
        t = AutoCheckpointTransformer()
        code = "model.fit(X, y)"
        result = t.transform(code, TransformContext(
            cell_num=1, session_id="s", namespace="{}",
            history=[], task="test"
        ))
        assert "checkpoint" in result

    def test_auto_checkpoint_skips_normal_code(self):
        from kerno.steps.transform import AutoCheckpointTransformer
        from kerno.interfaces import TransformContext
        t = AutoCheckpointTransformer()
        code = "x = 1 + 2"
        result = t.transform(code, TransformContext(
            cell_num=1, session_id="s", namespace="{}",
            history=[], task="test"
        ))
        assert result == code


class TestCompletionCheckStep:
    """Tests for CompletionCheckStep."""

    def test_signal_detected(self):
        from kerno.steps.compress import CompletionCheckStep
        from kerno.interfaces import AgentState
        state = AgentState(task="test")
        state.metadata["last_code"] = "x = 1\n# TASK_COMPLETE: done"
        result = CompletionCheckStep().run(state)
        assert result.complete is True

    def test_no_signal(self):
        from kerno.steps.compress import CompletionCheckStep
        from kerno.interfaces import AgentState
        state = AgentState(task="test")
        state.metadata["last_code"] = "x = 1"
        result = CompletionCheckStep().run(state)
        assert result.complete is False


class TestDryRunExecuteStep:
    """Tests for DryRunExecuteStep."""

    def test_dry_run(self):
        from kerno.steps.execute import DryRunExecuteStep
        from kerno.interfaces import AgentState
        state = AgentState(task="test")
        state.metadata["last_code"] = "x = 1"
        result = DryRunExecuteStep().run(state)
        assert len(result.history) == 1
        assert result.history[0].author == "dry-run"
        assert result.history[0].output.stdout == "[dry-run: not executed]\n"


# ── FormatOutputStep ───────────────────────────────────────────────────────────

class TestAnomalyFlagFormatter:
    """Tests for AnomalyFlagFormatter."""

    def test_nulls_flagged(self):
        from kerno.steps.format import AnomalyFlagFormatter
        from kerno.types import CellOutput
        formatter = AnomalyFlagFormatter()
        output = CellOutput(stdout="Result has null values")
        result = formatter.format(output)
        assert "Null" in result

    def test_no_anomalies(self):
        from kerno.steps.format import AnomalyFlagFormatter
        from kerno.types import CellOutput
        formatter = AnomalyFlagFormatter()
        output = CellOutput(stdout="All clean")
        result = formatter.format(output)
        assert "⚠️" not in result


class TestDataShapeFormatter:
    """Tests for DataShapeFormatter."""

    def test_shape_detected(self):
        from kerno.steps.format import DataShapeFormatter
        from kerno.types import CellOutput
        formatter = DataShapeFormatter()
        output = CellOutput(stdout="Shape: (1234, 56)")
        result = formatter.format(output)
        assert "shapes" in result

    def test_no_shape(self):
        from kerno.steps.format import DataShapeFormatter
        from kerno.types import CellOutput
        formatter = DataShapeFormatter()
        output = CellOutput(stdout="No shape info")
        result = formatter.format(output)
        assert "shapes" not in result


# ── SkillSet ────────────────────────────────────────────────────────────────────

class TestSkillSet:
    """Tests for SkillSet composition."""

    def test_add_skill(self):
        from kerno.skills.composer import SkillSet, CodeSkill
        ss = SkillSet()
        skill = CodeSkill(name="test", code="x = 1")
        result = ss.add(skill)
        assert len(ss) == 1
        assert result is ss  # chaining

    def test_add_duplicate_skipped(self):
        from kerno.skills.composer import SkillSet, CodeSkill
        ss = SkillSet()
        ss.add(CodeSkill(name="test", code="x = 1"))
        ss.add(CodeSkill(name="test", code="y = 2"))  # same name, skipped
        assert len(ss) == 1

    def test_remove_skill(self):
        from kerno.skills.composer import SkillSet, CodeSkill
        ss = SkillSet()
        ss.add(CodeSkill(name="a", code="a"))
        ss.add(CodeSkill(name="b", code="b"))
        ss.remove("a")
        assert len(ss) == 1
        assert "a" not in ss.names()

    def test_replace_skill(self):
        from kerno.skills.composer import SkillSet, CodeSkill
        ss = SkillSet()
        ss.add(CodeSkill(name="test", code="v1"))
        ss.replace("test", CodeSkill(name="test", code="v2"))
        assert ss._skills["test"].code == "v2"

    def test_load_order_no_deps(self):
        from kerno.skills.composer import SkillSet, CodeSkill
        ss = SkillSet()
        ss.add(CodeSkill(name="a", code="a"))
        ss.add(CodeSkill(name="b", code="b"))
        ss.add(CodeSkill(name="c", code="c"))
        assert ss._load_order() == ["a", "b", "c"]

    def test_load_order_with_deps(self):
        from kerno.skills.composer import SkillSet, CodeSkill
        ss = SkillSet()
        ss.add(CodeSkill(name="viz", code="viz", dependencies=["data"]))
        ss.add(CodeSkill(name="data", code="data"))
        order = ss._load_order()
        assert order.index("data") < order.index("viz")

    def test_combined_code(self):
        from kerno.skills.composer import SkillSet, CodeSkill
        ss = SkillSet()
        ss.add(CodeSkill(name="a", code="x = 1"))
        ss.add(CodeSkill(name="b", code="y = 2"))
        combined = ss.combined_code()
        assert "x = 1" in combined
        assert "y = 2" in combined

    def test_or_merge(self):
        from kerno.skills.composer import SkillSet, CodeSkill
        s1 = SkillSet()
        s1.add(CodeSkill(name="a", code="a"))
        s2 = SkillSet()
        s2.add(CodeSkill(name="b", code="b"))
        merged = s1 | s2
        assert len(merged) == 2

    def test_or_merge_override(self):
        from kerno.skills.composer import SkillSet, CodeSkill
        s1 = SkillSet()
        s1.add(CodeSkill(name="a", code="v1"))
        s2 = SkillSet()
        s2.add(CodeSkill(name="a", code="v2"))
        merged = s1 | s2
        assert merged._skills["a"].code == "v2"

    def test_sub_remove(self):
        from kerno.skills.composer import SkillSet, CodeSkill
        ss = SkillSet()
        ss.add(CodeSkill(name="a", code="a"))
        ss.add(CodeSkill(name="b", code="b"))
        result = ss - ["a"]
        assert len(result) == 1
        assert "b" in result.names()

    def test_names(self):
        from kerno.skills.composer import SkillSet, CodeSkill
        ss = SkillSet()
        ss.add(CodeSkill(name="x", code="x"))
        ss.add(CodeSkill(name="y", code="y"))
        assert set(ss.names()) == {"x", "y"}


# ── LLM Wrappers ────────────────────────────────────────────────────────────────

class TestLLMWrappers:
    """Tests for LLM wrapper composition."""

    def test_logged_llm(self):
        from kerno.llm.wrappers import LoggedLLM
        from kerno.types import Message

        calls = []
        def base_llm(messages):
            calls.append(len(messages))
            return "response"

        logged = LoggedLLM(base_llm)
        result = logged([Message(role="user", content="hi")])
        assert result == "response"
        assert len(calls) == 1

    def test_cached_llm(self):
        from kerno.llm.wrappers import CachedLLM
        from kerno.types import Message

        call_count = [0]
        def base_llm(messages):
            call_count[0] += 1
            return "cached_response"

        cached = CachedLLM(base_llm)
        msgs = [Message(role="user", content="test")]
        r1 = cached(msgs)
        assert r1 == "cached_response"
        assert call_count[0] == 1
        # Second call with same messages should hit cache
        r2 = cached(msgs)
        assert r2 == "cached_response"
        assert call_count[0] == 1  # Not incremented (cached)
        assert cached.cache_size >= 1

    def test_cached_llm_clear(self):
        from kerno.llm.wrappers import CachedLLM
        from kerno.types import Message

        def base_llm(messages):
            return "r"

        cached = CachedLLM(base_llm)
        cached([Message(role="user", content="test")])
        cached.clear()
        assert cached.cache_size == 0

    def test_fallback_llm_primary_works(self):
        from kerno.llm.wrappers import FallbackLLM
        from kerno.types import Message

        def good_llm(messages):
            return "good"

        def bad_llm(messages):
            raise RuntimeError("fail")

        fb = FallbackLLM([good_llm, bad_llm])
        result = fb([Message(role="user", content="test")])
        assert result == "good"

    def test_fallback_llm_all_fail(self):
        from kerno.llm.wrappers import FallbackLLM
        from kerno.types import Message

        def bad1(messages):
            raise RuntimeError("fail1")
        def bad2(messages):
            raise RuntimeError("fail2")

        fb = FallbackLLM([bad1, bad2])
        with pytest.raises(RuntimeError, match="All LLMs failed"):
            fb([Message(role="user", content="test")])

    def test_model_router(self):
        from kerno.llm.wrappers import ModelRouter
        from kerno.types import Message

        def cheap(messages):
            return "cheap"
        def expensive(messages):
            return "expensive"

        router = ModelRouter([
            (lambda msgs: len(msgs) > 30, expensive),
            (lambda msgs: True, cheap),
        ])
        short_msgs = [Message(role="user", content="short")]
        result = router(short_msgs)
        assert result == "cheap"

    def test_rate_limited_llm(self):
        from kerno.llm.wrappers import RateLimitedLLM
        from kerno.types import Message

        call_count = [0]
        def base(messages):
            call_count[0] += 1
            return "r"

        rl = RateLimitedLLM(base, max_calls=100, time_window=60.0)
        rl([Message(role="user", content="test")])
        assert call_count[0] == 1

    def test_ensemble_llm(self):
        from kerno.llm.wrappers import EnsembleLLM
        from kerno.types import Message

        def llm1(messages):
            return "short"
        def llm2(messages):
            return "longer response with more detail"

        ens = EnsembleLLM([llm1, llm2])
        result = ens([Message(role="user", content="test")])
        # Default combiner picks longest
        assert "longer" in result


# ── compose.py Session builder ────────────────────────────────────────────────

class TestSessionBuilder:
    """Tests for Session builder pattern (without actually running)."""

    def test_builder_chaining(self):
        from kerno.compose import Session
        s = Session()
        result = s.with_loop("reflect", max_cells=30)
        assert result is s
        assert s._loop_strategy == "reflect"
        assert s._max_cells == 30

    def test_builder_verbose(self):
        from kerno.compose import Session
        s = Session()
        result = s.verbose(True)
        assert result is s
        assert s._verbose is True

    def test_builder_with_kernel(self):
        from kerno.compose import Session
        s = Session()
        s.with_kernel(kernel_name="python3")
        assert s._kernel_name == "python3"

    def test_builder_with_notebook(self):
        from kerno.compose import Session
        s = Session()
        s.with_notebook(save=True, directory="out")
        assert s._save_notebook is True
        assert s._notebook_dir == "out"

    def test_builder_with_plugins(self):
        from kerno.compose import Session
        from kerno.plugins.registry import TimingPlugin
        s = Session()
        s.with_plugins(TimingPlugin())
        assert s._plugins is not None
        assert len(s._plugins) == 1

    def test_run_without_llm_raises(self):
        from kerno.compose import Session
        s = Session()
        with pytest.raises(ValueError, match="No LLM configured"):
            s.run("test task")

    def test_builder_with_transformers(self):
        from kerno.compose import Session
        from kerno.steps.transform import NormalizationTransformer
        s = Session()
        s.with_transformers(NormalizationTransformer())
        assert len(s._transformers) == 1

    def test_builder_with_formatters(self):
        from kerno.compose import Session
        from kerno.steps.format import AnomalyFlagFormatter
        s = Session()
        s.with_formatters(AnomalyFlagFormatter())
        assert len(s._formatters) == 1


# ── Import checks ──────────────────────────────────────────────────────────────

class TestImports:
    """Verify all new modules can be imported."""

    def test_interfaces(self):
        from kerno.interfaces import (
            LLM, Executor, ContextStrategy, Memory,
            CellTransformer, OutputFormatter, Skill, Step,
            AgentState, TransformContext,
        )

    def test_pipeline(self):
        from kerno.pipeline import (
            Pipeline, IdentityStep, ConditionalStep,
            LoopStep, ParallelStep, RetryStep,
        )

    def test_steps(self):
        from kerno.steps import (
            GenerateCodeStep, ReflectAndGenerateStep,
            ExecuteStep, DryRunExecuteStep,
            TransformCodeStep, FormatOutputStep,
            InjectMemoryStep, StoreMemoryStep, StoreInsightStep,
            ReflectStep, PlanStep, VerifyStep,
            CompressHistoryStep, CompletionCheckStep,
        )

    def test_loop_factory(self):
        from kerno.loop.factory import (
            make_reactive, make_reflect,
            make_plan_execute, make_custom, is_complete,
        )

    def test_skill_composer(self):
        from kerno.skills.composer import (
            CodeSkill, FileSkill, ComposedSkill, SkillSet,
            minimal_skills, analysis_skills, ml_skills,
        )

    def test_llm_wrappers(self):
        from kerno.llm.wrappers import (
            LoggedLLM, CachedLLM, RetryLLM,
            FallbackLLM, RateLimitedLLM,
            EnsembleLLM, ModelRouter,
        )

    def test_llm_adapters(self):
        from kerno.llm.adapters import anthropic_llm, openai_llm, make_llm

    def test_compose(self):
        from kerno.compose import Session

"""Tests für Pipeline-Orchestrator."""

import pytest
from pathlib import Path
from typing import Any, Dict

from sequencer.context import PipelineContext
from sequencer.module import Module
from sequencer.pipeline import Pipeline, PipelineError


class DummyModule(Module):
    name = "dummy"
    description = "Test"
    category = "test"
    inputs = []
    outputs = ["dummy_out"]

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        ctx.set("dummy_out", "hello")


class ConsumerModule(Module):
    name = "consumer"
    description = "Test Consumer"
    category = "test"
    inputs = ["dummy_out"]
    outputs = ["result"]

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        val = ctx.get("dummy_out")
        ctx.set("result", f"got:{val}")


class FailingModule(Module):
    name = "failing"
    description = "Fails"
    category = "test"
    inputs = []
    outputs = []

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        raise ValueError("boom")


class SkippableModule(Module):
    name = "skippable"
    description = "Skip"
    category = "test"
    inputs = []
    outputs = ["skip_out"]

    def skip_condition(self, ctx, params):
        return params.get("skip", False)

    def run(self, ctx: PipelineContext, params: Dict[str, Any]) -> None:
        ctx.set("skip_out", "done")


class MissingInputModule(Module):
    name = "needs_foo"
    description = "Needs foo"
    category = "test"
    inputs = ["foo_data"]
    outputs = []

    def run(self, ctx, params):
        pass


# ── Tests ──

def _make_ctx():
    return PipelineContext(work_dir=Path("/tmp"), fps=25.0)


def test_simple_pipeline():
    ctx = _make_ctx()
    p = Pipeline([DummyModule(), ConsumerModule()], ctx)
    assert p.validate() == []
    p.run({})
    assert ctx.get("result") == "got:hello"


def test_validation_catches_missing_input():
    ctx = _make_ctx()
    p = Pipeline([MissingInputModule()], ctx)
    errors = p.validate()
    assert len(errors) == 1
    assert "foo_data" in errors[0]


def test_validation_ok_when_input_provided():
    ctx = _make_ctx()
    p = Pipeline([DummyModule(), ConsumerModule()], ctx)
    assert p.validate() == []


def test_pipeline_error_wraps_exception():
    ctx = _make_ctx()
    p = Pipeline([FailingModule()], ctx)
    with pytest.raises(PipelineError) as exc_info:
        p.run({})
    err = exc_info.value
    assert err.module == "failing"
    assert err.step == 0
    assert isinstance(err.original_error, ValueError)


def test_skip_condition():
    ctx = _make_ctx()
    p = Pipeline([SkippableModule()], ctx)
    p.run({"skippable": {"skip": True}})
    assert not ctx.has("skip_out")


def test_skip_condition_false_runs():
    ctx = _make_ctx()
    p = Pipeline([SkippableModule()], ctx)
    p.run({"skippable": {"skip": False}})
    assert ctx.get("skip_out") == "done"


def test_progress_callback():
    ctx = _make_ctx()
    calls = []

    def cb(frac, mod, msg):
        calls.append((frac, mod, msg))

    p = Pipeline([DummyModule()], ctx)
    p.run({}, progress_callback=cb)

    # Mindestens Start + Ende
    assert len(calls) >= 2
    assert calls[-1][0] == 1.0
    assert calls[-1][1] == "done"


def test_empty_pipeline():
    ctx = _make_ctx()
    p = Pipeline([], ctx)
    assert p.validate() == []
    p.run({})

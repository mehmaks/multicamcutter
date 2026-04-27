"""Tests für PipelineContext."""

import pytest
from pathlib import Path

from sequencer.context import PipelineContext


def test_set_and_get():
    ctx = PipelineContext(work_dir=Path("/tmp"), fps=25.0)
    ctx.set("foo", 42)
    assert ctx.get("foo") == 42


def test_get_missing_raises():
    ctx = PipelineContext(work_dir=Path("/tmp"))
    with pytest.raises(KeyError, match="bar"):
        ctx.get("bar")


def test_has():
    ctx = PipelineContext(work_dir=Path("/tmp"))
    assert not ctx.has("x")
    ctx.set("x", "val")
    assert ctx.has("x")


def test_keys():
    ctx = PipelineContext(work_dir=Path("/tmp"))
    ctx.set("a", 1)
    ctx.set("b", 2)
    assert ctx.keys() == {"a", "b"}


def test_remove():
    ctx = PipelineContext(work_dir=Path("/tmp"))
    ctx.set("a", 1)
    ctx.remove("a")
    assert not ctx.has("a")


def test_snapshot_keys():
    ctx = PipelineContext(work_dir=Path("/tmp"))
    ctx.set("items", [1, 2, 3])
    ctx.set("name", "test")
    snap = ctx.snapshot_keys()
    assert snap["items"] == "List[3]"
    assert snap["name"] == "str"


def test_progress_callback():
    calls = []
    ctx = PipelineContext(work_dir=Path("/tmp"))
    ctx.set_progress_callback(lambda f, m: calls.append((f, m)))
    ctx.report_progress(0.5, "halfway")
    assert calls == [(0.5, "halfway")]


def test_fps_default():
    ctx = PipelineContext(work_dir=Path("/tmp"))
    assert ctx.fps == 25.0

    ctx2 = PipelineContext(work_dir=Path("/tmp"), fps=30.0)
    assert ctx2.fps == 30.0

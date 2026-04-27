"""Tests für Registry und Preset-Loading."""

import pytest
from pathlib import Path
from typing import Any, Dict

from sequencer.module import Module
from sequencer.registry import Registry
from sequencer.context import PipelineContext


class TestModule(Module):
    name = "test_reg"
    description = "Registry Test"
    category = "test"
    inputs = []
    outputs = []

    def run(self, ctx, params):
        pass


@pytest.fixture(autouse=True)
def clean_registry():
    Registry.reset()
    yield
    Registry.reset()


def test_register_and_get():
    Registry.register(TestModule)
    cls = Registry.get("test_reg")
    assert cls is TestModule


def test_get_unknown_raises():
    with pytest.raises(KeyError, match="nonexistent"):
        Registry.get("nonexistent")


def test_discover_finds_modules():
    Registry.discover()
    mods = Registry.all_modules()
    assert "ingest" in mods
    assert "rms_diarize" in mods
    assert "edl_parse" in mods


def test_load_preset_multicam():
    modules = Registry.load_preset("multicam_cutter")
    assert len(modules) == 22
    assert modules[0].name == "ingest"
    assert modules[-1].name == "cut_timeline_build"


def test_load_preset_not_found():
    with pytest.raises(FileNotFoundError):
        Registry.load_preset("nonexistent_preset")


def test_list_presets():
    presets = Registry.list_presets()
    names = [p["name"] for p in presets]
    assert "multicam_cutter" in names


def test_catalog():
    Registry.discover()
    cat = Registry.catalog()
    assert len(cat) > 0
    # Jeder Eintrag hat die erwarteten Felder
    for entry in cat:
        assert "name" in entry
        assert "inputs" in entry
        assert "outputs" in entry


def test_preset_validates():
    """Multicam-Preset muss ohne Fehler validieren."""
    modules = Registry.load_preset("multicam_cutter")
    from sequencer.pipeline import Pipeline
    ctx = PipelineContext(work_dir=Path("/tmp"), fps=25.0)
    p = Pipeline(modules, ctx)
    errors = p.validate()
    assert errors == [], f"Validierungsfehler: {errors}"

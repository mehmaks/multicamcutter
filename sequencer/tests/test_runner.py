"""Tests für den Sequencer Runner."""

import pytest
from pathlib import Path

from sequencer.runner import run_sequencer, _auto_type, _build_params_from_config


def test_auto_type_bool():
    assert _auto_type("true") is True
    assert _auto_type("false") is False
    assert _auto_type("yes") is True
    assert _auto_type("no") is False


def test_auto_type_int():
    assert _auto_type("42") == 42
    assert isinstance(_auto_type("42"), int)


def test_auto_type_float():
    assert _auto_type("3.14") == pytest.approx(3.14)
    assert isinstance(_auto_type("3.14"), float)


def test_auto_type_string():
    assert _auto_type("hello") == "hello"


def test_dry_run():
    result = run_sequencer(
        preset_name="multicam_cutter",
        source_mode="folder",
        fps=25.0,
        ingest_params={"folder_path": "/tmp"},
        dry_run=True,
    )
    assert result == 0


def test_dry_run_invalid_preset():
    result = run_sequencer(
        preset_name="nonexistent",
        source_mode="folder",
        dry_run=True,
    )
    assert result == 1


def test_build_params_from_config_empty():
    params = _build_params_from_config(Path("/nonexistent"), {})
    assert params == {}


def test_build_params_cli_overrides():
    params = _build_params_from_config(Path("/nonexistent"), {
        "rms_diarize.threshold": 0.5,
        "crossbleed_gate.enabled": True,
    })
    assert params["rms_diarize"]["threshold"] == 0.5
    assert params["crossbleed_gate"]["enabled"] is True


def test_progress_callback_called():
    calls = []

    def cb(frac, mod, msg):
        calls.append((frac, mod))

    # Dry-run ruft keinen Callback auf, aber validated
    result = run_sequencer(
        preset_name="multicam_cutter",
        source_mode="folder",
        fps=25.0,
        ingest_params={"folder_path": "/tmp"},
        dry_run=True,
        progress_callback=cb,
    )
    assert result == 0
    # Dry-run führt Pipeline nicht aus, also keine Callbacks
    assert len(calls) == 0

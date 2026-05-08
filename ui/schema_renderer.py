"""Datengetriebener Widget-Renderer für Streamlit-Settings-Panels.

Liest ein JSON-Schema und rendert daraus Expander, Columns und Widgets.
Unterstützt Expert-/Einfach-Modus über ein ``expert``-Flag pro Parameter.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import streamlit as st

from shared.paths import SCHEMAS_DIR, NODDING_PATTERNS

_SCHEMAS_DIR = SCHEMAS_DIR

# ---------------------------------------------------------------------------
# Schema laden
# ---------------------------------------------------------------------------

def load_schema(page_name: str) -> dict:
    """Lade und cache das JSON-Schema für eine Page."""
    path = _SCHEMAS_DIR / f"{page_name}_params.json"
    return json.loads(path.read_text(encoding="utf-8"))


def get_param_names(schema: dict) -> list[str]:
    """Extrahiere geordnete Liste aller Param-Namen aus dem Schema."""
    names: list[str] = []
    for exp in schema.get("expanders", []):
        for row in exp.get("rows", []):
            for p in row.get("params", []):
                names.append(p["name"])
    return names


def get_defaults(schema: dict) -> dict[str, Any]:
    """Extrahiere {name: default} Mapping aus dem Schema."""
    defaults: dict[str, Any] = {}
    for exp in schema.get("expanders", []):
        for row in exp.get("rows", []):
            for p in row.get("params", []):
                defaults[p["name"]] = p["default"]
    return defaults


def apply_preset_transforms(schema: dict, preset_values: dict) -> dict:
    """Konvertiere Preset-Werte in Display-Form (z.B. 'middle' → 'Middle').

    Presets können interne Werte enthalten (aus älteren Versionen oder
    aus collect_settings). Selectbox-Widgets erwarten aber Display-Werte.
    """
    result = dict(preset_values)
    for param in _get_all_params(schema):
        name = param["name"]
        if name not in result:
            continue
        transform = param.get("transform")
        if transform and transform["type"] == "map":
            raw = str(result[name])
            # Wenn der Wert ein interner Wert ist, konvertiere zu Display
            if raw in transform["to_display"]:
                result[name] = transform["to_display"][raw]
    return result


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _get_all_params(schema: dict) -> list[dict]:
    """Flache Liste aller Parameter im Schema."""
    params: list[dict] = []
    for exp in schema.get("expanders", []):
        for row in exp.get("rows", []):
            params.extend(row.get("params", []))
    return params


def _display_value(param: dict) -> Any:
    """Default-Wert in Display-Form umwandeln (für Selectbox-Transform)."""
    val = param["default"]
    transform = param.get("transform")
    if transform and transform["type"] == "map":
        return transform["to_display"].get(str(val), val)
    return val


def _render_widget(param: dict, prefix: str, expert: bool) -> None:
    """Einzelnes Widget rendern."""
    key = f"{prefix}_{param['name']}"
    label = param["label"]
    if expert and param.get("label_expert"):
        label = param["label_expert"]
    help_text = param.get("help", "")
    cfg = param.get("config", {})
    default = param["default"]

    widget_type = param["widget"]

    if widget_type == "number_input":
        st.number_input(
            label, value=default, key=key, help=help_text,
            **cfg,
        )
    elif widget_type == "toggle":
        st.toggle(label, value=default, key=key, help=help_text)
    elif widget_type == "slider":
        st.slider(
            label, key=key, help=help_text,
            value=default,
            **cfg,
        )
    elif widget_type == "selectbox":
        options = cfg.get("options", [])
        display_val = _display_value(param)
        idx = options.index(display_val) if display_val in options else 0
        st.selectbox(label, options=options, index=idx, key=key, help=help_text)


def _render_nodding_patterns(prefix: str) -> None:
    """Dynamische Nodding-Pattern-Toggles aus nodding_patterns.json."""
    patterns_path = NODDING_PATTERNS
    if not patterns_path.is_file():
        return
    pat_data = json.loads(patterns_path.read_text(encoding="utf-8"))
    for pat in pat_data.get("patterns", []):
        pname = pat["name"]
        pkey = f"{prefix}_nod_pat_{pname}"
        st.toggle(
            pname.replace("_", " ").title(),
            value=pat.get("enabled", True),
            key=pkey,
            help=pat.get("description", ""),
        )


def _has_visible_params(expander: dict, expert: bool) -> bool:
    """Prüfe ob der Expander sichtbare Parameter hat."""
    for row in expander.get("rows", []):
        for p in row.get("params", []):
            if expert or not p.get("expert", False):
                return True
    return False


def render_settings_panel(schema: dict, prefix: str, expert: bool,
                          filter_keys: list[str] | None = None) -> None:
    """Alle Expander und Widgets aus dem Schema rendern.

    Parameters
    ----------
    schema : Schema-Dict (aus ``load_schema``)
    prefix : Widget-Key-Prefix (z.B. ``"s"`` oder ``"f"``)
    expert : True → alle Parameter anzeigen, False → nur expert=false
    filter_keys : Nur Expander mit diesen Keys rendern (None = alle)
    """
    for exp in schema.get("expanders", []):
        if filter_keys and exp.get("key") not in filter_keys:
            continue
        if not _has_visible_params(exp, expert):
            continue

        with st.expander(exp["label"], expanded=exp.get("expanded", False)):
            for row in exp.get("rows", []):
                # Divider-Zeile
                if row.get("divider"):
                    # Prüfe ob nach dem Divider sichtbare Params kommen
                    # (schaue in die nachfolgenden Rows)
                    exp_rows = exp.get("rows", [])
                    div_idx = exp_rows.index(row)
                    has_visible_after = False
                    for subsequent in exp_rows[div_idx + 1:]:
                        for p in subsequent.get("params", []):
                            if expert or not p.get("expert", False):
                                has_visible_after = True
                                break
                        if has_visible_after:
                            break
                    if not has_visible_after:
                        continue
                    st.divider()
                    if row.get("section_label"):
                        st.markdown(f"**{row['section_label']}**")
                    continue

                # Normale Row mit Columns
                n_cols = row.get("columns", 1)
                params = row.get("params", [])

                # Params nach Column gruppieren, nur sichtbare
                col_groups: dict[int, list[dict]] = defaultdict(list)
                for p in params:
                    if expert or not p.get("expert", False):
                        col_groups[p["column"]].append(p)

                if not any(col_groups.values()):
                    continue

                cols = st.columns(n_cols)
                nod_slot = row.get("nodding_patterns_slot")
                caption_slot = row.get("caption_slot")

                for col_idx in range(n_cols):
                    with cols[col_idx]:
                        for p in col_groups.get(col_idx, []):
                            if p.get("section_label"):
                                st.markdown(f"**{p['section_label']}**")
                            _render_widget(p, prefix, expert)

                            # Nodding-Patterns nach dem markierten Param
                            if (nod_slot
                                    and nod_slot["column"] == col_idx
                                    and p["name"] == nod_slot.get("after")):
                                _render_nodding_patterns(prefix)

                        # Caption-Slot
                        if caption_slot and caption_slot.get("column") == col_idx:
                            st.caption(caption_slot["text"])


# ---------------------------------------------------------------------------
# Settings einsammeln
# ---------------------------------------------------------------------------

def collect_settings(schema: dict, prefix: str) -> dict[str, Any]:
    """Alle Parameter-Werte aus session_state lesen.

    Liest IMMER alle Parameter (auch unsichtbare Expert-Params) und wendet
    ggf. Transforms an (scale, map).
    """
    p = f"{prefix}_"
    result: dict[str, Any] = {}

    for param in _get_all_params(schema):
        name = param["name"]
        default = param["default"]
        raw = st.session_state.get(f"{p}{name}", default)

        transform = param.get("transform")
        if transform:
            if transform["type"] == "scale":
                raw = raw * transform["factor"]
            elif transform["type"] == "map":
                raw = transform["to_internal"].get(str(raw), raw)

        result[name] = raw

    return result

"""
resolve-toolkit — Main UI
Run with: streamlit run ui/app.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import queue as _queue
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

import streamlit as st
import license as _lic

st.set_page_config(
    page_title="resolve-toolkit",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Config-Migration ───────────────────────────────────────────────────────────

def _migrate_config() -> int:
    """
    Vergleicht config.ini mit config.template.ini und ergänzt fehlende
    Sections/Keys mit den Template-Defaults. Vorhandene Werte werden nie
    überschrieben. Gibt die Anzahl neu hinzugefügter Keys zurück.
    """
    import configparser as _cp
    _root     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _cfg_dir  = os.path.join(_root, "modules", "multicam_cutter")
    _cfg_path = os.path.join(_cfg_dir, "config.ini")
    _tpl_path = os.path.join(_cfg_dir, "config.template.ini")

    if not os.path.exists(_tpl_path) or not os.path.exists(_cfg_path):
        return 0

    tmpl = _cp.ConfigParser()
    tmpl.read(_tpl_path, encoding="utf-8")

    cfg = _cp.ConfigParser()
    cfg.read(_cfg_path, encoding="utf-8")

    added = 0
    for section in tmpl.sections():
        if not cfg.has_section(section):
            cfg.add_section(section)
        for key, value in tmpl.items(section):
            if not cfg.has_option(section, key):
                cfg.set(section, key, value)
                added += 1

    if added:
        with open(_cfg_path, "w", encoding="utf-8") as f:
            cfg.write(f)

    return added

_migrated = _migrate_config()

# ── Session state ──────────────────────────────────────────────────────────────

_DEFAULTS = {
    "bin_running":  False, "bin_log": [], "bin_progress": 0.0,
    "bin_label": "", "bin_eta": "", "bin_step": 0, "bin_total": 8,
    "folder_running": False, "folder_log": [], "folder_progress": 0.0,
    "folder_label": "", "folder_eta": "", "folder_step": 0, "folder_total": 6,
    "enhance_running": False, "enhance_log": [], "enhance_download_results": {},
    "silence_running": False, "silence_log": [], "silence_results": [],
    "auphonic_running": False, "auphonic_log": [],
    "mv_running": False, "mv_log": [],
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── License ────────────────────────────────────────────────────────────────────

if "license_info" not in st.session_state:
    st.session_state.license_info = _lic.validate()
_license: _lic.LicenseInfo = st.session_state.license_info

# ── Update-Dialog ──────────────────────────────────────────────────────────────

@st.dialog("Update-Prüfung")
def _update_dialog():
    if st.session_state.get("update_installed"):
        _inst_tag = st.session_state.get("update_tag", "")
        st.success(f"**{_inst_tag}** installiert — bitte neu starten.")
        st.code("bash ~/resolve-toolkit/start.command")
        if st.button("Schließen", type="primary", use_container_width=True):
            st.session_state.show_update_dialog = False
            st.session_state.update_installed   = False
            st.rerun()
        return

    if not st.session_state.get("update_check_done"):
        st.caption("Prüfe auf Updates...")
        with st.spinner(""):
            _up2, _tag2, _notes2 = _check_for_update()
        st.session_state.update_available  = _up2
        st.session_state.update_tag        = _tag2
        st.session_state.update_notes      = _notes2
        st.session_state.update_check_done = True
        st.rerun()
        return

    _up    = st.session_state.get("update_available", False)
    _tag   = st.session_state.get("update_tag", "")
    _notes = st.session_state.get("update_notes", "")

    if _up:
        st.success(f"Neue Version verfügbar: **{_tag}**")
        if _notes:
            with st.expander("Release Notes", expanded=True):
                st.markdown(_notes)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Abbrechen", use_container_width=True):
                st.session_state.show_update_dialog = False
                st.rerun()
        with c2:
            if st.button("Jetzt updaten", type="primary", use_container_width=True):
                with st.spinner("Aktualisiere..."):
                    import subprocess as _sup2, sys as _sys2
                    _req_before = _git("show", "HEAD:requirements.txt")
                    _git("pull", "origin", "main")
                    _req_after  = _git("show", "HEAD:requirements.txt")
                    if _req_before != _req_after:
                        _sup2.run([_sys2.executable, "-m", "pip", "install", "-q",
                                   "-r", os.path.join(_REPO_ROOT, "requirements.txt")],
                                  check=False)
                st.session_state.update_available = False
                st.session_state.update_installed = True
                st.rerun()
    else:
        st.info("Kein Update verfügbar — du hast die neueste Version.")
        if st.button("Schließen", type="primary", use_container_width=True):
            st.session_state.show_update_dialog = False
            st.rerun()


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:

    # ── Hilfsfunktionen ───────────────────────────────────────────────────────

    _REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _GH_REPO   = "mehmaks/resolve-toolkit"

    def _git(*args):
        import subprocess as _sp2
        r = _sp2.run(["git", "-C", _REPO_ROOT] + list(args), capture_output=True, text=True)
        return r.stdout.strip()

    def _current_version() -> str:
        try:
            with open(os.path.join(_REPO_ROOT, "VERSION")) as _f:
                return _f.read().strip()
        except Exception:
            return "?"

    def _fetch_release_notes(_tag: str) -> str:
        import requests as _rq2, configparser as _cp2
        _fcfg2 = _cp2.ConfigParser()
        _fcfg2.read(os.path.join(_REPO_ROOT, "modules", "multicam_cutter", "config.ini"))
        _tok2 = _fcfg2.get("Feedback", "github_token", fallback="").strip()
        _h = {"Accept": "application/vnd.github+json"}
        if _tok2:
            _h["Authorization"] = f"Bearer {_tok2}"
        try:
            _r = _rq2.get(f"https://api.github.com/repos/{_GH_REPO}/releases/tags/{_tag}",
                          headers=_h, timeout=5)
            if _r.status_code == 200:
                return _r.json().get("body", "").strip()
        except Exception:
            pass
        return ""

    def _check_for_update():
        try:
            _git("fetch", "--tags", "--quiet")
            _tags = _git("tag", "--list", "v*", "--sort=-version:refname")
            _latest = _tags.splitlines()[0] if _tags else ""
            if not _latest or _latest == _current_version():
                return False, None, ""
            return True, _latest, _fetch_release_notes(_latest)
        except Exception:
            return False, None, ""

    import subprocess as _sp, requests as _rq, configparser as _fcp
    _fcfg = _fcp.ConfigParser()
    _fcfg.read(os.path.join(_REPO_ROOT, "modules", "multicam_cutter", "config.ini"))
    _token = _fcfg.get("Feedback", "github_token", fallback="").strip()
    _repo  = _fcfg.get("Feedback", "github_repo",  fallback="").strip()

    if "update_available" not in st.session_state:
        (_up, _tag, _notes) = _check_for_update()
        st.session_state.update_available  = _up
        st.session_state.update_tag        = _tag
        st.session_state.update_notes      = _notes
        st.session_state.update_check_done = True

    # ── Resolve check (still, for status bar) ─────────────────────────────────

    def _check_resolve():
        from resolve_bridge.connection import get_resolve
        resolve = get_resolve()
        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject()
        tl = project.GetCurrentTimeline() if project else None
        return (
            project.GetName() if project else None,
            tl.GetName() if tl else None,
        )

    def _run_resolve_check():
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(_check_resolve)
                _rp, _rt = future.result(timeout=2.0)
            st.session_state.resolve_status = ("ok", _rp, _rt)
        except FuturesTimeout:
            st.session_state.resolve_status = ("timeout", None, None)
        except Exception:
            st.session_state.resolve_status = ("error", None, None)

    if "resolve_status" not in st.session_state:
        _run_resolve_check()

    _rs_status, _rs_project, _rs_tl = st.session_state.resolve_status

    # ── Tab-Sichtbarkeit + Seitenliste ────────────────────────────────────────

    _ui_cfg = _fcp.ConfigParser()
    _ui_cfg.read(os.path.join(_REPO_ROOT, "modules", "multicam_cutter", "config.ini"),
                 encoding="utf-8")

    def _tab_visible(config_key: str, module: str) -> bool:
        cfg_on = _ui_cfg.getboolean("UI", config_key, fallback=True)
        lic_on = _license.has_module(module)
        return cfg_on and lic_on

    _MOD_PAGE_DEFS = {
        "show_multicam":   ("pages/multicam.py",     "Multicam Cutter", ":material/content_cut:",  "multicam"),
        "show_enhance":    ("pages/enhance.py",       "Audio Enhance",   ":material/mic:",          "enhance"),
        "show_auphonic":   ("pages/auphonic.py",      "Auphonic",        ":material/cloud:",        "auphonic"),
        "show_maxxvolume": ("pages/voice_leveler.py", "Voice Leveler",   ":material/graphic_eq:",   "maxxvolume"),
        "show_silence":    ("pages/silence.py",       "Silence Cutter",  ":material/volume_off:",   "silence"),
        "show_resolve":    ("pages/resolve.py",       "Resolve Bridge",  ":material/link:",         "resolve"),
        "show_takes":      ("pages/takes.py",         "Take Selector",   ":material/theaters:","takes"),
    }
    _mod_order_raw = _ui_cfg.get("UI", "module_order", fallback="")
    _mod_order = ([k.strip() for k in _mod_order_raw.split(",") if k.strip() in _MOD_PAGE_DEFS]
                  if _mod_order_raw else list(_MOD_PAGE_DEFS))
    for _k in _MOD_PAGE_DEFS:
        if _k not in _mod_order:
            _mod_order.append(_k)

    _license_page = st.Page("pages/license.py", title="Lizenz", icon=":material/key:")
    _pages = [] if _license.valid else [_license_page]
    for _cfg_key in _mod_order:
        _pg_file, _pg_title, _pg_icon, _pg_lic = _MOD_PAGE_DEFS[_cfg_key]
        if _tab_visible(_cfg_key, _pg_lic):
            _pages.append(st.Page(_pg_file, title=_pg_title, icon=_pg_icon))
    _pages.append(st.Page("pages/docs.py",    title="Dokumentation", icon=":material/menu_book:"))
    if _license.valid:
        _pages.append(_license_page)
    _pages.append(st.Page("pages/config.py", title="Config",        icon=":material/settings:"))

    # ── Berechnete Werte ──────────────────────────────────────────────────────

    _ver     = _current_version()
    _upd     = st.session_state.get("update_available", False)
    _upd_tag = st.session_state.get("update_tag") or ""

    # ═══════════════════════════════════════════════════════════════════════════
    # Sidebar-Inhalt
    # ═══════════════════════════════════════════════════════════════════════════

    # Navigation ohne eigene UI — wir bauen sie manuell mit st.page_link
    page = st.navigation(_pages, position="hidden")

    # 1. Titel + Version
    st.title("RESOLVE TOOLKIT")
    st.caption(f"`{_ver}`")

    st.divider()

    # 2. Modul-Liste mit Sections
    _tool_pages    = []
    _setting_pages = []
    _tool_titles   = {"Multicam Cutter", "Audio Enhance", "Auphonic",
                      "Voice Leveler", "Silence Cutter", "Resolve Bridge", "Take Selector"}
    _setting_titles = {"Dokumentation", "Lizenz", "Config"}

    for _p in _pages:
        if _p.title in _tool_titles:
            _tool_pages.append(_p)
        elif _p.title in _setting_titles:
            _setting_pages.append(_p)

    if _tool_pages:
        st.caption("TOOLS")
        for _p in _tool_pages:
            st.page_link(_p, use_container_width=True)

    if _setting_pages:
        st.caption("SETTINGS")
        for _p in _setting_pages:
            st.page_link(_p, use_container_width=True)

    st.divider()

    # 3. Feedback-Button
    if _token and _repo:
        with st.popover("💬 Bugs & Feedback", use_container_width=True):
            with st.form("fb_form", clear_on_submit=True):
                _fb_type  = st.radio("Typ", ["🐛 Bug", "💡 Verbesserung"], horizontal=True,
                                     label_visibility="collapsed")
                _fb_title = st.text_input("Kurztitel",
                                          placeholder="z.B. 'Sync-Fehler bei MXF-Clips'")
                _fb_body  = st.text_area("Beschreibung",
                                         placeholder="Was ist passiert? Was wurde erwartet?",
                                         height=100)
                _fb_email = st.text_input("E-Mail (optional)",
                                          value=_license.email or "",
                                          placeholder="fuer Rückfragen")
                _submitted = st.form_submit_button("Senden", use_container_width=True)
            if _submitted:
                if not _fb_title.strip():
                    st.warning("Bitte einen Kurztitel eingeben.")
                else:
                    try:
                        _git_hash = _sp.run(
                            ["git", "-C", _REPO_ROOT, "rev-parse", "--short", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
                    except Exception:
                        _git_hash = "?"
                    _label = "bug" if "Bug" in _fb_type else "enhancement"
                    _body_parts = [_fb_body.strip()]
                    if _fb_email.strip():
                        _body_parts.append(f"**Kontakt:** {_fb_email.strip()}")
                    _body_parts.append(f"*Version: `{_git_hash}`*")
                    _resp = _rq.post(
                        f"https://api.github.com/repos/{_repo}/issues",
                        headers={"Authorization": f"Bearer {_token}",
                                 "Accept": "application/vnd.github+json"},
                        json={"title": _fb_title.strip(),
                              "body":  "\n\n".join(_body_parts),
                              "labels": [_label]},
                        timeout=10)
                    if _resp.status_code == 201:
                        st.success("Gesendet! Danke.")
                    else:
                        st.error(f"Fehler ({_resp.status_code})")

    # 4. Update-Button
    _btn_label = f"⬆ {_upd_tag} verfügbar" if _upd else "↻ Updates prüfen"
    _btn_type  = "primary" if _upd else "secondary"
    if st.button(_btn_label, use_container_width=True, type=_btn_type):
        st.session_state.update_check_done  = False  # force fresh check
        st.session_state.update_installed   = False
        st.session_state.show_update_dialog = True
        st.rerun()

    if st.session_state.get("show_update_dialog"):
        _update_dialog()

    # 4. Workflow Log (nur wenn aktiv oder letzter Log vorhanden)
    if st.session_state.bin_running:
        _active = "bin"
    elif st.session_state.folder_running:
        _active = "folder"
    elif st.session_state.enhance_running:
        _active = "enhance"
    elif st.session_state.silence_running:
        _active = "silence"
    elif st.session_state.auphonic_running:
        _active = "auphonic"
    elif st.session_state.mv_running:
        _active = "mv"
    else:
        _active = None

    _last_log = next(
        (st.session_state[k] for k in ("bin_log", "folder_log", "enhance_log",
                                        "silence_log", "auphonic_log", "mv_log")
         if st.session_state.get(k)), []
    )

    if _active or _last_log:
        st.divider()

    if _active:
        st.subheader("Workflow Log")

    if _active in ("bin", "folder"):
        st.info("⏳ Multicam Workflow läuft...  \n→ Fortschritt im **Multicam Cutter** Tab")

    elif _active == "silence" and "silence_queue" in st.session_state:
        _log_ph = st.empty()
        while st.session_state.silence_running:
            try:
                _line = st.session_state.silence_queue.get(timeout=0.1)
                if isinstance(_line, tuple) and _line[0] == "__RESULT__":
                    st.session_state.silence_results = _line[1]
                elif isinstance(_line, tuple) and _line[0] == "__FILE_RESULT__":
                    st.session_state.sc_file_results = _line[1]
                elif isinstance(_line, str) and _line.startswith("__DONE__"):
                    st.session_state.silence_running = False
                    break
                else:
                    st.session_state.silence_log.append(_line)
            except _queue.Empty:
                pass
            _log_ph.code("\n".join(st.session_state.silence_log[-50:]), language=None)
            time.sleep(0.05)

    elif _active == "enhance" and "enhance_queue" in st.session_state:
        _log_ph = st.empty()
        while st.session_state.enhance_running:
            try:
                _line = st.session_state.enhance_queue.get(timeout=0.1)
                if _line.startswith("__DONE__"):
                    st.session_state.enhance_running = False
                    break
                st.session_state.enhance_log.append(_line)
            except _queue.Empty:
                pass
            _log_ph.code("\n".join(st.session_state.enhance_log[-50:]), language=None)
            time.sleep(0.05)

    elif _active == "mv" and "mv_queue" in st.session_state:
        _log_ph = st.empty()
        while st.session_state.mv_running:
            try:
                _line = st.session_state.mv_queue.get(timeout=0.1)
                if _line.startswith("__DONE__"):
                    st.session_state.mv_running = False
                    break
                st.session_state.mv_log.append(_line)
            except _queue.Empty:
                pass
            _log_ph.code("\n".join(st.session_state.mv_log[-50:]), language=None)
            time.sleep(0.05)

    elif _active == "auphonic" and "auphonic_queue" in st.session_state:
        _log_ph = st.empty()
        while st.session_state.auphonic_running:
            try:
                _line = st.session_state.auphonic_queue.get(timeout=0.1)
                if _line.startswith("__DONE__"):
                    st.session_state.auphonic_running = False
                    break
                st.session_state.auphonic_log.append(_line)
            except _queue.Empty:
                pass
            _log_ph.code("\n".join(st.session_state.auphonic_log[-50:]), language=None)
            time.sleep(0.05)

    if _last_log and not _active:
        st.subheader("Letzter Log")
        st.code("\n".join(_last_log[-30:]), language=None)
        if st.button("Log leeren", use_container_width=True, key="sidebar_clear_log"):
            for _k in ("bin_log", "folder_log", "enhance_log",
                       "silence_log", "auphonic_log", "mv_log"):
                st.session_state[_k] = []
            for _k in ("bin_progress", "folder_progress"):
                st.session_state[_k] = 0.0
            for _k in ("bin_label", "bin_eta", "folder_label", "folder_eta"):
                st.session_state[_k] = ""
            for _k in ("bin_step", "folder_step"):
                st.session_state[_k] = 0
            st.rerun()

# ── Page ───────────────────────────────────────────────────────────────────────

page.run()

# ── Feste Statusleiste — nach page.run(), rechtsbündig ────────────────────────

_bar_parts = []

if _license.valid:
    _bar_dot = "🟡" if _license.grace else "🟢"
else:
    _bar_dot = "🔴"
_bar_lic = {
    "dummy": "Dev",
    "local": f"Betatester · {_license.email or ''}",
    "remote": _license.email or ("Aktiv" if _license.valid else "Keine Lizenz"),
}.get(_lic.MODE, "")
_bar_parts.append(f"{_bar_dot}&nbsp;{_bar_lic}")

if _rs_status == "ok" and _rs_project:
    _bar_resolve = f"🎬&nbsp;{_rs_project}"
    if _rs_tl:
        _bar_resolve += f"&nbsp;·&nbsp;{_rs_tl}"
    _bar_parts.append(_bar_resolve)

_bar_html = "&nbsp;&nbsp;<span style='color:#555'>|</span>&nbsp;&nbsp;".join(_bar_parts)

st.markdown(f"""
<style>
    ._rtk-statusbar {{
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        height: 32px;
        background: rgba(14, 17, 23, 0.97);
        border-top: 1px solid rgba(255, 255, 255, 0.08);
        display: flex;
        align-items: center;
        justify-content: flex-end;
        padding: 0 1.5rem;
        font-size: 13px;
        color: rgba(250, 250, 250, 0.65);
        z-index: 99999;
        font-family: "Source Sans Pro", sans-serif;
        gap: 0;
    }}
    section[data-testid="stMain"] > div:first-child {{
        padding-bottom: 40px !important;
    }}
</style>
<div class="_rtk-statusbar">{_bar_html}</div>
""", unsafe_allow_html=True)

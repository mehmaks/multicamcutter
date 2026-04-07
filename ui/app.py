"""
resolve-toolkit — Main UI
Run with: streamlit run ui/app.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

st.set_page_config(
    page_title="resolve-toolkit",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("resolve-toolkit")
    st.caption("Automated video editing tools")
    st.divider()

    # Resolve connection status (cached — only re-checked on button press)
    import time
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

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
                project_name, tl_name = future.result(timeout=2.0)
            st.session_state.resolve_status = ("ok", project_name, tl_name)
        except FuturesTimeout:
            st.session_state.resolve_status = ("timeout", None, None)
        except Exception:
            st.session_state.resolve_status = ("error", None, None)
        st.session_state.resolve_checked_at = time.time()

    # Run check only on first load; afterwards only when user clicks refresh
    if "resolve_status" not in st.session_state:
        _run_resolve_check()

    status, project_name, tl_name = st.session_state.resolve_status

    st.subheader("DaVinci Resolve")
    if status == "ok":
        st.success("Verbunden")
        if project_name:
            st.caption(f"Projekt: **{project_name}**")
        if tl_name:
            st.caption(f"Timeline: **{tl_name}**")
    elif status == "timeout":
        st.warning("Antwortet nicht")
    else:
        st.error("Nicht verbunden")
        st.caption("Resolve öffnen und Projekt laden")

    if st.button("↻ Aktualisieren", use_container_width=True):
        _run_resolve_check()
        st.rerun()

    st.divider()
    st.caption("github.com/mehmaks/resolve-toolkit")

# ── Navigation ────────────────────────────────────────────────────────────────

page = st.navigation([
    st.Page("pages/multicam.py",  title="Multicam Cutter", icon="✂️"),
    st.Page("pages/enhance.py",   title="Audio Enhance",   icon="🎙️"),
    st.Page("pages/resolve.py",   title="Resolve Bridge",  icon="🔗"),
    st.Page("pages/config.py",    title="Config",          icon="⚙️"),
])

page.run()

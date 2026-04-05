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

    # Resolve connection status
    st.subheader("DaVinci Resolve")
    try:
        from resolve_bridge.connection import get_resolve
        from resolve_bridge.timeline_reader import read_timeline

        resolve = get_resolve()
        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject()
        tl = project.GetCurrentTimeline() if project else None

        st.success("Verbunden")
        if project:
            st.caption(f"Projekt: **{project.GetName()}**")
        if tl:
            st.caption(f"Timeline: **{tl.GetName()}**")
    except Exception as e:
        st.error("Nicht verbunden")
        st.caption("Resolve öffnen und Projekt laden")

    st.divider()
    st.caption("github.com/mehmaks/resolve-toolkit")

# ── Navigation ────────────────────────────────────────────────────────────────

page = st.navigation([
    st.Page("pages/multicam.py",  title="Multicam Cutter", icon="✂️"),
    st.Page("pages/resolve.py",   title="Resolve Bridge",  icon="🔗"),
])

page.run()

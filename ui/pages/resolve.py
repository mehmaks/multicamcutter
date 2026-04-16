"""
Resolve Bridge — UI Page
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st

st.title(":material/link: Resolve Bridge")
st.caption("Verbindungsstatus und Projektübersicht")

try:
    from resolve_bridge.connection import get_resolve

    resolve = get_resolve()
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()

    st.success("DaVinci Resolve ist verbunden")
    st.divider()

    if not project:
        st.warning("Kein Projekt geöffnet.")
        st.stop()

    # Projektinfo
    st.subheader("Projekt")
    col1, col2 = st.columns(2)
    col1.metric("Name", project.GetName())
    col2.metric("Timelines", project.GetTimelineCount())

    # Timeline-Liste
    st.subheader("Timelines")
    current = project.GetCurrentTimeline()
    current_name = current.GetName() if current else None

    timeline_data = []
    for i in range(1, project.GetTimelineCount() + 1):
        t = project.GetTimelineByIndex(i)
        timeline_data.append({
            "": "▶" if t.GetName() == current_name else "",
            "Name": t.GetName(),
            "FPS": t.GetSetting("timelineFrameRate"),
        })
    st.dataframe(timeline_data, use_container_width=True, hide_index=True)

    # Timeline wechseln
    st.divider()
    st.subheader("Timeline aktivieren")
    names = [t["Name"] for t in timeline_data]
    selected = st.selectbox("Timeline auswählen", names,
                            index=names.index(current_name) if current_name in names else 0)

    if st.button("Aktivieren", type="primary"):
        for i in range(1, project.GetTimelineCount() + 1):
            t = project.GetTimelineByIndex(i)
            if t.GetName() == selected:
                project.SetCurrentTimeline(t)
                st.success(f"'{selected}' ist jetzt aktiv.")
                st.rerun()

except Exception as e:
    st.error("Resolve nicht erreichbar")
    st.caption(str(e))
    st.info("DaVinci Resolve öffnen und ein Projekt laden, dann hier neu laden.")

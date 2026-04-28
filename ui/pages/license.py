import streamlit as st
import subprocess
import licensing.license as _lic

_license: _lic.LicenseInfo = st.session_state.get("license_info") or _lic.validate()


def _fmt_date(iso: str | None) -> str:
    """'2026-12-31' → '31.12.2026', None → 'unbegrenzt'."""
    if not iso:
        return "unbegrenzt"
    try:
        y, m, d = iso.split("-")
        return f"{d}.{m}.{y}"
    except Exception:
        return iso


st.title("Lizenz")

if _license.valid:
    if _license.grace:
        st.warning("Lizenz läuft im Offline-Modus (Grace Period).")

    st.success("Lizenz aktiv")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("E-Mail", _license.email or "—")
    with col2:
        st.metric("Gültig bis", _fmt_date(_license.expires))

    st.subheader("Freigeschaltete Module")
    module_labels = {
        "multicam":   "Multicam Cutter",
        "enhance":    "Audio Enhance",
        "auphonic":   "Auphonic",
        "maxxvolume": "Voice Leveler",
        "silence":    "Silence Cutter",
        "takes":      "Take Selector",
    }
    for mod, label in module_labels.items():
        if mod in _license.modules and mod not in _lic.BETA_BLOCKED:
            st.markdown(f"- {label}")

elif _license.error and "Keine Lizenzdatei" in _license.error:
    st.error("Keine Lizenz gefunden")
    st.markdown("Wähle deine Lizenzdatei (`license.json`) aus, um sie zu aktivieren.")

    if st.button("Lizenzdatei auswählen …", type="primary"):
        try:
            _r = subprocess.run(
                ["osascript", "-e",
                 'POSIX path of (choose file with prompt "Lizenzdatei auswählen"'
                 ' of type {"public.json", "json"})',
                ],
                capture_output=True, text=True, timeout=60,
            )
            if _r.returncode == 0 and _r.stdout.strip():
                _chosen = _r.stdout.strip()
                _result = _lic.install_license(_chosen)
                if _result.valid:
                    st.session_state["license_info"] = _result
                    st.success(
                        f"Lizenz aktiviert für **{_result.email}** "
                        f"(gültig bis {_fmt_date(_result.expires)})."
                    )
                    st.rerun()
                else:
                    st.error(f"Aktivierung fehlgeschlagen: {_result.error}")
            # returncode != 0 → Nutzer hat Abbrechen gedrückt, still ignorieren
        except subprocess.TimeoutExpired:
            pass
        except Exception as _e:
            st.error(f"Dateidialog nicht verfügbar: {_e}")

    st.caption(
        "Alternativ: Datei manuell nach `~/.resolve-toolkit/license.json` kopieren "
        "und Seite neu laden."
    )

elif _license.error and ("ungültig" in _license.error or "manipuliert" in _license.error):
    st.error("Lizenz ungültig")
    st.markdown("""
Die Lizenzdatei konnte nicht verifiziert werden — sie ist möglicherweise beschädigt oder stammt aus einer älteren Version.

Bitte eine neue Lizenzdatei anfordern.
""")

elif _license.error and "abgelaufen" in _license.error:
    st.error("Lizenz abgelaufen")
    st.markdown(f"**{_license.error}**")
    st.markdown("Wähle eine neue Lizenzdatei (`license.json`) aus, um sie zu aktivieren.")

    if st.button("Neue Lizenzdatei auswählen …", type="primary"):
        try:
            _r = subprocess.run(
                ["osascript", "-e",
                 'POSIX path of (choose file with prompt "Lizenzdatei auswählen"'
                 ' of type {"public.json", "json"})',
                ],
                capture_output=True, text=True, timeout=60,
            )
            if _r.returncode == 0 and _r.stdout.strip():
                _chosen = _r.stdout.strip()
                _result = _lic.install_license(_chosen)
                if _result.valid:
                    st.session_state["license_info"] = _result
                    st.session_state["license_checked_at"] = __import__("time").time()
                    st.success(
                        f"Lizenz aktiviert für **{_result.email}** "
                        f"(gültig bis {_fmt_date(_result.expires)})."
                    )
                    st.rerun()
                else:
                    st.error(f"Aktivierung fehlgeschlagen: {_result.error}")
        except subprocess.TimeoutExpired:
            pass
        except Exception as _e:
            st.error(f"Dateidialog nicht verfügbar: {_e}")

    st.caption(
        "Alternativ: Datei manuell nach `~/.resolve-toolkit/license.json` kopieren "
        "und Seite neu laden."
    )

else:
    st.error("Lizenzproblem")
    st.markdown(f"**Details:** {_license.error or 'Unbekannter Fehler'}")

"""Stufen-Test: alle Varianten der Stufen-Ansicht aus EINEM Lauf bauen (ohne Gesichtsanalyse).

Vorgehen (User-Absprache 19.11.): eine Stellschraube nach der anderen, Rest „ausgewogen".
- Ausgangsbasis: Parameter eines echten App-Laufs (Session-Log) + alle Stufen „ausgewogen"
  (Werte wie in apps/multicam-cutter/MulticamCutter/Sources/Stufen.swift — hier gespiegelt).
- Je Variante ein Engine-Lauf mit --skip-analysis (Nick-Analyse aus dem App-Lauf wird
  wiederverwendet), fester Zufalls-Startwert (MCC_RANDOM_SEED) → Varianten vergleichbar.
- Ausgabe: AAF je Variante + Marker-EDL der Cutaway-Unterschiede zu „ausgewogen" +
  Player-Runde für die Treffsicherheit der Einwürfe (großzügig/streng).

Aufruf: venv/bin/python3 analyse/stufen_test.py KONFIG.json
KONFIG: {"folder", "test" (Ausgabeordner), "session_log", "work_dir", "reaktionen" (Ordner mit
         gesicherten *_reactions.json), "cams": [...], "wavs": [alle WAVs], "tabelle_prod",
         "player_ton" (Sitzung mit ton_*.m4a), "namen": {"clip": "Name"}}
"""
import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / "venv/bin/python3")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "modules" / "multicam_cutter"))

# Spiegel von Stufen.swift (Kennlinien). Index 0/1/2 = links/Mitte/rechts.
STUFEN = {
    "tempo": [
        {"min_shot": 4.0, "max_shot": 20.0, "reaction_dur": 2.2, "cleanup_dur": 1.8, "randomness": 0.2, "min_edit": 1.6},
        {"min_shot": 3.0, "max_shot": 14.0, "reaction_dur": 1.8, "cleanup_dur": 1.5, "randomness": 0.3, "min_edit": 1.6},
        {"min_shot": 1.2, "max_shot": 6.5, "reaction_dur": 1.2, "cleanup_dur": 1.0, "randomness": 0.3, "min_edit": 1.6}],
    "nicken_oft": [{"nodding_cooldown_s": 14.0}, {"nodding_cooldown_s": 8.0}, {"nodding_cooldown_s": 0.0}],
    "nicken_sicher": [
        {"min_conf": 0.6, "nodding_pattern_min_conf": {"slow_oscillation": 0.6, "strong_oscillation": 0.6}},
        {"min_conf": 0.6, "nodding_pattern_min_conf": {"slow_oscillation": 0.7, "strong_oscillation": 1.01}},
        {"min_conf": 0.6, "nodding_pattern_min_conf": {"slow_oscillation": 1.01, "strong_oscillation": 1.01}}],
    "einwurf_oft": [{"speaking_cooldown_s": 12.0}, {"speaking_cooldown_s": 4.0}, {"speaking_cooldown_s": 0.0}],
    "einwurf_sicher": [
        {"speaking_uebersprechen_db": 9.0, "speaking_umgebung_db": 4.5},
        {"speaking_uebersprechen_db": 12.0, "speaking_umgebung_db": 6.0},
        {"speaking_uebersprechen_db": 15.0, "speaking_umgebung_db": 8.0}],
    "pausen_kuerzen": [{"max_pause": 1.5}, {"max_pause": 1.0}, {"max_pause": 0.6}],
    "pausen_cutaways": [{"pause_cutaway_enabled": False},
                        {"pause_cutaway_enabled": True, "pause_cutaway_min_pause": 3.0},
                        {"pause_cutaway_enabled": True, "pause_cutaway_min_pause": 1.5}],
}
FEST = {"nodding_enabled": True, "speaking_enabled": True, "speaking_analysespur_enabled": True,
        "speaking_priority": True, "pause_trim_enabled": True, "mouth_reactions_enabled": False}

# (Dateiname, {regler: stufe}, Marker-Gründe oder None)
NICKEN_EINWURF = "reaction_nodding,reaction_speaking_reaction"
VARIANTEN = [
    ("00 ausgewogen", {}, None),
    ("01 Tempo ruhig", {"tempo": 0}, None),
    ("02 Tempo lebendig", {"tempo": 2}, None),
    ("03 Nicken selten", {"nicken_oft": 0}, NICKEN_EINWURF),
    ("04 Nicken oft", {"nicken_oft": 2}, NICKEN_EINWURF),
    ("05 Einwuerfe selten", {"einwurf_oft": 0}, NICKEN_EINWURF),
    ("06 Einwuerfe oft", {"einwurf_oft": 2}, NICKEN_EINWURF),
    ("07 Einwuerfe grosszuegig", {"einwurf_sicher": 0}, NICKEN_EINWURF),
    ("08 Einwuerfe streng", {"einwurf_sicher": 2}, NICKEN_EINWURF),
    ("09 Pausen sanft", {"pausen_kuerzen": 0}, None),
    ("10 Pausen straff", {"pausen_kuerzen": 2}, None),
    ("11 Pausen-Cutaways keine", {"pausen_cutaways": 0}, "pause_cutaway"),
    ("12 Pausen-Cutaways oft", {"pausen_cutaways": 2}, "pause_cutaway"),
    ("13 Kombi ruhiges Gespraech", {"tempo": 0, "nicken_oft": 0, "nicken_sicher": 2, "einwurf_oft": 0,
                                    "einwurf_sicher": 2, "pausen_kuerzen": 0, "pausen_cutaways": 0}, None),
    ("14 Kombi lebendiger Clip", {"tempo": 2, "nicken_oft": 2, "einwurf_oft": 2, "pausen_kuerzen": 2,
                                  "pausen_cutaways": 0}, None),
]


def params_fuer(basis, wahl):
    p = copy.deepcopy(basis)
    for regler, stufen in STUFEN.items():
        p.update(copy.deepcopy(stufen[wahl.get(regler, 1)]))
    p.update(FEST)
    return p


def main():
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    T = Path(cfg["test"])
    (T / "AAF").mkdir(parents=True, exist_ok=True)
    (T / "Marker").mkdir(exist_ok=True)
    (T / "laeufe").mkdir(exist_ok=True)

    # Mikros: Split-Teile wie die App zusammenfügen (Join-Ordner der App ist weg)
    os.environ["MCC_JOIN_DIR"] = str(T / "joined")
    from shared.split_audio import resolve_split_audio
    mics, _ = resolve_split_audio(cfg["wavs"])
    mics = sorted(mics, key=lambda m: Path(m).stem.split("_")[-1])   # Tr1, Tr2
    print("Mikros:", [Path(m).name for m in mics], flush=True)

    basis = json.loads(Path(cfg["session_log"]).read_text(encoding="utf-8").splitlines()[0])["params"]
    W = Path(cfg["work_dir"])
    for name, wahl, gruende in VARIANTEN:
        out = T / "laeufe" / name
        aaf = T / "AAF" / f"{name}.aaf"
        if aaf.exists() and (out / "final.edl").exists():
            print(f"✓ {name} (vorhanden)", flush=True)
            continue
        out.mkdir(parents=True, exist_ok=True)
        (out / "params.json").write_text(json.dumps(params_fuer(basis, wahl), indent=1), encoding="utf-8")
        for f in Path(cfg["reaktionen"]).glob("*_reactions.json"):
            shutil.copy(f, W / f.name)      # Nick-Analyse des App-Laufs, nie überschrieben
        cmd = [PY, str(ROOT / "apps/multicam-cutter/engine/multicam_engine.py"), "--folder", cfg["folder"],
               "--fps", "29.97", "--params", str(out / "params.json"), "--output", str(aaf),
               "--cams", *cfg["cams"], "--mics", *mics, "--cam-mics", "0", "1",
               "--cam-types", "close", "close", "--skip-analysis"]
        log = subprocess.run(cmd, capture_output=True, text=True,
                             env={**os.environ, "PYTHONUNBUFFERED": "1", "MCC_RANDOM_SEED": "1"}).stdout
        (out / "engine.log").write_text(log, encoding="utf-8")
        if not aaf.exists():
            print(f"✗ {name}: kein AAF, siehe {out / 'engine.log'}", flush=True)
            continue
        for f in ("final.edl", "final.colors.json", "decision_log.json"):
            if (W / f).exists():
                shutil.copy(W / f, out / f)
        from collections import Counter
        c = Counter(x["reason"] for x in json.loads((out / "final.colors.json").read_text()))
        print(f"✓ {name}: {dict(c)}", flush=True)

    # Marker-EDL: Unterschiede zu „ausgewogen"
    basis_dir = T / "laeufe" / VARIANTEN[0][0]
    namen = ",".join(f"{k}={v}" for k, v in cfg["namen"].items())
    for name, _, gruende in VARIANTEN[1:]:
        if not gruende or not (T / "laeufe" / name / "final.edl").exists():
            continue
        r = subprocess.run([PY, str(ROOT / "analyse/aktivitaet/ab_marker.py"), str(basis_dir), str(T / "laeufe" / name),
                            str(T / "Marker" / f"{name} – Unterschiede.edl"), "--aaf", str(T / "AAF" / f"{name}.aaf"),
                            "--namen", namen, "--gruende", gruende,
                            "--label-a", "nur in ausgewogen", "--label-b", f"nur in {name[3:]}"],
                           capture_output=True, text=True)
        print(f"  Marker {name}: {r.stdout.strip() or r.stderr[-300:]}", flush=True)

    # Player-Runde Treffsicherheit Einwürfe (großzügig / streng gegen ausgewogen)
    import numpy as np
    from einwurf_analysespur import detect
    d = np.load(cfg["tabelle_prod"], allow_pickle=True)
    fps = float(d["fps"])
    ev = {i: detect([d["lv_ana0"], d["lv_ana1"]], d["engine"], fps,
                    {"uebersprechen_db": s["speaking_uebersprechen_db"], "umgebung_db": s["speaking_umgebung_db"]})[0]
          for i, s in enumerate(STUFEN["einwurf_sicher"])}

    def neu(a, b):   # Ereignisse in a, die in b nicht vorkommen
        return [(s, e) for s, e in a if not any(s2 < e + 15 and e2 > s - 15 for s2, e2 in b)]
    marker = []
    for k in (0, 1):
        for s, e in neu(ev[0][k]["events"], ev[1][k]["events"]):
            marker.append({"id": f"g{s}_{k}", "start": max(0, s - 15), "end": e, "person": k, "art": "grosszuegig",
                           "notiz": "Kommt nur bei „großzügig“ dazu — echter Einwurf?"})
        for s, e in neu(ev[1][k]["events"], ev[2][k]["events"]):
            marker.append({"id": f"s{s}_{k}", "start": max(0, s - 15), "end": e, "person": k, "art": "streng",
                           "notiz": "Fällt bei „streng“ weg — war das ein echter Einwurf?"})
    mj = {"marker": marker, "warum": True,
          "arten": {"grosszuegig": ["Nur bei großzügig", "#3ecf7a"], "streng": ["Fällt bei streng weg", "#ff9b3d"]}}
    pd = T / "player_einwurf_sicher"
    pd.mkdir(exist_ok=True)
    (pd / "marker_runde.json").write_text(json.dumps(mj, ensure_ascii=False), encoding="utf-8")
    pc = json.loads(Path(cfg["player_json"]).read_text(encoding="utf-8"))
    pc.update({"tabelle": cfg["tabelle_prod"], "titel": pc.get("titel", "") + " · Treffsicherheit Einwürfe"})
    (T / "player_einwurf_sicher.json").write_text(json.dumps(pc, indent=1, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([PY, str(ROOT / "analyse/player/bauen.py"), str(T / "player_einwurf_sicher.json"), str(pd),
                        "--marker-json", str(pd / "marker_runde.json"), "--ton-von", cfg["player_ton"],
                        "--hinweis", "Treffsicherheit Einwürfe: grün = kommt nur bei „großzügig“ dazu, "
                                     "orange = fällt bei „streng“ weg."], capture_output=True, text=True)
    print("Player:", (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1], flush=True)
    print(f"  großzügig +{sum(1 for m in marker if m['art'] == 'grosszuegig')}, "
          f"streng −{sum(1 for m in marker if m['art'] == 'streng')}")


if __name__ == "__main__":
    main()

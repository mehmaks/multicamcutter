#!/usr/bin/env python3
"""
Visualisiert RMS-Diarization als HTML-Timeline
"""

import argparse
import wave
import numpy as np
from pathlib import Path


def load_audio(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, 'rb') as wf:
        sr = wf.getframerate()
        n_ch = wf.getnchannels()
        raw = wf.readframes(wf.getnframes())
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if n_ch > 1:
        audio = audio.reshape(-1, n_ch).mean(axis=1)
    return audio, sr


def compute_rms_db(audio: np.ndarray, sr: int, window_s: float) -> np.ndarray:
    win = int(sr * window_s)
    rms_db = []
    for i in range(0, len(audio) - win, win):
        chunk = audio[i:i+win]
        rms = np.sqrt(np.mean(chunk**2))
        rms_db.append(20 * np.log10(rms + 1e-9))
    return np.array(rms_db)


def s_to_tc(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mic1', required=True)
    parser.add_argument('--mic2', required=True)
    parser.add_argument('--mic1-label', default='MIC1')
    parser.add_argument('--mic2-label', default='MIC2')
    parser.add_argument('--min-edit-duration', type=float, default=1.0)
    parser.add_argument('--change-delay', type=float, default=0.3)
    parser.add_argument('--threshold-db', type=float, default=6.0)
    parser.add_argument('--analysis-window', type=float, default=0.05)
    parser.add_argument('--output', '-o', default='diarization.html')
    args = parser.parse_args()

    print("Lade Audio...")
    audio1, sr = load_audio(args.mic1)
    audio2, _  = load_audio(args.mic2)
    n = min(len(audio1), len(audio2))
    audio1, audio2 = audio1[:n], audio2[:n]
    duration_s = n / sr

    print("Berechne RMS...")
    win_s = args.analysis_window
    rms1 = compute_rms_db(audio1, sr, win_s)
    rms2 = compute_rms_db(audio2, sr, win_s)
    n_win = min(len(rms1), len(rms2))
    rms1, rms2 = rms1[:n_win], rms2[:n_win]

    # Dominanz
    diff = rms1 - rms2
    dominant = np.full(n_win, None, dtype=object)
    dominant[diff >  args.threshold_db] = 'MIC1'
    dominant[diff < -args.threshold_db] = 'MIC2'

    # Change Delay smoothing
    delay_wins = max(1, int(args.change_delay / win_s))
    smoothed = list(dominant)
    current = None
    consecutive_new = 0
    for i in range(n_win):
        raw = dominant[i]
        if raw == current or raw is None:
            consecutive_new = 0
            smoothed[i] = current
        else:
            consecutive_new += 1
            if consecutive_new >= delay_wins:
                current = raw
            smoothed[i] = current

    # Segmente
    segments = []
    seg_start = 0
    seg_speaker = smoothed[0]
    for i in range(1, n_win):
        if smoothed[i] != seg_speaker:
            segments.append({'speaker': seg_speaker, 'start': seg_start, 'end': i})
            seg_start = i
            seg_speaker = smoothed[i]
    segments.append({'speaker': seg_speaker, 'start': seg_start, 'end': n_win})

    # Min Edit Duration merge
    min_edit_wins = max(1, int(args.min_edit_duration / win_s))
    merged = True
    while merged:
        merged = False
        new_segs = []
        i = 0
        while i < len(segments):
            seg = segments[i]
            dur = seg['end'] - seg['start']
            if dur < min_edit_wins and seg['speaker'] is not None:
                prev_dur = segments[i-1]['end'] - segments[i-1]['start'] if i > 0 else 0
                next_dur = segments[i+1]['end'] - segments[i+1]['start'] if i < len(segments)-1 else 0
                if prev_dur >= next_dur and i > 0:
                    new_segs[-1]['end'] = seg['end']
                elif i < len(segments) - 1:
                    segments[i+1]['start'] = seg['start']
                    i += 1
                    continue
                merged = True
            else:
                new_segs.append(seg)
            i += 1
        segments = new_segs

    # None → Nachbar
    for i, seg in enumerate(segments):
        if seg['speaker'] is None:
            seg['speaker'] = segments[i-1]['speaker'] if i > 0 else (segments[i+1]['speaker'] if i < len(segments)-1 else 'MIC1')

    # Merge gleiche Nachbarn
    final = []
    for seg in segments:
        start_s = seg['start'] * win_s
        end_s   = seg['end']   * win_s
        if final and final[-1]['speaker'] == seg['speaker']:
            final[-1]['end_s'] = end_s
        else:
            final.append({'speaker': seg['speaker'], 'start_s': start_s, 'end_s': end_s})

    # RMS für Waveform (auf 1s resamplen für HTML-Performance)
    vis_win = 1.0
    vis_wins = int(duration_s / vis_win)
    rms1_vis = compute_rms_db(audio1, sr, vis_win)[:vis_wins]
    rms2_vis = compute_rms_db(audio2, sr, vis_win)[:vis_wins]

    # Normalisiere für Anzeige (0–1)
    def norm(arr):
        lo, hi = arr.min(), arr.max()
        return ((arr - lo) / (hi - lo + 1e-9)).tolist()

    rms1_norm = norm(rms1_vis)
    rms2_norm = norm(rms2_vis)

    # Stats
    mic1_s = sum(s['end_s'] - s['start_s'] for s in final if s['speaker'] == 'MIC1')
    mic2_s = sum(s['end_s'] - s['start_s'] for s in final if s['speaker'] == 'MIC2')

    # Waveform bars (pre-built)
    wv1_html = ''.join(
        f'<div class="waveform-bar" style="height:{int(v*100)}%;background:#3b82f6"></div>'
        for v in rms1_norm
    )
    wv2_html = ''.join(
        f'<div class="waveform-bar" style="height:{int(v*100)}%;background:#10b981"></div>'
        for v in rms2_norm
    )

    # Segmente als JS-Array
    seg_js = []
    for s in final:
        pct_start = s['start_s'] / duration_s * 100
        pct_end   = s['end_s']   / duration_s * 100
        pct_width = pct_end - pct_start
        color = '#3b82f6' if s['speaker'] == 'MIC1' else '#10b981'
        seg_js.append({
            'speaker': s['speaker'],
            'start_s': round(s['start_s'], 2),
            'end_s':   round(s['end_s'],   2),
            'pct_start': round(pct_start, 4),
            'pct_width': round(pct_width, 4),
            'color': color,
            'tc': s_to_tc(s['start_s']),
            'dur': round(s['end_s'] - s['start_s'], 1),
        })

    # Diarization bar segments (pre-built)
    diar_segs_html = ''.join(
        f'<div class="diar-seg" style="left:{s["pct_start"]}%;width:{s["pct_width"]}%;background:{s["color"]}"'
        f' data-speaker="{s["speaker"]}" data-tc="{s["tc"]}" data-dur="{s["dur"]}s"'
        f' data-start="{s["start_s"]}" data-end="{s["end_s"]}"></div>'
        for s in seg_js
    )

    # Cut list rows (pre-built)
    def row_label(sp):
        return args.mic1_label if sp == 'MIC1' else args.mic2_label
    def row_color(sp):
        return '#3b82f6' if sp == 'MIC1' else '#10b981'

    cutlist_rows = ''.join(
        f'<tr>'
        f'<td style="color:#475569">{i+1}</td>'
        f'<td><span class="dot" style="background:{row_color(s["speaker"])}"></span>{row_label(s["speaker"])}</td>'
        f'<td>{s_to_tc(s["start_s"])}</td>'
        f'<td>{s_to_tc(s["end_s"])}</td>'
        f'<td>{round(s["end_s"]-s["start_s"],1)}s</td>'
        f'</tr>'
        for i, s in enumerate(final)
    )

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>RMS Diarization</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, sans-serif; background: #0f172a; color: #e2e8f0; padding: 24px; }}
  h1 {{ font-size: 1.2rem; font-weight: 600; margin-bottom: 4px; }}
  .meta {{ font-size: 0.8rem; color: #64748b; margin-bottom: 24px; }}
  .stats {{ display: flex; gap: 24px; margin-bottom: 24px; }}
  .stat {{ background: #1e293b; border-radius: 8px; padding: 12px 18px; }}
  .stat-label {{ font-size: 0.7rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }}
  .stat-value {{ font-size: 1.3rem; font-weight: 700; margin-top: 2px; }}
  .mic1 {{ color: #3b82f6; }} .mic2 {{ color: #10b981; }}

  .timeline-wrap {{ background: #1e293b; border-radius: 10px; padding: 20px; margin-bottom: 16px; }}
  .timeline-label {{ font-size: 0.72rem; color: #64748b; margin-bottom: 8px; }}

  /* Waveform */
  .waveform-row {{ display: flex; align-items: center; gap: 10px; margin-bottom: 6px; height: 40px; }}
  .waveform-name {{ width: 42px; font-size: 0.7rem; color: #94a3b8; text-align: right; flex-shrink: 0; }}
  .waveform {{ flex: 1; height: 40px; display: flex; align-items: flex-end; gap: 0; overflow: hidden; border-radius: 4px; background: #0f172a; }}
  .waveform-bar {{ flex: 1; min-width: 1px; border-radius: 1px 1px 0 0; opacity: 0.7; }}

  /* Diarization bar */
  .diar-row {{ display: flex; align-items: center; gap: 10px; margin-top: 14px; }}
  .diar-name {{ width: 42px; font-size: 0.7rem; color: #94a3b8; text-align: right; flex-shrink: 0; }}
  .diar-bar {{ flex: 1; height: 28px; position: relative; background: #0f172a; border-radius: 4px; overflow: hidden; cursor: crosshair; }}
  .diar-seg {{ position: absolute; top: 0; height: 100%; border-radius: 2px; transition: opacity 0.1s; }}
  .diar-seg:hover {{ opacity: 0.75 !important; }}

  /* Playhead */
  .playhead {{ position: absolute; top: 0; width: 2px; background: #f8fafc; height: 100%; pointer-events: none; z-index: 10; }}

  /* Ruler */
  .ruler {{ flex: 1; height: 20px; position: relative; margin-left: 52px; margin-bottom: 4px; }}
  .ruler-tick {{ position: absolute; font-size: 0.6rem; color: #475569; transform: translateX(-50%); }}

  /* Tooltip */
  #tooltip {{ position: fixed; background: #0f172a; border: 1px solid #334155;
              padding: 8px 12px; border-radius: 6px; font-size: 0.75rem; pointer-events: none;
              display: none; z-index: 100; line-height: 1.6; }}

  /* Cut list */
  .cutlist {{ background: #1e293b; border-radius: 10px; padding: 20px; }}
  .cutlist h2 {{ font-size: 0.85rem; font-weight: 600; margin-bottom: 12px; color: #94a3b8; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.78rem; }}
  th {{ text-align: left; padding: 6px 10px; color: #64748b; font-weight: 500;
        border-bottom: 1px solid #334155; }}
  td {{ padding: 5px 10px; border-bottom: 1px solid #1e293b; font-variant-numeric: tabular-nums; }}
  tr:hover td {{ background: #0f172a; }}
  .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }}
</style>
</head>
<body>
<h1>RMS Diarization</h1>
<div class="meta">
  {Path(args.mic1).name} vs {Path(args.mic2).name} &nbsp;·&nbsp;
  {s_to_tc(duration_s)} &nbsp;·&nbsp;
  Threshold: {args.threshold_db} dB &nbsp;·&nbsp;
  Min Edit: {args.min_edit_duration}s &nbsp;·&nbsp;
  Change Delay: {args.change_delay}s
</div>

<div class="stats">
  <div class="stat">
    <div class="stat-label">Segmente</div>
    <div class="stat-value">{len(final)}</div>
  </div>
  <div class="stat">
    <div class="stat-label"><span class="dot" style="background:#3b82f6"></span>{args.mic1_label}</div>
    <div class="stat-value mic1">{mic1_s/60:.1f} min <span style="font-size:0.8rem;font-weight:400;color:#64748b">({mic1_s/duration_s*100:.0f}%)</span></div>
  </div>
  <div class="stat">
    <div class="stat-label"><span class="dot" style="background:#10b981"></span>{args.mic2_label}</div>
    <div class="stat-value mic2">{mic2_s/60:.1f} min <span style="font-size:0.8rem;font-weight:400;color:#64748b">({mic2_s/duration_s*100:.0f}%)</span></div>
  </div>
</div>

<div class="timeline-wrap">
  <div class="timeline-label">Waveform &amp; Schnitte</div>

  <div class="waveform-row">
    <div class="waveform-name">{args.mic1_label}</div>
    <div class="waveform" id="wv1">{wv1_html}</div>
  </div>
  <div class="waveform-row">
    <div class="waveform-name">{args.mic2_label}</div>
    <div class="waveform" id="wv2">{wv2_html}</div>
  </div>

  <div class="diar-row">
    <div class="diar-name">Schnitt</div>
    <div class="diar-bar" id="diarBar">
      {diar_segs_html}
      <div class="playhead" id="playhead" style="left:0%"></div>
    </div>
  </div>

  <div class="ruler" id="ruler"></div>
</div>

<div class="cutlist">
  <h2>Schnittliste ({len(final)} Cuts)</h2>
  <table>
    <thead><tr><th>#</th><th>Speaker</th><th>In</th><th>Out</th><th>Dauer</th></tr></thead>
    <tbody>{cutlist_rows}</tbody>
  </table>
</div>

<div id="tooltip"></div>

<script>
const duration = {round(duration_s, 2)};
const bar = document.getElementById('diarBar');
const playhead = document.getElementById('playhead');
const tooltip = document.getElementById('tooltip');
const ruler = document.getElementById('ruler');

// Ruler ticks (jede Minute)
const minCount = Math.floor(duration / 60);
for (let m = 0; m <= minCount; m++) {{
  const pct = (m * 60 / duration) * 100;
  const tick = document.createElement('div');
  tick.className = 'ruler-tick';
  tick.style.left = pct + '%';
  tick.textContent = m + 'm';
  ruler.appendChild(tick);
}}

function secToTC(s) {{
  const h = Math.floor(s / 3600).toString().padStart(2,'0');
  const m = Math.floor((s % 3600) / 60).toString().padStart(2,'0');
  const sec = Math.floor(s % 60).toString().padStart(2,'0');
  return h + ':' + m + ':' + sec;
}}

bar.addEventListener('mousemove', e => {{
  const rect = bar.getBoundingClientRect();
  const pct = (e.clientX - rect.left) / rect.width;
  const t = pct * duration;
  playhead.style.left = (pct * 100) + '%';

  // Segment unter Cursor
  const seg = e.target.closest('.diar-seg');
  if (seg) {{
    tooltip.style.display = 'block';
    tooltip.style.left = (e.clientX + 12) + 'px';
    tooltip.style.top  = (e.clientY - 10) + 'px';
    tooltip.innerHTML = `<b>${{seg.dataset.speaker}}</b><br>In: ${{secToTC(seg.dataset.start)}}<br>Out: ${{secToTC(seg.dataset.end)}}<br>Dauer: ${{seg.dataset.dur}}`;
  }} else {{
    tooltip.style.display = 'none';
  }}
}});

bar.addEventListener('mouseleave', () => {{
  tooltip.style.display = 'none';
}});

// Klick → TC in Zwischenablage
bar.addEventListener('click', e => {{
  const rect = bar.getBoundingClientRect();
  const pct = (e.clientX - rect.left) / rect.width;
  const t = pct * duration;
  navigator.clipboard.writeText(secToTC(t)).catch(()=>{{}});
}});
</script>
</body>
</html>"""

    with open(args.output, 'w') as f:
        f.write(html)
    print(f"✓ HTML gespeichert: {args.output}")


if __name__ == '__main__':
    main()

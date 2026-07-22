# Changelog — MultiCamCutter (English)

User-facing changes per version, English mirror of CHANGELOG.md. Same version
headings (`## 0.7.0`). English is optional per entry — if a version is missing
here, the website falls back to the German notes (contract, brain/Appcast-Hosting.md).

## 0.6.3

**New: More than two close-ups — setups with three or more people**

Until now the edit could only choose between two close-ups; a third person on
their own camera stayed silent in the cut. The app now recognizes any number of
speakers and cuts each person to the camera that frames them tightest — a third
person visible only on the wide shot lands on the wide shot. When several people
talk at once, it cuts to the smallest shot that shows everyone involved, and the
visual-language transitions work across several people too. Setups with exactly
two people behave unchanged.

**New: Multitrack recorder**

If all your audio tracks come from one multitrack recorder, you can now confirm
that in the "People" step. A track where no one is currently speaking is then no
longer wrongly rejected as "cannot be synchronized" — it inherits the shared
offset of the other tracks.

**More reliable audio synchronization**

If a person starts speaking only late, their track was sometimes not measured in.
Synchronization now looks for the most speech-rich part of a track instead of
always the very beginning, so late-starting speakers are found reliably.

## 0.6.2

Clearer messages during audio synchronization:

- When an audio track cannot be placed reliably, the message now names the file
  instead of only an internal label (such as "MIC3"). That makes it immediately
  clear which of your files is affected.
- The log shows at the start which file belongs to which track.

## 0.6.1

Small interface fixes:

- The first-launch hint is leaner: a point that described how the app works rather
  than a requirement for your material has been removed.
- In the overview, a very long camera name spilled out of its label. It is now
  truncated cleanly and adapts to the window width.

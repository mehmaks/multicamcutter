# Changelog — MultiCamCutter (English)

User-facing changes per version, English mirror of CHANGELOG.md. Same version
headings (`## 0.7.0`). English is optional per entry — if a version is missing
here, the website falls back to the German notes (contract, brain/Appcast-Hosting.md).

## 0.6.8

**Fixed: head-nod detection aborted the analysis**

In recent versions the analysis stopped as soon as head-nod detection began — an internal
component was missing from the shipped app. As a result, reaction cuts on head nods didn't
work. This is fixed; detection runs through completely again.

**New: sources that can't be synced automatically no longer stop the whole run**

If an audio or video track couldn't be synchronized with the others automatically, the
entire run used to abort. Now the app shows the affected source and you decide per source:
enter a time offset by hand (with a suggestion) or exclude the source from the edit. The
remaining sources continue normally.

**Fixed: wrong assignment after adding a new file to a known folder**

If you had opened a folder before and then copied a new audio track into it, the app could
assign a camera to the wrong person. The assignment is now restored via the file names and
stays correct.

**Improved: multiple wide shots are now used**

If you mark more than one camera as a wide shot, the edit now alternates between them — in
turn or at random, configurable in the expert settings — instead of always using only the
first.

**Further improvements**

The Dock progress bar reflects real progress more honestly: the long head-nod analysis now
dominates it, instead of the bar sitting just short of "done" for a long time. And the
window stays fixed during the analysis — it can no longer be resized by accident while a
run is in progress.

## 0.6.7

**Fixed: AAF export now imports flawlessly into Premiere Pro**

Until now Premiere Pro showed the media of an imported AAF as offline and searched
for wrongly named files — especially for video. The export is now structured so
Premiere links every clip to the right footage automatically. Importing into
DaVinci Resolve already worked before; both applications are now fully supported.

**Improved: converting mismatched frame rates is much faster**

When video files need converting to the timeline frame rate, the app now uses your
Mac's hardware acceleration. Depending on the material that's roughly three to four
times faster (half an hour becomes a few minutes), and the CPU stays free. The app
automatically picks a matching format so the copy is a faithful, still-gradeable
equivalent of the original. You can fine-tune the quality in the settings.

**New: cuts in the AAF are named by their reason**

Every cut in the exported AAF now carries a meaningful name — the speaking person
for speaker cuts, otherwise the reason (e.g. "cutaway"). That way, while reviewing,
you immediately see why a cut was made there. The naming pattern is fully
customizable in the settings; if you'd rather have exactly one clip per camera, you
can turn the feature off there.

**Fixed: audio preview kept playing when switching pages**

If you played an audio track on the first page and then switched pages, the sound
kept playing invisibly. It now stops when you switch pages.

**Further improvements**

The image-recognition (CLIP) filter prompts now only appear in the settings when
the model is installed. Short-lived info cards show a small depleting ring
indicating when they close on their own.

## 0.6.6

**Fixed: possible crash on the first launch after an update**

In rare cases the app could crash when relaunching right after an update. The
cause was an icon that wasn't ready yet at that exact moment. This can no longer
happen — if a graphic is briefly unavailable it simply stays blank instead of
taking down the app.

**New: isolation of each audio track is now visible**

Every audio card now shows how well its track is isolated — that is, how much
louder it is than the others when that person speaks (in dB). At a glance you
can tell which tracks are clean and which have a lot of bleed, and over several
episodes you get a feel for what's normal. The value is purely informational and
does not affect the edit.

**Improved: frame-rate conversion progress on the Dock icon**

When the app converts video files to the timeline frame rate, the Dock icon now
shows the progress too. Depending on the material this takes a few minutes — so
you can see how far along it is even with the app in the background.

## 0.6.5

**New: waveform for every audio track — click to listen**

Every audio card now shows its track's waveform, and a click plays it right
away. That lets you verify in seconds that the assignment is correct and that
each person is loudest on their own track. Waveforms are computed once (with a
progress indicator) and cached — the next time you open the folder they appear
instantly.

**Known folders open much faster**

Thumbnails, audio analysis and listening snippets are saved on the first scan
and reused afterwards instead of being recomputed every time.

**Window & interface**

The window now fits its height to the content on every page — no more empty
space below the overview, no manual resizing needed (the width is fixed now).
With two or more audio tracks the cards arrange in two columns, short-lived
notices dismiss themselves after a few seconds, and the app now uses the same
icon set as the website.

**Frame-rate warning right on the camera card**

If a video file's frame rate doesn't match the project, the warning now sits
directly on the affected camera card — no more guessing which file it means.

**Multi-seat licenses: seat usage visible**

For licenses with multiple seats, the settings now show how many seats are
currently in use (e.g. "2 of 3 in use").

**Updates arrive sooner**

The app now checks for new versions hourly instead of once a day.

## 0.6.4

**Fixed: 24-bit audio tracks were read incorrectly**

Audio tracks in 24 bit — the standard on many field recorders — were internally
misread as noise. Speaker detection then found no differences between the
tracks, and the run aborted with a technical error. All bit depths are now
decoded correctly. Audio synchronization was never affected by this bug.

**A clear message instead of a crash**

If speaker detection cannot tell the audio tracks apart, the app now explains
the likely causes (e.g. a mix instead of individual tracks) and suggests
listening to the tracks individually — instead of aborting with an unrelated
error message.

**New: notice for known folders**

When you reopen a folder, the app jumps straight to the overview as before —
but now also tells you that your previous assignments were loaded. Use "Reset
assignments" in the notice to start cleanly from scratch when needed.

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

# Changelog — MultiCamCutter (English)

User-facing changes per version, English mirror of CHANGELOG.md. Same version
headings (`## 0.7.0`). English is optional per entry — if a version is missing
here, the website falls back to the German notes (contract, brain/Appcast-Hosting.md).

## 1.1.0-beta.6

**New: The app remembers your settings**

When you open an episode that has no saved settings yet, the app now starts with the settings you used last – even after a restart. Previously it went back to the defaults. Episodes you have opened before keep their own settings as before.

**New: Beta updates after downloading from the website**

If you install a beta version, you are now automatically offered the next betas too. If you deliberately turned “Receive beta versions” off, it stays off. Note: this only works from this version on – if you downloaded beta.5 from the website, turn the switch on once yourself.

**Improved: A calmer picture during the analysis**

During the reaction analysis, the preview now shows just the camera image – without face mesh, reaction labels or file name. To see these overlays for checking the detection, turn on Expert settings → Debug → “Analysis overlays”.

**Improved: Progress bar in changing colours**

During a run, the progress bar slowly cycles through soft colours, starting with our green.

## 1.1.0-beta.5

**New: Simple view with tiles**

The simple view has been rebuilt. Tempo, head nods, interjections, pauses and – when there is a wide shot – the wide shot each get a tile with a switch and three levels, for example “calm · balanced · lively”. The levels have been checked on real episodes. Below them, “What to expect” describes in plain words what the cut will look like with your choice. All values are still available in the expert settings.

The built-in presets “Podcast 2-Cam”, “Interview (schnell)” and “Talk (entspannt)” are gone, because the levels take over their role. The preset list now only shows your own presets.

**Fixed: Pause trimming cut away quiet speech**

When trimming pauses at speaker changes, the app mistook quietly spoken sentence endings and beginnings – especially on the quieter microphone – for silence and removed them, sometimes almost two seconds. Pauses are now detected on the cleaned-up analysis track, and a little silence always remains before every sentence start and after every sentence end. If you cut with “Trim pauses”, run affected episodes again.

**Improved: Speaker changes in the silence**

If the camera change came just after the new person's first word or before the previous person's last word, it now moves into the silence in between – as long as the analysis track confirms that nobody is speaking there. The new person is on screen from their first word, and the pause can be shortened in the right place.

**Improved: Interjections always from the analysis track**

The analysis-track detection from beta.3 is now the only interjection detection. The “From analysis track (beta)” switch and the “Rise” slider are gone, as is the older crossbleed filter. The analysis track needs one microphone per person. Without it, the cut is made without interjections and the app tells you so.

**New: Trim pauses within a person's turn**

When “Trim pauses” and “Cutaways in pauses” are both on, the app also shortens long pauses in the middle of a person's turn – at the point where it cuts to the listener anyway. Pauses within a turn without a cutaway stay untouched.

**New: Cut offset for L- and J-cuts**

Under pause trimming, the new “Cut offset” slider sets how far the camera change moves away from the middle of the pause with an L- or J-cut. It always stays within the pause, however high the value.

**New: Interjections may shorten shots**

With this switch under interjections, an interjection cutaway is placed even if the shot before it becomes shorter than the minimum shot length. Together with the “often” level, every detected interjection is used.

**Improved: Laughter no longer triggers a speaker change**

The simple view now uses a minimum length of 1.6 s for speaker changes. A short laugh or sound from the other person no longer causes a change; short interjections become cutaways instead.

## 1.1.0-beta.4

**Fixed: Many cutaways were removed again during clean-up**

If the “Cutaway length” was set shorter than the “Min. cleanup length”, the final clean-up step
removed a large share of interjection and head-nod cutaways again — about 40 % in a test run with
1.6 s versus 1.8 s. Cutaways are now only removed if they are shorter than the cutaway length you
set yourself. If you cut with such settings, a new run will give you noticeably more cutaways.

**Improved: Interjection right before someone's own turn**

If someone made a short interjection just before a change of speaker and then went on talking,
the cutaway used to be cut short and dropped. Now that person's shot simply starts at the
interjection — the cut to them comes a little earlier.

**Improved: Clearer name**

The “Max. cutaway length” slider under Interjections is now called “Max. interjection length”. It
sets how long a sound may be to still count as an interjection — not how long the cutaway is. That
is set under Cutaway rules → Cutaway length.

## 1.1.0-beta.3

**New (beta): Interjections from the analysis track**

Under Expert settings → Interjections there is a new switch, “From analysis track (beta)”. The app then
creates a cleaned-up copy of each microphone with the other person's voice and the background noise
removed. Short interjections like “mhm” or “yes” stand out clearly there. In our test episodes this
produced three to four times as many interjection cuts as before, and about 95 % of the additional
interjections were genuine. Now and then the app mistakes a loud breath, a throat-clearing or a knock
for an interjection. The analysis takes about one minute longer. The “Rise” slider belongs to the
previous detection and is hidden while the switch is on. The feature needs two people with their own
microphone each; in other setups the previous detection stays active.

**New: Interjections take priority over head nods**

With “Priority over head nods” (also under Interjections), a head-nod cutaway gives way when it would
otherwise block an interjection shortly after it, for example because of the minimum shot length.
The switch is only active when both head nods and interjections are turned on.

**Removed for now: Interjections from mouth movement**

The beta feature “Mouth movement” from 1.1.0-beta.1 is hidden. The new detection on the analysis
track has the same goal and does not need face analysis. If you had it turned on, the analysis now
simply runs without it.

## 1.1.0-beta.2

**Improved: Clearer progress display**

During analysis the step is now called “Reaction analysis” instead of “Head-nod analysis”, because
it now also evaluates mouth movement. Instead of “CAM1” it shows the person's name with the shot
size, e.g. “Reaction analysis Seb · Close-up (C9667.MP4)”.

**Fixed: Camera label in German**

In German, the camera cards showed “Schließen” (close the window) instead of “Nah” (close-up). This
is corrected.

## 1.1.0-beta.1

**New: Beta versions**

In the settings under “Updates” you can now turn on “Receive beta versions”. You then get new
features before the official release. If you turn it off again, the app offers to take you back to
the current stable version.

**New (beta): Detect interjections from mouth movement**

Until now, the app only recognised short interjections from the listening person by sound and missed
many of them. With “Mouth movement (beta)” under Expert settings → Interjections, it also watches
whether the person's mouth moves. A cut is only added when the mouth moves and their own microphone
picks up sound at the same time. This finds considerably more real interjections like “yes”, “wow”
or a short laugh. Right at a change of speaker, mouth movement is ignored. The feature is off by
default and takes a bit more processing time if head-nod detection is turned off.

## 1.0.2

**Fixed: Split recordings were sometimes not joined**

When a recorder split a long multitrack recording into several files, the app sometimes failed to
recognise which parts belonged together, especially when nobody was speaking at the transition. The
parts then showed up as separate tracks. This is fixed. With Zoom recorders, the app now matches the
parts using the recorder input stored in every file, which is much more reliable than before. Your
existing edits are not affected.

## 1.0.1

**MultiCamCutter is now free**

You no longer need a license or a subscription. The 30-minute limit per recording is gone, so you
can cut episodes of any length. The License section in the settings has been removed.

## 1.0.0

**New: MultiCamCutter now speaks English**

The app follows your Mac's system language: on an English system it appears in English, otherwise
in German as before.

**New: split recordings are joined automatically**

Many recorders, such as the Zoom H6essential, split long recordings into several files. The app now
detects these parts on its own and treats them as one continuous track. The person overview then
shows e.g. "2 parts". Your edit project still uses your original files, placed seamlessly one after
another. If a recording isn't detected, use the link icon and choose "Belongs to …" to assign it by
hand. You can also split a wrong assignment there.

**Fixed: 29.97 fps projects drifting apart**

With cameras recording at 29.97 frames per second (e.g. Sony, drop-frame), the cameras in the edit
project drifted apart over time, and picture and sound could be offset right from the start.
External audio recorders were also off by one frame in such projects. Both are fixed. **If you
edited 29.97 fps footage with an earlier version, please export those projects again.**

**Fixed: presets**

Saving a preset under the name of a built-in preset seemed to have no effect. Also, with two presets
that had identical settings, the picker sometimes showed the wrong one. Both work now, and there is
a visible "Save preset" button.

## 0.6.10

**Fixed: reaction cuts (head nods, interjections) sit exactly on the reaction again**

In some recordings, part of the reaction cuts — head nods especially — were placed only after the
reaction was already over, so the cut landed on a motionless person. The cause was the
image-recognition filter ("move unsuitable cutaways"), which in rare cases wrongly shifted those
moments.
Reaction cuts are no longer shifted by it — they stay exactly on the detected moment. The filter
stays active for camera switches during long passages, and is a little more conservative overall.

**Fixed: occasional single-frame fragments in the timeline**

In a few spots, tiny fragments could remain between two cuts — a brief flash of the base camera.
These are now removed reliably.

## 0.6.9

**New: anonymous usage statistics — optional**

On first launch after this update, the app asks once whether it may send anonymous
usage numbers: how many cameras, microphones and people a project has, how long the
recordings and a run take, and which Mac. This helps improve the app in a targeted way —
for example, seeing which steps take the most time. Only numbers are sent, never names,
files or paths, and everything stays anonymous. The prompt is optional and can be turned
off any time in Settings under "Privacy".

**Fixed: the update dialogs now appear in the app's language**

The dialogs for finding and installing updates used to appear in English even though the
rest of the app is in German. They now match the app's language.

**Improved: clearer labels and help texts**

Many names and explanations in the settings were revised and unified — a few sliders now
have clearer names. Nothing about the behavior changes.

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

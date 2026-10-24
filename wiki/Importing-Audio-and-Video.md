# Importing audio and video

Already have a recording? A Zoom or Teams recording, a voice memo from your phone, a lecture video? Sabhalekh can
transcribe it.

## How

Either:

- Click **Upload Media** (or press **Ctrl+O**) and choose one or more files, or
- **Drag files** from File Explorer anywhere onto the Sabhalekh window.

Each file becomes a meeting in your list and is processed one after another. You can close the window while it works;
it carries on in the background (with *Keep running in the tray* turned on).

## Supported formats

| Audio | Video |
|---|---|
| mp3, wav, m4a, aac, flac, ogg, opus, wma | mp4, mkv, mov, avi, webm |

From video files only the sound is used.

Your original file is **never changed or moved**. Sabhalekh reads it once and keeps its own copy of the audio for
playback, so you can delete or move the original afterwards.

## Imported files vs recordings

Imported files work exactly like recordings, with one difference: a file has only one sound track, so there is no
"You". Every voice is detected and labelled *Speaker 1*, *Speaker 2* and so on. Click a name to rename it (see
[Working with transcripts](Working-with-Transcripts)).

## Choosing the language before processing

Imports use the language set in **Settings → Transcription → Language** (Auto by default, which handles English,
Hindi and a mix of both). To transcribe a file differently, open it and choose **⋯ → Re-process…** to pick another
language or model. See [Languages and Hindi](Languages-and-Hindi).

## Turning off automatic processing

If you want to import several files and process them later, turn off **Settings → Transcription → Process
automatically**. Then open a meeting and choose **⋯ → Re-process…** when you're ready.

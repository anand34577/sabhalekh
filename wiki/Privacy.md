# Privacy

**Short version: nothing ever leaves your PC.**

Sabhalekh has no account, no cloud service, no analytics, no crash reporting and no update checks. Recording,
transcription, speaker detection and search all run on your computer.

## How that is enforced

This isn't just a promise in a privacy policy. The app is built so that it can't go online:

- The processing engine blocks every network connection except to itself on the same PC (`127.0.0.1`). An attempt to
  reach the internet raises an error instead. **Settings → Privacy** shows how many attempts were blocked in the
  current session; it should always be 0.
- The app window may only load files that ship with the app and talk to that local engine.
- Microsoft Edge WebView2's background services (SmartScreen lookups, translation, component updates) are switched off
  for the app window.
- The project's automated tests fail if any of this stops working.

The source code is public, so anyone can check.

The only links to the internet are the **User guide**, **Report a problem** and **Source code** buttons in
**Settings → About**. They open in your own web browser, and only when you click them.

## What is stored, and where

Everything lives in one folder: `%APPDATA%\Sabhalekh` (paste that into the File Explorer address bar to open it).

| What | Where |
|---|---|
| Transcripts, speaker names, edits, settings | `sabhalekh.db` |
| Audio of each meeting | `sessions\<number>\` |
| Recordings in progress (for crash recovery) | `recordings-in-progress\` |
| Logs (technical messages, no transcript text) | `logs\` |
| Imported model packs | `models\` |

Imported files are never copied whole and never changed: Sabhalekh keeps only its own audio copy for playback.

## Deleting your data

- **One meeting:** open it, **⋯ → Delete…**
- **Audio only, automatically:** **Settings → Storage → Delete audio automatically** after 7, 30 or 90 days or a year.
  Transcripts are kept; only the audio of finished meetings is removed.
- **Everything:** close Sabhalekh (tray icon → Quit) and delete the `%APPDATA%\Sabhalekh` folder.

Uninstalling the app keeps your data, in case you reinstall.

## Recording other people

Sabhalekh makes recording easy, but the responsibility stays with you. **Tell people when you record**, and follow
the law where you live and the rules of your workplace. In many places recording a conversation without consent is
illegal.

## The local engine

The window talks to its processing engine over HTTP on `127.0.0.1`, on a random port, with a new random 256-bit
password for every launch. Other computers on your network can't reach it, and other programs on your PC can't use it
without that password.

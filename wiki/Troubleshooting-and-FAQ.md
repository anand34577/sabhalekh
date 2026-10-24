# Troubleshooting and FAQ

## Recording

### The audio test says "silent"

**Microphone was silent**
- Speak during the four seconds of the test, not before.
- Check that Windows can hear you: **Windows Settings → System → Sound → Input**, speak and watch the bar.
- Windows may be blocking microphone access: **Windows Settings → Privacy & security → Microphone**, turn on
  *Microphone access* and *Let desktop apps access your microphone*.
- Pick the right microphone in **Sabhalekh → Settings → Audio devices**.

**System audio was silent**
- Something has to *play* during the test. Start a YouTube video or music, then click **Start test**.
- Under **Settings → Audio devices → System audio**, choose the speakers or headset you actually listen on.

### Other people's voices are missing

Sabhalekh records what your PC plays on the selected output device. If the call plays somewhere else, it isn't heard.

1. In your meeting app's audio settings, check which **speaker** device it uses.
2. In Sabhalekh, **Settings → Audio devices → System audio**, choose the same device (or *Windows default output*
   if the meeting app also uses the default).
3. **Bluetooth headsets** often switch to a separate *Hands-Free* device during calls. Choose that one.

While recording, the **Others (system audio)** meter should move whenever someone else talks.

### My voice appears twice, or as another speaker

Without headphones your microphone also hears your speakers. Sabhalekh removes most of that echo, but some can slip
through. Headphones or earbuds fix it completely.

### The app crashed while I was recording

Open Sabhalekh again. It offers to **Recover** the unfinished recording. At most the last couple of seconds are lost.

### The recording hotkey doesn't work

Another program is using the same keys. Choose a different combination in **Settings → Shortcuts & startup**.

## Transcripts

### Hindi comes out as English words (or the other way round)

Set **Settings → Transcription → Language** to **Hindi only** (or **English only**), then **⋯ → Re-process…** the
meeting.

### English words appear in Devanagari

That's how the speech model writes Hinglish: "स्पीड डिटेक्शन" for "speed detection". Choose **Roman** under
**Hindi / Hinglish script** if you prefer Latin letters. See [Languages and Hindi](Languages-and-Hindi).

### Two people were merged into one speaker, or one person was split into two

- Re-process with **Minimum speakers** or **Maximum speakers** set (in **⋯ → Re-process…**). Minimum speakers helps
  when a quiet person is missed; it can't separate voices that sound very alike.
- Fix individual lines by clicking the speaker name. See [Working with transcripts](Working-with-Transcripts).
- Up to 8 speakers are supported. With more, some voices get merged.

### Some words are wrong

Speech recognition is never perfect, especially with background noise, people talking over each other, or very fast
speech. Edit the line (hover → ✏️). Better microphones and headphones make the biggest difference.

## Processing

### Processing is slow

Look at the badge at the bottom left. **CPU Mode** is about half as fast as a graphics card. If you have a graphics
card but see CPU Mode, update its driver, then **Settings → Hardware → Re-detect**. See
[Hardware and speed](Hardware-and-Speed).

### "GPU found but neither Vulkan nor CUDA could use it"

Your graphics driver is too old or broken. Install the latest driver from NVIDIA, AMD or Intel. Until then Sabhalekh
uses the built-in graphics or the CPU, so everything still works, just slower.

### A meeting failed to process

Open the **processing queue** (the list icon at the bottom left). The failed job shows the reason in plain words, for
example a full disk. Fix it and click **Retry**.

### "The processing engine stopped"

Click **Restart engine**. Your recordings and transcripts are safe. If it keeps happening, open
**Settings → Storage → Open logs folder**, and attach the end of `backend.log` to a
[bug report](https://github.com/anand34577/sabhalekh/issues/new/choose).

## Installation and start-up

### Windows says "Windows protected your PC"

The installer isn't code-signed yet. Click **More info → Run anyway**. You can check the download against
`SHA256SUMS.txt`, see [Installation](Installation#optional-check-that-your-download-is-genuine).

### The window is blank on Windows 10

Install the Microsoft Edge WebView2 Runtime. See [Installation](Installation#windows-10-blank-window).

### I want Sabhalekh to start with Windows

**Settings → Shortcuts & startup → Start with Windows**. It opens minimised in the tray, ready for the hotkey.

## Frequently asked questions

**Is it really free?** Yes. It's open source under the MIT License: no ads, no paid tier, no account.

**Does it work without internet?** Yes, completely. It never connects to the internet at all.

**Can it join my meeting as a bot?** No, and it doesn't need to. It records what your own PC plays and hears, so
nobody sees an extra participant. Please tell people you're recording.

**Does it work on Mac or Linux?** Not at the moment. Recording relies on Windows audio features.

**Can it summarise the meeting?** Not yet. Export the transcript and use whatever tool you like.

**Which languages are supported?** English, Hindi and Hinglish. See [Languages and Hindi](Languages-and-Hindi).

**Where are my files?** In `%APPDATA%\Sabhalekh`. See [Privacy](Privacy#what-is-stored-and-where).

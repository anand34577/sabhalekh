# Installation

## What you need

- A PC with **Windows 10 or Windows 11** (64-bit)
- **8 GB of RAM** or more
- About **2 GB of free disk space**, plus room for your recordings (an hour of meeting audio takes about 30 MB)
- A graphics card is **optional**. It makes processing about twice as fast, but any PC can run Sabhalekh on the CPU.

You do **not** need an internet connection to install or use Sabhalekh, and you do not need admin rights.

## Step 1: Download

1. Open the [latest release page](https://github.com/anand34577/sabhalekh/releases/latest).
2. Under **Assets**, click **`Sabhalekh-Setup-1.2.0.exe`** (the version number may be higher). It's about 850 MB,
   because the speech models are inside.

You don't need the other files to get started:

| File | What it is |
|---|---|
| `Sabhalekh-Setup-x.y.z.exe` | The installer. This is the one you want. |
| `Sabhalekh-ModelPack-Accuracy.zip` | Optional. Adds Hindi-to-English translation. See [Offline model packs](Offline-Model-Packs). |
| `SHA256SUMS.txt` | Checksums, if you want to verify your download (see below). |

## Step 2: Install

1. Double-click the downloaded file.
2. If Windows shows **"Windows protected your PC"**, click **More info**, then **Run anyway**. This warning appears
   because the installer isn't code-signed yet. It does not mean anything is wrong with it.
3. Click **Install**. It takes about a minute.
4. Leave **Run Sabhalekh** ticked and click **Finish**.

Sabhalekh installs for your Windows user only, in `%LOCALAPPDATA%\Sabhalekh`, and adds itself to the Start menu.

The first time it opens, a short welcome guide checks your microphone and speakers. Continue with
[Getting started](Getting-Started).

### Windows 10: blank window?

Sabhalekh draws its window with Microsoft Edge WebView2. Windows 11 always has it, and most Windows 10 PCs do too. If
the window stays blank or empty, install the **Evergreen Standalone** WebView2 Runtime from Microsoft's
[WebView2 download page](https://developer.microsoft.com/microsoft-edge/webview2/), then open Sabhalekh again.

## Optional: check that your download is genuine

Every release lists the SHA-256 checksum of each file in `SHA256SUMS.txt`. To compare:

1. Open **PowerShell** (press Start, type `powershell`, press Enter).
2. Run this, using the actual path of your download:

   ```powershell
   Get-FileHash "$env:USERPROFILE\Downloads\Sabhalekh-Setup-1.2.0.exe" -Algorithm SHA256
   ```

3. The long code it prints should match the line for that file in `SHA256SUMS.txt`.

## Updating

Sabhalekh never checks for updates on its own (it never goes online). To update, download the new installer from the
[releases page](https://github.com/anand34577/sabhalekh/releases) and run it. Your meetings and settings are kept.

To hear about new versions, open the [repository](https://github.com/anand34577/sabhalekh), click **Watch → Custom →
Releases**.

## Moving from MeetScribe

The pre-release builds of this app were called **MeetScribe**. If you used one:

1. Close MeetScribe completely (right-click its tray icon → **Quit**).
2. Install and open Sabhalekh. Your meetings, recordings and settings move to the new folder automatically.
3. Uninstall MeetScribe: **Settings → Apps → Installed apps → MeetScribe → Uninstall**.

If MeetScribe was still running in step 2, Sabhalekh uses your old folder as it is and tries the move again next
time. Nothing is lost either way.

## Uninstalling

**Settings → Apps → Installed apps → Sabhalekh → Uninstall.**

Uninstalling removes the app but **keeps your meetings** in `%APPDATA%\Sabhalekh`, in case you reinstall. To delete
them as well, open that folder (paste `%APPDATA%\Sabhalekh` into the File Explorer address bar) and delete it.

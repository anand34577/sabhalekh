# Contributing to Sabhalekh

Thanks for helping. Bug reports, ideas, documentation fixes and code are all welcome.

## Reporting bugs and suggesting features

Use the [issue templates](https://github.com/anand34577/sabhalekh/issues/new/choose). For bugs, include your Sabhalekh
and Windows versions and the end of `backend.log` (Settings → Storage → **Open logs folder**). The log contains file
names and hardware details but never your transcripts; look it over before you paste it.

Please don't attach recordings of real meetings. If a problem only shows up with certain audio, describe it, or share
a short clip you are allowed to share.

## Improving the user guide

The [wiki](https://github.com/anand34577/sabhalekh/wiki) is generated from the [`wiki/`](wiki) folder. Edit the
Markdown there and open a pull request; it is published automatically when merged. Write for someone who has never
used a terminal: short steps, the exact names of buttons, and what they will see.

## Working on the code

1. Install Python 3.12, Node.js 20+ and Rust (see [Building from source](https://github.com/anand34577/sabhalekh/wiki/Building-from-Source)).
2. Set up the backend and run the tests. These need no models:

   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\pip install -r backend\requirements-dev.txt
   .venv\Scripts\python -m pytest tests -q
   ```

3. Work on the UI in a browser against a running backend:

   ```powershell
   .venv\Scripts\python backend\run_backend.py --token devtoken0123456789 --port 8791
   cd app; npm ci; npm run dev
   # open http://localhost:1420/?port=8791&token=devtoken0123456789
   ```

4. For the full desktop app (`installer\dev.ps1`) or the installer (`installer\build.ps1`) you also need the models
   and the transcribe.cpp runtime; the guide explains how to produce them.

### Guidelines

- Sabhalekh is offline-only. Don't add anything that opens a network connection; `tests/test_offline.py` will fail.
- Keep the installer small. A new dependency needs a good reason and a row in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)
  with a license that allows redistribution.
- Test Hindi as well as English when you touch text handling, search or exports.
- Check both light and dark themes for UI changes.
- Add a line under **Unreleased** in [CHANGELOG.md](CHANGELOG.md) for anything users will notice, written for users.
- One topic per pull request, with a short note on what you changed and how you tested it.

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE).

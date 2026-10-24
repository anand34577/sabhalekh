# Security policy

## Supported versions

Security fixes go into the latest release. Please update before reporting.

## Reporting a vulnerability

Please **don't** open a public issue for security problems. Use GitHub's private reporting instead:
[Report a vulnerability](https://github.com/anand34577/sabhalekh/security/advisories/new).

Include what you found, how to reproduce it and the version affected. You'll get a reply as soon as possible, and
credit in the release notes if you'd like.

Things that are especially interesting: any way the app sends data off the PC, any way another program or web page
can reach the local backend (it listens on 127.0.0.1 with a random port and a per-launch token), and anything that
exposes recordings or transcripts to other user accounts.

## Verifying downloads

Every release includes `SHA256SUMS.txt`. Compare it with the file you downloaded:

```powershell
Get-FileHash .\Sabhalekh-Setup-1.2.0.exe -Algorithm SHA256
```

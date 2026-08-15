# UI fonts

Orbit prefers **Zen Kaku Gothic New** (body) and **Space Mono** (readouts)
when those files are present:

- `ZenKakuGothicNew-Regular.ttf`
- `ZenKakuGothicNew-Light.ttf` (optional; display)
- `SpaceMono-Regular.ttf`

Both families are SIL Open Font License. Drop the TTF files here to use them.

Otherwise Arelis maps to the bundled IBM Plex files (same tracking in QSS):

- `IBMPlexSans-Regular.ttf`
- `IBMPlexSans-SemiBold.ttf`
- `IBMPlexMono-Regular.ttf`

Source: [IBM/plex](https://github.com/IBM/plex) releases
`@ibm/plex-sans@1.1.0` and `@ibm/plex-mono@1.1.0` (SIL Open Font License).

If those are missing too, Arelis falls back to Segoe UI / Consolas on Windows
and logs a warning once at startup.

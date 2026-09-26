# UI fonts

Desk face is **Zen Kaku Gothic New**. Readouts are **Space Mono**.
Both are SIL Open Font License. The files in this folder are the ones
`load_fonts()` registers:

- `ZenKakuGothicNew-Light.ttf` (300)
- `ZenKakuGothicNew-Regular.ttf` (400, body weight)
- `ZenKakuGothicNew-Medium.ttf` (500)
- `ZenKakuGothicNew-Bold.ttf` (700)
- `SpaceMono-Regular.ttf`
- `SpaceMono-Bold.ttf`

Source: [google/fonts](https://github.com/google/fonts) `ofl/zenkakugothicnew`
and `ofl/spacemono`. License text is `OFL-ZenKakuGothicNew.txt` and
`OFL-SpaceMono.txt`.

IBM Plex is the fallback if a desk file fails to load:

- `IBMPlexSans-Regular.ttf`
- `IBMPlexSans-SemiBold.ttf`
- `IBMPlexMono-Regular.ttf`

Source: [IBM/plex](https://github.com/IBM/plex) releases
`@ibm/plex-sans@1.1.0` and `@ibm/plex-mono@1.1.0` (SIL Open Font License).

If those are missing too, Arelis falls back to Segoe UI / Consolas on Windows
and logs a warning once at startup.

# Changelog

## Unreleased

Filament is now the main theme and the default for new installs. Sodium and
night are listed as Sodium (legacy) and Night (legacy) and still fully work.
A saved choice is kept, and an install that never picked a theme stays on
sodium. A missing or unknown theme name now opens filament. In sodium and night Arelis's 3D figure is tinted to the room (amber
on sodium, violet on night); only her colour changes, and the painted face
still takes over when 3D cannot run. The legacy idle orbit wears her aether
look in the same colour, with floor rings that ripple outward, and the orb in
her panel matches it. Ctrl+1 closes her panel on the first press after
launch. See [docs/idle-orbit.md](docs/idle-orbit.md).

Christopher chose llama.cpp as the sole chat engine. The retired local
server (Ollama) is gone: the provider, the installer, model pull, and the
settings block. An old config that still sets `llm.provider` to `ollama`,
or keeps an `ollama:` block, loads as llama.cpp. Those keys are dropped in
memory. The file on disk is not rewritten.

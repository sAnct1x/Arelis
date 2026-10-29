# Changelog

## Unreleased

The sodium and night idle orbit now wears her aether look (violet thread
frame, floor rings, stars). Ctrl+1 closes her panel on the first press after
launch. See [docs/idle-orbit.md](docs/idle-orbit.md).

Christopher chose llama.cpp as the sole chat engine. The retired local
server (Ollama) is gone: the provider, the installer, model pull, and the
settings block. An old config that still sets `llm.provider` to `ollama`,
or keeps an `ollama:` block, loads as llama.cpp. Those keys are dropped in
memory. The file on disk is not rewritten.

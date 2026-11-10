# Third-party notices

Arelis downloads some speech weights at runtime. They are not shipped in
the repository or the installer.

## NVIDIA Parakeet TDT 0.6B v3

The optional speech-to-text engine (`voice.stt.engine: parakeet`) uses
NVIDIA's Parakeet TDT 0.6B v3 model, converted to int8 ONNX by the
sherpa-onnx project.

- Weights: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- Model card: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- Pack: `sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2` from
  https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models

Attribution: Parakeet TDT 0.6B v3 by NVIDIA, licensed under CC BY 4.0.

## sherpa-onnx

The CPU runtime that loads the Parakeet pack (and the optional streaming
Zipformer ear) is [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx),
licensed under [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).

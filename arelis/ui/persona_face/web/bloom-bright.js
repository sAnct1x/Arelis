// The bloom's bright pass (three's LuminosityHighPassShader), fed only finite light.
// index.html's import map loads this in place of the vendored shader, so UnrealBloomPass
// and aether.js stay as they are.
// Her glow is additive in a half-float target: dense overlaps (her legs, the hem threads, more
// of them while she listens, smiles or talks) can overflow to Inf, and a filtered Inf texel is
// NaN. One NaN spreads through the blur chain into a block of the smallest mip, and the
// composite (light keyed to alpha) turns every pixel that samples it see-through: in Sodium
// she was cut off at the chest. Same fix as the Quick 3D bloom (persona_q3d/bloom/bright.frag).
import { Color } from 'three';

const BRIGHT_MAX = '64.0';

const LuminosityHighPassShader = {
  name: 'LuminosityHighPassShader',
  shaderID: 'luminosityHighPass',
  uniforms: {
    tDiffuse: { value: null },
    luminosityThreshold: { value: 1.0 },
    smoothWidth: { value: 1.0 },
    defaultColor: { value: new Color(0x000000) },
    defaultOpacity: { value: 0.0 },
  },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }`,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse;
    uniform vec3 defaultColor;
    uniform float defaultOpacity;
    uniform float luminosityThreshold;
    uniform float smoothWidth;
    varying vec2 vUv;
    void main() {
      vec4 texel = texture2D(tDiffuse, vUv);
      if (any(isnan(texel))) texel = vec4(0.0);
      texel = clamp(texel, vec4(0.0), vec4(${BRIGHT_MAX}));
      float v = dot(texel.xyz, vec3(0.299, 0.587, 0.114));
      vec4 outputColor = vec4(defaultColor.rgb, defaultOpacity);
      float alpha = smoothstep(luminosityThreshold, luminosityThreshold + smoothWidth, v);
      gl_FragColor = mix(outputColor, texel, alpha);
    }`,
};

export { LuminosityHighPassShader };

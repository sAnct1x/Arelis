// The one knob for swapping the avatar. Path is relative to index.html.
export const GLB_PATH = './models/ellah.glb';
// Used only if GLB_PATH fails to load.
export const FALLBACK_GLB_PATH = './models/Toon3d2.glb';

export const LOOK = {
  violet: [0.28, 0.09, 0.85],   // #8a5cff saturated purple
  lilac: [0.42, 0.21, 0.92],    // glow / highlights
  interior: [0.06, 0.02, 0.16],// body fill colour (textures are never shown)
  interiorOpacity: 0.85,
  innerGlow: 0.2,             // lilac glow added inside the body shell
  threadDensity: 44.0,         // woven threads per metre-ish
  particles: 9000,             // stars on the skinned surface (GPU-skinned)
  auraStars: 3500,             // loose stars around her
  dressRibbons: 90,
  hairWisps: 40,
  flyaways: 7,                 // long thin strands off the head
  featureRibbons: 4,           // wide looping swirls around her
  bloom: { strength: 0.85, radius: 0.5, threshold: 0.55 },
};

// Per-model overrides, matched by substring of the loaded GLB path.
export const MODEL_LOOK = {
  'Toon3d2': { innerGlow: 0.3 },                 // v8 value
  'ellah': {
    innerGlow: 0.17, particles: 16000, threadDensity: 52.0, violet: [0.25, 0.07, 0.78], lilac: [0.37, 0.17, 0.87],
    faceDetail: 1.0, bodyForm: 1.0,                              // fine light lines on eyes/brows/lips/nose
    dressRibbons: 700, dressWidth: 0.3, dressBright: 0.95, hemFromLegs: true,   // flowing thread hem from hips/thighs
    eyeScale: 0.9,   // pass 13: eyeballs ~10% smaller (eye bones scaled about their pivots)
    handPose: { twist: 0.45, spread: 0.12, curl: 0.16 },   // pass 14: palms a bit forward, relaxed fanned fingers
    hairWisps: 0, flyaways: 0, hairLen: 1.25, noHeadSwirls: true, swirlMaxY: 0.7,                // long soft strands from the bob
  },
};

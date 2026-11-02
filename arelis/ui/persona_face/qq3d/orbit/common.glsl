// Shared by every orbit layer (QuickOrbit.qml). The Filament orbit of filament_field.py, the
// same arithmetic as FilamentField._point_fn / ellipse / _edge_fade / _path_fade / _tone, so
// the GPU traces the path the Python sim (beads, stems, tethers) still sits on.
// build_orbit_shaders.py prepends this to each stage before qsb; every layer binds all of it.
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;        // FilamentField.time (eased speed integrated, kept in step with Python)
    float form;
    float warm;
    float pulseT;
    float words;
    float speakHead;
    float ringScale;   // smoothstep(ringGrow): FilamentField.ring_scale()
    float fullHalf;
    float listenHalf;
    float fadeMargin;
    float strand;      // which strand (or hub thread) this layer draws
    float dustClock;   // integral of (0.012 + speed * 0.028) dt: the dust's own drift
    float speed;
    float hasHub;
    float pad0;
    vec2 view;         // window size, logical px
    vec2 hub;
    vec4 ring;         // settled ellipse: cx, cy, rx, ry
    vec4 ice;
    vec4 gold;
    vec4 coreColor;
};

const float PI = 3.14159265358979;
const float TAU = 6.28318530717959;

vec4 curEllipse() {
    vec2 c = ring.xy;
    vec2 r = ring.zw;
    float g = ringScale;
    if (g < 1.0) {
        if (hasHub > 0.5)
            c = hub + (c - hub) * g;
        r *= max(g, 0.01);
    }
    return vec4(c, r);
}

vec2 wavePoint(float t, float s, float halfW) {
    float amp = view.y * 0.11;
    float wv = sin(t * PI * 2.05 + time * 0.3 + s * 0.5) * amp
             + sin(t * PI * 4.6 + time * 0.12) * amp * 0.28
             + (s - 1.5) * view.y * 0.01;
    return vec2(view.x * 0.5 + (t - 0.5) * 2.0 * halfW, view.y * 0.40 + wv);
}

vec2 pathPoint(float t, float s) {
    vec4 e = curEllipse();
    float ang = t * TAU + time * 1.05 + s * 0.35;
    float rad = 0.90 + 0.10 * sin(t * TAU * 2.0 + s);
    vec2 k = e.xy + vec2(cos(ang) * e.z * rad, sin(ang) * e.w * rad);
    if (form <= 0.5)
        return mix(k, wavePoint(t, s, listenHalf), form / 0.5);
    return mix(wavePoint(t, s, listenHalf), wavePoint(t, s, fullHalf), (form - 0.5) / 0.5);
}

float edgeFade(float x) {
    float m = fadeMargin;
    if (m <= 0.0 || view.x <= 0.0) return 0.0;
    if (x < m) return pow(max(0.0, x / m), 1.6);
    if (x > view.x - m) return pow(max(0.0, (view.x - x) / m), 1.6);
    return 1.0;
}

float pathFade(float t) {
    const float a = 0.08;
    if (t < a) return pow(max(0.0, t / a), 1.5);
    if (t > 1.0 - a) return pow(max(0.0, (1.0 - t) / a), 1.5);
    return 1.0;
}

vec3 tone(float t) {
    return mix(ice.rgb, gold.rgb, clamp(t + warm * 0.25, 0.0, 1.0));
}

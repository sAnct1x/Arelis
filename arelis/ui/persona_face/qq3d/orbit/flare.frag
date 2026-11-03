// The node flare (flare.vert): two gaussian halos and the ring, added like the dust.
layout(location = 0) in vec2 vQ;
layout(location = 1) in vec4 vFlare;
layout(location = 0) out vec4 fragColor;

void main() {
    float r = length(vQ);
    float b = vFlare.x;
    float a = 1.3 * b * exp(-(r * r) / (40.0 * 40.0)) * 0.55 + 0.45 * b * exp(-(r * r) / (110.0 * 110.0)) * 0.55;
    float rw = (r - vFlare.y) / vFlare.w;
    a += vFlare.z * exp(-rw * rw);
    a *= 1.0 - smoothstep(240.0, 300.0, r);
    vec3 rgb = mix(gold.rgb, ice.rgb, 0.5) * 0.85 + coreColor.rgb * 0.15 * b;
    fragColor = vec4(rgb * clamp(a, 0.0, 1.5), 0.0) * qt_Opacity;
}

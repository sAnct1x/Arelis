// The glow round the tree's bundles (orbit_v11b's core blur): soft wide ribbons along the trunk
// and each limb, an inner bright one and an outer haze, drawn with glow.frag. GridMesh
// (24 * K - 1) x 1: ribbon r is path r / 2 (0 the trunk, 1..11 the limbs), width r % 2.
layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec4 vColor;
layout(location = 1) out vec2 vLine;

const float K = 64.0;
const float R = 24.0;

void main() {
    float col = floor(qt_MultiTexCoord0.x * (R * K - 1.0) + 0.5);
    float r = floor(col / K);
    float s = (col - r * K) / (K - 1.0);
    float side = qt_MultiTexCoord0.y * 2.0 - 1.0;
    float k = treeK();
    int path = int(floor(r / 2.0));
    bool outer = mod(r, 2.0) > 0.5;
    float s2 = min(1.0, s + 0.01);
    vec2 P, P2;
    float hw, a;
    if (path == 0) {
        P = trunkAt(s);
        P2 = trunkAt(s2);
        float base = exp(-s / 0.12);
        hw = (outer ? 46.0 + 80.0 * base : 15.0 + 40.0 * base - 4.0 * s) * k;
        a = (outer ? 0.07 : 0.16) * (0.55 + 0.45 * smoothstep(0.0, 0.25, s)) * (1.0 - 0.5 * smoothstep(0.7, 1.0, s));
    } else {
        int j = path - 1;
        Limb L = limbOf(j);
        P = limbPoint(L, s);
        P2 = limbPoint(L, s2);
        float main = j < 6 ? 1.0 : 0.6;
        hw = (outer ? 26.0 * (1.0 - s) + 6.0 : 9.0 * (1.0 - s) + 2.5) * k * (0.7 + 0.3 * main);
        a = (outer ? 0.05 : 0.11) * main * (1.0 - smoothstep(0.55, 1.0, s));
    }
    // a slow breath along the bundle, so the glow is never still
    a *= 0.85 + 0.15 * sin(TAU * (flow / TREE_LOOP) - s * 5.0 + float(path));
    vec2 dd = P2 - P;
    vec2 n = normalize(vec2(-dd.y, dd.x) + vec2(1e-6));
    float lock = path >= 1 && path <= 6 ? smoothstep(0.86, 1.0, s) : 0.0;
    vec2 X = mix(treeSway(P), P, lock);
    float grow = ringScale >= 1.0 ? 1.0 : ringScale;
    a *= grow >= 1.0 ? 1.0 : smoothstep(grow * 1.08, grow * 1.08 - 0.06, path == 0 ? s * 0.6 : 0.6 + 0.4 * s);
    a *= treeOn;
    float reach = (s <= 0.0 || s >= 1.0 || a <= 0.002) ? 0.0 : hw;
    vec3 rgb = outer ? gold.rgb : mix(ice.rgb, coreColor.rgb, path == 0 ? 0.45 : 0.25);
    vColor = vec4(rgb, a);
    vLine = vec2(side * reach, max(hw, 0.5));
    gl_Position = qt_Matrix * vec4(X + n * side * reach, 0.0, 1.0);
}

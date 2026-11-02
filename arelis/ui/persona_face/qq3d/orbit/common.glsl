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
    vec4 tree;         // Filament orbit tree (v11b): trunk base xy, fork xy (OrbitState.tree)
    vec2 feet;         // her feet on the floor, where the floor link and the packets start
    float flow;        // seconds of calm flow (QuickOrbit.qml): sway, packets, flares
    float treeOn;      // 1 while the tree shows (idle form), 0 as the current takes over
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

// ---- The orbit tree (Iris's v11b, orbit_v11b.py): geometry in the mockup's 1392 px tall frame,
// scaled by treeK. The six main limbs end on the tile beads (FilamentField.bead_point: the
// current's point at the tile's t on strand 2, pushed out radially by pad * 0.62), so the
// worker's beads and labels sit on the branch tips as they ride the ring.
const float TREE_LOOP = 6.0;  // the packet loop, seconds (spec: seamless 6 s)

float treeK() { return view.y / 1392.0; }
float th(float i, float k) { return fract(sin(i * 12.9898 + k * 78.233) * 43758.5453); }

float nodeT(int j) {  // FLOATS in filament_field.py: history notify contacts chat camera days
    if (j == 0) return 0.10;
    if (j == 1) return 0.18;
    if (j == 2) return 0.26;
    if (j == 3) return 0.42;
    if (j == 4) return 0.58;
    return 0.74;
}

vec2 nodeTip(int j) {
    vec2 p = pathPoint(nodeT(j), 2.0);
    vec2 d = p - curEllipse().xy;
    float l = length(d);
    if (l == 0.0) l = 1.0;
    return p + d / l * (j == 3 ? 62.0 : 58.0) * 0.62;
}

vec2 bez3(vec2 a, vec2 b, vec2 c, vec2 d, float s) {
    float o = 1.0 - s;
    return o * o * o * a + 3.0 * o * o * s * b + 3.0 * o * s * s * c + s * s * s * d;
}

vec2 trunkAt(float u) {
    float k = treeK();
    return bez3(tree.xy, tree.xy + vec2(-135.0, -270.0) * k, tree.zw + vec2(140.0, 240.0) * k,
                tree.zw, clamp(u, 0.0, 1.0));
}

vec2 trunkTan(float u) {
    vec2 d = trunkAt(u + 0.004) - trunkAt(u - 0.004);
    return d / max(length(d), 1e-4);
}

float trunkLen() { return length(tree.zw - tree.xy) * 1.12; }

// limb() of the mockup: out of the trunk along its tangent, bowed to one side, into the tip.
vec2 limbAt(vec2 st, vec2 tn, vec2 tg, float side, float bend, float s) {
    vec2 dd = tg - st;
    float L = max(length(dd), 1.0);
    vec2 d = dd / L;
    vec2 et = normalize(d + vec2(0.0, -0.35));
    vec2 perp = vec2(-d.y, d.x) * side * bend * L;
    return bez3(st, st + tn * L * 0.38, tg - et * L * 0.30 + perp, tg, s);
}

// Where limb j leaves the trunk: lower tips branch lower (TSTART 0.74 .. 1.0).
float limbStart(vec2 tip) {
    float k = treeK();
    return mix(0.72, 1.0, smoothstep(tree.w + 120.0 * k, tree.w - 420.0 * k, tip.y));
}

// The minor limbs (MINOR), placed round the fork the way the mockup's sit round (1085, 690).
vec3 minorSpec(int m) {  // dx, dy from the fork in mockup px, trunk u
    if (m == 0) return vec3(-225.0, -220.0, 0.84);
    if (m == 1) return vec3(205.0, -270.0, 0.90);
    if (m == 2) return vec3(-265.0, 130.0, 0.62);
    if (m == 3) return vec3(245.0, 70.0, 0.66);
    return vec3(-185.0, -440.0, 0.95);
}

// The calm wind (sway): integer harmonics of the loop, the tips move most, the floor not at all.
vec2 treeSway(vec2 x) {
    float k = treeK();
    float ph = TAU * flow / TREE_LOOP;
    float hgt = pow(clamp((tree.y - x.y) / (1150.0 * k), 0.0, 1.0), 1.7);
    float xx = x.x / k, yy = x.y / k;
    float dx = hgt * (9.0 * sin(ph + 0.0022 * xx + 0.0015 * yy)
                      + 3.5 * sin(2.0 * ph + 0.004 * yy + 1.3 + 0.002 * xx));
    float dy = hgt * (2.5 * sin(ph + 0.003 * xx + 2.1) + 1.2 * sin(2.0 * ph + 0.005 * xx));
    return x + vec2(dx, dy) * k;
}

// The floor link: her feet to the trunk base, a low wandering arc.
vec2 floorAt(float s) {
    float k = treeK();
    vec2 a = feet, b = tree.xy;
    vec2 p = bez3(a, mix(a, b, 0.3) + vec2(0.0, -20.0 * k), mix(a, b, 0.75) + vec2(0.0, 14.0 * k),
                  b, s);
    p.y += 7.0 * k * sin(TAU * s * 2.3 + 0.7) * sin(PI * s);
    return p;
}

// A packet's route for branch j (0..5 main, 6..10 minor): feet, floor, trunk, limb, tip.
// Returns the point at r in 0..1 along it, and the share of the route spent before the limb.
vec2 limbTarget(int j) {
    if (j < 6) return nodeTip(j);
    vec3 m = minorSpec(j - 6);
    return tree.zw + m.xy * treeK();
}

float limbU(int j) { return j < 6 ? limbStart(nodeTip(j)) : minorSpec(j - 6).z; }

float limbSide(int j, vec2 st) {
    vec2 tg = limbTarget(j);
    return tg.x > st.x ? 1.0 : -1.0;
}

vec2 branchAt(int j, float s) {  // s 0..1 along the limb only
    float u = limbU(j);
    vec2 st = trunkAt(u);
    vec2 tg = limbTarget(j);
    float bend = j < 6 ? 0.2 : 0.25;
    return limbAt(st, trunkTan(u), tg, limbSide(j, st), bend, s);
}

vec2 routeAt(int j, float r, out float limbFrom) {
    float lf = length(tree.xy - feet) * 1.05;
    float u = limbU(j);
    float lt = trunkLen() * u;
    float ll = length(limbTarget(j) - trunkAt(u)) * 1.15;
    float tot = max(lf + lt + ll, 1.0);
    float d = r * tot;
    limbFrom = (lf + lt) / tot;
    if (d < lf) return floorAt(d / max(lf, 1.0));
    if (d < lf + lt) return trunkAt((d - lf) / max(lt, 1.0) * u);
    return branchAt(j, (d - lf - lt) / max(ll, 1.0));
}

// Packet j's head along its route (0..1, it travels 82% of the loop) and its brightness.
// Staggered offsets as the spec: 0, .17, .33, .5, .67, .83 for the six, the minors between.
float packetOffset(int j) {
    if (j == 0) return 0.0;
    if (j == 1) return 0.5;
    if (j == 2) return 0.17;
    if (j == 3) return 0.67;
    if (j == 4) return 0.33;
    if (j == 5) return 0.83;
    if (j == 6) return 0.25;
    if (j == 7) return 0.75;
    if (j == 8) return 0.08;
    if (j == 9) return 0.58;
    return 0.42;
}

float packetPhase(int j) { return fract(packetOffset(j) + flow / TREE_LOOP); }
float packetHead(int j) { return packetPhase(j) / 0.82; }

// Twig i (0..35): six per main limb, off the limb at a hashed point, turned off its tangent,
// ending in a curl (twig_from + curl of the mockup). s 0..1: the first 72% is the twig's own
// curve, the rest the curl, tightening.
const float TWIGS = 36.0;

vec2 twigAt(float i, float s) {
    int j = int(floor(i / 6.0));
    float k = treeK();
    float at = 0.2 + th(i, 11.0) * 0.66;
    vec2 p = branchAt(j, at);
    vec2 tn = branchAt(j, at + 0.01) - branchAt(j, at - 0.01);
    tn /= max(length(tn), 1e-4);
    float sd = th(i, 12.0) < 0.5 ? -1.0 : 1.0;
    float rot = sd * (0.35 + th(i, 13.0) * 0.40);
    vec2 dn = vec2(tn.x * cos(rot) - tn.y * sin(rot), tn.x * sin(rot) + tn.y * cos(rot));
    dn.y -= 0.2;
    dn = normalize(dn);
    float L = (90.0 + th(i, 14.0) * 190.0) * k;
    vec2 e = p + dn * L;
    vec2 pp = vec2(-dn.y, dn.x);
    if (s <= 0.72)
        return bez3(p, p + tn * L * 0.35, e - dn * L * 0.3 + pp * sd * L * 0.18, e, s / 0.72);
    float q = (s - 0.72) / 0.28;
    float size = (10.0 + th(i, 15.0) * 16.0) * k;
    float turns = 1.3;
    float phi = sd * turns * TAU * pow(q, 1.3);
    float rc = size * (1.0 - 0.6 * q);
    vec2 c = e + pp * sd * size;
    vec2 r0 = -pp * sd;
    vec2 rr = vec2(r0.x * cos(phi) - r0.y * sin(phi), r0.x * sin(phi) + r0.y * cos(phi));
    return c + rr * rc;
}

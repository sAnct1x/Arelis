// The orbit tree's fibers (v11b): hair-fine ribbons, many per limb, added like the strands.
// GridMesh (COLS / 2 - 1) x 1, twice: K columns per fiber (K_TWIG a twig); each fiber's first and last column have no
// width, so the cell that joins one fiber to the next has no area. Everything moves with flow
// (the wind, the braid's twist, the roots' drift) and brightens under its branch's packet.
layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec4 vColor;
layout(location = 1) out vec2 vLine;

const float K = 48.0;
const float FIBERS = 1240.0;
// Fiber ranges: 6 x 80 main limb fibers, 5 x 30 minor, 72 x 6 twig (half of them long
// secondary limbs, for a dense crown), 60 left roots,
// 30 right roots, 24 floor wisps, 40 base-flare buttresses, 24 base wraps. Every limb fiber
// runs from the floor up the trunk, so the trunk is the dense bundle of all of them.
const float F_MINOR = 480.0;
const float F_TWIG = 630.0;
const float F_LROOT = 1062.0;
const float F_RROOT = 1122.0;
const float F_WISP = 1152.0;
const float F_FLARE = 1176.0;
const float F_WRAP = 1216.0;
// Columns: K per fiber, but a twig (short, its wander under a pixel) needs only K_TWIG.
// That is 17% fewer vertices than K for every fiber; QuickOrbit.qml's two orbitTree
// GridMeshes are (COLS / 2 - 1) x 1 each.
const float K_TWIG = 24.0;
const float C_TWIG = F_TWIG * K;
const float C_LROOT = C_TWIG + (F_LROOT - F_TWIG) * K_TWIG;
const float COLS = C_LROOT + (FIBERS - F_LROOT) * K;   // 49152

float wob(float f, float s, float k) {  // a smooth per-fiber wander, -1..1, drifting with flow
    return 0.6 * sin(s * (5.0 + 4.0 * th(f, k)) + th(f, k + 1.0) * TAU + flow * 0.35)
         + 0.4 * sin(s * (11.0 + 6.0 * th(f, k + 2.0)) + th(f, k + 3.0) * TAU - flow * 0.22);
}

float pkt(int j, float rv, float tot) {  // packet j's glow on a fiber at route position rv
    float ph = packetPhase(j);
    float e = (rv - packetHead(j)) * tot / treeK();
    float g = smoothstep(0.0, 0.03, ph) * (1.0 - smoothstep(0.78, 0.82, ph));
    return g * (e > 0.0 ? exp(-(e / 12.0) * (e / 12.0)) : exp(e / 70.0) * step(-420.0, e));
}

// A root from the trunk low down (u 0.075) out to end: the mockup's root bezier, s 0 at the end.
vec2 rootAt(vec2 end, float side, float L, float a, float b, float s) {
    float k = treeK();
    vec2 p0 = trunkAt(0.075);
    return bez3(end, end + vec2(-side * L * 0.5, a * k), p0 + vec2(side * b * k, 90.0 * k), p0, s);
}

void main() {
    // Four layers of a quarter of the columns each (strand 0-3): a GridMesh has 16-bit indices.
    // Each quarter starts on a fiber's first column (fibers 256, 512, 906), so none is cut.
    float col = floor(qt_MultiTexCoord0.x * (COLS * 0.25 - 1.0) + 0.5) + strand * COLS * 0.25;
    float f, s;
    if (col < C_TWIG) {
        f = floor(col / K);
        s = (col - f * K) / (K - 1.0);
    } else if (col < C_LROOT) {
        float c = col - C_TWIG;
        float i = floor(c / K_TWIG);
        f = F_TWIG + i;
        s = (c - i * K_TWIG) / (K_TWIG - 1.0);
    } else {
        float c = col - C_LROOT;
        float i = floor(c / K);
        f = F_LROOT + i;
        s = (c - i * K) / (K - 1.0);
    }
    float side = qt_MultiTexCoord0.y * 2.0 - 1.0;
    float k = treeK();
    float halfW = (0.42 + th(f, 1.0) * 0.38);
    float a = 0.0;
    float hot = 0.0;   // 0 body, 1 core colour
    float lockTip = 0.0;
    vec2 P, P2;
    float off = 0.0;
    float ph = flow / TREE_LOOP;
    float grow = ringScale >= 1.0 ? 1.0 : ringScale;
    float gpos = s;    // where this vertex is along the growth (base 0, tip 1)

    if (f < F_TWIG) {
        // A main or minor limb: up the trunk, out the limb, the trunk part braided.
        bool minor = f >= F_MINOR;
        int j = minor ? 6 + int(floor((f - F_MINOR) / 30.0)) : int(floor(f / 80.0));
        Limb Lb = limbOf(j);
        float u = Lb.u;
        float lt = trunkLen() * u;
        float ll = length(Lb.tg - Lb.st) * 1.15;
        float sT = lt / max(lt + ll, 1.0);
        float s2 = min(1.0, s + 0.01);
        P = s < sT ? trunkAt(s / sT * u) : limbPoint(Lb, (s - sT) / max(1.0 - sT, 1e-3));
        P2 = s2 < sT ? trunkAt(s2 / sT * u) : limbPoint(Lb, (s2 - sT) / max(1.0 - sT, 1e-3));
        float d = s * (lt + ll) / k;      // mockup px from the base
        float dT = lt / k;
        float sl = clamp((d - dT) / max(ll / k, 1.0), 0.0, 1.0);
        // Half width: a wide flared foot (stronger than the mockup's, Vela's note 1), the trunk
        // tapering to the fork, each limb tapering to its tip.
        float hw = d <= dT
            ? 21.0 - 7.0 * clamp(d / max(dT, 1.0), 0.0, 1.0) + 52.0 * exp(-d / 95.0)
              + 95.0 * exp(-d / 50.0)
            : (minor ? 14.0 : 22.0) * pow(1.0 - sl, 1.3) + 0.6;
        float b = mod(f, 9.0);
        float th0 = b * TAU / 9.0 + (th(b, 2.0) - 0.5) * 0.4;
        float tw = (mod(b, 2.0) < 0.5 ? 1.0 : -1.0) * (0.9 + th(b, 3.0) * 0.7);
        float bl = 160.0 + th(b, 4.0) * 100.0;
        float bps = th(b, 5.0) * TAU;
        float rf = 0.75 + th(b, 6.0) * 0.3;
        float thb = th0 + TAU * tw * d / 700.0 + tw * flow * 0.12;
        float rad = rf * (0.10 + 0.95 * pow(0.5 + 0.5 * sin(TAU * d / bl + bps + flow * 0.1), 1.6));
        rad = max(rad, 0.95 * exp(-d / 130.0));
        float splay = cos(th0 + 0.3 * mod(f, 5.0)) * (70.0 + th(f, 7.0) * 70.0)
                    * exp(-pow(d / 80.0, 1.3));
        float offb = hw * rad * cos(thb) + splay + wob(f, s * 6.0, 8.0) * (0.6 + 0.03 * hw);
        float thl = th(f, 9.0) * TAU + TAU * 1.4 * d / 700.0 + flow * 0.2;
        float lane = (th(f, 10.0) * 2.0 - 1.0) * 0.25;
        float offl = hw * (cos(thl) * 0.85 + lane) + wob(f, s * 9.0, 12.0) * (0.3 + th(f, 13.0) * 1.3);
        float mixb = 1.0 - smoothstep(dT - 50.0, dT + 30.0, d);
        off = (mixb * offb + (1.0 - mixb) * offl) * k;
        float dep = mixb * (0.25 + 0.75 * pow(0.5 + 0.5 * sin(thb), 1.3))
                  + (1.0 - mixb) * (minor ? 0.85 : 0.2 + 0.8 * pow(0.5 + 0.5 * sin(thl), 1.5));
        float trk = 1.0 - 0.42 * (1.0 - smoothstep(dT - 60.0, dT + 40.0, d));
        // They rise out of the floor over a long soft ramp: no splayed stub starts at full light.
        float fade = pow(smoothstep(0.0, 220.0, d), 1.5) * (1.0 - smoothstep(0.92, 1.0, s) * (minor ? 0.9 : 0.35));
        float lf = length(tree.xy - feet) * 1.05;
        float tot = lf + lt + ll;
        float pl = pkt(j, (lf + s * (lt + ll)) / max(tot, 1.0), tot) * (minor ? 0.55 : 1.0);
        a = (0.35 + 1.4 * pow(th(f, 14.0), 3.0)) * dep * fade * trk * 0.12 * (1.0 + (3.0 + 3.0 * form) * pl);
        if (mod(f, 14.0) < 0.5) {  // the luminous core: a few soft wide fibers near the centre line
            off *= 0.25;
            halfW = (d <= dT ? 4.5 : 3.0 * (1.0 - sl) + 0.8) * max(k * 1.4, 0.6);
            a *= 0.35;
            hot = max(hot, 0.35 * (1.0 - sl));
        }
        hot = clamp(pl * 0.8 + (1.0 - sl) * mixb * dep * 0.25, 0.0, 1.0);
        lockTip = minor ? 0.0 : smoothstep(0.86, 1.0, s);
        gpos = s;
    } else if (f < F_LROOT) {
        // A twig with its curl, six fibers each.
        float i = floor((f - F_TWIG) / 6.0);
        Limb Lb = limbOf(int(floor(i / 12.0)));
        P = twigAt(Lb, i, s);
        P2 = twigAt(Lb, i, min(1.0, s + 0.01));
        off = ((th(f, 2.0) * 2.0 - 1.0) * 3.5 * (1.0 - s) + wob(f, s * 5.0, 3.0) * 0.8) * k;
        // tapering, and fading out along its open curl (no closed ring at the tip)
        float fade = smoothstep(0.0, 0.08, s) * (1.0 - smoothstep(0.62, 1.0, s));
        a = (0.5 + th(f, 4.0)) * fade * 0.12;
        halfW *= 0.85 - 0.5 * s;
        gpos = 0.6 + 0.4 * s;
    } else if (f < F_WISP) {
        // The roots: thin ones flowing far to the left across the floor (Vela's note 2), and
        // the rest spread round the foot in all three directions: right, toward the viewer
        // (lower on the floor) and away (higher, fainter). s 0 is the root's far end.
        bool left = f < F_RROOT;
        float i = left ? floor((f - F_LROOT) / 3.0) : floor((f - F_RROOT) / 3.0) + 40.0;
        float dir = left ? -1.0 : mod(i, 3.0);   // 0 right, 1 front, 2 back
        float sd = left ? -1.0 : (dir < 0.5 || th(i, 8.0) > 0.5 ? 1.0 : -1.0);
        float L = (left ? 300.0 + th(i, 2.0) * 760.0
                 : dir < 0.5 ? (180.0 + th(i, 2.0) * 340.0) * 1.35
                 : 70.0 + th(i, 2.0) * (dir < 1.5 ? 200.0 : 260.0)) * k;
        float ey = left ? -30.0 + th(i, 3.0) * 72.0
                 : dir < 0.5 ? -40.0 + th(i, 3.0) * 80.0
                 : dir < 1.5 ? 22.0 + th(i, 3.0) * 26.0
                 : -24.0 - th(i, 3.0) * 30.0;
        // the left roots fan: the longer, the lower and the more they lift off the floor between
        vec2 end = tree.xy + vec2(sd * L, ey * k);
        float ca = left ? -10.0 - th(i, 4.0) * 70.0 : -30.0 + th(i, 4.0) * 55.0;
        float cb = 30.0 + th(i, 5.0) * 30.0;
        P = rootAt(end, sd, L, ca, cb, s);
        P2 = rootAt(end, sd, L, ca, cb, min(1.0, s + 0.01));
        float wv = left ? (2.0 + th(f, 6.0) * 6.0) : (2.0 + th(f, 6.0) * 7.0);
        off = ((1.0 + 6.0 * s) * (th(f, 7.0) * 2.0 - 1.0) * 1.3 + wob(f, s * 4.0, 8.0) * wv * (1.0 - smoothstep(0.75, 1.0, s))) * k;
        // a sheen that flows out along the root, away from the trunk
        float sheen = 0.7 + 0.3 * sin(TAU * (2.0 * s + ph) + th(i, 9.0) * TAU);
        float brk = clamp(wob(f, s * 3.0, 10.0) * 0.7 + 0.75, 0.0, 1.0);
        // Every root fades in from its far end and runs on into the trunk's foot.
        float fade = (left ? 1.7 : dir < 0.5 ? 1.8 : dir < 1.5 ? 1.6 : 1.1)
            * pow(smoothstep(0.0, left ? 0.2 : 0.35, s), 1.2) * (1.0 - 0.6 * smoothstep(0.85, 1.0, s)) * brk;
        a = (0.4 + th(f, 11.0) * 0.8) * fade * sheen * (left ? 0.16 : 0.14);
        halfW *= left ? 0.75 : 0.85;
        gpos = 1.0 - s;
        gpos *= 0.4;
    } else if (f < F_FLARE) {
        // The floor link: soft broken wisps from her feet to the root, drifting.
        float i = floor((f - F_WISP) / 2.0);
        P = floorAt(s);
        P2 = floorAt(min(1.0, s + 0.01));
        off = ((th(i, 2.0) * 2.0 - 1.0) * 14.0 * sin(PI * s) + wob(f, s * 5.0, 4.0) * (3.0 + th(f, 5.0) * 7.0) * sin(PI * s)) * k;
        float brk = clamp(wob(f, s * 2.5, 20.0) * 0.9 + 0.3, 0.0, 1.0);
        float pl = 0.0;
        float lf = length(tree.xy - feet) * 1.05;
        for (int j = 0; j < 6; ++j) {
            float tot = routeTot(j);
            pl += pkt(j, s * lf / tot, tot);
        }
        // They fade in softly beside her (s 0), never a hot point under her, and run on into
        // the trunk's foot, a sheen running away from her.
        float sheen = 0.7 + 0.3 * sin(TAU * (ph - 2.0 * s) + th(i, 9.0) * TAU);
        a = (0.4 + th(f, 6.0) * 0.6) * brk * smoothstep(0.0, 0.3, s) * (1.2 - 0.3 * s) * sheen * 0.09
          * (1.0 + 1.5 * pl);
        gpos = 0.0;
    } else if (f < F_WRAP) {
        // The flare at the trunk's foot: buttress strands from low on the trunk, swept out
        // and down onto the floor on both sides (Vela's note 1).
        float i = f - F_FLARE;
        float sd = mod(i, 2.0) < 0.5 ? -1.0 : 1.0;
        float u = 0.03 + th(i, 2.0) * 0.16;
        vec2 top = trunkAt(u);
        vec2 end = tree.xy + vec2(sd * (50.0 + th(i, 3.0) * 170.0), (-2.0 + th(i, 4.0) * 14.0)) * k;
        vec2 c1 = top + vec2(sd * 8.0, 50.0) * k;
        vec2 c2 = end + vec2(-sd * (30.0 + th(i, 5.0) * 40.0), -12.0) * k;
        P = bez3(top, c1, c2, end, s);
        P2 = bez3(top, c1, c2, end, min(1.0, s + 0.01));
        off = wob(f, s * 4.0, 6.0) * 2.5 * k;
        // out to nothing on the floor: a buttress thins away, it never stops short
        a = (0.6 + th(f, 7.0) * 0.8) * (1.0 - smoothstep(0.45, 1.0, s)) * smoothstep(0.0, 0.1, s) * 0.26;
        hot = 0.3 * (1.0 - s);
        gpos = 0.05;
    } else {
        // Loose strands wrapping the trunk's foot, turning slowly.
        float i = f - F_WRAP;
        float top = 0.3 + th(i, 2.0) * 0.45;
        float turns = 0.35 + th(i, 3.0) * 0.45;
        float p0 = th(i, 4.0) * TAU;
        float R0 = (60.0 + th(i, 5.0) * 80.0) * k;
        float t1 = p0 + TAU * turns * s + 0.6 * sin(TAU * ph + p0) * s;
        float s1 = min(1.0, s + 0.01);
        float t2 = p0 + TAU * turns * s1 + 0.6 * sin(TAU * ph + p0) * s1;
        vec2 c = trunkAt(s * top);
        vec2 cc = trunkAt(s1 * top);
        P = c + vec2(R0 * (1.0 - 0.75 * s) * cos(t1), R0 * (1.0 - 0.75 * s) * 0.3 * sin(t1) - 4.0 * k);
        P2 = cc + vec2(R0 * (1.0 - 0.75 * s1) * cos(t2), R0 * (1.0 - 0.75 * s1) * 0.3 * sin(t2) - 4.0 * k);
        float dep = 0.25 + 0.75 * (0.5 + 0.5 * sin(t1));
        a = (0.5 + th(i, 6.0)) * dep * pow(sin(PI * s), 0.8) * 0.09;
        gpos = 0.15;
    }

    vec2 dd = P2 - P;
    vec2 n = normalize(vec2(-dd.y, dd.x) + vec2(1e-6));
    vec2 X = P + n * off;
    vec2 Xs = treeSway(X);
    X = mix(Xs, X, lockTip);   // the main tips stay on the worker's beads
    // The load: the tree grows up out of the floor as the ring opens.
    a *= grow >= 1.0 ? 1.0 : smoothstep(grow * 1.08, grow * 1.08 - 0.06, gpos);
    a *= treeOn;
    float reach = halfW + 1.0;
    if (s <= 0.0 || s >= 1.0 || a <= 0.002) reach = 0.0;
    vec3 rgb = mix(mix(ice.rgb, gold.rgb, 0.3), coreColor.rgb, hot);
    vColor = vec4(rgb, clamp(a, 0.0, 1.0));
    vLine = vec2(side * reach, halfW);
    gl_Position = qt_Matrix * vec4(X + n * side * reach, 0.0, 1.0);
}

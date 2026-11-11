// SPEC 2.1 membrane: Fresnel rim + Voronoi cell lines, gate holes, traffic halo.
VARYING vec3 vWorld;
VARYING vec3 vNrm;
VARYING vec3 vView;

vec3 hash33(vec3 p) {
    p = vec3(dot(p, vec3(127.1, 311.7, 74.7)),
             dot(p, vec3(269.5, 183.3, 246.1)),
             dot(p, vec3(113.5, 271.9, 124.6)));
    return fract(sin(p) * 43758.5453);
}

float voronoiEdge(vec3 x) {
    vec3 n = floor(x);
    vec3 f = fract(x);
    float best = 8.0;
    vec3 bestR = vec3(0.0);
    for (int k = -1; k <= 1; k++) {
        for (int j = -1; j <= 1; j++) {
            for (int i = -1; i <= 1; i++) {
                vec3 g = vec3(float(i), float(j), float(k));
                vec3 o = hash33(n + g) * 0.35;
                vec3 r = g + o - f;
                float d = length(r);
                if (d < best) { best = d; bestR = r; }
            }
        }
    }
    float edge = 8.0;
    for (int k = -1; k <= 1; k++) {
        for (int j = -1; j <= 1; j++) {
            for (int i = -1; i <= 1; i++) {
                vec3 g = vec3(float(i), float(j), float(k));
                vec3 o = hash33(n + g) * 0.35;
                vec3 r = g + o - f;
                vec3 mid = r - bestR;
                float ml = length(mid);
                if (ml > 1e-5)
                    edge = min(edge, dot(0.5 * (bestR + r), mid / ml));
            }
        }
    }
    return edge;
}

void MAIN() {
    vec3 N = normalize(vNrm);
    vec3 V = normalize(vView);
    float ndv = abs(dot(N, V));
    float rim = pow(max(1.0 - ndv, 0.0), rimPow) * rimGain;
    float dEdge = voronoiEdge(vWorld / max(cell, 0.01));
    float edge = 1.0 - smoothstep(0.0, lineW, dEdge);
    float cells = edge * (cellGain * 0.3 + (1.0 - ndv) * cellGain);
    float s = rim + cells + body;
    float back = dot(N, V) < 0.0 ? 1.0 : 0.0;
    s *= (1.0 - back * (1.0 - backGain));
    vec3 col = (emp > 0.5 ? vec3(0.62, 0.60, 0.70) : barrierColor) * s;

    // Up to 8 gate centres: xyz + aperture radius in w; colour+halo in gateColN.
    vec4 gps[8];
    gps[0] = gate0; gps[1] = gate1; gps[2] = gate2; gps[3] = gate3;
    gps[4] = gate4; gps[5] = gate5; gps[6] = gate6; gps[7] = gate7;
    vec4 gcs[8];
    gcs[0] = gateCol0; gcs[1] = gateCol1; gcs[2] = gateCol2; gcs[3] = gateCol3;
    gcs[4] = gateCol4; gcs[5] = gateCol5; gcs[6] = gateCol6; gcs[7] = gateCol7;
    int n = int(gateCount + 0.5);
    for (int i = 0; i < 8; i++) {
        if (i >= n) break;
        float r = max(gps[i].w, 0.01);
        float d = distance(vWorld, gps[i].xyz);
        col *= smoothstep(r * 0.95, r * 1.15, d);
        float halo = (1.0 - smoothstep(r * 1.0, r * 3.2, d)) * gcs[i].a;
        col += gcs[i].rgb * halo;
    }
    FRAGCOLOR = vec4(col, 1.0);
}

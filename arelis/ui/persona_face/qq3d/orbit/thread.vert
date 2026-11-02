// One hub thread (FilamentField.hub_threads / _tether_point): her centre to the near side of
// the ring, a cubic with the same sag. strand is k + 1 for k in (-1, 0, 1).
layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec4 vColor;
layout(location = 1) out vec2 vLine;

vec2 bez(vec2 s, vec2 e, float u) {
    vec2 d = e - s;
    float len = length(d);
    if (len == 0.0) len = 1.0;
    float sag = min(70.0, len * 0.18);
    vec2 pp = vec2(-d.y, d.x) / len * sag;
    vec2 c1 = s + d * 0.32 + pp;
    vec2 c2 = s + d * 0.68 + pp * 0.45;
    float o = 1.0 - u;
    return o * o * o * s + 3.0 * o * o * u * c1 + 3.0 * o * u * u * c2 + u * u * u * e;
}

void main() {
    float u = qt_MultiTexCoord0.x;
    float side = qt_MultiTexCoord0.y * 2.0 - 1.0;
    vec4 el = curEllipse();
    float base = atan((hub.y - el.y) / max(el.w, 1.0), (hub.x - el.x) / max(el.z, 1.0));
    float ang = base + (strand - 1.0) * 0.32;
    vec2 e = el.xy + vec2(cos(ang) * el.z, sin(ang) * el.w);
    vec2 p = bez(hub, e, u);
    vec2 d = bez(hub, e, min(1.0, u + 0.004)) - bez(hub, e, max(0.0, u - 0.004));
    vec2 n = normalize(vec2(-d.y, d.x) + vec2(1e-6));
    float halfW = 0.7;
    vColor = vec4(gold.rgb, hasHub > 0.5 ? (0.10 + 0.14 * u) * (1.0 - treeOn) : 0.0);
    vLine = vec2(side * (halfW + 1.0), halfW);
    gl_Position = qt_Matrix * vec4(p + n * side * (halfW + 1.0), 0.0, 1.0);
}

// Places a curve-space strip along one tentacle. Control points are world space
// in curveTex (RGBA32F, 8 x 2048). Instances use an identity transform.
// INSTANCE_DATA = (row, r0, r1, dim). VERTEX.y = u in [0,1]; VERTEX.xz = radius 1.
// NORMAL is written already in world space and is not multiplied by
// INSTANCE_MODEL_MATRIX (identity). Catmull-Rom uses a rotation-minimising frame.
VARYING vec4 vTone;
VARYING vec3 vCaste;
VARYING float vDim;
VARYING float vWear;
VARYING vec4 vCol;
VARYING float vU;

vec3 cp(int i, int row) {
    return texelFetch(curveTex, ivec2(clamp(i, 0, 7), row), 0).xyz;
}

vec3 catmull(int row, float u, out vec3 tangent) {
    float f = clamp(u, 0.0, 0.99999) * 7.0;
    int i = int(floor(f));
    float t = f - float(i);
    vec3 p0 = cp(i - 1, row), p1 = cp(i, row), p2 = cp(i + 1, row), p3 = cp(i + 2, row);
    if (i == 0) p0 = 2.0 * p1 - p2;
    if (i >= 6) p3 = 2.0 * p2 - p1;
    vec3 a = 2.0 * p1, b = p2 - p0, c = 2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3, d = -p0 + 3.0 * p1 - 3.0 * p2 + p3;
    tangent = normalize(b + 2.0 * c * t + 3.0 * d * t * t);
    return 0.5 * (a + b * t + c * t * t + d * t * t * t);
}

void MAIN() {
    int row = int(INSTANCE_DATA.x + 0.5);
    float u = VERTEX.y;
    vec3 T;
    vec3 P = catmull(row, u, T);
    vec3 T0 = normalize(cp(1, row) - cp(0, row));
    vec3 ref = abs(T0.y) < 0.95 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0);
    vec3 N = normalize(cross(ref, T0));
    vec3 xa = cp(0, row), ta = T0;
    int iu = int(floor(clamp(u, 0.0, 0.99999) * 7.0));
    for (int k = 1; k <= 8; ++k) {
        bool last = (k > iu);
        vec3 xb = last ? P : cp(k, row);
        vec3 tb = last ? T : normalize(cp(min(k + 1, 7), row) - cp(k - 1, row));
        vec3 v1 = xb - xa;
        float c1 = dot(v1, v1);
        if (c1 > 1e-10) {
            vec3 rL = N - (2.0 / c1) * dot(v1, N) * v1;
            vec3 tL = ta - (2.0 / c1) * dot(v1, ta) * v1;
            vec3 v2 = tb - tL;
            float c2 = dot(v2, v2);
            N = c2 > 1e-10 ? rL - (2.0 / c2) * dot(v2, rL) * v2 : rL;
        }
        xa = xb;
        ta = tb;
        if (last) break;
    }
    N = normalize(N - T * dot(N, T));
    vec3 B = cross(T, N);
    float r = mix(INSTANCE_DATA.y, INSTANCE_DATA.z, u);
    // Minimum 1.5 px on-screen width so LOD2 tubes never speckle.
    vec4 clip = VIEWPROJECTION_MATRIX * vec4(P, 1.0);
    float pxPerUnit = PROJECTION_MATRIX[1][1] * 0.5 * uViewportH / max(clip.w, 0.001);
    r = max(r, 0.75 / max(pxPerUnit, 0.0001));
    vec3 world = P + (N * VERTEX.x + B * VERTEX.z) * r;
    // World-space normal: the instance transform is identity, so do not
    // rewrite this by INSTANCE_MODEL_MATRIX.
    NORMAL = normalize(N * NORMAL.x + B * NORMAL.z + T * NORMAL.y);
    POSITION = VIEWPROJECTION_MATRIX * vec4(world, 1.0);
    vTone = COLOR;
    vCaste = pow(max(INSTANCE_COLOR.rgb, vec3(0.0)), vec3(2.2));
    vDim = INSTANCE_DATA.w;
    vWear = 0.0;
    vCol = COLOR;
    vU = u;
}

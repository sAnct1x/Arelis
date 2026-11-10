// Iris, Pass E: instanced sentinel tentacle (trailing tentacles + front claw arms), ONE draw per LOD for all units.
// Design stub for Tycho. Reference maths: src/sentinel_anim.py (pose_trail, coil_pose, pose_arm, deform). Every
// constant below is that file's value. Qt Quick 3D CustomMaterial, shadingMode Shaded (LOD0/1) or Unshaded (LOD2).
//
// Mesh: mesh/sentinel_tentacle_lod{0,1,2}. VERTEX.y = u along the strand (claw prongs: 1 + t), VERTEX.xz = unit-circle
// cross-section (LOD2: VERTEX.x = side -1..1). COLOR_0: r = radius mult / 1.1, g = slit mask, b = (prong id + 1) / 8,
// a = rim k. Model transform is identity; every instance writes world position itself.
//
// INSTANCE_DATA  = (unitRow, slot, lod, 0)          slot 0..TRAIL-1 = trailing, TRAIL.. = arms (strandTex row)
// INSTANCE_COLOR = (caste.rgb linear, dim)          dim: 1 normal, 0.35 limp/EMP
// unitTex   RGBA32F 8 x 128, one row per unit, written each frame by the view (UnitTexData, SPEC.md 5.2)
//   T0 pos.xyz, scale        T1 quat xyzw           T2 speed, kappa, phase, lenMul
//   T3 wIdle wReach wHold wCoil      T4 wStrike wLimp clawOpen clawOpenArm
//   T5 targetL.xyz, wPart    T6 holdL.xyz, time0    T7 kHold (CPU bezier_fit), reserved x3
// strandTex RGBA32F 6 x 64, static (uploaded once): row = lod * 20 + slot
//   S0 root.xyz, L           S1 o.xyz, rr           S2 b.xyz, phi
//   S3 r0, r1, clawLen, clawR       S4 kind (0 trail 1 arm), side, big, role (0, 1 coil, 2 strike)
//   S5 coil: roleSign, uc, turns, leadLen
VARYING vec3 vN;
VARYING vec3 vW;
VARYING vec4 vC;       // slit, claw, rim k, dim
VARYING vec3 vCaste;
VARYING float vSide;

const float PI = 3.14159265;
// CRUISE = dict(f=0.50, lam=0.75, A=0.055, spread=0.14, sag=0.04)
const float CR_F = 0.50, CR_LAM = 0.75, CR_A = 0.055, CR_SPREAD = 0.14, CR_SAG = 0.04;
// IDLE = dict(f=0.14, A=0.025, cone=0.80, s0=0.40, curl=1.30, breath=0.20, fb=0.11)
const float ID_F = 0.14, ID_A = 0.025, ID_CONE = 0.80, ID_S0 = 0.40, ID_CURL = 1.30, ID_BR = 0.20, ID_FB = 0.11;
const float BEAD_R = 0.16;

vec4 U(int unitRow, int t) { return texelFetch(unitTex, ivec2(t, unitRow), 0); }
vec4 S(int row, int t) { return texelFetch(strandTex, ivec2(t, row), 0); }
vec3 qrot(vec4 q, vec3 v) { return v + 2.0 * cross(q.xyz, cross(q.xyz, v) + q.w * v); }
float smooth01(float x) { x = clamp(x, 0.0, 1.0); return x * x * (3.0 - 2.0 * x); }
vec3 bez(vec3 p0, vec3 p1, vec3 p2, vec3 p3, float u) {
    float v = 1.0 - u; return v * v * v * p0 + 3.0 * v * v * u * p1 + 3.0 * v * u * u * p2 + u * u * u * p3;
}
// straight for s0, then a circular arc of curvature k bending from d towards e (sentinel_anim.arc)
vec3 arcP(vec3 root, vec3 d, vec3 e, float s, float s0, float k) {
    if (s <= s0 || k < 1e-5) return root + d * s;
    float a = (s - s0) * k;
    return root + d * s0 + (d * sin(a) + e * (1.0 - cos(a))) / k;
}

struct Strand { vec3 root, o, b; float L, rr, phi, r0, r1, clawLen, clawR, kind, side, big, role, roleSign, uc, turns; };
Strand loadStrand(int row) {
    Strand s; vec4 a = S(row, 0), b = S(row, 1), c = S(row, 2), d = S(row, 3), e = S(row, 4), f = S(row, 5);
    s.root = a.xyz; s.L = a.w; s.o = b.xyz; s.rr = b.w; s.b = c.xyz; s.phi = c.w;
    s.r0 = d.x; s.r1 = d.y; s.clawLen = d.z; s.clawR = d.w; s.kind = e.x; s.side = e.y; s.big = e.z; s.role = e.w;
    s.roleSign = f.x; s.uc = f.y; s.turns = f.z; return s;
}

vec3 coilPose(Strand sd, float u, vec3 H, bool swing) {
    float side = sd.roleSign, rc = BEAD_R + 0.11;
    vec3 C3 = H + vec3(-rc, 0.0, 0.14 * side);
    vec3 C1 = sd.root + vec3(-0.55, -0.75, 0.62 * side);
    vec3 C2 = C3 + vec3(-0.9, -0.55, 0.38 * side);
    if (u <= sd.uc) return bez(sd.root, C1, C2, C3, u / sd.uc);
    float v = (u - sd.uc) / (1.0 - sd.uc);
    if (swing) {
        vec3 T = normalize(normalize(C3 - C2) + vec3(0.0, -0.2, 0.9 * side));
        return C3 + T * ((u - sd.uc) * sd.L);
    }
    float a = PI - side * v * 2.0 * PI * sd.turns;
    return vec3(H.x + rc * cos(a), H.y + rc * sin(a), H.z + side * (0.14 + 0.22 * v));
}

vec3 trailP(Strand sd, int r, float u, float t) {
    vec4 T2 = U(r, 2), T3 = U(r, 3), T4 = U(r, 4), T5 = U(r, 5), T6 = U(r, 6);
    float L = sd.L * T2.w, s = u * L, phi = sd.phi + T2.z, k = T2.y;
    // cruise: arc of the orbit curvature, comet spread, sag, travelling wave (phase per segment = -2 pi s / (lam L))
    vec3 path = arcP(sd.root, vec3(-1, 0, 0), vec3(0, 0, k >= 0.0 ? 1.0 : -1.0), s, 0.0, abs(k));
    float f = CR_F * clamp(T2.x / 1.2, 0.6, 2.2);
    float psi = 2.0 * PI * f * t - 2.0 * PI * s / (CR_LAM * L) + phi;
    float A = CR_A * L * pow(u, 1.5);
    vec3 P = path + sd.o * (L * (CR_SPREAD * pow(u, 0.9) + 0.05 * sd.rr)) - vec3(0, 1, 0) * (CR_SAG * L * u * u)
           + A * sin(psi) * sd.b + 0.4 * A * sin(0.73 * psi + 1.7) * sd.o;
    if (T3.x > 0.0) {   // idle: splayed cone + pinwheel curl
        vec3 d = normalize(vec3(-1, 0, 0) + ID_CONE * (0.45 + sd.rr) * sd.o);
        vec3 e = normalize(sd.b - d * dot(sd.b, d));
        float kc = (ID_CURL + ID_BR * sin(2.0 * PI * ID_FB * t + phi)) / ((1.0 - ID_S0) * L);
        float psi_i = 2.0 * PI * ID_F * t - 2.0 * PI * s / (0.9 * L) + phi;
        vec3 idle = arcP(sd.root, d, e, s, ID_S0 * L, kc) + ID_A * L * pow(u, 1.5) * sin(psi_i) * sd.o;
        P = mix(P, idle, T3.x);
    }
    if (T4.y > 0.0) {   // limp (EMP)
        vec3 dl = normalize(vec3(-0.45, -1.0, 0.0) + 0.25 * sd.o);
        P = mix(P, arcP(sd.root, dl, vec3(-1, 0, 0), s, 0.5 * L, 0.6 / L), T4.y);
    }
    if (sd.role != 1.0 && T5.w > 0.0) P += sd.o * (0.30 * L * u * T5.w) + vec3(0, 1, 0) * (0.12 * L * u * T5.w);
    if (sd.role == 1.0 && T3.w > 0.0) {   // coil: trail -> swing -> wrap the bead at holdL
        float w = T3.w;
        vec3 sw = coilPose(sd, u, T6.xyz, true);
        if (w < 0.5) P = mix(P, sw, smooth01((w / 0.5) * 1.25 - 0.25 * u));
        else P = mix(sw, coilPose(sd, u, T6.xyz, false), smooth01((w - 0.5) / 0.5));
    }
    if (sd.role == 2.0 && T4.x != 0.0) {   // strike: wind-up (w < 0) then lash at targetL (w > 0)
        float side = sd.roleSign, w = T4.x;
        vec3 Tg = T5.xyz; float dist = length(Tg - sd.root);
        vec3 Tc = sd.root + (Tg - sd.root) * min(1.0, 0.97 * L / max(dist, 1e-6));
        if (w < 0.0) P = mix(P, bez(sd.root, sd.root + vec3(-0.8, 1.2, 0.3 * side), sd.root + vec3(-1.6, 2.2, 0.5 * side), sd.root + vec3(-0.4, 2.8, 0.6 * side), u), -w);
        else P = mix(P, bez(sd.root, sd.root + vec3(-0.2, 1.6, 0.4 * side), sd.root + vec3(1.8, 2.0, 0.6 * side), Tc, u), w);
    }
    return P;
}

vec3 armP(Strand sd, int r, float u, float t) {
    vec4 T3 = U(r, 3), T5 = U(r, 5), T6 = U(r, 6), T7 = U(r, 7);
    float L = sd.L, s = u * L, side = sd.side;
    vec3 P = arcP(sd.root, normalize(vec3(0.85, -0.45, 0.25 * side)), vec3(0, -1, 0), s, 0.25 * L, 3.4 / L);
    P.z += 0.03 * L * u * u * sin(2.0 * PI * 0.3 * t + sd.phi);
    if (T3.y > 0.0) {   // reach
        vec3 Tg = T5.xyz + vec3(0.0, 0.0, 0.18 * side * (sd.big > 0.5 ? 1.0 : 0.5));
        vec3 Tc = sd.root + (Tg - sd.root) * min(1.0, 0.97 * L / max(length(Tg - sd.root), 1e-6));
        vec3 D = Tc - sd.root; float dl = length(D);
        P = mix(P, bez(sd.root, sd.root + D * 0.30 + vec3(0.0, 0.20, 0.10 * side) * dl, sd.root + D * 0.70 + vec3(0.0, 0.10, 0.03 * side) * dl, Tc, u), T3.y);
    }
    if (sd.big > 0.5 && T3.z > 0.0) {   // hold: claw tip 0.48 in front of the bead, prongs closed back onto it
        vec3 H = T6.xyz + vec3(0.48, 0.03, 0.06 * side); float k = T7.x;   // k from CPU bezier_fit (once per state change)
        P = mix(P, bez(sd.root, sd.root + normalize(vec3(0.7, 0.0, 0.6 * side)) * k, H + normalize(vec3(0.3, 0.0, 0.95 * side)) * k, H, u), T3.z);
    }
    float wt = max(T3.z, T3.w);
    if (sd.big < 0.5 && wt > 0.0)   // pincers tuck while the bead is held
        P = mix(P, arcP(sd.root, normalize(vec3(-0.35, -0.75, 0.05 * side)), normalize(vec3(-1.0, 0.35, 0.0)), s, 0.25 * L, 2.6 / L), wt);
    return P;
}

vec3 centre(Strand sd, int r, float u, float t) { return sd.kind < 0.5 ? trailP(sd, r, u, t) : armP(sd, r, u, t); }

void MAIN()
{
    int r = int(INSTANCE_DATA.x + 0.5), slot = int(INSTANCE_DATA.y + 0.5), lod = int(INSTANCE_DATA.z + 0.5);
    Strand sd = loadStrand(lod * 20 + slot);
    vec4 T0 = U(r, 0), T1 = U(r, 1), T4 = U(r, 4);
    float t = uTime - U(r, 6).w;
    float uv = VERTEX.y, u = clamp(uv, 0.0, 1.0);
    const float du = 1.0 / 96.0;
    vec3 P = centre(sd, r, u, t);
    vec3 Tn = normalize(centre(sd, r, min(u + du, 1.0), t) - centre(sd, r, max(u - du, 0.0), t));
    vec3 N = normalize(sd.b - Tn * dot(sd.b, Tn)); vec3 B = cross(Tn, N);
    float widthLod = lod == 2 ? 1.35 : 1.0;
    float rad = (sd.r0 + (sd.r1 - sd.r0) * pow(u, 0.9)) * COLOR.r * 1.1 * widthLod;
    vec3 local;
    vec3 camL = qrot(vec4(-T1.xyz, T1.w), (CAMERA_POSITION - T0.xyz)) / T0.w;   // camera in unit-local space
    if (COLOR.b > 0.01) {   // claw prong
        vec3 tipP = centre(sd, r, 1.0, t);
        float npr = lod == 2 ? 2.0 : (lod == 0 ? 4.0 : 3.0);
        float th = 2.0 * PI * (floor(COLOR.b * 8.0 + 0.5) - 1.0) / npr + (npr == 4.0 ? 0.25 * PI : 0.0);
        vec3 outw = cos(th) * N + sin(th) * B, tang = -sin(th) * N + cos(th) * B;
        float a = 0.10 + 0.85 * (sd.kind < 0.5 ? T4.z : T4.w);
        float tt = uv - 1.0, rt = sd.r1 * sd.clawR, Lp = sd.clawLen;
        vec3 dirv = Tn * cos(a) + outw * sin(a);
        vec3 cen = tipP + outw * rt * 0.6 + dirv * tt * Lp - outw * (0.55 * Lp * pow(tt, 2.2));   // prong tips hook in
        if (lod == 2) local = cen + normalize(cross(dirv - outw * 0.6 * tt, camL - cen)) * VERTEX.x * rt * 0.8;
        else local = cen + (tang * VERTEX.x + normalize(cross(dirv, tang)) * VERTEX.z) * rt;
    } else if (lod == 2) {   // camera-facing ribbon
        vec3 side = normalize(cross(Tn, camL - P));
        local = P + side * VERTEX.x * rad;
        vSide = VERTEX.x;
    } else {
        local = P + (N * VERTEX.x + B * VERTEX.z) * rad;
        vSide = 0.0;
    }
    vec3 world = T0.xyz + qrot(T1, local * T0.w);
    vW = world;
    vN = qrot(T1, lod == 2 ? -normalize(camL - P) : normalize(N * VERTEX.x + B * VERTEX.z));
    vC = vec4(COLOR.g, COLOR.b > 0.01 ? 1.0 : 0.0, COLOR.a, INSTANCE_COLOR.a);
    vCaste = pow(max(INSTANCE_COLOR.rgb, vec3(0.0)), vec3(2.2));
    // Pass D near-plane guard plus Pass E 2.0 px min width on LOD2 ribbons.
    vec4 clip = VIEWPROJECTION_MATRIX * vec4(world, 1.0);
    float wAbs = max(abs(clip.w), 0.25);
    if (lod == 2 && abs(clip.w) >= 0.25) {
        float pxPerUnit = PROJECTION_MATRIX[1][1] * 0.5 * uViewportH / wAbs;
        float minR = 1.0 / max(pxPerUnit, 0.0001);
        float curR = length(world - (T0.xyz + qrot(T1, P * T0.w)));
        if (curR < minR && curR > 1e-6) {
            vec3 mid = T0.xyz + qrot(T1, P * T0.w);
            world = mid + normalize(world - mid) * minR;
            clip = VIEWPROJECTION_MATRIX * vec4(world, 1.0);
        }
    }
    if (abs(clip.w) < 0.25) {
        clip = vec4(0.0, 0.0, 2.0, 1.0);
    }
    POSITION = clip;
}

// Combined memory/tools/results rings and their beads in one draw.
// COLOR.a is the part id: 0 memory ring, 1 tools ring, 2 results ring,
// 3 memory bead, 4 tools bead. Tilt and spin are applied here so the
// mesh can stay in each ring's local space. Min-px push matches
// emission_minpx.vert / the old bead scale path.
VARYING vec4 vCol;
VARYING float vU;
VARYING float vComp;
VARYING float vBack;
VARYING float vGain;
VARYING float vArc;
vec3 eulerZXY(vec3 p, vec3 deg) {
    // Qt Quick 3D eulerRotation is Z, then X, then Y.
    float rz = radians(deg.z), rx = radians(deg.x), ry = radians(deg.y);
    float cz = cos(rz), sz = sin(rz);
    float cx = cos(rx), sx = sin(rx);
    float cy = cos(ry), sy = sin(ry);
    vec3 zq = vec3(p.x * cz - p.y * sz, p.x * sz + p.y * cz, p.z);
    vec3 xq = vec3(zq.x, zq.y * cx - zq.z * sx, zq.y * sx + zq.z * cx);
    return vec3(xq.x * cy + xq.z * sy, xq.y, -xq.x * sy + xq.z * cy);
}

void MAIN() {
    float part = COLOR.a;
    vec3 tilt = memoryTiltEuler;
    float spin = memorySpin;
    float tube = 0.016;
    float gainMul = 0.95;
    if (part > 0.5 && part < 1.5) {
        tilt = toolsTiltEuler;
        spin = toolsSpin;
        tube = 0.020;
        gainMul = 0.85;
    } else if (part > 1.5 && part < 2.5) {
        tilt = resultsTiltEuler;
        spin = 0.0;
        tube = 0.011;
        gainMul = 0.42 * resultsFade;
    } else if (part > 2.5 && part < 3.5) {
        tilt = vec3(0.0);
        spin = memorySpin;
        tube = memoryBeadRadius;
        gainMul = 0.85;
    } else if (part > 3.5) {
        tilt = toolsTiltEuler;
        spin = toolsSpin;
        tube = toolsBeadRadius;
        gainMul = 2.8;
    }
    vec3 lp = VERTEX;
    vec3 ln = NORMAL;
    // Results orbit scales about the orb centre (local origin of the ring).
    if (part > 1.5 && part < 2.5) {
        float sc = resultsScale;
        lp *= sc;
        // Normals of a uniformly scaled torus stay the same.
    }
    vec3 p = eulerZXY(lp, vec3(tilt.x, tilt.y + spin, tilt.z));
    vec3 n = eulerZXY(ln, vec3(tilt.x, tilt.y + spin, tilt.z));
    vec3 w = (MODEL_MATRIX * vec4(p, 1.0)).xyz;
    float depth = max(dot(w - CAMERA_POSITION, CAMERA_DIRECTION), 0.1);
    // A vertex at or behind the near plane, or a degenerate normal, must
    // not be expanded into a screen-space streak.
    vComp = 1.0;
    float nlen = length(n);
    bool bead = part > 2.5;
    float minP = bead ? (part > 3.5 ? 2.5 : 2.0) : ringMinPx;
    if (nlen > 1e-5 && depth > 0.25) {
        float rMin = min(minP * pxAngle * depth, tube * 12.0);
        float rNew = max(tube, rMin);
        p += (n / nlen) * (rNew - tube);
        vComp = tube / rNew;
        if (bead)
            vComp = vComp * vComp;
    }
    float ringR = max(length(vec2((w - orbCentre).x, (w - orbCentre).z)), 0.5);
    float behind = dot(w - orbCentre, CAMERA_DIRECTION) / ringR;
    vBack = mix(1.0, backGain, smoothstep(-0.3, 0.3, behind));
    vCol = vec4(COLOR.rgb, 1.0);
    vU = UV0.x;
    vGain = gainMul;
    vArc = (part > 0.5 && part < 1.5) ? 1.0 : 0.0;
    POSITION = MODELVIEWPROJECTION_MATRIX * vec4(p, 1.0);
}

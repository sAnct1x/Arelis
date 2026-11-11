// Emission vertex for filaments and the three rings. Adds a min screen
// width push along NORMAL and a back-half dim behind the orb centre.
// Sparks (UV0.y > 1.5) are not pushed. POSITION is written here because
// Qt skips the default when MAIN assigns VERTEX.
// Properties: spinAxis, spinAngle, spinShear, tubeRadius, minPx, pxAngle,
// backGain, orbCentre.
VARYING vec4 vCol;
VARYING float vU;
VARYING float vComp;
VARYING float vBack;

vec3 rotateAxis(vec3 p, vec3 a, float ang) {
    float c = cos(ang), s = sin(ang);
    return p * c + cross(a, p) * s + a * dot(a, p) * (1.0 - c);
}

void MAIN() {
    vec3 p = VERTEX;
    vec3 n = NORMAL;
    if (abs(spinAngle) > 0.00001) {
        float r = length(p);
        vec3 axis = normalize(spinAxis);
        float ang = spinAngle * (1.0 + spinShear * (1.0 - r / 2.6));
        p = rotateAxis(p, axis, ang);
        n = rotateAxis(n, axis, ang);
    }
    vec3 w = (MODEL_MATRIX * vec4(p, 1.0)).xyz;
    float depth = max(dot(w - CAMERA_POSITION, CAMERA_DIRECTION), 0.1);
    vComp = 1.0;
    float nlen = length(n);
    // Cap the min-px push and skip degenerate normals or near-camera
    // vertices so a bad endpoint cannot blow up into a screen streak.
    if (UV0.y < 1.5 && nlen > 1e-5 && depth > 0.25) {
        float rMin = min(minPx * pxAngle * depth, tubeRadius * 12.0);
        float rNew = max(tubeRadius, rMin);
        p += (n / nlen) * (rNew - tubeRadius);
        vComp = tubeRadius / rNew;
    }
    float ringR = max(length(VERTEX.xz), 0.5);
    float behind = dot(w - orbCentre, CAMERA_DIRECTION) / ringR;
    vBack = mix(1.0, backGain, smoothstep(-0.3, 0.3, behind));
    vCol = COLOR;
    vU = UV0.x;
    POSITION = MODELVIEWPROJECTION_MATRIX * vec4(p, 1.0);
}

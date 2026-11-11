// Shared emission vertex for non-instanced orb parts (nucleus, filaments, rings).
// Properties: spinAxis, spinAngle, spinShear. Spin is a no-op when spinAngle is 0.
// POSITION must be written here: Qt skips the default when MAIN assigns VERTEX
// (even in a spinAngle branch), which left the orb invisible.
VARYING vec4 vCol;
VARYING float vU;

vec3 rotateAxis(vec3 p, vec3 a, float ang) {
    float c = cos(ang), s = sin(ang);
    return p * c + cross(a, p) * s + a * dot(a, p) * (1.0 - c);
}

void MAIN() {
    if (abs(spinAngle) > 0.00001) {
        float r = length(VERTEX);
        vec3 axis = normalize(spinAxis);
        VERTEX = rotateAxis(VERTEX, axis, spinAngle * (1.0 + spinShear * (1.0 - r / 2.6)));
    }
    vCol = COLOR;
    vU = UV0.x;
    POSITION = MODELVIEWPROJECTION_MATRIX * vec4(VERTEX, 1.0);
}

// One strand of the current as a ribbon: GridMesh (steps x 1), u is t along it, v the side.
layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec4 vColor;   // rgb, alpha before coverage
layout(location = 1) out vec2 vLine;    // signed px from the centre line, half width

void main() {
    float t = qt_MultiTexCoord0.x;
    float side = qt_MultiTexCoord0.y * 2.0 - 1.0;
    vec2 p = pathPoint(t, strand);
    vec2 d = pathPoint(min(1.0, t + 0.002), strand) - pathPoint(max(0.0, t - 0.002), strand);
    vec2 n = normalize(vec2(-d.y, d.x) + vec2(1e-6));
    float halfW = (2.8 - strand * 0.22) * 0.5;
    float reach = halfW + 1.0;
    float fade = min(edgeFade(p.x), pathFade(t));
    // Python skips a segment whose fade is 0.12 or less.
    float a = fade > 0.12 ? (0.10 + strand * 0.016) * fade : 0.0;
    // Idle: the tree (tree.vert) stands for the ring; the current comes back as form rises.
    vColor = vec4(tone(t), a * (1.0 - treeOn));
    vLine = vec2(side * reach, halfW);
    gl_Position = qt_Matrix * vec4(p + n * side * reach, 0.0, 1.0);
}

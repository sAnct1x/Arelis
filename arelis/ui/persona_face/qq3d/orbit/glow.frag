// A soft ribbon (glow.vert, pool.vert): brightest on its centre line, gone at its edge, added.
layout(location = 0) in vec4 vColor;
layout(location = 1) in vec2 vLine;
layout(location = 0) out vec4 fragColor;

void main() {
    float x = clamp(abs(vLine.x) / max(vLine.y, 0.5), 0.0, 1.0);
    float g = (1.0 - x) * (1.0 - x);
    fragColor = vec4(vColor.rgb * vColor.a * g, 0.0) * qt_Opacity;
}

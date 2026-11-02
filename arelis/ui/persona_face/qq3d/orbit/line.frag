// An antialiased line, added to what is under it (alpha 0: premultiplied over is then plus,
// the CompositionMode_Plus the Python paint used).
layout(location = 0) in vec4 vColor;
layout(location = 1) in vec2 vLine;
layout(location = 0) out vec4 fragColor;

void main() {
    float cover = clamp(vLine.y + 0.5 - abs(vLine.x), 0.0, 1.0);
    fragColor = vec4(vColor.rgb * vColor.a * cover, 0.0) * qt_Opacity;
}

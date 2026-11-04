// The tree's four fiber quarters, each drawn into its own texture, laid over each other in one
// pass (premultiplied "over", in item order) instead of four full-window composites.
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(binding = 1) uniform sampler2D q0;
layout(binding = 2) uniform sampler2D q1;
layout(binding = 3) uniform sampler2D q2;
layout(binding = 4) uniform sampler2D q3;

void main() {
    vec4 c = texture(q0, qt_TexCoord0);
    vec4 t = texture(q1, qt_TexCoord0);
    c = t + c * (1.0 - t.a);
    t = texture(q2, qt_TexCoord0);
    c = t + c * (1.0 - t.a);
    t = texture(q3, qt_TexCoord0);
    c = t + c * (1.0 - t.a);
    fragColor = c * qt_Opacity;
}

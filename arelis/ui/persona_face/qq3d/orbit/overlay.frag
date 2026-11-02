// The Python worker's layer of what is not ported yet (beads, stems, tethers, the reality
// orbit), painted with CompositionMode_Plus onto clear: added here as it was added there.
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(binding = 1) uniform sampler2D source;

void main() {
    fragColor = vec4(texture(source, qt_TexCoord0).rgb, 0.0) * qt_Opacity;
}

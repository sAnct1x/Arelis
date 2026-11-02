// The floor glow pool that joins her feet and the tree's root (orbit_v11b compose's pool):
// one quad over the floor between them, its haze worked out per pixel in pool.frag.
layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec2 vP;   // window px

void main() {
    float k = treeK();
    float x0 = min(feet.x, tree.x) - 260.0 * k;
    float x1 = max(feet.x, tree.x) + 200.0 * k;
    float on = treeOn * (ringScale >= 1.0 ? 1.0 : ringScale);
    vec2 lo = vec2(x0, tree.y - 130.0 * k);
    vec2 hi = vec2(x1, min(view.y, tree.y + 110.0 * k));
    vec2 p = mix(lo, hi, qt_MultiTexCoord0);
    if (on <= 0.001) p = lo;
    vP = p;
    gl_Position = qt_Matrix * vec4(p, 0.0, 1.0);
}

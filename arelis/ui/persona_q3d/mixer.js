.pragma library
// mixer.js: clip choice and crossfade timing for the Quick 3D avatar, ported from persona_face/web/anim-mixer.js.
// Pure logic, no Qt objects: Mixer.qml samples the balsam Timelines at the times this returns and blends the two.
// Same pools, aliases, 0.8 s fade, LCG seed and no-repeat pick as the web mixer, so both pick the same clip sequence.

var ALIAS = { talking: 'speaking', rest: 'idle' };   // same names anim.js accepts
var POOLS = {   // repeats = weight
    // calm idle (POSES.md): the breathing clip only. Idle swings her chest ~17 deg in yaw, WeightShift and HappyIdle
    // shift her weight every few seconds; together they read as antsy.
    idle: ['v2_BreathingIdle'],
    listening: ['Listening', 'Listening', 'v2_ThoughtfulHeadNod', 'Agreeing'],   // no idle clip: entering listening always fades away from idle
    thinking: ['v2_BreathingIdle', 'Idle', 'v2_ThoughtfulHeadNod'],
    speaking: ['Talking', 'Talking', 'Agreeing'],
    done: ['v2_BreathingIdle'] };
var FADE = 0.8;
// Playback rate per clip (clip seconds per wall second). Talking's Mixamo gesture cycle at 1x reads rushed against her
// voice; 0.7 puts a beat at roughly every 1.2 s. Mixer.qml divides the clip length by the rate and samples t * rate.
var RATE = { Talking: 0.7 };

// durations: { clipName: seconds }. Returns { setState(name), step(dt) -> blend, play(name), state() }.
// blend = { cur: {name, t}, prev: {name, t} or null, w: weight of cur in [0, 1] } (prev weight is 1 - w).
function create(durations, seed) {
    var s = (seed === undefined ? 1234567 : seed) >>> 0;
    function rnd() { s = (s * 1103515245 + 12345) >>> 0; return s / 4294967296; }   // same float LCG as anim-mixer.js
    var M = { mode: 'idle', cur: null, prev: null, fadeLeft: 0, fadeLen: 0, wantSwitch: false, force: '' };
    function pool(mode) { return (POOLS[mode] || POOLS.idle).filter(function (n) { return durations[n] > 0; }); }
    function pick() {
        if (M.force && durations[M.force]) return M.force;
        var p = pool(M.mode); if (!p.length) return '';
        var n = p[Math.floor(rnd() * p.length)];
        // no repeat: step to the next different name. anim-mixer.js steps one slot, which lands on the same clip again
        // when the pool lists it twice for weight (Idle, Talking, Listening), so the web mixer can repeat; this cannot.
        if (M.cur && n === M.cur.name) { var j = p.indexOf(n); for (var k = 1; k < p.length && p[(j + k) % p.length] === n; k++);
            n = p[(j + k) % p.length]; }
        return n;
    }
    function play(name, fade) {
        if (!name) return;
        if (M.cur && fade > 0) { M.prev = M.cur; M.fadeLen = fade; M.fadeLeft = fade; } else { M.prev = null; M.fadeLeft = 0; }
        M.cur = { name: name, t: 0, left: durations[name] };
    }
    function advance(st) {
        M.cur.t = Math.min(M.cur.t + st, durations[M.cur.name]); M.cur.left -= st;
        if (M.prev) {   // the outgoing clip keeps playing, clamped at its end (LoopOnce + clampWhenFinished)
            M.prev.t = Math.min(M.prev.t + st, durations[M.prev.name]);
            M.fadeLeft -= st; if (M.fadeLeft <= 1e-9) { M.prev = null; M.fadeLeft = 0; }
        }
    }
    function step(dt) {
        if (!M.cur) play(pick(), 0);
        if (!M.cur) return null;
        // state change: fade to a clip of the new pool. A change during a fade waits for that fade to end, so at most
        // two clips are ever weighted and the weights never jump.
        if (M.wantSwitch && !M.prev) {
            if (pool(M.mode).indexOf(M.cur.name) < 0) play(pick(), FADE);
            M.wantSwitch = false;
        }
        // sub-step so the next variant starts at exactly (end - fade) of clip time whatever the frame dt
        var rem = dt, guard = 0;
        while (rem > 1e-9 && guard++ < 8) {
            if (M.cur.left <= FADE + 1e-6 && !M.prev) play(pick(), FADE);
            var lim = M.prev ? M.fadeLeft : M.cur.left - FADE;
            var st = Math.min(rem, Math.max(1e-6, lim));
            advance(st); rem -= st;
            if (M.wantSwitch && !M.prev && pool(M.mode).indexOf(M.cur.name) < 0) { play(pick(), FADE); M.wantSwitch = false; }
        }
        return blend();
    }
    function blend() {
        var w = M.prev ? 1 - M.fadeLeft / M.fadeLen : 1;
        return { cur: { name: M.cur.name, t: M.cur.t }, prev: M.prev ? { name: M.prev.name, t: M.prev.t } : null, w: w };
    }
    return {
        setState: function (m) { M.mode = ALIAS[m] || m; M.wantSwitch = true; },
        play: function (name) { M.force = name || ''; if (name && durations[name]) play(name, M.cur ? 0.3 : 0); },
        step: step,
        state: function () { return { mode: M.mode, clip: M.cur ? M.cur.name : '', fading: !!M.prev }; }
    };
}

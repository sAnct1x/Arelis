// The Filament orbit on the GPU (ARELIS_SURFACE=quick, slice 2): the ring and its load-time
// growth out of her hub, the four strands of the current, the dust, and the hub threads, as
// ShaderEffects over the void. No Python per frame: OrbitState (quick_surface.py) carries the
// geometry and the weather and emits on change; this file eases the weather and runs the clock
// on a FrameAnimation, as FilamentField.tick does, and takes a 1 s sync of the sim's clock so
// the beads, stems and tethers the Python worker still paints (the overlay) stay on the path.
// The orbit tree (Iris's v11b) stands for the ring in every state: fibers, roots and floor
// link (tree.vert) with their glow (glow.vert) over the floor pool (pool.vert), light packets
// as travelling dots (pulse.vert) and node flares (flare.vert), all moving on `flow`, seconds
// of calm time. Thinking and speaking only brighten the packets; the tree never fades out.
import QtQuick

Item {
    id: orbit
    required property QtObject st
    visible: !!st && st.active

    property real time: 0
    property real form: 0
    property real speed: 0.08
    property real pulse: 0
    property real warm: 0
    property real words: 0
    property real dustClock: 0
    property real flow: 0
    readonly property real flowRate: 0.4
    // The packets' clock: the calm 15 s loop, and a 4 s loop while she thinks or speaks, so
    // every tile (all six crown tiles and reality) gets a packet within a few seconds of a
    // reply starting, not only the two or three whose turn falls in it.
    property real packetFlow: 0
    property real packetRate: flowRate
    readonly property real generatingRate: 1.5
    // The tree stands in every state (idle, thinking, speaking); form only brightens its packets.
    readonly property real treeOn: 1
    property real ringGrow: 0
    // The node flares (the ring round each tile) and the pulses (which light reality's orb)
    // fade in on the tile titles' own value (OrbitState.titleShow = FilamentField.title_show),
    // never on this file's ring clock, which can settle seconds before the field's does.
    readonly property real nodeShow: st ? st.titleShow : 0
    property real clockErr: 0
    property bool synced: false
    property bool clockRunning: true  // a still (a comparison grab) freezes the clock
    readonly property real ringScale: {
        const g = Math.max(0, Math.min(1, ringGrow));
        return g * g * (3 - 2 * g);
    }
    readonly property real speakHead: (time * 0.14) % 1.0
    readonly property real pulseT: (Math.sin(time * 1.15) * 0.5 + 0.5) * pulse
        + Math.pow(Math.max(0, Math.sin(time * 1.55)), 8) * words * 0.85

    property int fpsFrames: 0
    property real fpsSpan: 0

    function ease(cur, want, dt, sec) {
        return cur + (want - cur) * (1 - Math.exp(-dt / Math.max(0.05, sec)));
    }

    function step(raw) {
        if (!st)
            return; // its surface is being torn down: orbitState is already gone
        fpsFrames += 1;
        fpsSpan += raw;
        if (fpsSpan >= 5.0) {
            st.reportFps(Math.round(fpsFrames / fpsSpan));
            fpsFrames = 0;
            fpsSpan = 0;
        }
        const dt = Math.min(0.05, Math.max(0, raw));
        const phase = st.ringPhase;
        if (phase === "grow")
            ringGrow = Math.min(1, ringGrow + dt / st.ringGrowSeconds);
        else if (phase === "wait")
            ringGrow = 0;
        else
            ringGrow = 1;
        const want = st.target;  // form, speed, pulse, warm, words
        form = ease(form, want[0], dt, 1.85);
        speed = ease(speed, want[1], dt, 1.1);
        pulse = ease(pulse, want[2], dt, 0.9);
        warm = ease(warm, want[3], dt, 1.2);
        words = ease(words, want[4], dt, 0.8);
        const fix = clockErr * Math.min(1, dt * 3);
        clockErr -= fix;
        time += dt * speed * 1.7 + fix;
        dustClock += dt * (0.012 + speed * 0.028);
        // flow runs at FLOW_RATE of real time: a 15 s packet loop and a slow wind, calm water.
        flow = (flow + dt * flowRate) % 600.0;  // a whole number of loops, so the wrap is seamless
        const gen = st.weather === "think" || st.weather === "speak";
        packetRate = ease(packetRate, gen ? generatingRate : flowRate, dt, 0.5);
        packetFlow = (packetFlow + dt * packetRate) % 600.0;
    }

    function takeSync() {
        const s = st.sync;  // time, form, speed, pulse, warm, words
        if (!s || s.length < 6)
            return;
        if (!synced || Math.abs(s[0] - time) > 0.5) {
            time = s[0];
            clockErr = 0;
            synced = true;
        } else {
            clockErr = s[0] - time;
        }
        form = s[1]; speed = s[2]; pulse = s[3]; warm = s[4]; words = s[5];
    }

    Connections {
        target: orbit.st
        function onSyncChanged() { orbit.takeSync(); }
        function onRingPhaseChanged() { orbit.ringGrow = orbit.st.ringGrow; }
    }
    Component.onCompleted: { if (!st) return; takeSync(); ringGrow = st.ringPhase === "" ? 1 : st.ringGrow; }

    FrameAnimation {
        running: orbit.visible && orbit.clockRunning
        onTriggered: orbit.step(frameTime)
    }

    component Layer: ShaderEffect {
        anchors.fill: parent
        property real time: orbit.time
        property real form: orbit.form
        property real warm: orbit.warm
        property real pulseT: orbit.pulseT
        property real words: orbit.words
        property real speakHead: orbit.speakHead
        property real ringScale: orbit.ringScale
        property real fullHalf: orbit.st.fullHalf
        property real listenHalf: orbit.st.listenHalf
        property real fadeMargin: orbit.st.fadeMargin
        property real strand: 0
        property real dustClock: orbit.dustClock
        property real speed: orbit.speed
        property real hasHub: orbit.st.hasHub ? 1 : 0
        property real pad0: 0
        property size view: Qt.size(orbit.width, orbit.height)
        property point hub: orbit.st.hub
        property vector4d ring: orbit.st.ring
        property color ice: orbit.st.ice
        property color gold: orbit.st.gold
        property color coreColor: orbit.st.core
        property vector4d tree: orbit.st.tree
        property point feet: orbit.st.feet
        property point reality: orbit.st.reality
        property real flow: orbit.flow
        property real packetFlow: orbit.packetFlow
        property real treeOn: orbit.treeOn
        fragmentShader: "orbit/line.frag.qsb"
    }

    // Everything the orbit draws, so it can be held as one picture while the chat covers the
    // tree (OrbitState.treeCovered): the tree stays fully on, drawn from that picture (one
    // full-window texture), and none of its layers shades a pixel under the chat. It moves again
    // as soon as the chat leaves it.
    readonly property bool held: !!st && st.treeCovered
    Item {
        id: treeStack
        objectName: "orbitTreeStack"
        anchors.fill: parent

        Repeater {
            model: 4
            Layer {
                required property int index
                strand: index
                visible: orbit.treeOn < 0.999   // under the tree its alpha is 0: draw nothing
                mesh: GridMesh { resolution: Qt.size(192, 1) }
                vertexShader: "orbit/strand.vert.qsb"
            }
        }

        Layer {
            objectName: "orbitPool"
            vertexShader: "orbit/pool.vert.qsb"
            fragmentShader: "orbit/pool.frag.qsb"
        }

        Layer {
            objectName: "orbitTreeGlow"
            mesh: GridMesh { resolution: Qt.size(24 * 64 - 1, 1) }
            vertexShader: "orbit/glow.vert.qsb"
            fragmentShader: "orbit/glow.frag.qsb"
        }

        Layer {
            id: fibers0
            objectName: "orbitTree"
            strand: 0
            mesh: GridMesh { resolution: Qt.size(49152 / 4 - 1, 1) }
            vertexShader: "orbit/tree.vert.qsb"
        }
        ShaderEffectSource {
            id: fibersTex0
            visible: false   // sampled by orbitTreeFibers, not drawn itself
            objectName: "orbitTreeTex0"
            anchors.fill: parent
            sourceItem: fibers0
            hideSource: true
            live: false
        }
        Layer {
            id: fibers1
            objectName: "orbitTree1"
            strand: 1
            mesh: GridMesh { resolution: Qt.size(49152 / 4 - 1, 1) }
            vertexShader: "orbit/tree.vert.qsb"
        }
        ShaderEffectSource {
            id: fibersTex1
            visible: false   // sampled by orbitTreeFibers, not drawn itself
            objectName: "orbitTreeTex1"
            anchors.fill: parent
            sourceItem: fibers1
            hideSource: true
            live: false
        }
        Layer {
            id: fibers2
            objectName: "orbitTree2"
            strand: 2
            mesh: GridMesh { resolution: Qt.size(49152 / 4 - 1, 1) }
            vertexShader: "orbit/tree.vert.qsb"
        }
        ShaderEffectSource {
            id: fibersTex2
            visible: false   // sampled by orbitTreeFibers, not drawn itself
            objectName: "orbitTreeTex2"
            anchors.fill: parent
            sourceItem: fibers2
            hideSource: true
            live: false
        }
        Layer {
            id: fibers3
            objectName: "orbitTree3"
            strand: 3
            mesh: GridMesh { resolution: Qt.size(49152 / 4 - 1, 1) }
            vertexShader: "orbit/tree.vert.qsb"
        }
        ShaderEffectSource {
            id: fibersTex3
            visible: false   // sampled by orbitTreeFibers, not drawn itself
            objectName: "orbitTreeTex3"
            anchors.fill: parent
            sourceItem: fibers3
            hideSource: true
            live: false
        }
        Layer {   // a Layer so the uniform block it shares (common.glsl) is all bound
            id: fibersMerged
            property variant q0: fibersTex0
            property variant q1: fibersTex1
            property variant q2: fibersTex2
            property variant q3: fibersTex3
            fragmentShader: "orbit/fibers.frag.qsb"
        }
        ShaderEffectSource {
            id: fibersAll
            objectName: "orbitTreeFibers"
            anchors.fill: parent
            sourceItem: fibersMerged
            hideSource: true
            live: false
        }
        // The fibers are most of a frame's cost (vertex work and thin-triangle raster), so each
        // quarter draws into its own texture and one quarter redraws per frame, in turn (a major
        // limb quarter, then a minor one): every fiber moves at a quarter of the frame rate, none
        // thinner. The four are laid together once per redraw into one cached texture
        // (orbitTreeFibers), so a frame composites one full-window texture, not four. While the
        // chat tile covers the tree (OrbitState.treeCovered) the fibers hold still: the tree stays
        // fully drawn from that texture, and no fiber redraws under the chat.
        FrameAnimation {
            objectName: "orbitFiberClock"
            running: orbit.visible && !orbit.held
            onTriggered: {
                const q = currentFrame % 4
                if (q == 0) fibersTex0.scheduleUpdate()
                else if (q == 1) fibersTex2.scheduleUpdate()
                else if (q == 2) fibersTex1.scheduleUpdate()
                else fibersTex3.scheduleUpdate()
                fibersAll.scheduleUpdate()
            }
        }

        Layer {
            objectName: "orbitDust"
            mesh: GridMesh { resolution: Qt.size(4 * 1100 - 1, 1) }
            vertexShader: "orbit/dust.vert.qsb"
            fragmentShader: "orbit/dust.frag.qsb"
        }

        Repeater {
            model: 3
            Layer {
                required property int index
                visible: orbit.st.hasHub && orbit.treeOn < 0.999
                strand: index
                mesh: GridMesh { resolution: Qt.size(48, 1) }
                vertexShader: "orbit/thread.vert.qsb"
            }
        }

        Layer {
            objectName: "orbitFlares"
            opacity: orbit.nodeShow
            mesh: GridMesh { resolution: Qt.size(4 * 7 - 1, 1) }
            vertexShader: "orbit/flare.vert.qsb"
            fragmentShader: "orbit/flare.frag.qsb"
        }

        Layer {
            objectName: "orbitPulses"
            opacity: orbit.nodeShow
            mesh: GridMesh { resolution: Qt.size(4 * (11 * 6 + 36 * 3) - 1, 1) }
            vertexShader: "orbit/pulse.vert.qsb"
            fragmentShader: "orbit/dust.frag.qsb"
        }
    }
    // The held picture, in the four bands round the chat tile (above, below, left, right of
    // it): each band renders its part of the stack once, when the hold starts.
    Repeater {
        objectName: "orbitTreeHeld"
        model: 4
        ShaderEffectSource {
            required property int index
            readonly property rect c: orbit.st ? orbit.st.cover : Qt.rect(0, 0, 0, 0)
            readonly property real cTop: Math.max(0, Math.min(orbit.height, c.y))
            readonly property real cBottom: Math.max(cTop, Math.min(orbit.height, c.y + c.height))
            readonly property real cLeft: Math.max(0, Math.min(orbit.width, c.x))
            readonly property real cRight: Math.max(cLeft, Math.min(orbit.width, c.x + c.width))
            x: index == 3 ? cRight : 0
            y: index == 0 ? 0 : index == 1 ? cBottom : cTop
            width: index == 0 || index == 1 ? orbit.width : index == 2 ? cLeft : orbit.width - cRight
            height: index == 0 ? cTop : index == 1 ? orbit.height - cBottom : cBottom - cTop
            sourceItem: treeStack
            sourceRect: Qt.rect(x, y, width, height)
            hideSource: orbit.held
            visible: orbit.held && width > 0 && height > 0
            live: false
            onSourceRectChanged: if (orbit.held) scheduleUpdate()   // the chat moved
            Connections {
                target: orbit
                function onHeldChanged() { if (orbit.held) scheduleUpdate() }
            }
        }
    }
}

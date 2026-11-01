# Pose specs: Quick 3D avatar (qq3d)

Measured on the live scene (Avatar.qml + Mixer.qml + face.js, offscreen). Yaw is the head's world
forward about +y: + turns her face to her own left (the viewer's right). Pitch: + is up. Trunk lean is
hip to neck in the side plane: + is forward; her rest pose reads -5.4 deg.

## Idle (calm)
- Head level: pitch within +/-3 deg of her rest pose, never carried down by the chest.
- Head turned slightly to her left: yaw about +4 deg (face.js HOME_YAW 0.09 rad), drifting +/-3 deg.
- The head and neck hold their world orientation against the clip's trunk turn (face.js `rot` level:
  head 1, neck 0.5), so a curled or turned chest does not tip or turn the head.
- Body mostly still: only v2_BreathingIdle plays (mixer.js POOLS.idle and done). Idle, WeightShift and
  HappyIdle are out of the idle pool.
- Upright: Mixer.qml turns the blended waist back by uprightDeg (6.5 deg), the clips' extra forward
  lean against her rest pose. Trunk lean -7..-2 deg.
- Light breathing (face.js, 0.23 breaths/s); the neck stretch event is a small roll (0.06 rad), not a
  head circle; head drifts are half v14k's and slower.

## Talk
- Talking plays at 0.7x (mixer.js RATE), one gesture beat about every 1.2 s.
- Head stays level and slightly left like idle; the clip's chest turn does not reach it.
- Syllables: at least 0.13 s apart (0.38 s for sustained loud speech); the syllable head nods and tilts
  are about half v14k's, on softer springs (7 and 5.5 rad/s); gaze shifts less often (gap 1.3).
- Trunk lean mean about +1 deg, peaks about +10 deg on big gestures.

Check: /workspace/team/avatar-qq3d/calm-idle/render.py <repo> <out> <tag> renders front stills at idle
2, 6, 12, 20, 30 s and while talking, and prints head yaw, pitch and trunk lean.

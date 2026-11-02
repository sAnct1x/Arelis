import time
from types import SimpleNamespace

from arelis.ui.persona_face import qq3d_avatar


def test_her_next_frame_waits_out_a_60fps_slot_after_the_last_one_started():
    me = SimpleNamespace(_frame_t=time.monotonic())
    assert qq3d_avatar.QQ3DAvatar._frame_delay_ms(me) >= 10
    me._frame_t = time.monotonic() - 1.0
    assert qq3d_avatar.QQ3DAvatar._frame_delay_ms(me) == 0

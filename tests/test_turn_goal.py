"""Turn goal: login check stops on signed-in or hands over the form."""

from __future__ import annotations

from arelis.core.preflight import login_check_hop_args
from arelis.core.turn_goal import (
    LOGIN_READY,
    NEED_LOGIN,
    browser_errand_done,
)

_X_ASK = (
    "go to x.com and take me to the login page if it does not "
    "automatically sign me in."
)


def test_logged_out_splash_hops_to_login() -> None:
    errand = browser_errand_done(
        _X_ASK,
        action="navigate",
        requested_url="https://x.com",
        landed_url="https://x.com",
        snapshot="[e11] button 'Sign in'",
    )
    assert errand.status == NEED_LOGIN
    hop = login_check_hop_args("[e11] button 'Sign in'", "https://x.com")
    assert hop == {"action": "click", "ref": "e11"}
    assert login_check_hop_args("", "https://x.com/home") == {
        "action": "navigate",
        "url": "https://x.com/login",
    }


def test_login_wall_is_their_turn() -> None:
    errand = browser_errand_done(
        _X_ASK,
        action="navigate",
        requested_url="https://x.com/login",
        landed_url="https://x.com/login",
        wall="login",
        snapshot="[e11] button 'Sign in'",
    )
    assert errand.status == LOGIN_READY
    assert errand.done
    assert "login" in errand.reply.lower()


def test_youtube_search_ask_keeps_driving_after_navigate() -> None:
    errand = browser_errand_done(
        "Hay take me to you tube doc calm and do us search "
        "for the organic chemistry tutor",
        action="navigate",
        requested_url="https://www.youtube.com",
        landed_url="https://www.youtube.com/",
        snapshot="title: YouTube\nurl: https://www.youtube.com/",
    )
    assert not errand.done
    assert errand.status == "drive"



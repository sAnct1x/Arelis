"""Turn goal: login check stops on signed-in or hands over the form."""

from __future__ import annotations

from arelis.core.preflight import login_check_hop_args
from arelis.core.turn_goal import (
    LOGIN_READY,
    NEED_LOGIN,
    SIGNED_IN,
    browser_errand_done,
    derive_turn_goal,
    receipt_serves_goal,
)

_X_ASK = (
    "go to x.com and take me to the login page if it does not "
    "automatically sign me in."
)


def test_x_home_without_signin_is_already_in() -> None:
    errand = browser_errand_done(
        _X_ASK,
        action="navigate",
        requested_url="https://x.com",
        landed_url="https://x.com/home",
        snapshot="title: Home\nurl: https://x.com/home\nelements:\n[e1] link 'Home'",
    )
    assert errand.status == SIGNED_IN
    assert "signed in" in errand.reply.lower()


def test_login_bounce_to_home_is_already_in() -> None:
    errand = browser_errand_done(
        _X_ASK,
        action="navigate",
        requested_url="https://x.com/login",
        landed_url="https://x.com/home",
        snapshot="[e11] button 'Sign in'",
        signed_in=True,
    )
    assert errand.status == SIGNED_IN
    assert "signed in" in errand.reply.lower()


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


def test_cart_ask_keeps_driving_after_open() -> None:
    errand = browser_errand_done(
        "go to amazon.com and add batteries to cart",
        action="navigate",
        requested_url="https://www.amazon.com",
        landed_url="https://www.amazon.com",
        snapshot="title: Amazon\nurl: https://www.amazon.com",
    )
    assert not errand.done
    assert errand.status == "drive"


def test_derive_browser_goal_is_a_login_check() -> None:
    goal = derive_turn_goal(_X_ASK, kinds=["browser"])
    assert goal.kind == "browser"
    assert "login" in goal.line.lower()


def test_pay_wall_serves_browser_goal() -> None:
    goal = derive_turn_goal("add batteries to cart and checkout", kinds=["browser"])
    assert receipt_serves_goal(
        goal, "browser", "Stopped before Pay.", data={"wall": "pay"}
    )

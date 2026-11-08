"""Minutes from key events (unit level)."""

import json

from rondo.core.minutes import match_minutes

LENGTHS = {1: 2700.0, 2: 2880.0}  # 45:00 and 48:00, so 93 minutes


def _xi(team, ids):
    lineup = [{"player": {"id": i}, "position": {"id": 1}} for i in ids]
    return (team, None, 1, 0.0, "Starting XI", json.dumps({"tactics": {"lineup": lineup}}))


def _sub(team, off, on, period, ts):
    detail = {"substitution": {"replacement": {"id": on}}}
    return (team, off, period, ts, "Substitution", json.dumps(detail))


def _red(team, player, period, ts):
    return (
        team,
        player,
        period,
        ts,
        "Bad Behaviour",
        json.dumps({"bad_behaviour": {"card": {"name": "Red Card"}}}),
    )


def test_substitution_and_red_card():
    players, clock = match_minutes(
        [_xi(1, range(1, 12)), _sub(1, 11, 12, 2, 600.0), _red(1, 5, 2, 1200.0)], LENGTHS
    )
    assert clock.end == 5580.0
    assert players[11].off == 2700.0 + 600.0 and players[12].on == 3300.0
    assert players[5].sent_off and players[5].off == 3900.0


def test_red_card_after_substitution_is_not_a_sending_off():
    players, _ = match_minutes(
        [_xi(1, range(1, 12)), _sub(1, 11, 12, 1, 600.0), _red(1, 11, 2, 2000.0)], LENGTHS
    )
    assert not players[11].sent_off and players[11].off == 600.0


def test_red_card_to_unused_substitute_is_ignored():
    players, _ = match_minutes([_xi(1, range(1, 12)), _red(1, 99, 2, 100.0)], LENGTHS)
    assert 99 not in players

"""Rule tests for the Trouble Brewing engine. Run: uv run --with pytest pytest -q"""

import random

import pytest

import info
from game import Game, GameError
from roles import CHARACTERS, is_good

NAMES = ["Asha", "Ben", "Chen", "Dev", "Ema", "Finn", "Gita", "Hari", "Ines"]


def make(chars: list[str], seed: int = 1) -> Game:
    """Seat len(chars) players, force their characters in seat order, and start night 1."""
    g = Game(random.Random(seed))
    for n in NAMES[:len(chars)]:
        g.add_player(n)
    g.deal()
    for p, c in zip(g.players, chars):
        g.set_character(p.pid, c)
    # re-pick the Drunk's belief now that every real character is placed
    for p in g.players:
        if p.character == "drunk":
            g.set_character(p.pid, "drunk")
    g.red_herring = next(p.pid for p in g.players if p.character not in ("imp", "poisoner", "spy", "scarlet_woman", "baron"))
    held = {x for p in g.players for x in (p.character, p.believed)}
    g.bluffs = [c for c in CHARACTERS if is_good(c) and c not in held][:3]
    g.start_game()
    return g


def p(g: Game, name: str):
    return next(x for x in g.players if x.name == name)


def to_night2(g: Game) -> None:
    g.start_day()
    g.end_day()


def step(g: Game, key: str) -> int:
    return next(i for i, s in enumerate(g.steps) if s["key"] == key)


NINE = ["imp", "scarlet_woman", "monk", "soldier", "empath", "virgin", "slayer", "saint", "mayor"]


def test_first_night_order_and_evil_info():
    g = make(NINE)
    assert [s["key"] for s in g.steps] == ["minion_info", "demon_info", "empath"]
    g.resolve(0, [])
    assert "The Demon is Asha" in g.steps[0]["suggestion"]


def test_small_game_skips_evil_info():
    g = make(["imp", "poisoner", "empath", "chef", "saint"])
    assert "minion_info" not in [s["key"] for s in g.steps]


def test_monk_protects_and_soldier_survives():
    g = make(NINE)
    to_night2(g)
    g.resolve(step(g, "monk"), [p(g, "Ema").pid])
    g.resolve(step(g, "imp"), [p(g, "Ema").pid])
    assert p(g, "Ema").alive
    g.start_day(); g.end_day()
    g.resolve(step(g, "imp"), [p(g, "Dev").pid])
    assert p(g, "Dev").alive


def test_poisoned_soldier_dies():
    g = make(["imp", "poisoner", "soldier", "empath", "chef", "saint", "mayor"])
    to_night2(g)
    g.resolve(step(g, "poisoner"), [p(g, "Chen").pid])
    g.resolve(step(g, "imp"), [p(g, "Chen").pid])
    assert not p(g, "Chen").alive


def test_star_pass_prefers_scarlet_woman():
    g = make(NINE)
    to_night2(g)
    g.resolve(step(g, "imp"), [p(g, "Asha").pid])
    assert p(g, "Ben").character == "imp" and not p(g, "Asha").alive and g.winner is None


def test_executing_demon_promotes_scarlet_woman_then_good_wins():
    g = make(NINE)
    g.start_day()
    g.nominate(p(g, "Chen").pid, p(g, "Asha").pid)
    g.record_votes(0, [x.pid for x in g.players[:5]])
    g.end_day()
    assert p(g, "Ben").character == "imp" and g.winner is None
    g.start_day()
    g.nominate(p(g, "Chen").pid, p(g, "Ben").pid)
    g.record_votes(0, [x.pid for x in g.players[:5]])
    g.end_day()
    assert g.winner == "good"


def test_virgin_executes_townsfolk_nominator_only_once():
    g = make(NINE)
    g.start_day()
    g.nominate(p(g, "Gita").pid, p(g, "Finn").pid)
    assert not p(g, "Gita").alive and g.executed_today == p(g, "Gita").pid
    with pytest.raises(GameError):
        g.nominate(p(g, "Ema").pid, p(g, "Dev").pid)


def test_virgin_ignores_minion_nominator():
    g = make(NINE)
    g.start_day()
    g.nominate(p(g, "Ben").pid, p(g, "Finn").pid)
    assert p(g, "Ben").alive and g.virgin_spent


def test_slayer_kills_demon_once():
    g = make(NINE)
    g.start_day()
    g.slayer_shot(p(g, "Gita").pid, p(g, "Chen").pid)
    assert g.slayer_spent and p(g, "Chen").alive
    g.slayer_shot(p(g, "Gita").pid, p(g, "Asha").pid)
    assert p(g, "Asha").alive


def test_saint_execution_loses():
    g = make(NINE)
    g.start_day()
    g.nominate(p(g, "Chen").pid, p(g, "Hari").pid)
    g.record_votes(0, [x.pid for x in g.players[:5]])
    g.end_day()
    assert g.winner == "evil"


def test_tie_means_no_execution():
    g = make(NINE)
    g.start_day()
    g.nominate(p(g, "Chen").pid, p(g, "Dev").pid)
    g.record_votes(0, [x.pid for x in g.players[:5]])
    g.nominate(p(g, "Dev").pid, p(g, "Ema").pid)
    g.record_votes(1, [x.pid for x in g.players[4:]])
    g.end_day()
    assert all(x.alive for x in g.players)


def test_ghost_vote_spent_and_refunded():
    g = make(NINE)
    g.start_day()
    g.kill(p(g, "Ema").pid)
    g.nominate(p(g, "Chen").pid, p(g, "Dev").pid)
    g.record_votes(0, [p(g, "Ema").pid])
    assert not p(g, "Ema").ghost_vote
    g.record_votes(0, [])
    assert p(g, "Ema").ghost_vote


def test_mayor_wins_at_three_without_execution():
    g = make(["imp", "poisoner", "mayor", "empath", "chef"])
    g.start_day()
    g.kill(p(g, "Dev").pid)
    g.kill(p(g, "Ema").pid)
    g.end_day()
    assert g.winner == "good"


def test_evil_wins_at_two_alive():
    g = make(["imp", "poisoner", "monk", "empath", "chef"])
    g.start_day()
    for n in ("Chen", "Dev"):
        g.kill(p(g, n).pid)
    assert g.winner is None
    g.kill(p(g, "Ema").pid)
    assert g.winner == "evil"


def test_empath_skips_dead_neighbours():
    g = make(NINE)
    g.kill(p(g, "Dev").pid)
    g.kill(p(g, "Finn").pid)
    assert {x.name for x in info.living_neighbours(g, p(g, "Ema"))} == {"Chen", "Gita"}


def test_drunk_monk_wakes_but_cannot_protect():
    g = make(["imp", "poisoner", "drunk", "empath", "chef", "saint", "mayor"])
    g.set_character(p(g, "Chen").pid, "drunk", believed="monk")
    to_night2(g)
    i = step(g, "monk")
    assert g.steps[i]["pids"] == [p(g, "Chen").pid]
    assert g.storyteller_view()["steps"][i]["impaired"]
    g.resolve(i, [p(g, "Dev").pid])
    g.resolve(step(g, "imp"), [p(g, "Dev").pid])
    assert not p(g, "Dev").alive


def test_fortune_teller_red_herring_reads_yes():
    g = make(["imp", "poisoner", "fortune_teller", "empath", "chef", "saint", "mayor"])
    g.red_herring = p(g, "Ema").pid
    i = step(g, "fortune_teller")
    g.resolve(i, [p(g, "Ema").pid, p(g, "Dev").pid])
    assert "YES" in g.steps[i]["suggestion"]
    g.resolve(i, [p(g, "Dev").pid, p(g, "Finn").pid])
    assert "NO" in g.steps[i]["suggestion"]


def test_chef_counts_adjacent_pairs_around_circle():
    g = make(["imp", "empath", "chef", "saint", "mayor", "monk", "poisoner"])
    assert info.evil_pairs(g) == 1


# --- eyes-open nights ---

def test_night_start_prompts_every_living_chooser_and_buzzes():
    g = make(["imp", "poisoner", "fortune_teller", "butler", "chef", "saint", "ravenkeeper"])
    assert g.buzz == 1
    choosers = {x.name for x in g.players if x.prompt["kind"] == "choose"}
    assert choosers == {"Ben", "Chen", "Dev"}
    to_night2(g)
    choosers = {x.name for x in g.players if x.prompt["kind"] == "choose"}
    assert choosers == {"Asha", "Ben", "Chen", "Dev"}


def test_info_is_held_until_dawn_and_everyone_gets_a_slip():
    g = make(NINE)
    i = step(g, "empath")
    g.resolve(i, [])
    g.send(i, g.steps[i]["suggestion"])
    assert p(g, "Ema").messages == []
    before = g.buzz
    g.start_day()
    assert g.buzz == before + 1
    assert "neighbours" in p(g, "Ema").messages[-1]["text"]
    assert p(g, "Chen").messages[-1]["text"] == "Nothing to report tonight."
    assert all(x.messages for x in g.players)


def test_imp_kill_starts_second_round_and_prompts_dead_ravenkeeper():
    g = make(["imp", "poisoner", "ravenkeeper", "empath", "chef", "saint", "mayor"])
    to_night2(g)
    before = g.buzz
    g.resolve(step(g, "imp"), [p(g, "Chen").pid])
    assert g.buzz == before + 1 and g.second_round_done
    assert p(g, "Chen").prompt and not p(g, "Chen").alive


def test_second_round_buzzes_even_when_ravenkeeper_survives():
    g = make(["imp", "poisoner", "ravenkeeper", "empath", "chef", "saint", "mayor"])
    to_night2(g)
    before = g.buzz
    g.resolve(step(g, "imp"), [p(g, "Dev").pid])
    assert g.buzz == before + 1 and p(g, "Chen").prompt["kind"] == "tap"


def test_star_pass_news_waits_for_dawn():
    g = make(NINE)
    to_night2(g)
    seen = len(p(g, "Ben").messages)
    g.resolve(step(g, "imp"), [p(g, "Asha").pid])
    assert len(p(g, "Ben").messages) == seen
    g.start_day()
    assert p(g, "Ben").messages[-1]["text"] == "You are now the Imp."


def test_phone_answer_only_shows_on_its_own_step():
    g = make(["imp", "poisoner", "empath", "chef", "saint", "mayor", "monk"])
    ben = p(g, "Ben")
    g.choose(ben.token, [p(g, "Ema").pid])
    view = g.storyteller_view()["steps"]
    assert view[step(g, "minion_info")]["answer"] is None
    assert view[step(g, "poisoner")]["answer"] == [p(g, "Ema").pid]


def test_holding_evil_info_keeps_poisoner_prompt_open():
    g = make(["imp", "poisoner", "empath", "chef", "saint", "mayor", "monk"])
    i = step(g, "minion_info")
    g.resolve(i, [])
    g.send(i, g.steps[i]["suggestion"])
    assert p(g, "Ben").prompt and p(g, "Ben").prompt["step"] == step(g, "poisoner")


def test_player_note_reaches_storyteller_only():
    g = make(NINE)
    g.note_to_storyteller(p(g, "Ema").token, "Can the Monk protect themselves?")
    st = g.storyteller_view()["inbox"]
    assert st[0]["pid"] == p(g, "Ema").pid and not st[0]["read"]
    assert g.player_view(p(g, "Ema").token)["me"]["notes"][0]["text"].startswith("Can the Monk")
    assert g.player_view(p(g, "Ben").token)["me"]["notes"] == []
    assert "inbox" not in g.public_view()
    g.read_inbox()
    assert g.storyteller_view()["inbox"][0]["read"]
    with pytest.raises(GameError):
        g.note_to_storyteller(p(g, "Ema").token, "   ")


def test_night_message_now_skips_dawn_queue():
    g = make(NINE)
    g.message(p(g, "Ema").pid, "Yes, the Monk cannot pick themselves.", now=True)
    assert p(g, "Ema").messages[-1]["text"].startswith("Yes")
    assert p(g, "Ema").pid not in g.queued


def test_night_kill_hidden_from_phones_until_dawn():
    g = make(NINE)
    to_night2(g)
    ema = p(g, "Ema")
    g.resolve(step(g, "imp"), [ema.pid])
    assert not ema.alive
    seat = next(x for x in g.public_view()["seats"] if x["pid"] == ema.pid)
    assert seat["alive"] and g.player_view(ema.token)["me"]["alive"]
    assert not next(x for x in g.storyteller_view()["players"] if x["pid"] == ema.pid)["alive"]
    g.start_day()
    assert not next(x for x in g.public_view()["seats"] if x["pid"] == ema.pid)["alive"]


def test_scarlet_woman_gets_imp_kill_prompt_after_imp_executed():
    g = make(NINE)
    g.start_day()
    g.nominate(p(g, "Chen").pid, p(g, "Asha").pid)
    g.record_votes(0, [x.pid for x in g.players[:5]])
    g.end_day()
    i = step(g, "imp")
    assert g.steps[i]["pids"] == [p(g, "Ben").pid]
    assert g.step_applies(g.steps[i]) and p(g, "Ben").prompt["step"] == i


def test_new_imp_after_star_pass_acts_next_night():
    g = make(NINE)
    to_night2(g)
    g.resolve(step(g, "imp"), [p(g, "Asha").pid])
    g.start_day()
    g.end_day()
    assert g.steps[step(g, "imp")]["pids"] == [p(g, "Ben").pid]


def test_undertaker_info_sent_automatically_at_dawn():
    g = make(["imp", "poisoner", "undertaker", "empath", "chef", "soldier", "mayor"])
    g.start_day()
    g.nominate(p(g, "Asha").pid, p(g, "Ben").pid)
    g.record_votes(0, [x.pid for x in g.players[:4]])
    g.end_day()
    g.start_day()
    assert p(g, "Chen").messages[-1]["text"] == "Ben, executed today, was the Poisoner."


def test_undertaker_manual_send_is_not_duplicated():
    g = make(["imp", "poisoner", "undertaker", "empath", "chef", "soldier", "mayor"])
    g.start_day()
    g.nominate(p(g, "Asha").pid, p(g, "Ben").pid)
    g.record_votes(0, [x.pid for x in g.players[:4]])
    g.end_day()
    i = step(g, "undertaker")
    g.send(i, "Ben was the Chef.")
    g.start_day()
    night_msgs = [m["text"] for m in p(g, "Chen").messages if m["label"] == "Night 2"]
    assert night_msgs == ["Ben was the Chef."]


def test_undertaker_sleeps_without_execution():
    g = make(["imp", "poisoner", "undertaker", "empath", "chef", "soldier", "mayor"])
    to_night2(g)
    g.start_day()
    assert p(g, "Chen").messages[-1]["text"] == "Nothing to report tonight."


def _setup(chars: list[str]) -> Game:
    g = Game(random.Random(1))
    for n in NAMES[:len(chars)]:
        g.add_player(n)
    g.deal()
    for pl, c in zip(g.players, chars):
        g.set_character(pl.pid, c)
    return g


def test_start_refuses_drunk_believing_in_play_character():
    g = _setup(["imp", "poisoner", "fortune_teller", "drunk", "chef", "saint", "mayor"])
    g.set_character(g.players[3].pid, "drunk", believed="fortune_teller")
    with pytest.raises(GameError, match="Fortune Teller is in play"):
        g.start_game()
    assert g.phase == "setup"


def test_start_refuses_duplicate_characters():
    g = _setup(["imp", "poisoner", "fortune_teller", "fortune_teller", "chef", "saint", "mayor"])
    with pytest.raises(GameError, match="only be dealt once"):
        g.start_game()


# --- tap tasks ---

def test_everyone_without_a_choice_gets_a_tap_task():
    g = make(["imp", "poisoner", "fortune_teller", "empath", "chef", "saint", "mayor"])
    kinds = {x.name: x.prompt["kind"] for x in g.players}
    assert kinds == {"Asha": "tap", "Ben": "choose", "Chen": "choose", "Dev": "tap",
                     "Ema": "tap", "Finn": "tap", "Gita": "tap"}
    tap = p(g, "Dev").prompt
    assert tap["target"] in tap["options"] and len(set(tap["options"])) == 3
    assert sorted(tap["target"]) == sorted(tap["options"][0])


def test_tap_needs_the_matching_button():
    g = make(["imp", "poisoner", "fortune_teller", "empath", "chef", "saint", "mayor"])
    dev = p(g, "Dev")
    wrong = next(o for o in dev.prompt["options"] if o != dev.prompt["target"])
    with pytest.raises(GameError):
        g.tap(dev.token, wrong)
    assert g.phones_done() == (0, 7)
    g.tap(dev.token, dev.prompt["target"])
    assert dev.prompt["answer"] == dev.prompt["target"] and g.phones_done() == (1, 7)


def test_second_round_taps_keep_earlier_answers_and_skip_known_dead():
    g = make(["imp", "poisoner", "fortune_teller", "empath", "chef", "saint", "mayor"])
    g.start_day()
    g.kill(p(g, "Finn").pid)
    g.end_day()
    assert p(g, "Finn").prompt is None
    chen = p(g, "Chen")
    g.choose(chen.token, [p(g, "Asha").pid, p(g, "Dev").pid])
    g.resolve(step(g, "imp"), [p(g, "Ema").pid])
    assert chen.prompt["kind"] == "tap"
    assert g.storyteller_view()["steps"][step(g, "fortune_teller")]["answer"] == [p(g, "Asha").pid, p(g, "Dev").pid]
    assert p(g, "Ema").prompt["kind"] == "tap" and p(g, "Finn").prompt is None


def test_unanswered_real_choice_survives_second_round():
    g = make(["imp", "poisoner", "fortune_teller", "empath", "chef", "saint", "mayor"])
    to_night2(g)
    g.resolve(step(g, "imp"), [p(g, "Ema").pid])
    assert p(g, "Chen").prompt["kind"] == "choose"


# --- demon bluffs ---

def dealt(n: int = 7, seed: int = 3) -> Game:
    """A freshly dealt game in setup, not yet started."""
    g = Game(random.Random(seed))
    for name in NAMES[:n]:
        g.add_player(name)
    g.deal()
    return g


def test_dealt_bluffs_are_legal():
    for seed in range(50):
        g = dealt(seed=seed)
        assert g.bluff_problems(g.bluffs) == []


@pytest.mark.parametrize("pick, message", [
    (lambda g, free: [free[0], free[0], free[1]], "different"),
    (lambda g, free: [free[0], free[1], "baron"], "good characters"),
    (lambda g, free: [free[0], free[1], next(p.character for p in g.players if is_good(p.character))], "in play"),
    (lambda g, free: [free[0], free[1], "nobody"], "exactly three"),
    (lambda g, free: free[:2], "exactly three"),
])
def test_illegal_bluffs_rejected(pick, message):
    g = dealt()
    held = {p.character for p in g.players}
    free = [c for c in CHARACTERS if is_good(c) and c not in held]
    with pytest.raises(GameError, match=message):
        g.set_setup(g.red_herring, pick(g, free))


def test_drunk_belief_cannot_be_a_bluff():
    g = dealt()
    g.set_character(g.players[0].pid, "drunk")
    believed = g.players[0].believed
    with pytest.raises(GameError, match="Drunk believes"):
        g.set_setup(g.red_herring, [believed] + [b for b in g.bluffs if b != believed][:2])


def test_start_refuses_bluff_put_in_play_after_saving():
    g = dealt()
    g.set_character(g.players[0].pid, g.bluffs[0])
    assert g.storyteller_view()["bluff_problems"]
    with pytest.raises(GameError, match="must not be in play"):
        g.start_game()


# --- undo ---

def undoable(g: Game, action: str, *args, label: str = "x", **kwargs) -> None:
    """Run a Storyteller action the way the server does: snapshot first, push on success."""
    before = g.snapshot()
    getattr(g, action)(*args, **kwargs)
    g.push_undo(label, before, seen=False)


def test_undo_reverses_a_kill_and_logs_it():
    g = make(["imp", "baron", "chef", "empath", "monk", "saint", "soldier"])
    to_night2(g)
    asha = p(g, "Asha")
    undoable(g, "kill", asha.pid, label="Kill Asha")
    assert not p(g, "Asha").alive
    assert g.undo_info()["label"] == "Kill Asha"
    g.undo()
    assert p(g, "Asha").alive
    assert g.undo_info() is None
    assert g.log[-1].endswith("Storyteller undid: Kill Asha")


def test_undo_with_empty_history_refuses():
    with pytest.raises(GameError, match="Nothing to undo"):
        Game().undo()


def test_undo_keeps_buzz_notes_and_counts_lost_phone_picks():
    g = make(["imp", "baron", "chef", "empath", "monk", "saint", "soldier"])
    buzz = g.buzz
    undoable(g, "start_day")
    g.note_to_storyteller(p(g, "Ben").token, "Is the Saint safe?")
    g.undo()
    assert g.phase == "night"
    assert g.buzz == buzz + 1, "undo must not lower the buzz, or phones would buzz again"
    assert g.inbox[-1]["text"] == "Is the Saint safe?"

    undoable(g, "kill", p(g, "Gita").pid)
    tapper = next(x for x in g.players if x.prompt and x.prompt["kind"] == "tap" and not x.prompt["answer"])
    g.tap(tapper.token, tapper.prompt["target"])
    assert g.undo_info()["phone_picks"] == 1


def test_undo_in_lobby_keeps_players_who_joined_since():
    g = Game(random.Random(1))
    for n in NAMES[:5]:
        g.add_player(n)
    undoable(g, "move_player", g.players[0].pid, 1)
    late = g.add_player("Zed")
    g.undo()
    assert [x.name for x in g.players] == NAMES[:5] + ["Zed"]
    assert g.add_player("Yan").pid != late.pid


def test_undo_history_is_capped():
    g = Game(random.Random(1))
    for n in NAMES[:5]:
        g.add_player(n)
    for _ in range(Game.UNDO_DEPTH + 5):
        undoable(g, "move_player", g.players[0].pid, 1)
    assert g.undo_info()["depth"] == Game.UNDO_DEPTH


def test_night_kill_does_not_move_public_threshold():
    g = make(["imp", "baron", "chef", "empath", "monk", "saint", "soldier"])
    before = g.public_view()["threshold"]
    g.kill(p(g, "Gita").pid)
    assert g.public_view()["threshold"] == before
    g.start_day()
    assert g.public_view()["threshold"] == g.threshold()

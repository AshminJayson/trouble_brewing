"""Truthful information suggestions for night steps.

Every function reads the grimoire and returns the text a player would learn if their ability
worked and nobody misregistered. The Storyteller edits it before sending when the player is
drunk/poisoned or when a Spy/Recluse should register differently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from roles import CHARACTERS, DEMON, MINION, OUTSIDER, TOWNSFOLK, is_good

if TYPE_CHECKING:
    from game import Game, Player


def char_name(character: str) -> str:
    """Display name of a character id."""
    return CHARACTERS[character]["name"]


def char_type(character: str) -> str:
    """Type of a character id (townsfolk / outsider / minion / demon)."""
    return CHARACTERS[character]["type"]


def one_of_two(game: Game, actor: Player, wanted_type: str) -> str:
    """Washerwoman / Librarian / Investigator info.

    Algorithm: pick a random player (not the actor) whose true character has the wanted type, then
    a random decoy who is neither the actor nor that player. Show both in random order with the
    first player's character. If nobody has that type, say so.

    Args:
        game (Game): current game.
        actor (Player): the player receiving the info.
        wanted_type (str): TOWNSFOLK, OUTSIDER or MINION.

    Returns:
        str: message for the player.
    """
    hits = [p for p in game.players if p is not actor and char_type(p.character) == wanted_type]
    if not hits:
        return f"There are no {wanted_type.title()}s in play."
    hit = game.rng.choice(hits)
    decoy = game.rng.choice([p for p in game.players if p not in (actor, hit)])
    pair = [hit, decoy]
    game.rng.shuffle(pair)
    return f"One of {pair[0].name} and {pair[1].name} is the {char_name(hit.character)}."


def evil_pairs(game: Game) -> int:
    """Chef count: adjacent evil seat pairs around the full circle, dead or alive."""
    evil = [not is_good(p.character) for p in game.players]
    n = len(evil)
    return sum(evil[i] and evil[(i + 1) % n] for i in range(n))


def living_neighbours(game: Game, actor: Player) -> list[Player]:
    """Nearest living player clockwise and anticlockwise of the actor (one entry if they coincide)."""
    seats = game.players
    i = seats.index(actor)
    found = []
    for direction in (-1, 1):
        for step in range(1, len(seats)):
            p = seats[(i + direction * step) % len(seats)]
            if p.alive and p is not actor:
                if p not in found:
                    found.append(p)
                break
    return found


def grimoire_text(game: Game) -> str:
    """Spy view: every seat with true character, Drunk's belief, and status markers."""
    lines = []
    for seat, p in enumerate(game.players, 1):
        marks = []
        if p.character != p.believed:
            marks.append(f"thinks {char_name(p.believed)}")
        if not p.alive:
            marks.append("dead")
        if game.poisoned == p.pid:
            marks.append("poisoned")
        if game.red_herring == p.pid:
            marks.append("Fortune Teller red herring")
        suffix = f" ({', '.join(marks)})" if marks else ""
        lines.append(f"{seat}. {p.name}: {char_name(p.character)}{suffix}")
    return "\n".join(lines)


def suggest(game: Game, key: str, actor: Player | None, targets: list[Player]) -> str | None:
    """Truthful info text for a night step, or None for steps that only change state.

    Args:
        game (Game): current game.
        key (str): night step key (a character id, "minion_info" or "demon_info").
        actor (Player | None): the woken player; None for multi-player steps.
        targets (list[Player]): players chosen for this step, in order.

    Returns:
        str | None: message for the player(s).
    """
    if key == "washerwoman":
        return one_of_two(game, actor, TOWNSFOLK)
    if key == "librarian":
        return one_of_two(game, actor, OUTSIDER)
    if key == "investigator":
        return one_of_two(game, actor, MINION)
    if key == "chef":
        return f"There are {evil_pairs(game)} pairs of evil players sitting next to each other."
    if key == "empath":
        evil = sum(not is_good(p.character) for p in living_neighbours(game, actor))
        return f"{evil} of your living neighbours are evil."
    if key == "fortune_teller":
        hit = any(char_type(t.character) == DEMON or t.pid == game.red_herring for t in targets)
        return f"{' and '.join(t.name for t in targets)}: {'YES, one of them is' if hit else 'NO, neither is'} the Demon."
    if key == "undertaker":
        executed = game.get(game.executed_today)
        return f"{executed.name}, executed today, was the {char_name(executed.character)}."
    if key == "ravenkeeper":
        return f"{targets[0].name} is the {char_name(targets[0].character)}."
    if key == "spy":
        return grimoire_text(game)
    if key == "minion_info":
        demon = ", ".join(p.name for p in game.players if char_type(p.character) == DEMON)
        minions = ", ".join(p.name for p in game.players if char_type(p.character) == MINION)
        return f"The Demon is {demon}. The Minions are {minions}."
    if key == "demon_info":
        minions = ", ".join(p.name for p in game.players if char_type(p.character) == MINION)
        bluffs = ", ".join(char_name(b) for b in game.bluffs)
        return f"Your Minions are {minions}. These good characters are not in play (safe bluffs): {bluffs}."
    return None


if __name__ == "__main__":
    import random

    from game import Game

    g = Game(random.Random(7))
    for name in ["Asha", "Ben", "Chen", "Dev", "Ema", "Finn", "Gita", "Hari", "Ines"]:
        g.add_player(name)
    g.deal()
    print(grimoire_text(g))
    print("chef pairs:", evil_pairs(g))
    for p in g.players:
        if p.believed in ("washerwoman", "librarian", "investigator", "empath"):
            print(char_name(p.believed), "->", suggest(g, p.believed, p, []))

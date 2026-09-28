"""Random, rules-valid role dealing for a Trouble Brewing game."""

import random

from roles import CHARACTERS, DEMON, MINION, OUTSIDER, SETUP_COUNTS, TOWNSFOLK, ids_of, is_good


def pick_characters(players: int, rng: random.Random) -> list[str]:
    """Choose which characters are in play for a player count.

    Algorithm: look up the base (townsfolk, outsiders, minions, demons) counts, draw the Minions
    first, and if the Baron was drawn swap two Townsfolk slots for Outsiders. Then draw that many
    Townsfolk and Outsiders without replacement, and add the Imp.

    Args:
        players (int): 5-15.
        rng (random.Random): randomness source.

    Returns:
        list[str]: character ids, one per player, unshuffled.
    """
    if players not in SETUP_COUNTS:
        raise ValueError(f"Trouble Brewing supports 5-15 players, got {players}")
    tf, out, mn, _ = SETUP_COUNTS[players]
    minions = rng.sample(ids_of(MINION), mn)
    if "baron" in minions:
        tf, out = tf - 2, out + 2
    return rng.sample(ids_of(TOWNSFOLK), tf) + rng.sample(ids_of(OUTSIDER), out) + minions + ids_of(DEMON)


def deal(pids: list[str], rng: random.Random) -> dict:
    """Deal characters to players and make the Storyteller's hidden setup choices.

    Algorithm: pick the characters in play and shuffle them onto the players. If the Drunk is in
    play, give them a random Townsfolk that is not in play to believe in. Pick a random good player
    as the Fortune Teller's red herring. Pick three good characters that are not in play, not the
    Drunk's fake role, and not the Drunk itself as the Demon's bluffs.

    Args:
        pids (list[str]): public player ids in seat order.
        rng (random.Random): randomness source.

    Returns:
        dict with keys:
            characters  (dict[str, str]) pid -> true character id
            believed    (dict[str, str]) pid -> character the player is told (differs only for the Drunk)
            red_herring (str) pid
            bluffs      (list[str]) three character ids
    """
    chars = pick_characters(len(pids), rng)
    rng.shuffle(chars)
    characters = dict(zip(pids, chars))
    in_play = set(chars)

    drunk_as = None
    if "drunk" in in_play:
        drunk_as = rng.choice([t for t in ids_of(TOWNSFOLK) if t not in in_play])
    believed = {pid: (drunk_as if c == "drunk" else c) for pid, c in characters.items()}

    red_herring = rng.choice([pid for pid, c in characters.items() if is_good(c)])
    # nobody knowingly claims Drunk, so it is never a useful bluff
    bluff_pool = [c for c in CHARACTERS if is_good(c) and c not in in_play | {drunk_as, "drunk"}]
    return {
        "characters": characters,
        "believed": believed,
        "red_herring": red_herring,
        "bluffs": rng.sample(bluff_pool, 3),
    }


if __name__ == "__main__":
    result = deal([f"p{i}" for i in range(1, 10)], random.Random())
    for pid, c in result["characters"].items():
        shown = result["believed"][pid]
        note = f" (thinks {CHARACTERS[shown]['name']})" if shown != c else ""
        print(f"{pid}: {CHARACTERS[c]['name']}{note}")
    print("red herring:", result["red_herring"])
    print("bluffs:", [CHARACTERS[b]["name"] for b in result["bluffs"]])

"""Trouble Brewing character data, setup table, and night order.

CHARACTERS schema: dict[str, dict] keyed by character id (snake_case), each value:
    name     (str) display name
    type     (str) one of TOWNSFOLK / OUTSIDER / MINION / DEMON
    summary  (str) one-line ability summary
    ability  (str) full ability text shown to the holder

SETUP_COUNTS schema: dict[int, tuple[int, int, int, int]]
    player count -> (townsfolk, outsiders, minions, demons), before the Baron's adjustment.

NIGHT_CHOICES schema: dict[str, tuple[int, bool, str]]
    step key -> (players to choose, may choose self, prompt shown on the player's phone).
"""

TOWNSFOLK, OUTSIDER, MINION, DEMON = "townsfolk", "outsider", "minion", "demon"

CHARACTERS = {
    # --- townsfolk ---
    "washerwoman": {
        "name": "Washerwoman", "type": TOWNSFOLK,
        "summary": "Learns that one of two players is a specific Townsfolk.",
        "ability": "On the first night, you are shown a Townsfolk character, then shown two players. "
                   "One of those two players is that character.",
    },
    "librarian": {
        "name": "Librarian", "type": TOWNSFOLK,
        "summary": "Learns that one of two players is a specific Outsider.",
        "ability": "On the first night, you are shown an Outsider character, then shown two players. "
                   "One of those two players is that character - or, if there are no Outsiders in this "
                   "game, you are told that instead.",
    },
    "investigator": {
        "name": "Investigator", "type": TOWNSFOLK,
        "summary": "Learns that one of two players is a specific Minion.",
        "ability": "On the first night, you are shown a Minion character, then shown two players. "
                   "One of those two players is that character.",
    },
    "chef": {
        "name": "Chef", "type": TOWNSFOLK,
        "summary": "Learns how many pairs of evil players are sitting next to each other.",
        "ability": "On the first night, you learn how many pairs of evil players there are. A pair is two "
                   "evil players seated directly beside one another; three evil players in a row counts "
                   "as two pairs.",
    },
    "empath": {
        "name": "Empath", "type": TOWNSFOLK,
        "summary": "Learns how many of their living neighbours are evil.",
        "ability": "Every night, you learn how many of your two living neighbours are evil. Your neighbours "
                   "are the nearest living players seated to your left and right.",
    },
    "fortune_teller": {
        "name": "Fortune Teller", "type": TOWNSFOLK,
        "summary": "Each night, checks two players for the Demon.",
        "ability": "Every night, choose two players - you learn whether either of them is the Demon. "
                   "One good player always registers as the Demon to you.",
    },
    "undertaker": {
        "name": "Undertaker", "type": TOWNSFOLK,
        "summary": "Learns the character of whoever was executed that day.",
        "ability": "Every night except the first, if a player was executed that day, you learn their character.",
    },
    "monk": {
        "name": "Monk", "type": TOWNSFOLK,
        "summary": "Protects one player from the Demon each night.",
        "ability": "Every night except the first, choose a player other than yourself. They cannot be "
                   "killed by the Demon that night.",
    },
    "ravenkeeper": {
        "name": "Ravenkeeper", "type": TOWNSFOLK,
        "summary": "If killed at night, learns one player's character.",
        "ability": "If you are killed during the night, you wake immediately to choose a player, and you "
                   "learn their character.",
    },
    "virgin": {
        "name": "Virgin", "type": TOWNSFOLK,
        "summary": "The first Townsfolk to nominate them is executed instantly.",
        "ability": "The first time you are nominated, if your nominator is a Townsfolk, they are executed "
                   "immediately. Your ability is spent on that first nomination, whatever the outcome.",
    },
    "slayer": {
        "name": "Slayer", "type": TOWNSFOLK,
        "summary": "Once per game, can publicly attempt to kill the Demon.",
        "ability": "Once per game, during the day, publicly choose a player. If they are the Demon, they die. "
                   "Your ability is spent either way.",
    },
    "soldier": {
        "name": "Soldier", "type": TOWNSFOLK,
        "summary": "Cannot be killed by the Demon.",
        "ability": "You cannot be killed by the Demon. You can still be executed, and killed by other means.",
    },
    "mayor": {
        "name": "Mayor", "type": TOWNSFOLK,
        "summary": "May win the game outright, and may survive the Demon's attack.",
        "ability": "If only three players are alive and no execution happens that day, your team wins. If the "
                   "Demon tries to kill you at night, the Storyteller may choose for a different player to die instead.",
    },
    # --- outsiders ---
    "butler": {
        "name": "Butler", "type": OUTSIDER,
        "summary": "Can only vote when their chosen Master also votes.",
        "ability": "Every night, choose another player to be your Master for the next day. The next day, you may "
                   "only vote on a nomination if your Master also votes on it. You may still nominate freely.",
    },
    "drunk": {
        "name": "Drunk", "type": OUTSIDER,
        "summary": "Believes they're a Townsfolk, but their ability doesn't work.",
        "ability": "You do not know you are the Drunk. You believe you are a specific Townsfolk, but that "
                   "ability does not work, and anything it seems to tell you may be false.",
    },
    "recluse": {
        "name": "Recluse", "type": OUTSIDER,
        "summary": "May appear evil to other players' abilities.",
        "ability": "You may appear evil, and even as a specific Minion or Demon, to other players' abilities, "
                   "even though you are good.",
    },
    "saint": {
        "name": "Saint", "type": OUTSIDER,
        "summary": "If executed, good instantly loses the game.",
        "ability": "If you are executed, your team loses the game immediately. Dying any other way is harmless.",
    },
    # --- minions ---
    "poisoner": {
        "name": "Poisoner", "type": MINION,
        "summary": "Each night, makes one player's ability malfunction.",
        "ability": "Every night, choose a player. Their ability malfunctions for the rest of that night and the "
                   "following day - anything they learn may be false, and they will not be told.",
    },
    "spy": {
        "name": "Spy", "type": MINION,
        "summary": "Sees the full truth of every player, every night.",
        "ability": "Every night, you see the Grimoire. You may also appear as good, and as a specific Townsfolk "
                   "or Outsider, to other players' abilities.",
    },
    "scarlet_woman": {
        "name": "Scarlet Woman", "type": MINION,
        "summary": "May inherit the Demon's power if it dies.",
        "ability": "If the Demon dies while five or more players are alive, you become the new Demon.",
    },
    "baron": {
        "name": "Baron", "type": MINION,
        "summary": "Adds extra Outsiders to the game.",
        "ability": "There are two extra Outsiders in this game, in place of two Townsfolk.",
    },
    # --- demon ---
    "imp": {
        "name": "Imp", "type": DEMON,
        "summary": "Kills a player each night - and can pass on the role.",
        "ability": "Every night except the first, choose a player to kill. You may choose yourself instead - "
                   "if you do, a Minion becomes the new Imp.",
    },
}

SETUP_COUNTS = {
    5: (3, 0, 1, 1), 6: (3, 1, 1, 1), 7: (5, 0, 1, 1), 8: (5, 1, 1, 1), 9: (5, 2, 1, 1),
    10: (7, 0, 2, 1), 11: (7, 1, 2, 1), 12: (7, 2, 2, 1),
    13: (9, 0, 3, 1), 14: (9, 1, 3, 1), 15: (9, 2, 3, 1),
}

# evil info steps only exist in games of this size or larger
EVIL_INFO_MIN_PLAYERS = 7

FIRST_NIGHT = ["minion_info", "demon_info", "poisoner", "washerwoman", "librarian", "investigator",
               "chef", "empath", "fortune_teller", "butler", "spy"]
OTHER_NIGHTS = ["poisoner", "monk", "imp", "ravenkeeper", "empath", "fortune_teller", "undertaker",
                "butler", "spy"]

NIGHT_CHOICES = {
    "poisoner": (1, True, "Choose a player to poison."),
    "monk": (1, False, "Choose a player to protect from the Demon tonight."),
    "imp": (1, True, "Choose a player to kill (choosing yourself passes the Imp to a Minion)."),
    "ravenkeeper": (1, True, "You died tonight. Choose a player to learn their character."),
    "fortune_teller": (2, True, "Choose two players to check for the Demon."),
    "butler": (1, False, "Choose your Master for tomorrow."),
}


def ids_of(char_type: str) -> list[str]:
    """Character ids of one type (TOWNSFOLK / OUTSIDER / MINION / DEMON), in almanac order."""
    return [cid for cid, c in CHARACTERS.items() if c["type"] == char_type]


def is_good(character: str) -> bool:
    """True for Townsfolk and Outsiders."""
    return CHARACTERS[character]["type"] in (TOWNSFOLK, OUTSIDER)


def expected_counts(players: int, baron: bool) -> tuple[int, int, int, int]:
    """(townsfolk, outsiders, minions, demons) for a player count, after the Baron's +2/-2 swap."""
    tf, out, mn, dm = SETUP_COUNTS[players]
    return (tf - 2, out + 2, mn, dm) if baron else (tf, out, mn, dm)


if __name__ == "__main__":
    for t in (TOWNSFOLK, OUTSIDER, MINION, DEMON):
        print(f"{t:10} {', '.join(CHARACTERS[c]['name'] for c in ids_of(t))}")
    print("9 players:", expected_counts(9, baron=False), "with Baron:", expected_counts(9, baron=True))

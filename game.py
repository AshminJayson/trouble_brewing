"""Trouble Brewing game state and rules: seating, setup, night steps, nominations, deaths, wins.

Every public method is either a Storyteller action (called with pids) or a player action (called
with the player's secret token). Invalid actions raise GameError with a message for the user.
"""

from __future__ import annotations

import math
import random
import secrets
from dataclasses import dataclass, field

import dealing
import info
from roles import (CHARACTERS, DEMON, EVIL_INFO_MIN_PLAYERS, FIRST_NIGHT, MINION, NIGHT_CHOICES,
                   OTHER_NIGHTS, OUTSIDER, SETUP_COUNTS, TOWNSFOLK, expected_counts, is_good)


class GameError(Exception):
    """Invalid action; the message is shown to whoever attempted it."""


@dataclass
class Player:
    """One seat at the table.

    pid is public (used by everyone to refer to the player); token is secret (the player's login).
    messages schema: list of {"label": str, "text": str}.
    prompt schema, one of (or None):
        real choice: {"kind": "choose", "text": str, "count": int, "allow_self": bool,
                      "answer": list[str] | None, "step": int (index into Game.steps)}
        tap task:    {"kind": "tap", "text": str, "target": str, "options": list[str] (3),
                      "answer": str | None, "step": None}
    """
    pid: str
    token: str
    name: str
    character: str | None = None
    believed: str | None = None
    alive: bool = True
    ghost_vote: bool = True
    messages: list[dict] = field(default_factory=list)
    prompt: dict | None = None


class Game:
    """Single game in memory. Seat order is the order of self.players."""

    def __init__(self, rng: random.Random | None = None):
        """Empty lobby. rng is injectable for reproducible games."""
        self.rng = rng or random.Random()
        self.players: list[Player] = []
        self.version = 0
        self._next_pid = 1
        self._reset_round()

    def _reset_round(self) -> None:
        """Clear everything except the seated players."""
        self.phase = "lobby"  # lobby | setup | night | day | over
        self.night = 0
        self.day = 0
        self.red_herring: str | None = None
        self.bluffs: list[str] = []
        self.counts: dict[str, int] = {}
        self.poisoned: str | None = None
        self.protected: str | None = None
        self.master: str | None = None
        self.virgin_spent = False
        self.slayer_spent = False
        self.executed_today: str | None = None
        self.night_deaths: list[str] = []
        self.steps: list[dict] = []
        self.nominations: list[dict] = []
        self.announcements: list[str] = []
        self.winner: str | None = None
        self.win_reason = ""
        self.log: list[str] = []
        # every phone vibrates when this rises, so a buzz never singles anyone out
        self.buzz = 0
        # pid -> private texts held until the next table-wide buzz
        self.queued: dict[str, list[str]] = {}
        self.second_round_done = False
        # notes from players to the Storyteller: [{"pid", "text", "label", "read"}]
        self.inbox: list[dict] = []
        for p in self.players:
            p.character = p.believed = None
            p.alive, p.ghost_vote, p.messages, p.prompt = True, True, [], None

    # --- lookups ---

    def get(self, pid: str | None) -> Player:
        """Player by public id."""
        for p in self.players:
            if p.pid == pid:
                return p
        raise GameError(f"No player {pid!r}")

    def by_token(self, token: str) -> Player:
        """Player by secret token."""
        for p in self.players:
            if p.token == token:
                return p
        raise GameError("Unknown player - please join again")

    def alive_count(self) -> int:
        """Number of living players."""
        return sum(p.alive for p in self.players)

    def threshold(self) -> int:
        """Votes needed to put a nominee up for execution: half the living, rounded up."""
        return math.ceil(self.alive_count() / 2)

    def impaired(self, p: Player) -> bool:
        """True if the player's ability does not work: they are the Drunk or currently poisoned."""
        return p.character == "drunk" or self.poisoned == p.pid

    def _working(self, p: Player, character: str) -> bool:
        """True if p is alive, truly holds character, and is not poisoned."""
        return p.alive and p.character == character and not self.impaired(p)

    def _alive_demon(self) -> Player | None:
        """The living Demon, if any."""
        return next((p for p in self.players if p.alive and CHARACTERS[p.character]["type"] == DEMON), None)

    def _type_of(self, p: Player) -> str:
        return CHARACTERS[p.character]["type"]

    def _require(self, *phases: str) -> None:
        if self.phase not in phases:
            raise GameError(f"Not allowed during {self.phase}")

    def _log(self, text: str) -> None:
        self.log.append(f"[{self._stamp()}] {text}")

    def _stamp(self) -> str:
        return f"Night {self.night}" if self.phase == "night" else f"Day {self.day}" if self.phase == "day" else self.phase

    def _announce(self, text: str) -> None:
        self.announcements.append(text)
        self._log(text)

    # --- lobby ---

    def add_player(self, name: str) -> Player:
        """Seat a new player at the end of the circle (lobby only). Returns the player incl. token."""
        self._require("lobby")
        name = name.strip()
        if not name:
            raise GameError("Name required")
        if any(p.name.lower() == name.lower() for p in self.players):
            raise GameError(f"{name} is already taken")
        if len(self.players) >= max(SETUP_COUNTS):
            raise GameError("Table is full")
        p = Player(pid=f"p{self._next_pid}", token=secrets.token_urlsafe(12), name=name)
        self._next_pid += 1
        self.players.append(p)
        return p

    def remove_player(self, pid: str) -> None:
        """Remove a player from the lobby."""
        self._require("lobby")
        self.players.remove(self.get(pid))

    def move_player(self, pid: str, delta: int) -> None:
        """Shift a player's seat by delta (lobby/setup), to match the real seating circle."""
        self._require("lobby", "setup")
        p = self.get(pid)
        i = self.players.index(p)
        j = max(0, min(len(self.players) - 1, i + delta))
        self.players.insert(j, self.players.pop(i))

    # --- setup ---

    def deal(self) -> None:
        """Randomly deal a valid setup to the seated players (lobby or re-deal during setup)."""
        self._require("lobby", "setup")
        if len(self.players) not in SETUP_COUNTS:
            raise GameError("Trouble Brewing needs 5-15 players")
        result = dealing.deal([p.pid for p in self.players], self.rng)
        for p in self.players:
            p.character = result["characters"][p.pid]
            p.believed = result["believed"][p.pid]
        self.red_herring = result["red_herring"]
        self.bluffs = result["bluffs"]
        self.phase = "setup"

    def set_character(self, pid: str, character: str, believed: str | None = None) -> None:
        """Storyteller override of a player's character (any time before the game ends).

        For the Drunk, believed must be a Townsfolk; it defaults to a random Townsfolk not in play.
        For everyone else, believed always equals character.
        """
        self._require("setup", "night", "day")
        if character not in CHARACTERS:
            raise GameError(f"Unknown character {character!r}")
        p = self.get(pid)
        if character == "drunk":
            in_play = {q.character for q in self.players}
            believed = believed or self.rng.choice(
                [c for c in CHARACTERS if CHARACTERS[c]["type"] == TOWNSFOLK and c not in in_play])
            if CHARACTERS[believed]["type"] != TOWNSFOLK:
                raise GameError("The Drunk must believe they are a Townsfolk")
        else:
            believed = character
        p.character, p.believed = character, believed
        if self.phase != "setup":
            self._log(f"Storyteller set {p.name} to {info.char_name(character)}")

    def set_setup(self, red_herring: str, bluffs: list[str]) -> None:
        """Set the Fortune Teller red herring (a pid) and the Demon's three bluffs (character ids)."""
        self._require("setup")
        self.get(red_herring)
        if len(bluffs) != 3 or any(b not in CHARACTERS for b in bluffs):
            raise GameError("Pick exactly three bluff characters")
        self.red_herring, self.bluffs = red_herring, bluffs

    def setup_warnings(self) -> list[str]:
        """Soft problems with the current setup; the Storyteller may start anyway."""
        if self.phase != "setup":
            return []
        chars = [p.character for p in self.players]
        warnings = []
        counts = tuple(sum(CHARACTERS[c]["type"] == t for c in chars) for t in (TOWNSFOLK, OUTSIDER, MINION, DEMON))
        want = expected_counts(len(chars), "baron" in chars)
        if counts != want:
            warnings.append(f"Counts (townsfolk, outsiders, minions, demons) are {counts}; rules say {want}")
        dupes = {c for c in chars if chars.count(c) > 1}
        if dupes:
            warnings.append("Duplicate characters: " + ", ".join(info.char_name(c) for c in dupes))
        if any(b in chars for b in self.bluffs):
            warnings.append("A Demon bluff is actually in play")
        drunk = next((p for p in self.players if p.character == "drunk"), None)
        if drunk and drunk.believed in chars:
            warnings.append("The Drunk believes they are a character that is in play")
        if self.red_herring and not is_good(self.get(self.red_herring).character):
            warnings.append("The red herring should be a good player")
        return warnings

    def start_game(self) -> None:
        """Lock the setup, publish type counts, and begin the first night.

        Refuses duplicate characters, counting the Drunk's believed character: two holders of one
        character would share a single night step, so only one of them would ever be prompted.
        """
        self._require("setup")
        if not any(CHARACTERS[p.character]["type"] == DEMON for p in self.players):
            raise GameError("There must be a Demon")
        chars = [p.character for p in self.players]
        dupes = sorted({info.char_name(c) for c in chars if chars.count(c) > 1})
        if dupes:
            raise GameError(f"Each character can only be dealt once: {', '.join(dupes)}")
        drunk = next((p for p in self.players if p.character == "drunk"), None)
        if drunk and drunk.believed in chars:
            raise GameError(f"The Drunk must believe they are a Townsfolk not in play, "
                            f"and the {info.char_name(drunk.believed)} is in play")
        self.counts = {t: sum(CHARACTERS[p.character]["type"] == t for p in self.players)
                       for t in (TOWNSFOLK, OUTSIDER, MINION, DEMON)}
        self._log("Game started: " + ", ".join(f"{p.name}={info.char_name(p.character)}" for p in self.players))
        self.start_night()

    # --- night ---

    def start_night(self) -> None:
        """Begin the next night with every phone buzzing at once.

        Algorithm: expire poison, protection and Master; build the night order; push each living
        chooser's prompt (except the Ravenkeeper, who waits for the second round); deliver anything
        held since the day (e.g. a Scarlet Woman who became the Imp); buzz every phone.
        """
        self._require("setup", "day")
        self.phase = "night"
        self.night += 1
        self.poisoned = self.protected = self.master = None
        self.night_deaths = []
        self.second_round_done = False
        for p in self.players:
            p.prompt = None
        self.steps = self._build_steps()
        for i, s in enumerate(self.steps):
            if s["choose"] and s["key"] != "ravenkeeper" and self.step_applies(s):
                self.ask(i)
        self._hand_out_tap_tasks()
        self._log("Night falls")
        self._flush()
        self.buzz += 1

    def second_round(self) -> None:
        """Buzz every phone again (nights 2+); the Ravenkeeper gets their prompt only if killed tonight.

        Runs every night regardless, so the second buzz never reveals that a Ravenkeeper died.
        """
        self._require("night")
        if self.second_round_done:
            return
        self.second_round_done = True
        for i, s in enumerate(self.steps):
            if s["key"] == "ravenkeeper" and self.step_applies(s):
                self.ask(i)
        self._hand_out_tap_tasks()
        self.buzz += 1
        self._log("Second round: every phone buzzes")

    def _hand_out_tap_tasks(self) -> None:
        """Give a tap task to every publicly alive player not busy with an unanswered real choice.

        Algorithm: pick three distinct letters, take their six orderings, and offer the target plus
        two other orderings in random order. Tonight's victims count as alive so they tap like
        everyone else; players known dead since an earlier day are left alone.
        """
        letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
        for p in self.players:
            if not self._publicly_alive(p):
                continue
            if p.prompt and p.prompt["kind"] == "choose" and p.prompt["answer"] is None:
                continue
            a, b, c = self.rng.sample(letters, 3)
            orders = [a + b + c, a + c + b, b + a + c, b + c + a, c + a + b, c + b + a]
            target = self.rng.choice(orders)
            options = [target] + self.rng.sample([o for o in orders if o != target], 2)
            self.rng.shuffle(options)
            p.prompt = {"kind": "tap", "text": f"Tap the button that says {target}.", "target": target,
                        "options": options, "answer": None, "step": None}

    def phones_done(self) -> tuple[int, int]:
        """(publicly alive players whose phone has nothing left to tap, publicly alive players)."""
        alive = [p for p in self.players if self._publicly_alive(p)]
        return sum(not p.prompt or p.prompt["answer"] is not None for p in alive), len(alive)

    def _notify(self, pid: str, text: str) -> None:
        """Hold a private text for the next table-wide buzz."""
        self.queued.setdefault(pid, []).append(text)

    def _flush(self, filler: str | None = None) -> None:
        """Deliver held texts; with filler, every player without one gets filler instead."""
        for p in self.players:
            texts = self.queued.pop(p.pid, []) or ([filler] if filler else [])
            for text in texts:
                p.messages.append({"label": self._stamp(), "text": text})

    def _build_steps(self) -> list[dict]:
        """Night order for this night, limited to characters that are in play.

        Step schema: {"key": str, "pids": list[str], "choose": int, "allow_self": bool,
                      "prompt": str, "choices": list[str], "answer": list[str] | None (phone pick),
                      "suggestion": str | None,
                      "sent": str | None (text held for dawn), "done": bool}
        """
        steps = []
        for key in FIRST_NIGHT if self.night == 1 else OTHER_NIGHTS:
            if key in ("minion_info", "demon_info"):
                if len(self.players) < EVIL_INFO_MIN_PLAYERS:
                    continue
                wanted = MINION if key == "minion_info" else DEMON
                pids = [p.pid for p in self.players if CHARACTERS[p.character]["type"] == wanted]
            else:
                # living only: a dead Imp still holds the token after the Scarlet Woman or a star-pass takes over
                pids = [p.pid for p in self.players if p.believed == key and p.alive]
            if not pids:
                continue
            count, allow_self, prompt = NIGHT_CHOICES.get(key, (0, True, ""))
            steps.append({"key": key, "pids": pids, "choose": count, "allow_self": allow_self, "prompt": prompt,
                          "choices": [], "answer": None, "suggestion": None, "sent": None, "done": False})
        return steps

    def _step(self, index: int) -> dict:
        self._require("night")
        if not 0 <= index < len(self.steps):
            raise GameError("No such step")
        return self.steps[index]

    def step_applies(self, step: dict) -> bool:
        """Whether a step's player should be woken now (alive, or Ravenkeeper killed tonight)."""
        if step["key"] == "ravenkeeper":
            return step["pids"][0] in self.night_deaths
        if step["key"] == "undertaker" and not self.executed_today:
            return False
        return all(self.get(pid).alive for pid in step["pids"])

    def ask(self, step: int) -> None:
        """Push a step's choice prompt to the woken player's phone."""
        s = self._step(step)
        if not s["choose"]:
            raise GameError("This step has no choice to make")
        self.get(s["pids"][0]).prompt = {"kind": "choose", "text": s["prompt"], "count": s["choose"],
                                         "allow_self": s["allow_self"], "answer": None, "step": step}
        s["answer"] = None

    def resolve(self, step: int, choices: list[str], redirect: str | None = None,
                new_demon: str | None = None) -> None:
        """Apply a step's effect and compute the truthful info suggestion.

        Algorithm: validate the chosen pids against the step's choice count; apply the effect
        (Poisoner poisons, Monk protects if working, Butler sets Master, Imp attacks); then
        store the info suggestion. Steps with no info to give are marked done.

        Args:
            step (int): index into self.steps.
            choices (list[str]): chosen pids, in order.
            redirect (str | None): Imp only - pid that dies instead when the Mayor is attacked.
            new_demon (str | None): Imp only - Minion pid who becomes the Imp on a self-kill.
        """
        s = self._step(step)
        if len(choices) != s["choose"]:
            raise GameError(f"Choose exactly {s['choose']} player(s)")
        targets = [self.get(c) for c in choices]
        actor = self.get(s["pids"][0])
        if not s["allow_self"] and actor in targets:
            raise GameError("This character cannot choose themselves")
        key = s["key"]
        if key == "poisoner":
            self.poisoned = targets[0].pid
            self._log(f"Poisoner poisons {targets[0].name}")
        elif key == "monk":
            self.protected = None if self.impaired(actor) else targets[0].pid
            self._log(f"Monk protects {targets[0].name}{' (no effect: impaired)' if self.impaired(actor) else ''}")
        elif key == "butler":
            self.master = targets[0].pid
            self._log(f"Butler chooses {targets[0].name} as Master")
        elif key == "imp":
            self._demon_attack(actor, targets[0], redirect, new_demon)
            if self.phase == "night":
                self.second_round()
        s["choices"] = choices
        s["suggestion"] = info.suggest(self, key, actor if len(s["pids"]) == 1 else None, targets)
        if s["suggestion"] is None:
            s["done"] = True
            self._close_prompt(actor, step)

    def _demon_attack(self, imp: Player, target: Player, redirect: str | None, new_demon: str | None) -> None:
        """Imp kill: poisoned Imp fails; self-target star-passes; Monk, Soldier and Mayor may save."""
        if self.impaired(imp):
            self._log(f"Imp attacks {target.name}: no effect, Imp is poisoned")
            return
        if target is imp:
            self._star_pass(imp, new_demon)
            return
        if redirect:
            if not self._working(target, "mayor"):
                raise GameError("Only an attack on a working Mayor can be redirected")
            self._log(f"Imp attacks the Mayor; Storyteller redirects to {self.get(redirect).name}")
            target = self.get(redirect)
        if self.protected == target.pid:
            self._log(f"Imp attacks {target.name}: saved by the Monk")
        elif self._working(target, "soldier"):
            self._log(f"Imp attacks {target.name}: the Soldier survives")
        elif not target.alive:
            self._log(f"Imp attacks {target.name}: already dead")
        else:
            self.night_deaths.append(target.pid)
            self._die(target, "killed by the Demon")

    def _star_pass(self, imp: Player, new_demon: str | None) -> None:
        """Imp kills themselves: a living Minion (Scarlet Woman preferred) becomes the Imp."""
        minions = [p for p in self.players if p.alive and self._type_of(p) == MINION]
        heir = self.get(new_demon) if new_demon else (
            next((p for p in minions if p.character == "scarlet_woman"), None)
            or (self.rng.choice(minions) if minions else None))
        if heir and heir not in minions:
            raise GameError("The new Imp must be a living Minion")
        if heir:
            self._promote(heir, f"{imp.name} killed themselves")
        self.night_deaths.append(imp.pid)
        self._die(imp, "killed themselves as the Imp")

    def _promote(self, heir: Player, why: str) -> None:
        heir.character = heir.believed = "imp"
        self._notify(heir.pid, "You are now the Imp.")
        self._log(f"{heir.name} becomes the Imp ({why})")

    def _close_prompt(self, p: Player, step: int) -> None:
        """Clear p's prompt only if it belongs to this step (a Minion may hold their own prompt)."""
        if p.prompt and p.prompt.get("step") == step:
            p.prompt = None

    def send(self, step: int, text: str) -> None:
        """Hold info text for every player in a step until dawn, and mark the step done."""
        s = self._step(step)
        if not text.strip():
            raise GameError("Message is empty")
        for pid in s["pids"]:
            self._notify(pid, text.strip())
            self._close_prompt(self.get(pid), step)
        s["sent"] = text.strip()
        s["done"] = True
        self._log(f"For {', '.join(self.get(pid).name for pid in s['pids'])} at dawn: {text.strip()}")

    def finish_step(self, step: int, done: bool = True) -> None:
        """Mark a step done (e.g. skipped) or reopen it."""
        self._step(step)["done"] = done

    # --- messages and player actions ---

    def message(self, pid: str, text: str, now: bool = False) -> None:
        """Private message to one player: held until dawn at night unless now, delivered at once by day.

        Delivery never vibrates the phone (only table-wide buzzes do), so now is safe for rules answers.
        """
        p = self.get(pid)
        if not text.strip():
            raise GameError("Message is empty")
        if self.phase == "night" and not now:
            self._notify(pid, text.strip())
            self._log(f"For {p.name} at dawn: {text.strip()}")
        else:
            p.messages.append({"label": self._stamp(), "text": text.strip()})
            self._log(f"To {p.name}: {text.strip()}")

    def choose(self, token: str, choices: list[str]) -> None:
        """Player answers their current prompt with a list of pids."""
        p = self.by_token(token)
        if not p.prompt or p.prompt["kind"] != "choose":
            raise GameError("Nothing to choose right now")
        if len(choices) != p.prompt["count"] or len(set(choices)) != len(choices):
            raise GameError(f"Choose exactly {p.prompt['count']} different player(s)")
        for c in choices:
            self.get(c)
        if not p.prompt["allow_self"] and p.pid in choices:
            raise GameError("You cannot choose yourself")
        p.prompt["answer"] = choices
        if p.prompt["step"] is not None:
            self.steps[p.prompt["step"]]["answer"] = choices

    def tap(self, token: str, option: str) -> None:
        """Player completes their tap task by pressing the button matching the target."""
        p = self.by_token(token)
        if not p.prompt or p.prompt["kind"] != "tap":
            raise GameError("Nothing to tap right now")
        if option != p.prompt["target"]:
            raise GameError(f"That one says {option}. Tap {p.prompt['target']}.")
        p.prompt["answer"] = option

    def note_to_storyteller(self, token: str, text: str) -> None:
        """Player sends a private note to the Storyteller (any phase, alive or dead)."""
        p = self.by_token(token)
        text = text.strip()
        if not text:
            raise GameError("Write something first")
        if len(text) > 500:
            raise GameError("Keep it under 500 characters")
        self.inbox.append({"pid": p.pid, "text": text, "label": self._stamp(), "read": False})
        self._log(f"Note from {p.name}: {text}")

    def read_inbox(self) -> None:
        """Storyteller marks every note as read."""
        for note in self.inbox:
            note["read"] = True

    # --- day ---

    def start_day(self) -> None:
        """Dawn: every player gets their held info (or a blank slip), every phone buzzes, nominations open.

        An Undertaker step the Storyteller did not send is worked out and sent automatically first.
        """
        self._require("night")
        self._auto_undertaker()
        self._flush(filler="Nothing to report tonight.")
        self.buzz += 1
        self.phase = "day"
        self.day += 1
        self.nominations = []
        self.announcements = []
        self.executed_today = None
        for p in self.players:
            p.prompt = None
        dead = [self.get(pid).name for pid in self.night_deaths]
        self._announce(f"Dawn. {' and '.join(dead) + ' died' if dead else 'Nobody died'} in the night.")

    def _auto_undertaker(self) -> None:
        """Hold the truthful Undertaker info for dawn unless the Storyteller already sent or skipped it."""
        for s in self.steps:
            if s["key"] != "undertaker" or s["done"] or not self.step_applies(s):
                continue
            actor = self.get(s["pids"][0])
            text = info.suggest(self, "undertaker", actor, [])
            self._notify(actor.pid, text)
            s["suggestion"], s["sent"], s["done"] = text, text, True
            impaired = " (sent true info although they are drunk or poisoned)" if self.impaired(actor) else ""
            self._log(f"Undertaker info sent automatically to {actor.name}: {text}{impaired}")

    def nominate(self, nominator: str, nominee: str, spy_as_townsfolk: bool = False) -> None:
        """Record a nomination; triggers the Virgin on their first nomination.

        Args:
            nominator (str): pid, must be alive and not have nominated today.
            nominee (str): pid, must be alive and not have been nominated today.
            spy_as_townsfolk (bool): if the nominator is the Spy, whether they register as Townsfolk.
        """
        self._require("day")
        if self.executed_today:
            raise GameError("There has already been an execution today")
        a, b = self.get(nominator), self.get(nominee)
        if not a.alive or not b.alive:
            raise GameError("Only living players nominate and can be nominated")
        if any(n["nominator"] == a.pid for n in self.nominations):
            raise GameError(f"{a.name} has already nominated today")
        if any(n["nominee"] == b.pid for n in self.nominations):
            raise GameError(f"{b.name} has already been nominated today")
        self.nominations.append({"nominator": a.pid, "nominee": b.pid, "voters": [], "votes": None})
        self._announce(f"{a.name} nominates {b.name}.")
        if b.character == "virgin" and not self.virgin_spent:
            self.virgin_spent = True
            townsfolk = self._type_of(a) == TOWNSFOLK or (a.character == "spy" and spy_as_townsfolk)
            if townsfolk and not self.impaired(b):
                self._execute(a)

    def record_votes(self, nomination: int, voters: list[str]) -> None:
        """Set who voted on a nomination; dead voters spend their one ghost vote (refunded on re-record)."""
        self._require("day")
        if not 0 <= nomination < len(self.nominations):
            raise GameError("No such nomination")
        n = self.nominations[nomination]
        previous = set(n["voters"])
        for pid in voters:
            p = self.get(pid)
            if not p.alive and not p.ghost_vote and pid not in previous:
                raise GameError(f"{p.name} is dead and has used their vote")
        for pid in previous:
            if not self.get(pid).alive:
                self.get(pid).ghost_vote = True
        for pid in voters:
            if not self.get(pid).alive:
                self.get(pid).ghost_vote = False
        n["voters"], n["votes"] = list(voters), len(voters)
        self._announce(f"{len(voters)} vote(s) to execute {self.get(n['nominee']).name} "
                       f"(needs {self.threshold()}).")

    def slayer_shot(self, shooter: str, target: str, recluse_as_demon: bool = False) -> None:
        """Public Slayer claim: kills the target only if shooter is a working, unspent Slayer and target is the Demon."""
        self._require("day")
        s, t = self.get(shooter), self.get(target)
        self._announce(f"{s.name} claims Slayer and shoots {t.name}.")
        hit = False
        if s.alive and s.character == "slayer" and not self.slayer_spent:
            self.slayer_spent = True
            is_demon = self._type_of(t) == DEMON or (t.character == "recluse" and recluse_as_demon)
            hit = not self.impaired(s) and is_demon and t.alive
        if hit:
            self._announce(f"{t.name} dies.")
            self._die(t, "shot by the Slayer")
        else:
            self._announce("Nothing happens.")

    def end_day(self) -> None:
        """Dusk: execute the unique top nominee at or above threshold, check the Mayor, then start the night."""
        self._require("day")
        if not self.executed_today:
            t = self.threshold()
            eligible = [n for n in self.nominations if n["votes"] is not None and n["votes"] >= t]
            if eligible:
                top = max(n["votes"] for n in eligible)
                leaders = [n for n in eligible if n["votes"] == top]
                if len(leaders) == 1:
                    self._execute(self.get(leaders[0]["nominee"]))
                else:
                    self._announce("Tied vote: nobody is executed.")
            else:
                self._announce("Nobody is executed.")
        if not self.winner and not self.executed_today and self.alive_count() == 3 \
                and any(self._working(p, "mayor") for p in self.players):
            self._win("good", "Three players remain with no execution, and the Mayor lives.")
        if not self.winner:
            self.start_night()

    def _execute(self, p: Player) -> None:
        """Execute a player; a working Saint loses the game for good."""
        self.executed_today = p.pid
        self._announce(f"{p.name} is executed.")
        if self._working(p, "saint"):
            self._win("evil", "The Saint was executed.")
        self._die(p, "executed")

    # --- deaths and wins ---

    def _die(self, p: Player, cause: str) -> None:
        """Kill a player: ends Poisoner's poison, may promote the Scarlet Woman, then checks for a win."""
        if not p.alive:
            return
        alive_before = self.alive_count()
        p.alive = False
        self._log(f"{p.name} ({info.char_name(p.character)}) dies: {cause}")
        if p.character == "poisoner":
            self.poisoned = None
        if self._type_of(p) == DEMON and not self._alive_demon() and alive_before >= 5:
            sw = next((q for q in self.players if self._working(q, "scarlet_woman")), None)
            if sw:
                self._promote(sw, "the Demon died")
        self._check_win()

    def _check_win(self) -> None:
        if self.winner:
            return
        if not self._alive_demon():
            self._win("good", "The Demon is dead.")
        elif self.alive_count() <= 2:
            self._win("evil", "Only two players remain and the Demon is one of them.")

    def _win(self, team: str, reason: str) -> None:
        self.winner, self.win_reason, self.phase = team, reason, "over"
        self._log(f"{team.upper()} WINS: {reason}")

    # --- storyteller overrides ---

    def kill(self, pid: str) -> None:
        """Storyteller kills a player directly (win checks still apply)."""
        self._require("night", "day")
        p = self.get(pid)
        if self.phase == "night" and p.alive:
            self.night_deaths.append(pid)
        self._die(p, "Storyteller")

    def revive(self, pid: str) -> None:
        """Storyteller undoes a death."""
        self._require("night", "day")
        p = self.get(pid)
        p.alive = True
        if pid in self.night_deaths:
            self.night_deaths.remove(pid)
        self._log(f"Storyteller revives {p.name}")

    def set_poisoned(self, pid: str | None) -> None:
        """Storyteller sets or clears the poisoned player."""
        self._require("night", "day")
        self.poisoned = pid and self.get(pid).pid
        self._log(f"Storyteller sets poisoned: {self.get(pid).name if pid else 'nobody'}")

    def set_ghost_vote(self, pid: str, value: bool) -> None:
        """Storyteller sets whether a dead player still has their vote."""
        self.get(pid).ghost_vote = value

    def declare_winner(self, team: str) -> None:
        """Storyteller ends the game."""
        if team not in ("good", "evil"):
            raise GameError("Team must be good or evil")
        self._win(team, "Declared by the Storyteller.")

    def reset(self) -> None:
        """Back to the lobby with the same seated players."""
        self._reset_round()

    # --- views ---

    def public_view(self) -> dict:
        """What every player may see. Characters are revealed only once the game is over.

        Schema: {version, phase, night, day, counts: {type: int}, threshold, buzz,
                 seats: [{pid, name, alive, ghost_vote, character|None}],
                 announcements: [str], nominations: [{nominator, nominee, votes}],
                 winner: str|None, win_reason: str}
        Tonight's deaths stay hidden (seat still alive) until dawn is announced.
        """
        over = self.phase == "over"
        return {
            "version": self.version, "phase": self.phase, "night": self.night, "day": self.day,
            "counts": self.counts, "threshold": self.threshold(), "buzz": self.buzz,
            "seats": [{"pid": p.pid, "name": p.name, "alive": self._publicly_alive(p), "ghost_vote": p.ghost_vote,
                       "character": p.character if over else None} for p in self.players],
            "announcements": self.announcements,
            "nominations": [{"nominator": self.get(n["nominator"]).name, "nominee": self.get(n["nominee"]).name,
                             "votes": n["votes"]} for n in self.nominations],
            "winner": self.winner, "win_reason": self.win_reason,
        }

    def _publicly_alive(self, p: Player) -> bool:
        """Alive as the table knows it: a player killed tonight still looks alive until dawn."""
        return p.alive or (self.phase == "night" and p.pid in self.night_deaths)

    def player_view(self, token: str) -> dict:
        """Public view plus the player's own role (as they believe it), messages and prompt."""
        p = self.by_token(token)
        started = self.phase in ("night", "day", "over")
        return {**self.public_view(), "me": {
            "pid": p.pid, "name": p.name, "alive": self._publicly_alive(p),
            "role": {"id": p.believed, **CHARACTERS[p.believed]} if started and p.believed else None,
            "messages": p.messages, "prompt": p.prompt,
            "notes": [{"text": n["text"], "label": n["label"]} for n in self.inbox if n["pid"] == p.pid],
        }}

    def storyteller_view(self) -> dict:
        """Everything: grimoire, hidden setup choices, night steps with live answers, warnings, log.

        Extra keys over public_view: players [{pid, name, character, believed, alive, ghost_vote,
        impaired, answer}], red_herring, bluffs, poisoned, protected, master, virgin_spent,
        slayer_spent, executed_today, night_deaths, steps (with applies / impaired / answer added),
        nominations_full, queued {pid: [text]}, second_round_done, inbox [{pid, text, label, read}],
        phones_done [done, total],
        warnings, log.
        """
        steps = []
        for i, s in enumerate(self.steps):
            actor = self.get(s["pids"][0])
            asked = bool(actor.prompt and actor.prompt.get("step") == i)
            steps.append({**s, "applies": self.step_applies(s), "impaired": self.impaired(actor), "asked": asked})
        return {
            **self.public_view(),
            "players": [{"pid": p.pid, "name": p.name, "character": p.character, "believed": p.believed,
                         "alive": p.alive, "ghost_vote": p.ghost_vote,
                         "impaired": bool(p.character) and self.impaired(p)} for p in self.players],
            "red_herring": self.red_herring, "bluffs": self.bluffs, "poisoned": self.poisoned,
            "protected": self.protected, "master": self.master, "virgin_spent": self.virgin_spent,
            "slayer_spent": self.slayer_spent, "executed_today": self.executed_today,
            "night_deaths": self.night_deaths, "steps": steps, "nominations_full": self.nominations,
            "queued": {pid: texts for pid, texts in self.queued.items()}, "second_round_done": self.second_round_done,
            "inbox": self.inbox, "phones_done": list(self.phones_done()),
            "warnings": self.setup_warnings(), "log": self.log,
        }


if __name__ == "__main__":
    g = Game(random.Random(3))
    for name in ["Asha", "Ben", "Chen", "Dev", "Ema", "Finn", "Gita", "Hari", "Ines"]:
        g.add_player(name)
    g.deal()
    print("warnings:", g.setup_warnings())
    g.start_game()
    for i, s in enumerate(g.steps):
        picks = [p.pid for p in g.players if s["allow_self"] or p.pid != s["pids"][0]][:s["choose"]]
        g.resolve(i, picks)
        print(f"{s['key']:15} -> {s['suggestion']}")
    g.start_day()
    g.nominate(g.players[0].pid, g.players[1].pid)
    g.record_votes(0, [p.pid for p in g.players[:6]])
    g.end_day()
    print("\n".join(g.log))

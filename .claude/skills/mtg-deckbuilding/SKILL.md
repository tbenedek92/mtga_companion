---
name: mtg-deckbuilding
description: Deckbuilding principles for MTG Arena Standard (60-card, 1v1, 20 life), translated from multiplayer Commander advice. Use whenever building, evaluating, cutting, or diagnosing a Standard deck — card selection, mana curve, land counts, category budgets, sideboarding, or checking whether a deck actually has a win condition. For Brawl/Historic Brawl (100-card singleton commander deck), see references/brawl_mode.md instead.
---

# MTG deckbuilding (Standard, 1v1)

Derived from two Commander deckbuilding videos, translated for **Standard** (60-card, 1v1,
20 life) — the format actually played here. A parallel translation for **Arena Brawl /
Historic Brawl** (100-card singleton, 1v1, 25 life) lives in `references/brawl_mode.md`; use
this file only when the deck in question is a Brawl/commander deck. Full source notes and a
red/burn deep-dive are also in `references/`.

Last updated: 2026-08-28

---

## 0. Read this first — the translation problem

**Both source videos are about multiplayer Commander: 4 players, 40 life each, 120 life across
the table, singleton, and a social metagame where being the visible threat gets you killed.**

That is not the format being played here. The structural differences that break the videos'
advice:

| | Video's Commander | Standard |
|---|---|---|
| Players | 4 | 2 |
| Life to burn through | 120 | **20** |
| Deck size | 100 singleton | 60, up to 4-of |
| Guaranteed card | Commander | none |
| Game length | 8–12 turns | **4–7 turns** |
| Politics / threat assessment | central | **irrelevant** |

**Consequences, stated plainly:**

1. **The red video's central thesis does not apply here.** It argues red's burn plan is weak
   *because opponents have 120 collective life*. Against 20 or 25 life in 1v1, burn is at its
   strongest. Take the video's *diagnosis* of red; discard its *prescription*.
2. **"Don't be the visible threat" is meaningless in 1v1.** There is nobody else to redirect
   hostility toward. Deploy threats as fast as they are useful.
3. **All the ratios are 100-card multiplayer ratios.** 38 lands / 12 card advantage / 10 ramp /
   10 interaction. These compress for Brawl and are simply the wrong units for 60-card Standard.
4. **Ramp is worth far less in 1v1.** Its value in Commander comes from 40 life buying you time
   to get to a big payoff. At 20 life against an aggressive opponent, a turn-2 mana rock that
   does nothing to the board is often just a lost turn.

**What survives intact** is everything in §1. That part is genuinely format-agnostic and is the
real value of both videos.

---

## 1. Universal principles — apply everywhere

### 1.1 Require multiple overlapping synergies ★

The most important selection rule in either video. Any single keyword matches thousands of
cards. **A card earns its slot when it does several things the deck cares about at once.**

Method: write out the deck's core card (commander, or key engine piece) **line by line** and
extract every keyword hiding in it. Then score candidates against that keyword list. Two
synergies is a real card; one synergy is filler.

Corollary: **cards must synergize with each other, not only with the centrepiece.** In Brawl the
test is "could this win without ever casting the commander?" In Standard it's "does this card
still do work when the best card is answered?"

### 1.2 The mana-value rubric ★★

Every card must clear the bar for its cost. **In 1v1 formats this rubric gets *stricter*, not
looser** — games end 3–5 turns earlier than in Commander, so expensive cards have less time to
justify themselves.

| MV | Bar to clear | 1v1 adjustment |
|---|---|---|
| 6+ | Must dramatically change the game state or win within a turn. No exceptions. | Standard aggro: **zero** of these. Brawl: 2–3 max. |
| 5 | Dramatic advantage the turn it lands, or an unanswered threat that runs away. | Standard: 0–2. Brawl: a small handful. |
| 4 | Powerful **and** highly synergistic. | Standard aggro: the top of the curve. |
| 1–3 | **Must give value turn after turn**, not just on arrival. | This is where 1v1 decks live. |

### 1.3 Card advantage means *net* cards

Strict definition, worth internalising: a card is card advantage only if it **replaces itself and
draws beyond that**. Looting and rummaging (draw 2, discard 2 for one card spent) are **card
selection**, not advantage. Don't let selection inflate the count.

Both still matter — but count them in separate buckets and know which problem each solves.
Selection fixes "wrong cards in hand." Advantage fixes "no cards left."

### 1.4 Cut from the top of the curve

Sort by mana value. Start cutting at the expensive end. Only a handful of top-end cards survive
in any deck. Drawing multiple uncastable bombs is the worst failure mode there is.

**Tiebreak between two similar cards: synergy first, mana value second.**

### 1.5 The goldfish win-condition audit ★

Play a solo mock game — honestly, no free wins. Then ask, in order:

1. Can I win right now?
2. Is there a card **in hand** that wins?
3. Is there a card **in the deck** that, drawn now, wins?

**Three no's means the deck has a real defect — go find a finisher and cut something for it.**
Most homebrews fail this and their owners never check.

**Adjust the checkpoint turn to the format:**

| Deck | Goldfish to the start of |
|---|---|
| Standard aggro / burn | **turn 5** |
| Standard midrange | turn 6 |
| Standard control | turn 8 |
| Brawl | turn 7 |

Target **3–4 real win conditions** in Brawl. In 60-card Standard, redundancy replaces variety —
aim for 8–12 *copies* of a small number of finisher effects.

### 1.6 Audit weaknesses honestly, then sort real from fake

The red video's best structural move: enumerate what a colour/deck is bad at, then decide
**which weaknesses are real constraints to design around and which are outdated assumptions to
attack.** Applied to red: "bad permanent interaction" is real and permanent; "no cheap value
engines" turned out to be fake as of recent sets.

Do this for any archetype before building. Write the list down.

### 1.7 Make removal asymmetric for free

If the deck's key permanents are types its sweeper doesn't hit, a symmetric board wipe becomes
one-sided at no cost. Choose sweepers that dodge your own threats. This generalises well beyond
Commander.

### 1.8 Value doesn't have to be permanents

Digging, filling the graveyard, and banking mana are all value. Board presence is the most
*visible* form of advantage, not the only one.

---

## 2. Standard (60-card, 1v1, 20 life)

The videos give no usable numbers here. These are the 60-card analogues.

### 2.1 Consistency comes from 4-ofs, not from tutors

The single largest structural difference from both videos. In singleton you fight variance with
card selection and tutors. In Standard you fight it by **playing four copies**.

Practical rule: **if a card is core to the plan, play 4. If you wouldn't play 4, ask why it's in
the deck at all.** One-ofs and two-ofs in a 60-card deck are usually a sign of indecision, not
sophistication. Legitimate exceptions: legendary permanents, situational cards wanted as a
single copy, and curve-topping finishers.

### 2.2 Land counts

| Archetype | Lands | Curve tops at |
|---|---|---|
| Mono-red aggro / burn | **20–22** | 3 |
| Aggro with a 4-drop top end | 22–23 | 4 |
| Midrange | 24–25 | 5 |
| Control | 26–27 | 6+ |

Note this directly contradicts the video's "always 38, suck it up" — correctly so. 38/100 is
38%; 24/60 is 40%. The *ratio* is comparable; the absolute number is a Commander artifact.
Aggro decks go below the ratio deliberately because flooding loses games faster than missing a
fourth land drop.

### 2.3 Category budget (60 cards, aggro shell)

Rough starting point, to be tuned:

- **Lands** 20–22
- **Threats** (creatures that pressure) 16–20
- **Interaction / reach** (removal that can also go face) 10–14
- **Card advantage or selection** 2–4 — much lower than Commander. In aggro, *the burn spell is
  the card advantage*, because it converts a card into lethal damage rather than into more cards.
- **Curve targets:** 8–12 one-drops, 12–16 two-drops, 6–8 three-drops, 0–4 four-drops.

### 2.4 Interaction in Standard

Efficiency dominates. Two-mana removal that trades up is worth far more than flexible five-mana
removal. **Prefer removal that doubles as reach** — a burn spell that can kill a blocker *or*
finish the opponent is two cards in one slot, which is the closest a Standard aggro deck gets to
card advantage.

### 2.5 Sideboard

15 cards for Bo3. Don't build it as "cards that are almost good enough." Build it as answers to
the three or four decks actually being lost to. For Bo1, that budget goes back into maindeck
consistency.

---

## 3. Working checklist

Sequence for building anything new:

1. **Pick the strategy, then the payoff cards.** Bottom-up is fine and often better.
2. **Break the centrepiece into keywords, line by line.** Write them down.
3. **Pull candidates from the collection first** (`get_deck_candidates`, `search_cards`), then
   widen. Score every candidate on how many keywords it hits. Two or more, or it's out.

   > ⚠️ **`get_deck_candidates` truncation trap.** Do **not** pass `limit` by hand — if the result
   > risks exceeding the token limit, let it spill to a file and `jq` it instead of shrinking
   > `limit`. The result is ordered by ascending mana value, so a low `limit` silently amputates
   > the **top of the curve** — a plausible-looking list with no expensive cards in it and no
   > obvious sign anything is missing. Always check the `total_matching` and `truncated` fields.
4. **Apply the MV rubric** (§1.2). Cut from the top of the curve down.
5. **Fill the category budget** (§2.3).
6. **Set the land count** from the archetype table (§2.2), not from habit.
7. **Goldfish to the format's checkpoint turn** and run the three win-condition questions.
8. **Verify buildability** — `validate_deck` for wildcard cost before committing. `owned` counts
   are a **lower bound** (Arena stopped reporting collections in 2021).
9. **Play it, then diagnose with real data** — `get_match_plays` for turn-by-turn casts rather
   than guessing from feel.

---

## 4. Explicitly does *not* transfer

Recorded so these aren't reapplied by accident:

- ❌ "38 lands, always" → ratio-based, archetype-dependent, and much lower in 60-card aggro.
- ❌ "10+ pieces of ramp" → ramp is a liability in fast 1v1 unless it's also doing something else.
- ❌ "Red's burn plan is too weak to win" → true at 120 life, false at 20.
- ❌ "Hold your damage payoffs so you don't get targeted" → 1v1; deploy on curve.
- ❌ Bracket 1–4 power calibration → a multiplayer social contract, not a ladder concept.
- ❌ "Cut cards that are too rude" → the ladder has no feelings.
- ❌ Singleton tutoring/redundancy logic → in Standard, redundancy is spelled "4×".

---

## References

- `references/brawl_mode.md` — the parallel translation for Arena Brawl / Historic Brawl
  (100-card singleton, 1v1, 25 life). Use this instead of this file when the deck in question is
  a Brawl/commander deck.
- `references/video-notes-commander-from-scratch.md` — full notes on the 7-step Commander
  deckbuilding process (source video).
- `references/video-notes-red-analysis.md` — full notes on red's weaknesses and what changed
  about the colour (source video).
- `references/red-principles-and-burn-deck.md` — red-specific principles and a worked mono-red
  Standard burn list, applying §1–§2 above.

Load a reference file only when going deep on that specific sub-topic (e.g. building a red deck,
building a Brawl deck, or wanting the original video's full reasoning) — the sections above are
the day-to-day Standard summary.

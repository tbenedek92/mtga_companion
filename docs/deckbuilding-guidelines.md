# Deckbuilding Guidelines

Derived from two Commander deckbuilding videos, translated for the formats I actually play:
**Standard** (60-card, 1v1, 20 life) and **Arena Brawl / Historic Brawl** (100-card singleton,
1v1, 25 life).

Sources:
- [`video-notes-commander-from-scratch.md`](video-notes-commander-from-scratch.md) — the 7-step process
- [`video-notes-red-analysis.md`](video-notes-red-analysis.md) — red's weaknesses, and what changed

Last updated: 2026-08-28

---

## 0. Read this first — the translation problem

**Both source videos are about multiplayer Commander: 4 players, 40 life each, 120 life across
the table, singleton, and a social metagame where being the visible threat gets you killed.**

I play neither of those things. The structural differences that break the videos' advice:

| | Video's Commander | My Standard | My Brawl (Arena) |
|---|---|---|---|
| Players | 4 | 2 | 2 |
| Life to burn through | 120 | **20** | **25** |
| Deck size | 100 singleton | 60, up to 4-of | 100 singleton |
| Guaranteed card | Commander | none | Commander |
| Game length | 8–12 turns | **4–7 turns** | 6–9 turns |
| Politics / threat assessment | central | **irrelevant** | **irrelevant** |

**Consequences, stated plainly:**

1. **The red video's central thesis does not apply to my decks.** It argues red's burn plan is
   weak *because opponents have 120 collective life*. Against 20 or 25 life in 1v1, burn is at
   its strongest. Take the video's *diagnosis* of red; discard its *prescription*.
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
cards. **A card earns its slot when it does several things your deck cares about at once.**

Method: write out your deck's core card (commander, or key engine piece) **line by line** and
extract every keyword hiding in it. Then score candidates against that keyword list. Two
synergies is a real card; one synergy is filler.

Corollary: **cards must synergize with each other, not only with the centrepiece.** In Brawl the
test is "could I win without ever casting my commander?" In Standard it's "does this card still
do work when my best card is answered?"

### 1.2 The mana-value rubric ★★

Every card must clear the bar for its cost. **In 1v1 formats this rubric gets *stricter*, not
looser** — games end 3–5 turns earlier than in Commander, so expensive cards have less time to
justify themselves.

| MV | Bar to clear | 1v1 adjustment |
|---|---|---|
| 6+ | Must dramatically change the game state or win within a turn. No exceptions. | Standard aggro: **zero** of these. Brawl: 2–3 max. |
| 5 | Dramatic advantage the turn it lands, or an unanswered threat that runs away. | Standard: 0–2. Brawl: a small handful. |
| 4 | Powerful **and** highly synergistic. | Standard aggro: the top of your curve. |
| 1–3 | **Must give value turn after turn**, not just on arrival. | This is where 1v1 decks live. |

### 1.3 Card advantage means *net* cards

Strict definition, worth internalising: a card is card advantage only if it **replaces itself and
draws beyond that**. Looting and rummaging (draw 2, discard 2 for one card spent) are **card
selection**, not advantage. Don't let selection inflate your count.

Both still matter — but count them in separate buckets and know which problem each solves.
Selection fixes "I have the wrong cards." Advantage fixes "I have no cards."

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
you want 8–12 *copies* of a small number of finisher effects.

### 1.6 Audit weaknesses honestly, then sort real from fake

The red video's best structural move: enumerate what your colour/deck is bad at, then decide
**which weaknesses are real constraints to design around and which are outdated assumptions to
attack.** Applied to red: "bad permanent interaction" is real and permanent; "no cheap value
engines" turned out to be fake as of recent sets.

Do this for any archetype before building. Write the list down.

### 1.7 Make your removal asymmetric for free

If your deck's key permanents are types your sweeper doesn't hit, a symmetric board wipe becomes
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
sophistication. Legitimate exceptions: legendary permanents, situational cards you only want one
of, and curve-topping finishers.

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
the three or four decks you actually lose to. If you play Bo1, that budget goes back into
maindeck consistency.

---

## 3. Brawl / Historic Brawl (100-card singleton, 1v1, 25 life)

This is where the videos' process transfers **best**, with compression. Same 100-card singleton
structure and a guaranteed commander — but 1v1 at 25 life, so it plays roughly twice as fast as
multiplayer Commander.

### 3.1 What carries over unchanged

- The whole **7-step process** as a sequence.
- The **line-by-line commander breakdown** and multiple-overlapping-synergy rule.
- "Could I win without casting my commander?"
- **Commander-cost curve shaping:** if you'll always cast the commander on turn N, run fewer
  cards at N. If the commander needs a board already in play, load 1–3 drops so it lands into an
  active board.

### 3.2 What to compress

| Category | Video (multiplayer) | Brawl 1v1 |
|---|---|---|
| Lands | 38 | **35–37** (33–35 for a genuinely aggressive deck) |
| Card advantage | 12–17 | **10–12**, weighted cheaper — 8+ at MV ≤ 3 |
| Normal ramp | 10–11 | **6–9**, and it must do something besides make mana |
| Explosive ramp | 3–5 | **1–2** — games end before it pays off |
| Interaction | 10 + 2–4 wipes | **12–15 + 1–2 wipes** ← *increased* |
| Top end (MV 6+) | as budget allows | **2–3 max** |

**Interaction goes up, ramp goes down.** In multiplayer, someone else usually answers the scary
thing and ramp buys you a big turn. In 1v1 there is no "someone else" — if you can't answer
their commander, you lose to it, and a turn spent ramping is a turn they spent attacking.

### 3.3 The 1v1 commander reality

The opponent's commander is guaranteed to show up, is recastable, and is usually their best card.
**Carry answers that handle a recurring threat** — exile, bounce-to-hand is weak, and "kill it
once" is often not enough. Conversely, your own commander will eat their removal, so have a plan
for the turns it isn't on the board.

### 3.4 Ignore entirely

Bracket calibration, "don't play something that pisses people off," political cards, threat
assessment, and anything about not drawing the table's attention. There is no table.

---

## 4. Working checklist

Sequence for building anything new:

1. **Pick the centrepiece.** Brawl: the commander (rule of cool is legitimate — I have to want to
   play it). Standard: the strategy, then the payoff cards. Bottom-up is fine and often better.
2. **Break the centrepiece into keywords, line by line.** Write them down.
3. **Pull candidates from my own collection first** (`get_deck_candidates`, `search_cards`), then
   widen. Score every candidate on how many keywords it hits. Two or more, or it's out.

   > ⚠️ **`get_deck_candidates` truncation trap.** Do **not** pass `limit` by hand. The result is
   > ordered by ascending mana value, so a low `limit` silently amputates the **top of the
   > curve** — you get a plausible-looking list with no expensive cards in it and no obvious sign
   > anything is missing. Always check the `total_matching` and `truncated` fields in the
   > response. My Standard pool is **857 cards**; a `limit=400` call returned a list that ended
   > five cards into the three-drops and contained not a single card costing 4 or more.
4. **Apply the MV rubric** (§1.2). Cut from the top of the curve down.
5. **Fill the category budget** for the format (§2.3 / §3.2).
6. **Set the land count** from the archetype table, not from habit.
7. **Goldfish to the format's checkpoint turn** and run the three win-condition questions.
8. **Verify buildability** — `validate_deck` for wildcard cost before committing. Remember
   `owned` counts are a **lower bound** (Arena stopped reporting collections in 2021), and my
   rare wildcard count currently reads as unknown.
9. **Play it, then diagnose with real data** — `get_match_plays` for turn-by-turn casts rather
   than guessing from feel.

---

## 5. Explicitly does *not* transfer

Recorded so I don't reapply these by accident:

- ❌ "38 lands, always" → ratio-based, archetype-dependent, and much lower in 60-card aggro.
- ❌ "10+ pieces of ramp" → ramp is a liability in fast 1v1 unless it's also doing something else.
- ❌ "Red's burn plan is too weak to win" → true at 120 life, false at 20–25.
- ❌ "Hold your damage payoffs so you don't get targeted" → 1v1; deploy on curve.
- ❌ Bracket 1–4 power calibration → a multiplayer social contract, not a ladder concept.
- ❌ "Cut cards that are too rude" → the ladder has no feelings.
- ❌ Singleton tutoring/redundancy logic → in Standard, redundancy is spelled "4×".

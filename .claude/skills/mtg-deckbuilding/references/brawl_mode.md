# Brawl / Historic Brawl (100-card singleton, 1v1, 25 life)

Companion to [`../SKILL.md`](../SKILL.md), which covers the universal principles (§1) that apply
here unchanged, plus the Standard-specific translation. This file holds everything specific to
**Arena Brawl / Historic Brawl**: same 100-card singleton structure as multiplayer Commander, and
a guaranteed commander, but 1v1 at 25 life — so it plays roughly twice as fast as multiplayer
Commander and the ratios need compressing.

Last updated: 2026-08-28

---

## Format comparison

| | Video's Commander | Brawl (Arena) |
|---|---|---|
| Players | 4 | 2 |
| Life to burn through | 120 | **25** |
| Deck size | 100 singleton | 100 singleton |
| Guaranteed card | Commander | Commander |
| Game length | 8–12 turns | 6–9 turns |
| Politics / threat assessment | central | **irrelevant** |

Same universal-principles caveat as Standard applies: the video's *diagnosis* of red (and of
other archetypes) transfers; its life-total-120-dependent *prescriptions* do not.

---

## What carries over unchanged from the source video

- The whole **7-step process** as a sequence (full notes in
  `video-notes-commander-from-scratch.md`).
- The **line-by-line commander breakdown** and multiple-overlapping-synergy rule (SKILL.md §1.1).
- "Could this win without ever casting the commander?"
- **Commander-cost curve shaping:** if the commander will always be cast on turn N, run fewer
  cards at N. If the commander needs a board already in play, load 1–3 drops so it lands into an
  active board.

## What to compress

This is where the video's process transfers **best**, with compression — not a rebuild like
Standard needed.

| Category | Video (multiplayer) | Brawl 1v1 |
|---|---|---|
| Lands | 38 | **35–37** (33–35 for a genuinely aggressive deck) |
| Card advantage | 12–17 | **10–12**, weighted cheaper — 8+ at MV ≤ 3 |
| Normal ramp | 10–11 | **6–9**, and it must do something besides make mana |
| Explosive ramp | 3–5 | **1–2** — games end before it pays off |
| Interaction | 10 + 2–4 wipes | **12–15 + 1–2 wipes** ← *increased* |
| Top end (MV 6+) | as budget allows | **2–3 max** |

**Interaction goes up, ramp goes down.** In multiplayer, someone else usually answers the scary
thing and ramp buys you a big turn. In 1v1 there is no "someone else" — if the opponent's
commander can't be answered, it wins the game, and a turn spent ramping is a turn they spent
attacking.

The MV rubric (SKILL.md §1.2) applies at the Brawl adjustment column: Standard aggro numbers
don't apply here, but the "1v1 is stricter than multiplayer" principle does.

## The 1v1 commander reality

The opponent's commander is guaranteed to show up, is recastable, and is usually their best card.
**Carry answers that handle a recurring threat** — exile, bounce-to-hand is weak, and "kill it
once" is often not enough. Conversely, the deck's own commander will eat their removal, so have a
plan for the turns it isn't on the board.

## Ignore entirely

Bracket calibration, "don't play something that pisses people off," political cards, threat
assessment, and anything about not drawing the table's attention. There is no table.

## Goldfish checkpoint

Goldfish to the start of **turn 7** (SKILL.md §1.5). Target **3–4 real win conditions** — Brawl's
singleton structure means redundancy has to come from variety, not from playing four copies the
way Standard does.

## Working checklist (Brawl variant)

Same sequence as SKILL.md §4, with these format-specific swaps:

1. **Pick the commander first.** Rule of cool is legitimate — wanting to play it matters.
2. Break the commander into keywords, line by line, same as SKILL.md §4 step 2.
3. Pull candidates from the collection first, same truncation trap applies (SKILL.md §4 step 3).
4. Apply the MV rubric using the Brawl adjustment column.
5. Fill the category budget from the compression table above, not the Standard one.
6. Set lands to 35–37 (33–35 aggressive), not the Standard archetype table.
7. Goldfish to turn 7, check for 3–4 real win conditions.
8. Verify buildability — `validate_deck`; `owned` counts are a lower bound.
9. Play it, then diagnose with `get_match_plays`.

## Explicitly does *not* transfer (Brawl)

- ❌ Bracket 1–4 power calibration → a multiplayer social contract, not a ladder concept.
- ❌ "Cut cards that are too rude" → no one else at the table to offend.
- ❌ "Hold your damage payoffs so you don't get targeted" → 1v1; deploy on curve.
- ❌ "Red's burn plan is too weak to win" → true at 120 life, false at 25.

# Notes — "How to Build a Commander Deck from Scratch"

Source: https://www.youtube.com/watch?v=YJ8X8bO8jeY
Reviewed: 2026-08-28 · Format context: **Commander (100-card singleton, 4-player, 40 life)**

> Read the caveats in `../SKILL.md` and `brawl_mode.md` before applying the ratios. This video's
> numbers are tuned for multiplayer Commander. They transfer to Brawl with compression and
> do **not** transfer to 60-card Standard at all.

---

## The seven-step process

### Step 1 — Pick the commander

Two rules only:

1. **Rule of cool.** Pick what you actually want to play — art, character, play pattern.
2. **Don't pick something that stops other players from playing.** Oppressive or overpowered
   commanders get you targeted, and being targeted means you don't get to play either.

Colour identity: your 99 may only use colours appearing in the commander's mana cost **or
rules text**.

> **Bottom-up alternative** (used in the red video): don't start from a commander. Start from a
> *strategy*, assemble the engine cards, then go find a commander with multiple overlapping
> synergies with what you already picked.

### Step 2 — Find your themed cards ★ (author flags this as the most important step)

**Break the commander down line by line and extract the hidden keywords.** The worked example
pulls eight keywords out of two ability lines — `enters`, `attacks`, `sacrifice creature`,
`sacrifice artifact`, `+1/+1 counters`, `leaves the battlefield`, `counters`, `target creature
you control`.

Then ask two separate questions:

- What does the commander *do*?
- What does the commander *want to do* — i.e. what does it need on the board to function?

**The core selection rule: require multiple overlapping synergies, not one.** Tens of thousands
of cards match any single keyword. A card earns a slot when it hits several at once. The
worked example scores one card at five distinct synergies (flying, lifelink, an ETB trigger,
graveyard recursion, and a from-graveyard activated ability).

**Cards in the 99 must synergize with each other, not just with the commander.**

> "A hallmark of a really good deck is to be able to never play your commander and still win
> the game."

**Search method:** go through your own collection first and make a pile. Then use Scryfall,
seeded with keywords lifted off cards you already picked — use a known-good card as a
*reference* to find more like it.

#### The mana-value cut rubric ★★ — the single most portable idea in either video

| MV | Bar the card must clear |
|---|---|
| **6+** | Must dramatically change the game state **or** give an insurmountable advantage **within one turn**. "If a card does not meet these requirements, I cut it. No exceptions." |
| **5** | Must give a dramatic advantage the turn it lands, **or** be a threat that runs away with the game in a few turns if unanswered. |
| **4** | Must be powerful **and** highly synergistic — pushes the deck into overdrive or sets up the next few turns. |
| **1–3** | Must be **engine pieces that provide value turn after turn**, not just on the turn they land. |

Narrow the themed pile to ~40 cards. Also cut anything "too rude" that stops opponents having fun.

### Step 3 — Card advantage

> "The single most important thing that if you get right, will make your deck work."
> Called "the hidden engine."

**Definition is strict.** Card advantage = *net positive* cards. A card must replace itself
**and** draw beyond that — minimum two cards. Faithless Looting draws 2 and discards 2 for one
card spent, so it is **card selection, not card advantage**. Do not count selection toward your
density.

Three rules:

- **Density** — bare minimum **12** dedicated pieces. Author runs 16–17 in several decks.
- **Synergy** — card advantage pieces should have 1–3 synergies with the rest of the deck, so
  you extract value from both halves.
- **Curve** — of 12 pieces, roughly **8 at MV ≤ 3** and **4 at MV ≥ 4**. The expensive ones must
  draw *explosively* (5, 6, or more). The cheap ones draw one or two, or one every turn.

### Step 4 — Ramp

Two categories.

- **Normal ramp — minimum 10–11 pieces.** Mana rocks, mana dorks, land tutors. Bias toward
  efficiency: 1 MV > 2 MV > 3 MV, unless a synergy is too good to pass up or the deck genuinely
  needs bulk mana.
- **Explosive ramp** — anything that doubles your expected mana output for a turn or more.
  Rituals, treasure makers, cost-reducers, mass free-cast effects. **Bracket 2: ~2 pieces.
  Bracket 3: 3–5 pieces.**

Rationale: normal ramp powers the early game, explosive ramp closes it. If opponents ramp early
and you don't, you fall behind permanently.

### Step 5 — Interaction

**~10 dedicated interaction + 2–4 board wipes.** Subtract 1–2 from the dedicated count if the
deck has meaningful incidental interaction elsewhere.

Four kinds: removal, interruption (counterspells), protection, and board wipes as their own
category.

Scaling rule: **the higher the power level, the more interaction you need and the more efficient
it must be.** At brackets 1–3 you can afford cute, synergistic interaction over maximally
efficient interaction. Too much interaction and nobody has fun, including you.

### Step 6 — Lands and cuts ★

> "I always aim for 38 lands. I know that seems like a lot, but missing land drops is
> devastating to your win rate. Suck it up and put 38 in."

- Mono-colour → mostly basics plus colourless utility lands.
- 3+ colours → majority colour-fixing lands, **still 38**.

**Cutting procedure:**

1. Add up every non-themed category, subtract from 99 — that's your themed-card budget.
2. Sort themed cards by mana value.
3. **Start cutting from the top.** Only 3–4 genuinely expensive cards survive. Drawing multiples
   of them with no mana is the worst outcome in the game.
4. Weight toward the bottom of the curve.
5. **Adjust around your commander's own cost.** If you'll cast the commander over any other
   3-drop, run fewer 3s and more 2s and 4s.
6. **Ask if the commander is a setup piece.** If it wants a board already in play before it
   lands (e.g. it needs a sacrifice target on ETB), load up on 1–3 drops so it comes down into
   an active board.
7. **Tiebreak: affinity first, mana value second.**

### Step 7 — Goldfish and win conditions ★

Goldfish (play a solo mock game, realistically — don't award yourself free attacks with a 1/1 on
turn 5) **to the start of turn 7**. Then interrogate the board with three questions in order:

1. Can I win the game right now?
2. Is there a card **in my hand** that wins the game?
3. Is there a card **in my deck** that, drawn this turn, wins the game?

If all three are no, the deck has a real defect: **go find a win condition on Scryfall and cut
something for it.** The video does this twice and swaps in a specific finisher each time.

Repeat until you know the deck. **Target 3–4 real win conditions** — cards that convert a
typical big board into a win.

**Bracket calibration signal:** if goldfishing keeps winning on turn 6, the deck is a bracket
higher than you intended. Turn 7 is bracket 3; turn 6 is bracket 4.

---

## Things worth stealing verbatim

- Requiring **multiple overlapping synergies** rather than one is the whole difference between a
  pile and a deck.
- The **MV cut rubric** — especially "1–3 drops must give value turn after turn."
- **Card advantage means net cards.** Stop counting looting as draw.
- The **turn-7 win-condition audit**. Most homebrews fail this and their owners never check.
- Sorting by mana value and **cutting from the top down**.

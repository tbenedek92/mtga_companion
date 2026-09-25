# Red in 1v1 Standard — Principles, and the Mono-Red Burn List

Companion to [`deckbuilding-guidelines.md`](deckbuilding-guidelines.md) and
[`video-notes-red-analysis.md`](video-notes-red-analysis.md).

Written: 2026-08-28 · Format: **Standard — 60 cards, 1v1, 20 life, up to 4 copies**

---

## 1. Red principles for a 20-life format

The source video is Commander analysis: 4 players, 40 life each, 120 life across the table.
Its diagnosis of red is excellent. Its prescription is written for a life total six times
larger than mine. Sorting the two:

### 1.1 What inverts (do not import)

- **"Red's aggro/burn plan is too weak to win."** True at 120 life. At 20 life it is the whole
  point. Do not turn this deck into a grindy value deck.
- Politics, threat assessment, "don't be the visible threat", holding payoffs so you don't get
  targeted, bracket calibration, 38 lands, 10+ ramp, 12+ card advantage. There is no table.

### 1.2 What transfers intact

**Red's permanent interaction is genuinely bad, and it is a real constraint.** Direct damage is
the only removal red has. It fails against high toughness, ward, indestructible, protection and
"exile it" effects, and red has essentially no catch-all answer to enchantments. Consequence for
a burn deck: **don't try to answer permanents. Race them.** Every removal slot must be a slot
that can also point at the opponent's face, or it should not be in the maindeck. That single
rule is what condemns Impractical Joke below.

**Red is the worst colour at protecting its own life total.** No lifelink, no lifegain, bad
blockers. In Commander this is about surviving the table. **In Standard it shows up in one very
specific place: any opponent who gains life.** The burn deck's clock is finite — about 44 points
of face damage exist in the whole list — so an opponent gaining 3–4 a turn doesn't slow the
clock, it *breaks* it. This is not a theoretical concern here; it is the observed loss pattern
(§2.4). The answer is not to gain life back. It is to **turn their lifegain off**, which red can
do at common/uncommon rates.

**"The best removal is player removal."** Instant-speed damage held for the face. Two of the four
maindeck burn spells (Shock, Burst Lightning, Lightning Strike) are instants; the default should
be to hold them unless killing a creature this turn is strictly necessary.

**Red is being pushed hard at 1, 2 and 3 mana right now, and Standard is the video's own proof.**
The video names Slickshot Show-Off and Monstrous Rage as "perfect for Standard, bad in Commander."
I own 4 Slickshot Show-Off, 4 Emberheart Challenger, 4 Hired Claw. This shell is built on the
correct half of the pushed-red pool. (Note: **Monstrous Rage is no longer Standard legal** —
checked with `validate_deck`, along with Heartfire Hero and Screaming Nemesis. All three are out.)

**Red's card advantage always carries a downside; looting is selection, not advantage.** Grab the
Prize and Seize the Spoils are rummage. Case of the Crimson Pulse is the one owned card that is
genuinely net-positive.

**Value doesn't have to be permanents.** In this deck, the burn spell *is* the value: it converts
a card into a fixed slice of the 20 points I need. That is why the deck's card-advantage budget
is 2–4 slots and not 10.

### 1.3 The one number that matters

At 20 life the deck has to find 20 damage in roughly 5 turns. Every card gets scored on **how
much of the 20 it contributes.** A card that contributes zero to that number needs a very good
reason to be in the maindeck.

---

## 2. The current list — analysis

Deck `68358494-5b8d-438c-8421-96932a82cda1` "Mono-Red Burn", favourite, **61 cards**.

| MV | Cards |
|---|---|
| Lands | 20 Mountain |
| 1 (28) | 4 Boltwave · 4 Burst Lightning · 4 Shock · 4 Tectonic Hazard · 4 Impractical Joke · 4 Hired Claw · 4 Fleeting Effigy |
| 2 (12) | 4 Lightning Strike · 4 Slickshot Show-Off · 4 Emberheart Challenger |
| 3 (1) | 1 Firespitter Whelp |

Against the §2.3 budget (8–12 one-drops, 12–16 two-drops, 6–8 three-drops): **28 / 12 / 1**. The
curve is not merely low, it is a spike at one mana with nothing to spend mana on afterwards.

### 2.1 The 61st card

**Firespitter Whelp** — a lone 3-MV 2/2 flier that pings each opponent for 1 per noncreature or
Dragon spell. The *effect* is good in this shell. The *card* is a one-of at the top of an
otherwise empty part of the curve, which §2.1 calls indecision rather than sophistication. Only 1
copy is owned, which is presumably why it's a one-of.

The fix is not "find three more Whelps." **Firebrand Archer** ({1}{R}, common, 2/1) is the same
effect one mana cheaper — 1 damage to each opponent per noncreature spell — and a playset costs
3 common wildcards.

### 2.2 Reach audit — where the 20 damage actually comes from

| Card | × | Face damage each | Total to face |
|---|---|---|---|
| Boltwave | 4 | 3 | 12 |
| Lightning Strike | 4 | 3 | 12 |
| Shock | 4 | 2 | 8 |
| Burst Lightning | 4 | 2 | 8 |
| Tectonic Hazard | 4 | **1** | 4 |
| Impractical Joke | 4 | **0** | **0** |

- **Impractical Joke cannot target a player.** Four maindeck slots — 6.6% of the deck — contribute
  literally nothing to the win condition. This is the clearest violation of §2.4 in the list.
- **Tectonic Hazard** is 1 damage to the face plus 1 to each of their creatures. As a sweeper it
  kills X/1s only; as reach it is the worst rate in the deck by a factor of two.
- **Burst Lightning's kicker is dead weight here.** Kicked it deals 4, but that costs 5 mana.
  Across five logged games this deck reached 4 lands *once*. Treat it as Shocks 5–8.

### 2.3 Threats

17 creatures. Verified printed stats (not inferred):

| Card | P/T | Notes |
|---|---|---|
| Hired Claw | **1/2** | Lizard; pings 1 on Lizard attack; grows with {1}{R} once/turn |
| Fleeting Effigy | **2/2** | haste; **returns to hand at your end step** |
| Emberheart Challenger | **2/2** | haste, prowess, Valiant |
| Slickshot Show-Off | **1/2** | flying, haste, +2/+0 per noncreature spell, Plot {1}{R} |
| Firespitter Whelp | **2/2** | flying |

Two structural problems:

**(a) Emberheart Challenger's Valiant is switched off.** Valiant triggers when the creature
becomes the target of a spell or ability *I* control. The deck contains **zero** cards that can
target my own creature. Four rare slots are running at roughly half power.

**(b) Fleeting Effigy is a tax, not a threat.** It is a 2/2 haste for {R} that bounces to my hand
every end step, so it costs {R} again every turn to redeploy, forever. It can't accumulate
counters, carry equipment or hold a board. In the logged games it was cast **6 times in one game
and 8 in another** — that's 6–8 mana spent to deal 2 per turn, in a deck whose problem is
converting mana into damage.

### 2.4 What the play data actually shows

`get_deck_stats` reports 0 matches for this deck because match rows carry `deck_id = null`. I
identified games by decklist fingerprint in `get_match_plays` (Fleeting Effigy + Impractical Joke
+ Tectonic Hazard together only occur in this list). **Five logged mono-red games, 2 wins and 3
losses**, plus one further loss on the v2/v3 build.

**Finding 1 — the deck operates on 2–3 lands and cannot use more.** Land drops by turn:

| Match | Result | Lands played on turns |
|---|---|---|
| `6172a8c0` | win | 1, 2, — , — , 5 |
| `54e6e7b5` | loss | 1, 2, — , — , 5, — , 7 |
| `a49edaa3` | win | 1, 2, — , 4 |
| `43fd1a48` | loss | 1, 2, 3, — , — , 6 |
| `20b996a4` | loss | 1, 2, — , 4, — , — , 7 |

It never exceeded 4 lands in any of them. With 28 one-drops that is the *designed* state, not bad
luck — but it means turns 4+ consist of casting one or two 1-mana spells and passing. **There is
nothing in the deck that turns a long game into more damage.** That is the actual failure mode,
not "the deck is slow."

**Finding 2 — both clean losses were to white lifegain.** In `20b996a4` the opponent played
Healer's Hawk, Essence Channeler, Leonin Vanguard, Ajani's Pridemate and Sheltered by Ghosts. My
side spent **four Shocks on creatures**, cast Fleeting Effigy eight times, and ran out of reach.
`79b13b13` (the v2 build) lost to the same shell: Veteran Survivor, Optimistic Scavenger,
Sheltered by Ghosts, Seam Rip. This is the video's "red can't protect its life total" weakness in
its exact Standard form, and it is the deck's most fixable matchup.

**Finding 3 — Equipment shows up constantly on ladder.** Dragonfire Blade, Buster Sword,
Samurai's Katana, Machinist's Arsenal, Summoner's Grimoire all appeared across the logged games.
Abrade and Fiery Annihilation (both already owned) are the sideboard answers.

### 2.5 Direction of travel across the four versions

The user has been oscillating, not converging:

- **v2** (`8e3721e6`) — 21 lands, Ghitu Lavarunner + Fanatical Firebrand + Searslicer Goblin,
  3 Abrade + 2 Heartfire Immolator maindeck. Joke/Hazard in the sideboard.
- **Mono-red Burn revision** (`9d067bb6`) — 16 lands (!), Burnout Bashtronaut, Joke/Hazard back in.
- **Mono-Red Burn** (`68358494`, the 61) — 20 lands, all-in on 1-drops, no creature removal at all.
- **v3** (`1d1aea93`) — 20 lands, Joke/Hazard back to the sideboard, 3 Abrade + 2 Heartfire
  Immolator back in.

**v3's instinct is the right one** — it recognised that Impractical Joke and Tectonic Hazard
belong in the sideboard. It just replaced them with more 2-mana creature removal (Abrade), which
is the same category error one step smaller: still zero contribution to the 20 damage. The
recommendation below keeps v3's cut and spends the slots on reach and on shutting off lifegain.

---

## 3. Recommended changes

All prices are wildcards against a budget of **23 common / 10 uncommon / 6 mythic / rare UNKNOWN**.
Owned counts are a **lower bound** — Arena stopped reporting collections in 2021 — so anything
listed as needing wildcards may already be in the collection.

### Cuts (–14)

| Cut | Reason |
|---|---|
| **–4 Impractical Joke** | Cannot target a player. Zero contribution to the 20 damage. §2.4. → sideboard |
| **–4 Tectonic Hazard** | 1 damage to the face for a whole card; the worst rate in the deck |
| **–4 Fleeting Effigy** | Bounces every end step, so it re-taxes {R} every turn forever; cast 6–8× per game to deal 2 per turn |
| **–1 Firespitter Whelp** | The 61st card. A one-of at the top of an empty curve; replaced by a cheaper, craftable version of the same effect |
| **–1 Mountain** | Making room; land count net *rises* by one, see below |

### Adds (+14)

| Add | Reason | Wildcards |
|---|---|---|
| **+4 Giant Cindermaw** ({2}{R}, uncommon, **4/3 trample**, "Players can't gain life") | Directly answers the two logged losses. Symmetric text that is one-sided for free (§1.7) — this deck gains no life. Also the fastest clock in the owned pool. **No haste**: it attacks the turn after it lands. | **2 uncommon** (own 2) |
| **+4 Firebrand Archer** ({1}{R}, common, **2/1**) | 1 damage to each opponent per noncreature spell. With 16 burn spells left in the deck, one Archer surviving two turns is 2–4 free damage. The Firespitter Whelp effect, one mana cheaper. | **3 common** (own 1) |
| **+3 Guttersnipe** ({2}{R}, uncommon, **2/2**) | *The biggest single upgrade available.* 2 damage to each opponent per instant or sorcery. Every one of the 16 remaining burn spells is an instant or sorcery, so a Guttersnipe that lives one turn cycle is 4–6 free damage — double Firebrand Archer's rate. This is the card that fixes "turns 4+ do nothing." | **3 uncommon** (own 0) |
| **+1 Rockface Village** (uncommon land) | Turns Emberheart Challenger's dead Valiant on: `{R}, {T}: target Lizard/Mouse/Otter/Raccoon gets +1/+0 and haste` targets my own Mouse, triggering Valiant for a free impulse draw each turn. Also pumps Hired Claw (Lizard). **Caveat:** its red mana is creature-spells-only, so it cannot pay for Boltwave/Shock — hence exactly 1 copy. | **0** (own 1) |
| **+2 Mountain** | Land count 20 → 21, because the deck now has 7 three-drops | 0 |

**Total: 3 common, 5 uncommon, 0 rare, 0 mythic** — confirmed by `validate_deck` against the
stated budget (`within_budget: true`). This build deliberately spends **zero rare wildcards**,
which matters because the rare stock reads as *unknown* rather than zero. Nothing here is blocked
on checking it.

**Not recommended, and why** (so these don't get re-litigated):

- *Monstrous Rage, Heartfire Hero, Screaming Nemesis* — **not Standard legal**, confirmed via
  `validate_deck`. Screaming Nemesis would have been the perfect anti-lifegain card; Giant
  Cindermaw is the legal substitute.
- *Twinflame Tyrant* (5 MV mythic, 3/5 flying, doubles all my damage to opponents) — turns
  Boltwave into 6 damage and is the most tempting card in the collection. It is 5 mana in a deck
  that has reached 4 lands once in five games. §1.2 says zero 5-drops in Standard aggro. No.
- *Stormsplitter* (4 MV mythic, **1/4** haste, copies itself per instant/sorcery) — a real
  finisher, but 4 MV and 3 more mythic wildcards. See "what to test".
- *Abrade / Fiery Annihilation / Scorching Dragonfire* — good cards, zero face damage.
  Sideboard, not maindeck.
- *Slumbering Cerberus* — verified **4/2 that doesn't untap during untap step**. Not a burn card.

---

## 4. The revised 60

```
Deck
20 Mountain
1  Rockface Village

4  Shock
4  Burst Lightning
4  Boltwave
4  Hired Claw

4  Lightning Strike
4  Slickshot Show-Off
4  Emberheart Challenger
4  Firebrand Archer

4  Giant Cindermaw
3  Guttersnipe
```

**Curve:** 21 lands · 16 one-drops · 16 two-drops · 7 three-drops. Tops out at 3, per §2.2.

**Category budget** (§2.3): threats 23 · reach 16 · lands 21. Dedicated card-advantage slots: 0 —
see the note below.

`validate_deck` result: **valid, 60 cards, Standard legal, within budget.** Cost **3 common /
5 uncommon / 0 rare / 0 mythic.**

**How it wins.** Three damage multipliers stack on the same 16 burn spells:

- **Slickshot Show-Off** (1/2 flier) gets +2/+0 per noncreature spell — the fastest clock.
- **Firebrand Archer** (2/1) turns each one into +1 to the face at 2 mana.
- **Guttersnipe** (2/2) turns each one into +2 to the face at 3 mana.

A turn-4 board of Archer + Guttersnipe means Shock reads *"5 damage to the opponent"* for one
mana. That is the answer to "turns 4+ do nothing": the deck stops needing more lands and starts
needing more spells, which is what the 16 one- and two-mana burn cards supply.
**Giant Cindermaw** is the 4-power trampler that closes and the switch that turns lifegain off.

**On zero card-advantage slots:** §2.3 explicitly allows this in aggro — the burn spell *is* the
advantage, because it converts a card into a fixed slice of 20. The only draw effect in the list
is Emberheart Challenger's Valiant impulse-draw, enabled by Rockface Village. If the deck proves
to run out of gas in testing, Case of the Crimson Pulse is the fix — see §6.2.

**Goldfish checkpoint (§1.5): start of turn 5.** Sample line — T1 Hired Claw; T2 Slickshot
Show-Off, attack for 1+1; T3 Firebrand Archer + Shock face (2 + 1 Archer + 3 attack); T4 Giant
Cindermaw + Boltwave (3 + 1 Archer + attacks). Roughly 16–18 by the start of turn 5 with a
Boltwave or Lightning Strike left in hand. Swap the T3 Archer for a Guttersnipe and the same line
is lethal a turn earlier. The deck passes the audit — which the current 61 does only on a
Slickshot draw.

---

## 5. Sideboard sketch (Bo3) — 15 cards, **0 wildcards**

Everything here is already owned in sufficient quantity.

```
Sideboard
4  Impractical Joke      // creature decks; "damage can't be prevented" beats protection,
                         // prevention effects and shield counters
3  Fiery Annihilation    // 5 damage to a creature AND exiles the Equipment on it AND exiles
                         // the creature — the answer to Sheltered by Ghosts and to the
                         // Equipment decks that keep appearing on ladder
3  Abrade                // 3 to a creature or destroy an artifact; the Equipment matchup
3  Searslicer Goblin     // 2/1 that makes a 1/1 each end step I attacked — rebuilds through
                         // Day of Judgment; bring in vs control
2  Scorching Dragonfire  // 3 damage that exiles; recursive/death-trigger creatures
```

**Boarding notes:**

- **vs white lifegain / auras** (the logged losses): the four Giant Cindermaw are already
  maindeck and are the plan. In 3 Fiery Annihilation for Sheltered by Ghosts; out 3 Guttersnipe,
  which is too slow when their clock is a lifelinker rather than damage.
- **vs control** (Day of Judgment, Stock Up, Spell Snare all seen on ladder): in 3 Searslicer
  Goblin, out 3 Hired Claw. **Plot Slickshot Show-Off** — plotting it for {1}{R} dodges
  counterspells and sorcery-speed sweepers entirely. Keep Guttersnipe; against a creature-light
  deck it survives, and 2 damage per burn spell is how this matchup is won.
- **vs Equipment / Boros** (Dwalin, Dragonfire Blade, Samurai's Katana): 3 Abrade + 3 Fiery
  Annihilation, out 3 Guttersnipe + 3 Boltwave.
- **vs aggro mirrors:** in 4 Impractical Joke, out 4 Boltwave. This is the one matchup where
  creature removal outranks face damage, because red loses races it doesn't interact in. Giant
  Cindermaw's 4/3 body is also the best blocker in the deck by a wide margin.

If the user is playing **Bo1** ladder, shift 3 Guttersnipe → 3 Impractical Joke in the maindeck:
game 1 has no sideboard, and the lifegain and aggro decks in the logs are common enough that a
maindeck creature answer beats a build-around payoff.

---

## 6. Open questions — what to test

1. **Is cutting all 4 Fleeting Effigy right, or keep 1?** The bounce is genuinely unkillable by
   sorcery-speed removal and it's a mana sink on a flooded board. Test 0 first; if games are lost
   with 3 lands untapped, try 1.
2. **Does the deck run out of gas with zero draw?** This is the one place the list knowingly
   ignores §2.3's 2–4 card-advantage slots. If games are being lost with an empty hand and the
   opponent at 5–8 life, the fix is **Case of the Crimson Pulse** ({2}{R}, rare, own 1): ETB is
   net **+1 card**, it solves the moment my hand is empty (turn 3–4 in the logged games), and
   then draws 2 every upkeep. Genuine card advantage, not looting (§1.3), and the clearest
   example in the collection of the video's "pushed cheap red value engine." **Cost: 2 rare
   wildcards for a third copy — check the real rare stock first.** Swap in for 3 Guttersnipe or
   split them.
3. **Guttersnipe at 3 or 4 copies?** Three is the cautious number given the logged games rarely
   reached 4 lands. If it consistently lands and lives, the 4th copy (1 more uncommon wildcard)
   is probably the strongest card in the deck.
4. **21 lands or 22?** Seven three-drops is a real top end and the logged games missed land drops
   repeatedly. If 21 still misses, go to 22 by cutting a Burst Lightning.
5. **Rockface Village: 1 or 2?** Each copy is a land that can't cast Shock. Two copies gives a
   more reliable free Valiant trigger; count how often a Village is stranded.
6. **Stormsplitter as a 2-of finisher?** Mythic, 1 owned, 3 mythic wildcards of 6 available. It
   is a **1/4 haste** that copies itself on every instant or sorcery — a real "cast two burn
   spells and swing for lethal" card. But 4 MV. Only worth it if testing shows games regularly
   reaching turn 6+.
7. **Might of the Meek** ({R} common, 4 common wildcards) — trample, +1/+0 if I control a Mouse,
   **draw a card**. It targets my own creature, so it triggers Emberheart's Valiant *and* prowess
   *and* Slickshot's +2/+0, and it replaces itself. The cheapest possible experiment for turning
   Valiant on if Rockface Village proves too slow.
8. **Verify Giant Cindermaw in Arena's own deckbuilder.** The local card data reports it Standard
   legal (it's a BRO printing), and `validate_deck` accepts it, but it's worth 10 seconds of
   sanity-checking before spending 2 uncommon wildcards.
9. **Attribute matches to decks.** Match rows currently store `deck_id = null`, which is why
   `get_deck_stats` shows 0 games on the deck. Identifying games by decklist fingerprint works but
   is manual; fixing the attribution would make every future diagnosis much cheaper.

---

## Appendix — how this was checked

- **Pool coverage is complete, not sampled.** `get_deck_candidates(format='standard', colors='R',
  limit=3000)` returned `total_matching: 190, truncated: false` for owned cards and
  `total_matching: 1035, truncated: false` including unowned; both were read in full. An earlier
  `limit=400` call silently truncated five cards into MV 3 and hid the entire 3+ curve —
  **always check the `truncated` field.** Guttersnipe, Giant Cindermaw and Case of the Crimson
  Pulse were all in the hidden portion.
- **Every power/toughness, haste and keyword here was read from card data**, never inferred from
  oracle text or card name (standing rule). Cases where the real value changed the call: Giant
  Cindermaw is a 4/3 trampler **without haste**; Slickshot Show-Off is a **1/2** before pumps;
  Hired Claw is a **1/2**; Stormsplitter is a **1/4**; Slumbering Cerberus is a 4/2 that does not
  untap.
- **Standard legality was checked with `validate_deck`, not assumed.** It rejected Monstrous Rage,
  Heartfire Hero and Screaming Nemesis — all three were on the initial shortlist, and Screaming
  Nemesis would otherwise have been the headline anti-lifegain recommendation.
- **Match diagnosis used `get_match_plays`, not feel.** The land-drop table in §2.4 and the
  Fleeting Effigy recast counts are read off turn-by-turn play logs.
- **`owned` counts are a lower bound** — Arena stopped reporting collection contents in 2021 —
  so every "needs N wildcards" figure above is a ceiling, not a certainty.
- **Nothing was written back to Arena.** No deck was saved, imported, duplicated or annotated.

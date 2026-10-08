# Part 1 — SHODAN answerability audit (small, seeds 0 and 1)

## Step 1: my independent answers (written BEFORE opening the key or generator)

Method: read seed 0 in full by hand and solved it manually; then wrote
`scripts/part1_SHODAN_solve.py`, a parser over the TEXT only (no generator import),
which refuses to guess (every paragraph must match a known phrase; unknown ones are
listed). The parser reproduced my manual seed-0 answer exactly, then was applied to
seed 1 (one new phrase added: "A signed packaging waiver is in the booking envelope." =
signed). Seed 1's sole credited shipment was re-checked by hand from the quoted lines.

Rules applied (from "Closing instructions"): signed replacement lab report controls both
tests and the seal; amended agreement terms (all 9 agreements have a signed closing
amendment in both seeds); packaging OK iff own seal intact OR (waiver signed AND
agreement permits waivers); signed final carrier audit decides custody; credited units
= max(shipped - damaged - allowance, 0) x rate; contact radio name -> person ->
closing manager -> manager's closing office.

### Seed 0 — my answer

```json
{"Alderwick": 0, "Brindleford": 0, "Cairnstead": 0, "Dunmere": 0, "Elmbridge": 819, "Fenhurst": 1968, "Gorsehaven": 0}
```

Of 18 shipments, 12 are retained at closing; only 3 of those pass quality + packaging:

- **white pebble (FR-443486)** — booked Ashglass ("Sales compared Ashglass with
  Heathersteel; the former was executed"), waiver signed. Ashglass amendment: "Two
  successes are no more acceptable than two failures; one trial must pass and the other
  fail. The allowance becomes 7 units ... rate becomes 11". Signed lab: "The vibration
  and moisture trials were reconsidered in that order. The former met its limit; the
  latter failed. The dispatched crate's seal remained intact" -> exactly one, seal OK.
  Custody: "The former stayed with the consignee at closing". Accounts: "109 units, of
  which 6 are damaged"; "“Red Willow” was considered before “Blue Lantern”. The first was
  declined; the second is the responsible contact." Blue Lantern -> Victor Ross ->
  "Signed personnel correction — Victor Ross ... line manager is Estelle Gray" -> "The
  closing registration for Estelle Gray considered Elmbridge and Fenhurst. Only the
  latter was approved." => (109-6-7)x11 = **1056 -> Fenhurst**.
- **evening swan (FR-581326)** — booked Flintpaper. Amendment: "One successful trial
  suffices ... allowance becomes 2 ... rate becomes 6". Lab: both passed, "That seal was
  unbroken." Custody: "At closing the consignee still held the shipment." 159 shipped,
  5 damaged; "Silver Heron" accepted -> Pavel Stone -> Julian Lowe (signed correction) ->
  "use Fenhurst" => (159-5-2)x6 = **912 -> Fenhurst**.
- **azure lily (FR-500429)** — booked Glimmerwood. Amendment: "Exactly one ... allowance
  becomes 2 ... rate becomes 9". Lab: "The former [moisture] passed; the latter
  [vibration] failed. ... The former [sample box] had a torn seal; the latter did not."
  Custody: still held. 97 shipped, 4 damaged; "Lilac Bridge" accepted -> Felix Reed ->
  closing review: Imogen Keene -> "Imogen Keene considered Alderwick and Elmbridge. Only
  the latter was approved." => (97-4-2)x9 = **819 -> Elmbridge**.

Retained but failing: silver elm (Birchstone exactly-one, both failed), narrow candle
(Embercloth both, M failed), granite sparrow, fern elm, narrow orchard (both failed),
red gull / narrow heron (Cloudweave both, one failed), ancient lark (Heathersteel both),
narrow gate (Embercloth both). Not retained: rose harbor, dusk fox, azure willow,
soft flute, ochre wren, emerald hill. Full per-shipment table = script output.

### Seed 1 — my answer

```json
{"Alderwick": 0, "Brindleford": 0, "Cairnstead": 0, "Dunmere": 0, "Elmbridge": 365, "Fenhurst": 0, "Gorsehaven": 0}
```

Only **clear brook (FR-243204)** earns credit:
"Sales compared Glimmerwood with Birchstone; the former was executed" / "A packaging
waiver was requested but never signed." Amendment: "Signed closing amendment to
Glimmerwood. ... Neither trial may fail ... allowance becomes 5 ... rate becomes 5".
Signed lab: "The former met its limit; the latter passed. ... The former had a torn
seal; the latter did not." (crate intact). Custody: "At closing the consignee still held
the shipment." Accounts: "87 units, of which 9 are damaged"; "“Harbor Moon” was
considered before “Yellow Harbor”. The first was declined; the second is the responsible
contact." Yellow Harbor -> Cora Wells -> "Signed personnel correction — Cora Wells ...
line manager is Julian Lowe" -> "Signed office correction for Julian Lowe: use
Elmbridge" => (87-9-5)x5 = **365 -> Elmbridge**.

The other 17 fail on custody, quality, or packaging (several near-misses: white basket,
moss birch, moss crane, bronze meadow, red basket, silver sparrow pass quality+packaging
but were not retained; golden river/navy bridge retained but fail quality/packaging).

Text oddity noticed while solving (both seeds): signed personnel corrections say
"the line manager is X, not Y" where Y is NOT the provisional manager on the directory
card (seed 0: Victor Ross card says Brennan Cole, correction says "not Hadrian Jones";
seed 1: Cora Wells card says Amira Bell, correction says "not Hadrian Jones"). Harmless
to the answer (X is unambiguous) but it is a contradiction a careful reader may stall on.

## Step 2: comparison with the key (opened only after Step 1 was written)

| Seed | My answer | Key | Match |
|---|---|---|---|
| 0 | Elmbridge 819, Fenhurst 1968, rest 0 | Elmbridge 819, Fenhurst 1968, rest 0 | exact |
| 1 | Elmbridge 365, rest 0 | Elmbridge 365, rest 0 | exact |
| 2 (parser only) | Dunmere 1209, rest 0 | same | exact |
| 3 (parser only) | Cairnstead 830, Elmbridge 120 | same | exact |
| 4 (parser only) | Alderwick 552, Cairnstead 356, Fenhurst 176 | same | exact |

The text-only parser (`scripts/part1_SHODAN_solve.py`) never imports the generator and
reports zero unrecognized paragraphs on seeds 0-4; it agrees with the key on all five.
Generator truth logic (SHODAN.py lines 550-570) applies exactly the rules stated in the
closing instructions (lines ~95-125): retained AND quality gate AND (seal OR signed
waiver AND agreement permits), units minus damaged minus allowance, x rate, attributed
via radio -> person -> final manager -> final office.

## Step 3: classification

| Seed | Classification |
|---|---|
| 0 | **HARD-BUT-FAIR** — key correct and fully derivable; 18 shipments x ~6 rule layers, with many inverted/negated phrasings ("The former ...; the latter ..." with stated order, "the allegation that X failed was withdrawn"). |
| 1 | **HARD-BUT-FAIR** — same; only 1 of 18 shipments earns credit. |

### Findings (none change the key)

1. **Cosmetic contradiction in personnel corrections** — SHODAN.py line 264-268:
   `alternate = _different(rng, MANAGERS, final)` is a random manager, rendered as
   "the line manager is {final}, not {alternate}", so the "not X" name usually differs
   from the provisional manager on the directory card (seed 0 Victor Ross: card Brennan
   Cole, correction "not Hadrian Jones"; seed 1 Cora Wells: card Amira Bell, "not
   Hadrian Jones"). Answer unaffected; may cost a model a hesitation. Fix: use
   `initial_managers[person]` as `alternate` when it differs from `final`.
2. **Sparse truth at small** (systematic, not a defect): over seeds 0-19 small, only
   1-4 of 18 shipments are eligible and 0-3 of 7 offices are non-zero (seed 10 small is
   all zeros). The scorer (lines 619-690) requires all seven totals exact, so an all-zero
   guess does not get partial credit, but one missed shipment zeroes the cell. Medium has
   13-28 eligible shipments.
3. Model failures on SHODAN at small in #22 are therefore attributable to difficulty
   (and possibly scorer format strictness — see Part 2), not to an underivable or wrong
   key.

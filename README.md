# ATP Fantasy Credit Arbitrage Python CLI

A manual-confirmation tool for ATP Fantasy credit arbitrage.

It does **not** log in, click buttons, save teams, or submit switches. You keep your Fantasy team/prices in a local text file, and the script can now pull ATP Live Rankings directly from:

```text
https://www.atptour.com/en/rankings/singles/live
```

The script then simulates staged match outcomes and prints the manual switch queue: who to sell, who to buy, who to hold, projected team value, and switches needed.

---

## Quick start

Run this from the repo folder:

```bash
python atp_arb_cli.py --fetch-live
```

That will:

1. Fetch ATP Live Rankings from the ATP website.
2. Overwrite `rankings.csv` with the latest parsed live rankings.
3. Read your local `fantasy_state.txt`.
4. Read staged outcomes from `scenario.txt`.
5. Print the recommended manual switches.

To only refresh `rankings.csv` and stop:

```bash
python atp_arb_cli.py --fetch-live --dump-rankings-only
```

To fetch more than the top 100:

```bash
python atp_arb_cli.py --fetch-live --rank-limit 150
```

---

## `fantasy_state.txt`

You still need to update this manually because it contains your private Fantasy team, remaining budget, and visible Fantasy credit prices.

```text
Budget: 7
Free switches: 2
Switches made: 7
Switch cost: -250

Team:
Sinner 40
Rublev 9
Darderi 8
Zverev 36
Davidovich Fokina 8
Djokovic 21
Hurkacz 3
Basilashvili 1

Players:
Sinner 40
Zverev 36
Auger-Aliassime 30
de Minaur 27
Shelton 24
Medvedev 21
Djokovic 21
Cobolli 17
Fritz 15
Bublik 14
Lehecka 13
Ruud 12
Musetti 11
Tien 10
Rublev 9
Darderi 8
Davidovich Fokina 8
Mensik 8
Tiafoe 8
Mpetshi Perricard 2
Hurkacz 3
Basilashvili 1
```

The `Players:` section is important because ATP Fantasy credits are not always a simple formula from ranking alone. Add as many visible Fantasy player prices as possible. Any missing players use the built-in fallback price-band model.

---

## ATP Fantasy Player Prices

Prices are based on players’ ranking position in the Official PIF ATP Live Rankings (Singles). The script uses this table as the fallback credit model when a player is missing from your pasted `Players:` section.

| Ranking position | Credits |
|---:|---:|
| World No. 1 | 40 |
| World No. 2 | 36 |
| World No. 3 | 33 |
| World No. 4 | 30 |
| World No. 5 | 27 |
| World No. 6 | 24 |
| World No. 7 | 21 |
| World No. 8 | 19 |
| World No. 9 | 17 |
| World No. 10 | 15 |
| World No. 11 | 14 |
| World No. 12 | 13 |
| World No. 13 | 12 |
| World No. 14 | 11 |
| World No. 15 | 10 |
| World No. 16 | 9 |
| World No. 17–20 | 8 |
| World No. 21–25 | 7 |
| World No. 26–30 | 6 |
| World No. 31–36 | 5 |
| World No. 37–49 | 4 |
| World No. 50–74 | 3 |
| World No. 75–100 | 2 |
| From World No. 101 | 1 |

Note: World No. 16 is listed separately at 9 credits, so the next shared band starts at World No. 17.

---

## `rankings.csv`

You can now generate this automatically:

```bash
python atp_arb_cli.py --fetch-live --dump-rankings-only
```

Generated format:

```csv
rank,player,current,next
1,Jannik Sinner,12750,13450
2,Alexander Zverev,8480,9180
3,Carlos Alcaraz,8160,
```

`current` = current ATP live-ranking points.  
`next` = the ATP page's next/max projection field when available. If blank, the player has no next projection on the page.

---

## `scenario.txt`

One update stage per line.

```text
Djokovic=win
Cobolli=win, Fritz=win
```

Separate lines mean the site may update prices after each stage. Same line means you are treating those results as one batched update.

Short names such as `Djokovic=win`, `Fritz=win`, and `Cobolli=win` work as long as they uniquely match the rankings file.

You can also enter explicit projected points:

```text
Djokovic=4260
Cobolli=3860, Fritz=3765
```

---

## Common commands

Use live ATP data and run optimiser:

```bash
python atp_arb_cli.py --fetch-live
```

Use an already saved rankings file:

```bash
python atp_arb_cli.py --fantasy fantasy_state.txt --rankings rankings.csv --scenario scenario.txt
```

Refresh rankings only:

```bash
python atp_arb_cli.py --fetch-live --dump-rankings-only
```

Fetch top 150 instead of top 100:

```bash
python atp_arb_cli.py --fetch-live --rank-limit 150
```

Include a credit-equivalent switch penalty in the optimiser objective:

```bash
python atp_arb_cli.py --fetch-live --points-aware --switch-penalty-credit 2
```

---

## Recommended arbitrage workflow

Use it one stage at a time.

1. Before Djokovic plays, put this in `scenario.txt`:
   ```text
   Djokovic=win
   ```
2. Run:
   ```bash
   python atp_arb_cli.py --fetch-live
   ```
3. Make the manual switches it recommends.
4. When ATP Fantasy prices update, edit `fantasy_state.txt` to your new team/prices.
5. Before Cobolli/Fritz play, put this in `scenario.txt`:
   ```text
   Cobolli=win, Fritz=win
   ```
6. Run the script again.

This keeps the process manual-confirmation only and avoids automated contest actions.

---

## Notes

- The ATP page structure can change. If the fetcher fails, manually update `rankings.csv` using the same columns.
- The script uses only Python standard-library modules. No `pip install` is required.
- The tool estimates Fantasy credit movement from ranking-band movement and visible Fantasy price data. It is not an official ATP Fantasy product.

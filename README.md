# ATP Fantasy Credit Arbitrage Python CLI

This is the easier alternative to the browser extension.

It does **not** log in, click buttons, or submit switches.  
You paste your team/prices and the ATP Live Ranking points into simple files, then the script tells you the manual switches to make.

## 1. Files

### `fantasy_state.txt`

Use this format:

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

The `Players:` section is important. Add as many visible Fantasy players/prices as possible.  
The more prices you paste, the better the projected credit mapping.

### `rankings.csv`

Use this format:

```csv
rank,player,current,next
4,Felix Auger-Aliassime,4740,5140
5,Alex de Minaur,4110,
6,Ben Shelton,3770,
7,Novak Djokovic,3760,4260
8,Daniil Medvedev,3670,
9,Flavio Cobolli,3460,3860
10,Taylor Fritz,3365,3765
```

`current` = current ATP Live Ranking points.  
`next` = what ATP shows if the player wins the next match. Leave blank if out or no next projection.

### `scenario.txt`

One update stage per line.

```text
Djokovic=win
Cobolli=win, Fritz=win
```

Separate lines = one result updates before the next.  
Same line = batched update.

Short names such as `Djokovic=win`, `Fritz=win` and `Cobolli=win` work as long as they uniquely match the rankings file.

You can also enter explicit projected points:

```text
Djokovic=4260
Cobolli=3860, Fritz=3765
```

## 2. Run

Open Command Prompt or Terminal inside this folder and run:

```bash
python atp_arb_cli.py --fantasy fantasy_state.txt --rankings rankings.csv --scenario scenario.txt
```

## 3. How to read the output

The script prints:

- which owned players are projected to rise/fall
- which players to sell
- which players to buy
- the target team
- projected team value
- switches needed

## 4. Recommended workflow

Use it one stage at a time.

Example:

1. Before Djokovic plays, run `scenario.txt` with:
   ```text
   Djokovic=win
   ```
2. Make the recommended manual switches.
3. When Djokovic's Fantasy price updates, edit `fantasy_state.txt` to your new team/prices.
4. Then run:
   ```text
   Cobolli=win, Fritz=win
   ```

This is more reliable than trying to automate the website.

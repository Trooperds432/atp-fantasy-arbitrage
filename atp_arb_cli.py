#!/usr/bin/env python3
"""ATP Fantasy credit-arbitrage CLI.

Manual-confirmation tool only: it never logs in, clicks, saves, or submits
switches. It can now fetch ATP Live Rankings directly from:
https://www.atptour.com/en/rankings/singles/live

Workflow:
  1) Keep fantasy_state.txt updated with your Fantasy team/prices.
  2) Run with --fetch-live to refresh rankings.csv from ATP.
  3) Put staged outcomes in scenario.txt.
  4) Read the recommended manual sell/buy queue.
"""
from __future__ import annotations

import argparse
import csv
import html as html_lib
import re
import sys
import unicodedata
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

ATP_LIVE_URL = "https://www.atptour.com/en/rankings/singles/live"

TOP16_CREDITS = {
    1: 40, 2: 35, 3: 33, 4: 30, 5: 27, 6: 24, 7: 21, 8: 19,
    9: 17, 10: 15, 11: 14, 12: 13, 13: 12, 14: 11, 15: 10, 16: 9,
}


# ---------------------------------------------------------------------------
# Fantasy credit model
# ---------------------------------------------------------------------------

def fallback_credit(rank: int) -> int:
    """Fallback ATP Fantasy credit band if a Fantasy price is not pasted."""
    if rank in TOP16_CREDITS:
        return TOP16_CREDITS[rank]
    if 17 <= rank <= 20:
        return 8
    if 21 <= rank <= 25:
        return 7
    if 26 <= rank <= 30:
        return 6
    if 31 <= rank <= 36:
        return 5
    if 37 <= rank <= 50:
        return 4
    if 51 <= rank <= 100:
        return 3
    if 101 <= rank <= 150:
        return 2
    return 1


def norm(name: str) -> str:
    name = unicodedata.normalize("NFKD", name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = re.sub(r"[^a-z0-9]+", " ", name.lower())
    return " ".join(name.split())


def number(text: str) -> int:
    m = re.search(r"[+-]?\d+(?:\.\d+)?", text.replace(",", "").replace("−", "-"))
    if not m:
        raise ValueError(f"No number found in {text!r}")
    return int(float(m.group(0)))


def resolve(query: str, keys: Iterable[str]) -> Optional[str]:
    keys = list(keys)
    q = norm(query)
    if q in keys:
        return q
    parts = q.split()
    q_last = parts[-1] if parts else q
    hits = []
    for k in keys:
        k_parts = k.split()
        if k_parts and (k_parts[-1] == q_last or k.endswith(" " + q) or q in k):
            hits.append(k)
    return hits[0] if len(hits) == 1 else None


@dataclass
class Price:
    name: str
    credit: int


@dataclass
class Ranking:
    name: str
    points: int
    next_points: Optional[int] = None
    rank: Optional[int] = None


@dataclass
class Fantasy:
    budget: int
    free_switches: int
    switches_made: int
    switch_cost: int
    team: Dict[str, Price]
    players: Dict[str, Price]


# ---------------------------------------------------------------------------
# ATP website extraction
# ---------------------------------------------------------------------------

def fetch_url(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def html_to_lines(raw_html: str) -> List[str]:
    """Convert ATP HTML into a stable text-line stream for row parsing."""
    text = re.sub(r"(?is)<script.*?</script>", " ", raw_html)
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"(?is)<noscript.*?</noscript>", " ", text)

    # Force line breaks around common block/table elements before stripping tags.
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(
        r"(?i)</?(tr|td|th|li|ul|ol|div|p|section|article|h[1-6]|span|a)[^>]*>",
        "\n",
        text,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = text.replace("\u00a0", " ")
    out: List[str] = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            out.append(line)
    return out


BAD_NAME_PREFIXES = (
    "image", "headshot", "tournament", "defeated", "lost", "withdrawn", "retired",
    "walkover", "live rank", "player", "official", "current tournament", "rank range",
)
BAD_NAME_EXACT = {
    "wimbledon", "newport", "braunschweig", "stuttgart", "halle", "london",
    "singles", "doubles", "live", "refresh", "age", "profile", "latest",
}


def _looks_like_player_name(line: str) -> bool:
    low = line.lower().strip()
    if low in BAD_NAME_EXACT:
        return False
    if any(low.startswith(p) for p in BAD_NAME_PREFIXES):
        return False
    if "{{" in line or "}}" in line:
        return False
    if re.search(r"\d", line):
        return False
    # Accept names like "Jannik Sinner", "A. Zverev", "Alex de Minaur".
    if not re.search(r"[A-Za-z]", line):
        return False
    words = [w for w in re.split(r"\s+", line) if w]
    if len(words) < 2:
        return False
    if len(line) > 45:
        return False
    return True


def _extract_int_tokens(line: str) -> List[int]:
    # Remove round labels so R128/R64 do not contaminate point extraction.
    cleaned = re.sub(r"\bR\d+\b", " ", line, flags=re.IGNORECASE)
    tokens = re.findall(r"[+-]?\d{1,3}(?:,\d{3})*|[+-]?\d+", cleaned.replace("−", "-"))
    vals: List[int] = []
    for tok in tokens:
        try:
            vals.append(int(tok.replace(",", "")))
        except ValueError:
            pass
    return vals


def parse_atp_live_rankings_html(raw_html: str, rank_limit: int = 100) -> List[Ranking]:
    """Parse ATP live rankings page into Ranking rows.

    The ATP page exposes both a compact table and a full table in the HTML. This
    parser prefers the full table because it contains full player names. It uses
    sequential rank markers (1, 2, 3...) to avoid confusing player ages with ranks.
    """
    lines = html_to_lines(raw_html)

    header_idx = None
    for i, line in enumerate(lines):
        low = line.lower()
        if "live rank" in low and "official points" in low and "next" in low:
            header_idx = i
            break
    if header_idx is None:
        for i, line in enumerate(lines):
            low = line.lower()
            if "live rank" in low and "next" in low and "max points" in low:
                header_idx = i
                break
    if header_idx is None:
        raise RuntimeError("Could not find ATP live-ranking table header in page HTML")

    rows: List[Ranking] = []
    pos = header_idx + 1
    expected_rank = 1

    def find_rank(start: int, target: int) -> Optional[int]:
        needle = str(target)
        for j in range(start, len(lines)):
            if lines[j] == needle:
                return j
        return None

    start = find_rank(pos, expected_rank)
    while start is not None and expected_rank <= rank_limit:
        next_start = find_rank(start + 1, expected_rank + 1)
        block = lines[start + 1: next_start if next_start is not None else min(len(lines), start + 80)]

        name = None
        name_idx = 0
        for bi, bline in enumerate(block):
            if _looks_like_player_name(bline):
                name = bline
                name_idx = bi
                break

        # Pull numeric tokens after the name, skipping age-only lines.
        nums: List[int] = []
        for bline in block[name_idx + 1:]:
            if re.fullmatch(r"\d{1,2}", bline.strip()):
                continue  # age
            vals = _extract_int_tokens(bline)
            if vals:
                nums.extend(vals)

        # In the full table, the first numeric token after the name/status is live points.
        # Then official points, +/- and optionally next/max points follow.
        if name and nums:
            live_points = nums[0]
            next_points = None
            if len(nums) >= 5:
                # current, official, delta, next, max
                next_points = nums[-2]
            elif len(nums) == 4:
                # compact active row: current, delta, next, max
                next_points = nums[-2]
            rows.append(Ranking(name=name, points=live_points, next_points=next_points, rank=expected_rank))

        expected_rank += 1
        if next_start is None:
            break
        start = next_start

    if not rows:
        raise RuntimeError("ATP page was fetched, but no ranking rows were parsed")
    return rows[:rank_limit]


def fetch_atp_live_rankings(url: str = ATP_LIVE_URL, rank_limit: int = 100) -> List[Ranking]:
    return parse_atp_live_rankings_html(fetch_url(url), rank_limit=rank_limit)


def write_rankings_csv(rankings: List[Ranking], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "player", "current", "next"])
        for r in rankings:
            writer.writerow([r.rank or "", r.name, r.points, r.next_points if r.next_points is not None else ""])


# ---------------------------------------------------------------------------
# Local file parsing
# ---------------------------------------------------------------------------

def parse_name_credit(line: str) -> Optional[Tuple[str, int]]:
    line = line.strip().replace("—", "-").replace("–", "-")
    if not line or line.startswith("#"):
        return None
    m = re.search(r"(-?\d+)\s*$", line)
    if not m:
        return None
    name = line[:m.start()].strip(" ,:-\t")
    return (name, int(m.group(1))) if name else None


def parse_fantasy(path: Path) -> Fantasy:
    budget = free = made = cost = 0
    team: Dict[str, Price] = {}
    players: Dict[str, Price] = {}
    section = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        low = line.lower()
        if low.startswith("budget"):
            budget = number(line.split(":", 1)[-1]); continue
        if low.startswith("free switch"):
            free = number(line.split(":", 1)[-1]); continue
        if low.startswith("switches made"):
            made = number(line.split(":", 1)[-1]); continue
        if low.startswith("switch cost"):
            cost = number(line.split(":", 1)[-1]); continue
        if low.rstrip(":") in {"team", "selected", "selected team"}:
            section = "team"; continue
        if low.rstrip(":") in {"players", "player list", "available", "available players"}:
            section = "players"; continue

        parsed = parse_name_credit(line)
        if not parsed:
            continue
        name, credit = parsed
        key = norm(name)
        if section == "team":
            team[key] = Price(name, credit)
            players[key] = Price(name, credit)
        else:
            players[key] = Price(name, credit)

    if not team:
        raise ValueError("fantasy_state.txt needs a Team: section with 8 player/credit lines")
    if len(team) != 8:
        print(f"WARNING: Team has {len(team)} players, expected 8", file=sys.stderr)
    return Fantasy(budget, free, made, cost, team, players)


def parse_rankings(path: Path) -> Dict[str, Ranking]:
    out: Dict[str, Ranking] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = {c.lower().strip(): c for c in (reader.fieldnames or [])}
        if "player" not in fields:
            raise ValueError("rankings.csv requires a player column")
        curr_col = fields.get("current") or fields.get("current_points") or fields.get("points") or fields.get("live_points")
        next_col = fields.get("next") or fields.get("next_points") or fields.get("if_win") or fields.get("next_win")
        rank_col = fields.get("rank")
        if not curr_col:
            raise ValueError("rankings.csv requires current/points/live_points column")
        for row in reader:
            name = (row.get(fields["player"]) or "").strip()
            if not name:
                continue
            pts = number(row.get(curr_col, "0"))
            nxt = None
            raw_next = (row.get(next_col, "") if next_col else "").strip()
            if raw_next and raw_next not in {"-", "—"}:
                try:
                    nxt = number(raw_next)
                except ValueError:
                    pass
            rnk = None
            raw_rank = (row.get(rank_col, "") if rank_col else "").strip()
            if raw_rank:
                try:
                    rnk = number(raw_rank)
                except ValueError:
                    pass
            out[norm(name)] = Ranking(name, pts, nxt, rnk)
    if not out:
        raise ValueError("No ranking rows parsed")
    return out


def canonicalise(fantasy: Fantasy, rankings: Dict[str, Ranking]) -> Fantasy:
    def rekey(src: Dict[str, Price]) -> Dict[str, Price]:
        dst = {}
        for key, price in src.items():
            dst[resolve(key, rankings.keys()) or key] = price
        return dst
    fantasy.team = rekey(fantasy.team)
    fantasy.players = rekey(fantasy.players)
    for key, price in fantasy.team.items():
        fantasy.players.setdefault(key, price)
    return fantasy


def parse_scenario(path: Path) -> List[List[Tuple[str, str]]]:
    stages: List[List[Tuple[str, str]]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        stage = []
        for part in line.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" not in part:
                raise ValueError(f"Bad scenario item {part!r}; use Name=win or Name=points")
            name, val = part.split("=", 1)
            stage.append((name.strip(), val.strip().lower()))
        if stage:
            stages.append(stage)
    if not stages:
        raise ValueError("scenario.txt has no stages")
    return stages


# ---------------------------------------------------------------------------
# Simulation and optimisation
# ---------------------------------------------------------------------------

def sort_rankings(rankings: Dict[str, Ranking], points: Dict[str, int]) -> List[Tuple[str, Ranking, int]]:
    rows = [(k, r, points.get(k, r.points)) for k, r in rankings.items()]
    rows.sort(key=lambda x: (-x[2], x[1].rank if x[1].rank is not None else 9999, x[1].name))
    return rows


def rank_price_schedule(rankings: Dict[str, Ranking], prices: Dict[str, Price], points: Dict[str, int]) -> Dict[int, int]:
    sched = {}
    for i, (key, _, _) in enumerate(sort_rankings(rankings, points), 1):
        sched[i] = prices[key].credit if key in prices else fallback_credit(i)
    return sched


def simulate(
    rankings: Dict[str, Ranking],
    points: Dict[str, int],
    stage: List[Tuple[str, str]],
    schedule: Dict[int, int],
) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int]]:
    new_points = dict(points)
    for name, value in stage:
        key = resolve(name, rankings.keys())
        if key is None:
            print(f"WARNING: {name!r} not found or ambiguous in rankings", file=sys.stderr)
            continue
        row = rankings[key]
        if value == "win":
            if row.next_points is None:
                print(f"WARNING: no next-points for {row.name}; unchanged", file=sys.stderr)
                continue
            new_points[key] = row.next_points
        elif value.startswith("current+"):
            new_points[key] = points.get(key, row.points) + number(value.replace("current+", ""))
        else:
            new_points[key] = number(value)

    ranks: Dict[str, int] = {}
    credits: Dict[str, int] = {}
    for i, (key, _, _) in enumerate(sort_rankings(rankings, new_points), 1):
        ranks[key] = i
        credits[key] = schedule.get(i, fallback_credit(i))
    return new_points, ranks, credits


def optimise(
    fantasy: Fantasy,
    rankings: Dict[str, Ranking],
    projected: Dict[str, int],
    current_credit: Dict[str, int],
    credit_only: bool,
    penalty_credit: int,
    hold_risers: bool,
    sell_fallers: bool,
) -> Tuple[List[str], Dict[str, int | List[str] | str]]:
    team = set(fantasy.team)
    total_budget = sum(p.credit for p in fantasy.team.values()) + fantasy.budget
    required: Set[str] = set()
    forbidden: Set[str] = set()

    for key in team:
        cur = current_credit.get(key, fantasy.team[key].credit)
        proj = projected.get(key, cur)
        if hold_risers and proj > cur:
            required.add(key)
        if sell_fallers and proj < cur:
            forbidden.add(key)
    forbidden -= required

    candidates: Dict[str, Tuple[int, int]] = {}
    base_points = {k: r.points for k, r in rankings.items()}
    current_rank = {k: i for i, (k, _, _) in enumerate(sort_rankings(rankings, base_points), 1)}
    for key, price in fantasy.players.items():
        cur = current_credit.get(key, price.credit)
        candidates[key] = (cur, projected.get(key, cur))
    for key in rankings:
        if key not in candidates:
            cost = fallback_credit(current_rank.get(key, 999))
            candidates[key] = (cost, projected.get(key, cost))

    chosen: List[str] = []
    spent = value = new_count = 0
    for key in required:
        if key not in candidates:
            continue
        cost, val = candidates[key]
        chosen.append(key); spent += cost; value += val
        if key not in team:
            new_count += 1

    slots = 8 - len(chosen)
    budget_left = total_budget - spent
    if slots < 0 or budget_left < 0:
        return chosen, {"error": "required risers exceed budget"}

    dp: Dict[Tuple[int, int, int], Tuple[int, List[str]]] = {(0, 0, 0): (0, [])}
    for key, (cost, val) in candidates.items():
        if key in required or key in forbidden or cost > budget_left:
            continue
        is_new = int(key not in team)
        ndp = dict(dp)
        for (cnt, cst, nw), (raw, picks) in dp.items():
            if cnt + 1 > slots or cst + cost > budget_left:
                continue
            state = (cnt + 1, cst + cost, nw + is_new)
            cand = (raw + val, picks + [key])
            if state not in ndp or cand[0] > ndp[state][0]:
                ndp[state] = cand
        dp = ndp

    best_score = -10**9
    best_raw = -10**9
    best_picks: List[str] = []
    best_cost = best_new = 0
    for (cnt, cst, nw), (raw, picks) in dp.items():
        if cnt != slots:
            continue
        total_new = nw + new_count
        excess = max(0, total_new - fantasy.free_switches)
        score = value + raw - (0 if credit_only else excess * penalty_credit)
        if score > best_score:
            best_score = score
            best_raw = value + raw
            best_picks = chosen + picks
            best_cost = spent + cst
            best_new = total_new

    return best_picks, {
        "total_budget": total_budget,
        "team_cost_now": best_cost,
        "cash_left": total_budget - best_cost,
        "projected_team_value": best_raw,
        "switches_needed": best_new,
        "free_switches": fantasy.free_switches,
        "excess_switches": max(0, best_new - fantasy.free_switches),
        "required": sorted(required),
        "forbidden": sorted(forbidden),
    }


def dname(key: str, fantasy: Fantasy, rankings: Dict[str, Ranking]) -> str:
    return fantasy.players.get(key, Price(rankings.get(key, Ranking(key, 0)).name, 0)).name


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="ATP Fantasy credit-arbitrage manual switch recommender")
    ap.add_argument("--fantasy", default="fantasy_state.txt", help="Fantasy team/prices text file")
    ap.add_argument("--rankings", default="rankings.csv", help="ATP rankings CSV file")
    ap.add_argument("--scenario", default="scenario.txt", help="Scenario stages file")
    ap.add_argument("--fetch-live", action="store_true", help="Fetch ATP Live Rankings and overwrite --rankings before running")
    ap.add_argument("--atp-url", default=ATP_LIVE_URL, help="ATP live rankings URL")
    ap.add_argument("--rank-limit", type=int, default=100, help="Number of live-ranking rows to fetch")
    ap.add_argument("--dump-rankings-only", action="store_true", help="Fetch/write rankings.csv, then exit")
    ap.add_argument("--points-aware", action="store_true", help="Include switch penalty in objective")
    ap.add_argument("--switch-penalty-credit", type=int, default=0, help="Credit-equivalent penalty per excess switch if --points-aware")
    ap.add_argument("--no-auto-hold-risers", action="store_true", help="Do not force-hold owned players projected to rise")
    ap.add_argument("--no-auto-sell-fallers", action="store_true", help="Do not force-sell owned players projected to fall")
    args = ap.parse_args()

    rankings_path = Path(args.rankings)
    if args.fetch_live:
        rows = fetch_atp_live_rankings(args.atp_url, rank_limit=args.rank_limit)
        write_rankings_csv(rows, rankings_path)
        print(f"Fetched {len(rows)} ATP live-ranking rows -> {rankings_path}")
        if args.dump_rankings_only:
            return 0

    fantasy = parse_fantasy(Path(args.fantasy))
    rankings = parse_rankings(rankings_path)
    fantasy = canonicalise(fantasy, rankings)
    stages = parse_scenario(Path(args.scenario))

    points = {k: r.points for k, r in rankings.items()}
    current_credit = {k: p.credit for k, p in fantasy.players.items()}
    schedule = rank_price_schedule(rankings, fantasy.players, points)
    team_value = sum(p.credit for p in fantasy.team.values())

    print("\nATP Fantasy Credit Arbitrage CLI")
    print("=" * 72)
    print(f"Team value now: {team_value}")
    print(f"Cash budget:    {fantasy.budget}")
    print(f"Total budget:   {team_value + fantasy.budget}")
    print(f"Free switches:  {fantasy.free_switches}")
    print("Team: " + ", ".join(p.name for p in fantasy.team.values()))
    print("=" * 72)

    for i, stage in enumerate(stages, 1):
        label = []
        for name, val in stage:
            key = resolve(name, rankings.keys())
            label.append(f"{rankings[key].name if key else name}={val}")
        print(f"\nSTAGE {i}: " + ", ".join(label))
        new_points, ranks, proj = simulate(rankings, points, stage, schedule)

        rows = []
        current_ranks = {k: i for i, (k, _, _) in enumerate(sort_rankings(rankings, points), 1)}
        for key in set(rankings) | set(fantasy.players):
            cur = current_credit.get(key, fallback_credit(current_ranks.get(key, 999)))
            pr = proj.get(key, cur)
            delta = pr - cur
            owned = key in fantasy.team
            if owned or delta != 0:
                rows.append((delta, owned, key, cur, pr, ranks.get(key), new_points.get(key, points.get(key, 0))))
        rows.sort(key=lambda x: (-x[0], not x[1], x[5] or 9999, dname(x[2], fantasy, rankings)))

        print("\nCredit movement watch:")
        print(f"{'OWN':<4} {'Player':<28} {'Now':>4} {'Proj':>5} {'Δ':>4} {'Rank':>5} {'Pts':>7}")
        print("-" * 72)
        for delta, owned, key, cur, pr, rank, pts in rows[:45]:
            print(f"{'YES' if owned else '':<4} {dname(key, fantasy, rankings):<28} {cur:>4} {pr:>5} {delta:+4d} {str(rank or '-'):>5} {pts:>7}")

        target, meta = optimise(
            fantasy, rankings, proj, current_credit,
            credit_only=not args.points_aware,
            penalty_credit=args.switch_penalty_credit,
            hold_risers=not args.no_auto_hold_risers,
            sell_fallers=not args.no_auto_sell_fallers,
        )
        if "error" in meta:
            print("\nOPTIMISER ERROR:", meta["error"])
            continue
        target_set = set(target)
        current_set = set(fantasy.team)
        sells = sorted(current_set - target_set, key=lambda k: dname(k, fantasy, rankings))
        buys = sorted(target_set - current_set, key=lambda k: dname(k, fantasy, rankings))
        holds = sorted(current_set & target_set, key=lambda k: dname(k, fantasy, rankings))

        print("\nRecommended manual switch queue:")
        print("SELL:\n  " + (", ".join(dname(k, fantasy, rankings) for k in sells) or "None"))
        print("BUY:\n  " + (", ".join(dname(k, fantasy, rankings) for k in buys) or "None"))
        print("HOLD:\n  " + (", ".join(dname(k, fantasy, rankings) for k in holds) or "None"))

        print("\nTarget team:")
        for key in sorted(target, key=lambda k: dname(k, fantasy, rankings)):
            cur = current_credit.get(key, fallback_credit(current_ranks.get(key, 999)))
            pr = proj.get(key, cur)
            print(f"  {dname(key, fantasy, rankings):<28} cost_now={cur:<3} projected={pr:<3} Δ={pr-cur:+d}")

        print("\nOptimiser summary:")
        for k in ["team_cost_now", "cash_left", "projected_team_value", "switches_needed", "free_switches", "excess_switches"]:
            print(f"  {k.replace('_', ' ').title():<23} {meta[k]}")
        if meta.get("forbidden"):
            print("  Auto-sell fallers:     " + ", ".join(dname(k, fantasy, rankings) for k in meta["forbidden"]))
        if meta.get("required"):
            print("  Auto-held risers:      " + ", ".join(dname(k, fantasy, rankings) for k in meta["required"]))

    print("\nDone. Manual-confirmation only; no switches were submitted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

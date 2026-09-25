import pandas as pd
import requests
import streamlit as st
from itertools import combinations, permutations


st.set_page_config(
    page_title="FPL Draft H2H",
    page_icon="⚽",
    layout="wide",
)

BASE_URL = "https://draft.premierleague.com/api"
FPL_BASE_URL = "https://fantasy.premierleague.com/api"
DEFAULT_LEAGUE_ID = 48609
CLOSE_GAME_DEFAULT = 5


# ============================================================
# API
# ============================================================

class FPLDraftAPI:
    def __init__(self, league_id: int):
        self.league_id = int(league_id)
        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/153 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://draft.premierleague.com/",
        })

    def get(self, path: str):
        url = f"{BASE_URL}/{path.lstrip('/')}"
        response = self.session.get(url, timeout=20)
        response.raise_for_status()
        return response.json()

    def get_optional(self, path: str):
        try:
            return self.get(path)
        except requests.RequestException:
            return {}

    def details(self):
        return self.get(
            f"league/{self.league_id}/details"
        )

    def choices(self):
        return self.get(
            f"draft/{self.league_id}/choices"
        )

    def transactions(self):
        # Public Draft endpoint used by the FPL site for
        # league transfer/waiver activity.
        return self.get_optional(
            f"draft/league/{self.league_id}/transactions"
        )

    def bootstrap_static(self):
        return self.get_optional(
            "bootstrap-static"
        )

    def entry_event(self, entry_id: int, gw: int):
        return self.get_optional(
            f"entry/{int(entry_id)}/event/{int(gw)}"
        )

    def event_live(self, gw: int):
        # Individual player GW points live on the regular FPL API, not the
        # Draft API. Element IDs are shared between FPL and FPL Draft.
        url = f"{FPL_BASE_URL}/event/{int(gw)}/live/"
        try:
            response = self.session.get(url, timeout=20)
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            return {}


# ============================================================
# API parsing
# ============================================================

def parse_entries(details):
    candidates = details.get(
        "league_entries",
        [],
    )

    rows = []

    for entry in candidates:
        if not isinstance(entry, dict):
            continue

        league_entry = entry.get("id")
        entry_id = entry.get("entry_id")

        if league_entry is None:
            continue

        first_name = (
            entry.get("player_first_name")
            or ""
        )

        last_name = (
            entry.get("player_last_name")
            or ""
        )

        team_name = (
            entry.get("entry_name")
            or ""
        )

        manager = (
            f"{first_name} {last_name}"
            .strip()
        )

        if not manager:
            manager = (
                team_name
                or f"Entry {league_entry}"
            )

        rows.append({
            "league_entry":
                int(league_entry),
            "entry_id":
                int(entry_id)
                if entry_id is not None
                else pd.NA,
            "manager":
                manager,
            "team_name":
                team_name,
        })

    return (
        pd.DataFrame(
            rows,
            columns=[
                "league_entry",
                "entry_id",
                "manager",
                "team_name",
            ],
        )
        .drop_duplicates(
            "league_entry"
        )
        .reset_index(
            drop=True
        )
    )


def get_scores_from_matches(details):
    rows = []

    for match in details.get(
        "matches",
        [],
    ):
        if not match.get(
            "started",
            False,
        ):
            continue

        gw = int(
            match["event"]
        )

        rows.append({
            "GW":
                gw,
            "league_entry":
                int(
                    match[
                        "league_entry_1"
                    ]
                ),
            "score":
                match[
                    "league_entry_1_points"
                ],
        })

        rows.append({
            "GW":
                gw,
            "league_entry":
                int(
                    match[
                        "league_entry_2"
                    ]
                ),
            "score":
                match[
                    "league_entry_2_points"
                ],
        })

    if not rows:
        return pd.DataFrame(
            columns=[
                "GW",
                "league_entry",
                "score",
            ]
        )

    return (
        pd.DataFrame(rows)
        .drop_duplicates(
            [
                "GW",
                "league_entry",
            ]
        )
        .sort_values(
            [
                "GW",
                "league_entry",
            ]
        )
        .reset_index(
            drop=True
        )
    )


def parse_matchups(details):
    """
    All fixtures supplied by the Draft API,
    including future gameweeks.
    """

    rows = []

    for match in details.get(
        "matches",
        [],
    ):
        event = match.get("event")

        entry_a = match.get(
            "league_entry_1"
        )

        entry_b = match.get(
            "league_entry_2"
        )

        if (
            event is None
            or entry_a is None
            or entry_b is None
        ):
            continue

        rows.append({
            "GW":
                int(event),
            "entry_a":
                int(entry_a),
            "entry_b":
                int(entry_b),
            "started":
                bool(
                    match.get(
                        "started",
                        False,
                    )
                ),
            "finished":
                bool(
                    match.get(
                        "finished",
                        False,
                    )
                ),
        })

    return (
        pd.DataFrame(
            rows,
            columns=[
                "GW",
                "entry_a",
                "entry_b",
                "started",
                "finished",
            ],
        )
        .drop_duplicates(
            [
                "GW",
                "entry_a",
                "entry_b",
            ]
        )
        .sort_values(
            [
                "GW",
                "entry_a",
                "entry_b",
            ]
        )
        .reset_index(
            drop=True
        )
    )


# ============================================================
# Player / transaction parsing
# ============================================================

def build_player_names(
    bootstrap_data,
):
    elements = bootstrap_data.get(
        "elements",
        [],
    )

    player_names = {}

    for player in elements:
        if not isinstance(
            player,
            dict,
        ):
            continue

        player_id = player.get("id")

        if player_id is None:
            continue

        web_name = (
            player.get("web_name")
            or ""
        )

        first_name = (
            player.get("first_name")
            or ""
        )

        second_name = (
            player.get("second_name")
            or ""
        )

        full_name = (
            f"{first_name} "
            f"{second_name}"
        ).strip()

        player_names[
            int(player_id)
        ] = (
            web_name
            or full_name
            or f"Player {player_id}"
        )

    return player_names


def extract_transaction_list(transaction_data):
    """Return the transaction rows from the Draft API response."""
    if isinstance(transaction_data, list):
        return transaction_data
    if isinstance(transaction_data, dict):
        value = transaction_data.get("transactions", [])
        return value if isinstance(value, list) else []
    return []


def parse_transactions(transaction_data, entries, player_names):
    """Normalize the actual Draft transaction schema without guessing field names."""
    raw = extract_transaction_list(transaction_data)

    columns = [
        "GW", "Manager", "entry_id", "kind", "result", "priority", "index",
        "element_in", "element_out", "Player in", "Player out", "Time",
    ]
    if not raw:
        return pd.DataFrame(columns=columns)

    manager_map = {
        int(row.entry_id): row.manager
        for row in entries.itertuples()
        if pd.notna(row.entry_id)
    }

    rows = []
    for t in raw:
        if not isinstance(t, dict):
            continue
        entry_id = t.get("entry")
        element_in = t.get("element_in")
        element_out = t.get("element_out")
        rows.append({
            "GW": t.get("event"),
            "Manager": manager_map.get(int(entry_id), "Unknown") if entry_id is not None else "Unknown",
            "entry_id": entry_id,
            "kind": t.get("kind", ""),
            "result": t.get("result", ""),
            "priority": t.get("priority"),
            "index": t.get("index"),
            "element_in": element_in,
            "element_out": element_out,
            "Player in": player_names.get(int(element_in), f"Player {element_in}") if element_in is not None else "",
            "Player out": player_names.get(int(element_out), f"Player {element_out}") if element_out is not None else "",
            "Time": t.get("added", ""),
        })

    df = pd.DataFrame(rows, columns=columns)
    for col in ["GW", "entry_id", "priority", "index", "element_in", "element_out"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return df


def build_initial_squads(choices_data):
    """Original 15-player squads keyed by global entry id."""
    squads = {}
    for choice in choices_data.get("choices", []):
        entry_id = choice.get("entry")
        element = choice.get("element")
        if entry_id is None or element is None:
            continue
        squads.setdefault(int(entry_id), set()).add(int(element))
    return squads


def analyse_waivers(transactions, choices_data):
    """
    Replay accepted moves to determine which denied-incoming (di) claims were
    genuinely viable when processed.

    A di is a genuine contested loss only when:
      * another manager won the same incoming player in that GW, and
      * the losing manager still owned element_out immediately before the
        winning acquisition was processed.

    This excludes duplicate claims by the eventual winner and claims already
    made impossible by that manager's earlier successful waiver.
    """
    if transactions.empty:
        return transactions.copy(), pd.DataFrame()

    tx = transactions.copy()
    tx["Outcome"] = ""
    tx.loc[(tx["kind"] == "f") & (tx["result"] == "a"), "Outcome"] = "Free agent"
    tx.loc[(tx["kind"] == "w") & (tx["result"] == "a"), "Outcome"] = "Successful waiver"
    tx.loc[(tx["kind"] == "w") & (tx["result"] == "do"), "Outcome"] = "Superseded waiver"
    tx.loc[(tx["kind"] == "w") & (tx["result"] == "di"), "Outcome"] = "Unavailable incoming"
    tx["Genuine failed waiver"] = False

    squads = {entry: set(players) for entry, players in build_initial_squads(choices_data).items()}
    contested_rows = []

    for gw in sorted(tx["GW"].dropna().astype(int).unique()):
        gw_tx = tx[tx["GW"] == gw]

        # Free-agent moves happen at their timestamps. They are replayed before
        # later GWs; within this GW they do not define waiver contention.
        waiver_tx = gw_tx[gw_tx["kind"] == "w"]
        winners = waiver_tx[(waiver_tx["result"] == "a") & waiver_tx["index"].notna()].sort_values("index")

        for winner in winners.itertuples():
            winner_entry = int(winner.entry_id)
            incoming = int(winner.element_in)
            outgoing = int(winner.element_out)
            winner_index = int(winner.index)

            # Squad state immediately BEFORE this successful waiver.
            losing_claimants = []
            candidates = waiver_tx[
                (waiver_tx["element_in"] == incoming)
                & (waiver_tx["result"] == "di")
                & (waiver_tx["entry_id"] != winner_entry)
                & (waiver_tx["index"].notna())
                & (waiver_tx["index"] > winner_index)
            ]

            for loser in candidates.itertuples():
                loser_entry = int(loser.entry_id)
                loser_out = int(loser.element_out)
                # If the outgoing player is still owned now, the claim would
                # have been executable but for the incoming player being gone.
                if loser_out in squads.get(loser_entry, set()):
                    losing_claimants.append(loser.Manager)
                    tx.loc[loser.Index, "Genuine failed waiver"] = True
                    tx.loc[loser.Index, "Outcome"] = "Failed waiver"

            if losing_claimants:
                unique_losers = list(dict.fromkeys(losing_claimants))
                contested_rows.append({
                    "GW": gw,
                    "Player": tx.loc[winner.Index, "Player in"],
                    "Winner": winner.Manager,
                    "Other claimants": ", ".join(unique_losers),
                    # Keep the list internally so summary statistics are derived
                    # from exactly the same genuine contests shown in this table.
                    "_losing_managers": unique_losers,
                })

            # Apply the successful waiver before considering later winners.
            squads.setdefault(winner_entry, set()).discard(outgoing)
            squads[winner_entry].add(incoming)

        # Apply accepted free-agent transfers after waiver processing for this GW.
        # They affect squad state going into the next waiver round.
        free_agents = gw_tx[(gw_tx["kind"] == "f") & (gw_tx["result"] == "a")].sort_values("Time")
        for move in free_agents.itertuples():
            entry = int(move.entry_id)
            squads.setdefault(entry, set()).discard(int(move.element_out))
            squads[entry].add(int(move.element_in))

    # di rows that were not viable contests are intentionally not failures.
    mask = (tx["kind"] == "w") & (tx["result"] == "di") & (~tx["Genuine failed waiver"])
    tx.loc[mask, "Outcome"] = "Non-viable waiver"

    contested = pd.DataFrame(
        contested_rows,
        columns=[
            "GW",
            "Player",
            "Winner",
            "Other claimants",
            "_losing_managers",
        ],
    )
    return tx, contested


def build_squad_activity_summary(transactions, contested, participant_order, names):
    """
    Build manager-level squad activity statistics.

    Contested wins and failed waivers are both derived from the final
    `contested` table, making that table the single source of truth.
    Therefore:

        Contested win % = Contested won / (Contested won + Failed waivers)

    Uncontested successful waivers do not enter the percentage.
    """
    managers = [
        names[e]
        for e in participant_order
        if names.get(e) != "Average"
    ]

    rows = []

    for manager in managers:
        own = transactions[transactions["Manager"] == manager]

        free_agents = int(
            ((own["kind"] == "f") & (own["result"] == "a")).sum()
        )
        successful = int(
            ((own["kind"] == "w") & (own["result"] == "a")).sum()
        )

        if contested.empty:
            contested_wins = 0
            failed = 0
        else:
            contested_wins = int((contested["Winner"] == manager).sum())

            # Count only genuine losing appearances in the same final
            # contested-waiver records used to count wins.
            failed = int(
                contested["_losing_managers"]
                .apply(lambda losers: manager in losers)
                .sum()
            )

        contested_total = contested_wins + failed
        contested_pct = (
            round(100 * contested_wins / contested_total, 1)
            if contested_total > 0
            else pd.NA
        )

        rows.append({
            "Manager": manager,
            "Free agents": free_agents,
            "Successful waivers": successful,
            "Failed waivers": failed,
            "Contested won": contested_wins,
            "Contested win %": contested_pct,
        })

    return pd.DataFrame(rows)


# ============================================================
# Core analytics
# ============================================================

def compute_actual_points(
    scores,
    matchups,
):
    if (
        scores.empty
        or matchups.empty
    ):
        return pd.DataFrame(
            columns=[
                "GW",
                "league_entry",
                "actual_points",
                "W",
                "D",
                "L",
            ]
        )

    score_map = {
        (
            int(row.GW),
            int(row.league_entry),
        ):
            row.score
        for row
        in scores.itertuples()
    }

    rows = []

    for match in matchups.itertuples():

        score_a = score_map.get(
            (
                int(match.GW),
                int(match.entry_a),
            )
        )

        score_b = score_map.get(
            (
                int(match.GW),
                int(match.entry_b),
            )
        )

        if (
            score_a is None
            or score_b is None
        ):
            continue

        if score_a > score_b:
            points_a, points_b = 3, 0
            w_a, d_a, l_a = 1, 0, 0
            w_b, d_b, l_b = 0, 0, 1

        elif score_a < score_b:
            points_a, points_b = 0, 3
            w_a, d_a, l_a = 0, 0, 1
            w_b, d_b, l_b = 1, 0, 0

        else:
            points_a, points_b = 1, 1
            w_a, d_a, l_a = 0, 1, 0
            w_b, d_b, l_b = 0, 1, 0

        rows.append({
            "GW":
                int(match.GW),
            "league_entry":
                int(match.entry_a),
            "actual_points":
                points_a,
            "W":
                w_a,
            "D":
                d_a,
            "L":
                l_a,
        })

        rows.append({
            "GW":
                int(match.GW),
            "league_entry":
                int(match.entry_b),
            "actual_points":
                points_b,
            "W":
                w_b,
            "D":
                d_b,
            "L":
                l_b,
        })

    return pd.DataFrame(rows)


def compute_expected_points(
    scores,
):
    """
    Expected H2H points against a randomly selected
    opponent from the other five participants.
    """

    if scores.empty:
        return pd.DataFrame(
            columns=[
                "GW",
                "league_entry",
                "expected_points",
            ]
        )

    rows = []

    for gw, group in scores.groupby(
        "GW"
    ):
        gw_scores = {
            int(row.league_entry):
                row.score
            for row
            in group.itertuples()
        }

        for (
            league_entry,
            score,
        ) in gw_scores.items():

            possible_points = []

            for (
                opponent,
                opponent_score,
            ) in gw_scores.items():

                if (
                    opponent
                    == league_entry
                ):
                    continue

                if score > opponent_score:
                    possible_points.append(
                        3
                    )

                elif score == opponent_score:
                    possible_points.append(
                        1
                    )

                else:
                    possible_points.append(
                        0
                    )

            expected = (
                sum(possible_points)
                / len(possible_points)
                if possible_points
                else 0
            )

            rows.append({
                "GW":
                    int(gw),
                "league_entry":
                    int(league_entry),
                "expected_points":
                    expected,
            })

    return pd.DataFrame(
        rows
    )


def compute_weekly_finishes(
    scores,
):
    """
    Competition ranking:

        1, 2, 2, 4, 5, 6
    """

    if scores.empty:
        return pd.DataFrame()

    rows = []

    for gw, group in scores.groupby(
        "GW"
    ):
        group = group.copy()

        group["position"] = (
            group["score"]
            .rank(
                method="min",
                ascending=False,
            )
            .astype(int)
        )

        rows.append(
            group[
                [
                    "GW",
                    "league_entry",
                    "position",
                ]
            ]
        )

    weekly_positions = pd.concat(
        rows,
        ignore_index=True,
    )

    return (
        weekly_positions
        .groupby(
            [
                "league_entry",
                "position",
            ]
        )
        .size()
        .unstack(
            fill_value=0
        )
    )


# ============================================================
# Opponent strength
# ============================================================

def compute_opponent_strength(
    scores,
    matchups,
):
    """
    Average and total FPL points scored by each manager's
    actual scheduled opponents in played gameweeks.
    """

    columns = [
        "league_entry",
        "Opponent avg",
        "Opponent FPL points",
    ]

    if (
        scores.empty
        or matchups.empty
    ):
        return pd.DataFrame(
            columns=columns
        )

    score_map = {
        (
            int(row.GW),
            int(row.league_entry),
        ):
            row.score
        for row
        in scores.itertuples()
    }

    rows = []

    for match in matchups.itertuples():

        gw = int(match.GW)
        entry_a = int(match.entry_a)
        entry_b = int(match.entry_b)

        score_a = score_map.get(
            (
                gw,
                entry_a,
            )
        )

        score_b = score_map.get(
            (
                gw,
                entry_b,
            )
        )

        if (
            score_a is None
            or score_b is None
        ):
            continue

        rows.append({
            "league_entry":
                entry_a,
            "opponent_score":
                score_b,
        })

        rows.append({
            "league_entry":
                entry_b,
            "opponent_score":
                score_a,
        })

    if not rows:
        return pd.DataFrame(
            columns=columns
        )

    return (
        pd.DataFrame(rows)
        .groupby(
            "league_entry",
            as_index=False,
        )
        .agg(
            **{
                "Opponent avg": (
                    "opponent_score",
                    "mean",
                ),
                "Opponent FPL points": (
                    "opponent_score",
                    "sum",
                ),
            }
        )
    )


# ============================================================
# Best / worst weeks
# ============================================================

def compute_best_worst(
    scores,
    entries,
):
    rows = []

    for entry in entries.itertuples():

        manager_scores = (
            scores[
                scores[
                    "league_entry"
                ]
                == int(
                    entry.league_entry
                )
            ]
        )

        if manager_scores.empty:
            continue

        best_score = (
            manager_scores[
                "score"
            ].max()
        )

        worst_score = (
            manager_scores[
                "score"
            ].min()
        )

        best_gws = (
            manager_scores[
                manager_scores[
                    "score"
                ] == best_score
            ]["GW"]
            .astype(int)
            .tolist()
        )

        worst_gws = (
            manager_scores[
                manager_scores[
                    "score"
                ] == worst_score
            ]["GW"]
            .astype(int)
            .tolist()
        )

        rows.append({
            "Manager":
                entry.manager,
            "Best GW":
                ", ".join(
                    str(gw)
                    for gw
                    in best_gws
                ),
            "Best score":
                int(best_score),
            "Worst GW":
                ", ".join(
                    str(gw)
                    for gw
                    in worst_gws
                ),
            "Worst score":
                int(worst_score),
        })

    return pd.DataFrame(
        rows
    )


# ============================================================
# Consistency
# ============================================================

def compute_consistency(
    scores,
    entries,
):
    if scores.empty:
        return pd.DataFrame()

    stats = (
        scores
        .groupby(
            "league_entry",
            as_index=False,
        )
        .agg(
            Mean=(
                "score",
                "mean",
            ),
            Median=(
                "score",
                "median",
            ),
            SD=(
                "score",
                "std",
            ),
            Min=(
                "score",
                "min",
            ),
            Max=(
                "score",
                "max",
            ),
        )
    )

    stats = stats.merge(
        entries[
            [
                "league_entry",
                "manager",
            ]
        ],
        on="league_entry",
        how="left",
    )

    stats = stats[
        [
            "manager",
            "Mean",
            "Median",
            "SD",
            "Min",
            "Max",
        ]
    ]

    stats.columns = [
        "Manager",
        "Mean",
        "Median",
        "SD",
        "Min",
        "Max",
    ]

    stats[
        [
            "Mean",
            "Median",
            "SD",
        ]
    ] = (
        stats[
            [
                "Mean",
                "Median",
                "SD",
            ]
        ]
        .round(2)
    )

    return stats


# ============================================================
# Close games
# ============================================================

def compute_close_games(
    scores,
    matchups,
    entries,
    threshold,
):
    score_map = {
        (
            int(row.GW),
            int(row.league_entry),
        ):
            row.score
        for row
        in scores.itertuples()
    }

    records = {
        int(row.league_entry): {
            "Manager":
                row.manager,
            "Close games":
                0,
            "W":
                0,
            "D":
                0,
            "L":
                0,
        }
        for row
        in entries.itertuples()
    }

    for match in matchups.itertuples():

        gw = int(match.GW)
        a = int(match.entry_a)
        b = int(match.entry_b)

        score_a = score_map.get(
            (
                gw,
                a,
            )
        )

        score_b = score_map.get(
            (
                gw,
                b,
            )
        )

        if (
            score_a is None
            or score_b is None
        ):
            continue

        margin = abs(
            score_a - score_b
        )

        if margin > threshold:
            continue

        records[a][
            "Close games"
        ] += 1

        records[b][
            "Close games"
        ] += 1

        if score_a > score_b:
            records[a]["W"] += 1
            records[b]["L"] += 1

        elif score_b > score_a:
            records[b]["W"] += 1
            records[a]["L"] += 1

        else:
            records[a]["D"] += 1
            records[b]["D"] += 1

    result = pd.DataFrame(
        records.values()
    )

    result["Win %"] = (
        result.apply(
            lambda row:
                (
                    100
                    * row["W"]
                    / row["Close games"]
                )
                if row[
                    "Close games"
                ] > 0
                else 0,
            axis=1,
        )
        .round(1)
    )

    return result


# ============================================================
# H2H matrix
# ============================================================

def compute_h2h_matrix(
    scores,
    matchups,
    participant_order,
    names,
):
    """
    Each cell is W-D-L from the row manager's perspective.
    """

    score_map = {
        (
            int(row.GW),
            int(row.league_entry),
        ):
            row.score
        for row
        in scores.itertuples()
    }

    records = {}

    for a in participant_order:
        for b in participant_order:

            if a == b:
                continue

            records[
                (
                    int(a),
                    int(b),
                )
            ] = {
                "W": 0,
                "D": 0,
                "L": 0,
            }

    for match in matchups.itertuples():

        gw = int(match.GW)
        a = int(match.entry_a)
        b = int(match.entry_b)

        score_a = score_map.get(
            (
                gw,
                a,
            )
        )

        score_b = score_map.get(
            (
                gw,
                b,
            )
        )

        if (
            score_a is None
            or score_b is None
        ):
            continue

        if (
            (a, b)
            not in records
        ):
            continue

        if score_a > score_b:
            records[
                (a, b)
            ]["W"] += 1

            records[
                (b, a)
            ]["L"] += 1

        elif score_a < score_b:
            records[
                (a, b)
            ]["L"] += 1

            records[
                (b, a)
            ]["W"] += 1

        else:
            records[
                (a, b)
            ]["D"] += 1

            records[
                (b, a)
            ]["D"] += 1

    matrix = pd.DataFrame(
        "",
        index=[
            names.get(
                entry,
                str(entry),
            )
            for entry
            in participant_order
        ],
        columns=[
            names.get(
                entry,
                str(entry),
            )
            for entry
            in participant_order
        ],
    )

    for (
        a,
        b,
    ), record in records.items():

        row_name = names.get(
            a,
            str(a),
        )

        column_name = names.get(
            b,
            str(b),
        )

        matrix.loc[
            row_name,
            column_name,
        ] = (
            f"{record['W']}-"
            f"{record['D']}-"
            f"{record['L']}"
        )

    matrix.index.name = (
        "Manager"
    )

    return matrix


# ============================================================
# League table
# ============================================================

def compute_league_table(
    scores,
    actual,
    expected,
    entries,
    matchups,
):
    participant_ids = (
        entries[
            "league_entry"
        ]
        .astype(int)
        .tolist()
    )

    base = pd.DataFrame({
        "league_entry":
            participant_ids
    })

    # FPL points

    if scores.empty:

        score_summary = (
            base.copy()
        )

        score_summary[
            "FPL_points"
        ] = 0

    else:

        score_summary = (
            scores
            .groupby(
                "league_entry",
                as_index=False,
            )
            .agg(
                FPL_points=(
                    "score",
                    "sum",
                )
            )
        )

        score_summary = (
            base.merge(
                score_summary,
                on="league_entry",
                how="left",
            )
        )

    # Actual H2H

    if actual.empty:

        result_summary = (
            base.copy()
        )

        result_summary["W"] = 0
        result_summary["D"] = 0
        result_summary["L"] = 0
        result_summary["Points"] = 0

    else:

        result_summary = (
            actual
            .groupby(
                "league_entry",
                as_index=False,
            )
            .agg(
                W=("W", "sum"),
                D=("D", "sum"),
                L=("L", "sum"),
                Points=(
                    "actual_points",
                    "sum",
                ),
            )
        )

        result_summary = (
            base.merge(
                result_summary,
                on="league_entry",
                how="left",
            )
        )

    # Expected

    if expected.empty:

        expected_summary = (
            base.copy()
        )

        expected_summary[
            "Expected"
        ] = 0.0

    else:

        expected_summary = (
            expected
            .groupby(
                "league_entry",
                as_index=False,
            )
            .agg(
                Expected=(
                    "expected_points",
                    "sum",
                )
            )
        )

        expected_summary = (
            base.merge(
                expected_summary,
                on="league_entry",
                how="left",
            )
        )

    # Opponent strength

    opponent_strength = (
        compute_opponent_strength(
            scores,
            matchups,
        )
    )

    table = (
        score_summary
        .merge(
            result_summary,
            on="league_entry",
            how="left",
        )
        .merge(
            expected_summary,
            on="league_entry",
            how="left",
        )
    )

    table = table.merge(
        opponent_strength,
        on="league_entry",
        how="left",
    )

    table = table.merge(
        entries[
            [
                "league_entry",
                "manager",
            ]
        ],
        on="league_entry",
        how="left",
    )

    for column in [
        "W",
        "D",
        "L",
        "Points",
        "FPL_points",
    ]:
        table[column] = (
            table[column]
            .fillna(0)
            .astype(int)
        )

    for column in [
        "Expected",
        "Opponent avg",
        "Opponent FPL points",
    ]:
        if column not in table:
            table[column] = 0

        table[column] = (
            table[column]
            .fillna(0)
        )

    table["Delta"] = (
        table["Points"]
        - table["Expected"]
    )

    table = (
        table
        .sort_values(
            [
                "Points",
                "FPL_points",
            ],
            ascending=[
                False,
                False,
            ],
        )
        .reset_index(
            drop=True
        )
    )

    table["Rank"] = range(
        1,
        len(table) + 1,
    )

    return table


# ============================================================
# Schedule what-if analysis
# ============================================================

def enumerate_schedule_outcomes(scores, matchups, participant_order, names):
    """Enumerate every permutation of participants over the existing fixture slots.

    Scores stay attached to the manager who actually scored them; only the fixture draw
    changes. With six fixture slots this evaluates all 6! = 720 possible assignments.
    The pseudo-manager ``Average`` remains a valid schedule participant when present,
    because drawing the Average slot is part of the real league schedule.
    """
    slots = [int(x) for x in participant_order]
    if len(slots) != 6:
        return pd.DataFrame(), {}, []

    score_map = {
        (int(r.GW), int(r.league_entry)): float(r.score)
        for r in scores.itertuples()
    }
    score_gws = sorted(scores["GW"].unique()) if not scores.empty else []
    template = matchups[matchups["GW"].isin(score_gws)].copy()

    # Only analyze completed GWs for which every schedule slot has a score and
    # the fixture template contains three matches.
    valid_gws = []
    for gw in score_gws:
        if all((int(gw), slot) in score_map for slot in slots):
            gw_template = template[template["GW"] == gw]
            if len(gw_template) == len(slots) // 2:
                valid_gws.append(int(gw))
    template = template[template["GW"].isin(valid_gws)].copy()

    # Average is a genuine fixture slot in Draft H2H schedule analysis. Treat it
    # exactly like the named managers here: it can earn H2H points, occupy a
    # finishing position, and appear in the 720-schedule distributions.
    schedule_participants = list(slots)
    fpl_totals = {
        entry: sum(score_map[(gw, entry)] for gw in valid_gws)
        for entry in schedule_participants
    }

    rows = []
    assignments = {}
    actual_tuple = tuple(slots)

    for schedule_id, perm in enumerate(permutations(slots), start=1):
        slot_to_entry = dict(zip(slots, perm))
        assignments[schedule_id] = slot_to_entry
        h2h = {entry: 0 for entry in schedule_participants}
        wdl = {entry: [0, 0, 0] for entry in schedule_participants}

        for m in template.itertuples():
            gw = int(m.GW)
            a = slot_to_entry[int(m.entry_a)]
            b = slot_to_entry[int(m.entry_b)]
            sa = score_map[(gw, a)]
            sb = score_map[(gw, b)]

            if sa > sb:
                pa, pb = 3, 0
                ra, rb = 0, 2
            elif sa < sb:
                pa, pb = 0, 3
                ra, rb = 2, 0
            else:
                pa, pb = 1, 1
                ra = rb = 1

            if a in h2h:
                h2h[a] += pa
                wdl[a][ra] += 1
            if b in h2h:
                h2h[b] += pb
                wdl[b][rb] += 1

        standings = sorted(
            schedule_participants,
            key=lambda e: (-h2h[e], -fpl_totals[e], slots.index(e)),
        )
        rank = {entry: i + 1 for i, entry in enumerate(standings)}

        for entry in schedule_participants:
            rows.append({
                "Schedule": schedule_id,
                "league_entry": entry,
                "Manager": names.get(entry, str(entry)),
                "H2H points": h2h[entry],
                "Rank": rank[entry],
                "W": wdl[entry][0],
                "D": wdl[entry][1],
                "L": wdl[entry][2],
                "FPL points": fpl_totals[entry],
                "Actual schedule": perm == actual_tuple,
            })

    return pd.DataFrame(rows), assignments, valid_gws


def build_schedule_summary(schedule_results, participant_order, names):
    if schedule_results.empty:
        return pd.DataFrame()
    rows = []
    for manager, g in schedule_results.groupby("Manager", sort=False):
        actual = g[g["Actual schedule"]]
        if actual.empty:
            continue
        actual_row = actual.iloc[0]
        actual_pts = float(actual_row["H2H points"])
        rows.append({
            "Manager": manager,
            "Actual H2H": int(actual_pts),
            "Mean H2H": g["H2H points"].mean(),
            "Median H2H": g["H2H points"].median(),
            "Min H2H": int(g["H2H points"].min()),
            "Max H2H": int(g["H2H points"].max()),
            "H2H percentile": 100 * (g["H2H points"] <= actual_pts).mean(),
            "Actual position": int(actual_row["Rank"]),
            "Avg position": g["Rank"].mean(),
            "Best position": int(g["Rank"].min()),
            "Worst position": int(g["Rank"].max()),
            "1st-place schedules": int((g["Rank"] == 1).sum()),
            "1st-place %": 100 * (g["Rank"] == 1).mean(),
        })
    out = pd.DataFrame(rows)
    return order_by_draft(out, "Manager", participant_order, names)


def build_finish_distribution(schedule_results, participant_order, names):
    if schedule_results.empty:
        return pd.DataFrame()
    max_rank = int(schedule_results["Rank"].max())
    rows = []
    for manager, g in schedule_results.groupby("Manager", sort=False):
        row = {"Manager": manager}
        n = len(g)
        for rank in range(1, max_rank + 1):
            count = int((g["Rank"] == rank).sum())
            row[f"{ordinal(rank)}"] = f"{count} ({100 * count / n:.1f}%)"
        rows.append(row)
    out = pd.DataFrame(rows)
    return order_by_draft(out, "Manager", participant_order, names)


def build_all_season_h2h_matrix(scores, participant_order, names):
    """Return schedule-independent W-D-L records for every participant pairing.

    Each cell is from the row manager's perspective and assumes the two participants
    played one another in every completed GW for which both have a recorded score.
    Average is retained as a full participant when it is present in participant_order.
    """
    if scores.empty:
        return pd.DataFrame()

    participants = [int(e) for e in participant_order]
    score_map = {
        (int(r.GW), int(r.league_entry)): float(r.score)
        for r in scores.itertuples()
    }
    gws = sorted(int(gw) for gw in scores["GW"].unique())

    rows = []
    for entry in participants:
        row = {"Manager": names.get(entry, str(entry))}
        for opp in participants:
            opp_name = names.get(opp, str(opp))
            if opp == entry:
                row[opp_name] = "—"
                continue

            wins = draws = losses = 0
            for gw in gws:
                own = score_map.get((gw, entry))
                other = score_map.get((gw, opp))
                if own is None or other is None:
                    continue
                if own > other:
                    wins += 1
                elif own == other:
                    draws += 1
                else:
                    losses += 1
            row[opp_name] = f"{wins}-{draws}-{losses}"
        rows.append(row)

    columns = ["Manager"] + [names.get(e, str(e)) for e in participants]
    return pd.DataFrame(rows)[columns]


def schedule_fixture_view(schedule_id, manager_entry, assignments, matchups, scores, valid_gws, names):
    if schedule_id not in assignments:
        return pd.DataFrame()
    mapping = assignments[schedule_id]
    score_map = {
        (int(r.GW), int(r.league_entry)): float(r.score)
        for r in scores.itertuples()
    }
    rows = []
    template = matchups[matchups["GW"].isin(valid_gws)]
    for m in template.itertuples():
        a = mapping[int(m.entry_a)]
        b = mapping[int(m.entry_b)]
        if manager_entry not in (a, b):
            continue
        opp = b if a == manager_entry else a
        own = score_map[(int(m.GW), manager_entry)]
        other = score_map[(int(m.GW), opp)]
        result = "W" if own > other else ("D" if own == other else "L")
        rows.append({
            "GW": int(m.GW),
            "Opponent": names.get(opp, str(opp)),
            "Manager score": int(own),
            "Opponent score": int(other),
            "Result": result,
        })
    return pd.DataFrame(rows).sort_values("GW")


# ============================================================
# Display helpers
# ============================================================

def display_names(entries):
    return dict(
        zip(
            entries[
                "league_entry"
            ],
            entries[
                "manager"
            ],
        )
    )


def get_participant_order(
    entries,
    choices_data,
):
    choices = choices_data.get(
        "choices",
        [],
    )

    first_round = [
        choice
        for choice in choices
        if choice.get("round") == 1
    ]

    first_round = sorted(
        first_round,
        key=lambda choice:
            choice.get(
                "pick",
                999,
            ),
    )

    entry_to_league_entry = {}

    for row in entries.itertuples():

        if pd.notna(
            row.entry_id
        ):
            entry_to_league_entry[
                int(row.entry_id)
            ] = int(
                row.league_entry
            )

    participant_order = []

    for choice in first_round:

        entry_id = (
            choice.get("entry")
        )

        if entry_id is None:
            continue

        league_entry = (
            entry_to_league_entry.get(
                int(entry_id)
            )
        )

        if (
            league_entry is not None
            and league_entry
            not in participant_order
        ):
            participant_order.append(
                league_entry
            )

    remaining = [
        int(league_entry)
        for league_entry
        in entries[
            "league_entry"
        ]
        if int(league_entry)
        not in participant_order
    ]

    participant_order.extend(
        remaining
    )

    return participant_order


def ordinal(number):
    if (
        10
        <= number % 100
        <= 20
    ):
        suffix = "th"

    else:
        suffix = {
            1: "st",
            2: "nd",
            3: "rd",
        }.get(
            number % 10,
            "th",
        )

    return (
        f"{number}{suffix}"
    )


def style_score_rows(df):
    score_columns = [
        column
        for column
        in df.columns
        if column != "GW"
    ]

    return (
        df.style
        .background_gradient(
            cmap="RdYlGn",
            axis=1,
            subset=score_columns,
        )
    )


def build_score_table(
    scores,
    participant_order,
    names,
    gameweeks=None,
):
    if scores.empty:
        pivot = pd.DataFrame()

    else:
        pivot = scores.pivot(
            index="GW",
            columns="league_entry",
            values="score",
        )

    if gameweeks is not None:
        pivot = pivot.reindex(
            gameweeks
        )

    else:
        pivot = pivot.sort_index()

    pivot = pivot.reindex(
        columns=participant_order
    )

    pivot = pivot.rename(
        columns=names
    )

    pivot.index.name = "GW"

    return (
        pivot.reset_index()
    )


def build_finish_table(
    scores,
    participant_order,
    names,
):
    finish_counts = (
        compute_weekly_finishes(
            scores
        )
    )

    number_of_participants = (
        len(
            participant_order
        )
    )

    positions = list(
        range(
            1,
            number_of_participants + 1,
        )
    )

    if finish_counts.empty:

        finish_counts = (
            pd.DataFrame(
                0,
                index=participant_order,
                columns=positions,
            )
        )

    else:

        finish_counts = (
            finish_counts
            .reindex(
                index=participant_order,
                columns=positions,
                fill_value=0,
            )
        )

    finish_counts.columns = [
        ordinal(position)
        for position
        in positions
    ]

    finish_counts.index = [
        names.get(
            league_entry,
            str(league_entry),
        )
        for league_entry
        in finish_counts.index
    ]

    finish_counts.index.name = (
        "Manager"
    )

    return (
        finish_counts
        .reset_index()
    )


def format_league_table(
    table,
):
    display = table[
        [
            "Rank",
            "manager",
            "W",
            "D",
            "L",
            "FPL_points",
            "Expected",
            "Delta",
            "Opponent avg",
            "Points",
        ]
    ].copy()

    display.columns = [
        "Rank",
        "Manager",
        "W",
        "D",
        "L",
        "FPL points",
        "Expected",
        "Delta",
        "Opponent avg",
        "Points",
    ]

    display["Expected"] = (
        display["Expected"]
        .round(2)
    )

    display["Delta"] = (
        display["Delta"]
        .round(2)
    )

    display[
        "Opponent avg"
    ] = (
        display[
            "Opponent avg"
        ]
        .round(2)
    )

    return display


def order_by_draft(
    df,
    manager_column,
    participant_order,
    names,
):
    order = {
        names.get(
            league_entry,
            str(league_entry),
        ):
            index
        for index, league_entry
        in enumerate(
            participant_order
        )
    }

    result = df.copy()

    result["_order"] = (
        result[
            manager_column
        ]
        .map(order)
        .fillna(999)
    )

    result = (
        result
        .sort_values(
            "_order"
        )
        .drop(
            columns=[
                "_order"
            ]
        )
        .reset_index(
            drop=True
        )
    )

    return result



# ============================================================
# Player performance
# ============================================================

def build_player_metadata(bootstrap_data):
    """Player name/position metadata from Draft bootstrap-static."""
    position_names = {
        int(x.get("id")): x.get("singular_name_short", x.get("singular_name", ""))
        for x in bootstrap_data.get("element_types", [])
        if x.get("id") is not None
    }
    rows = []
    for x in bootstrap_data.get("elements", []):
        if x.get("id") is None:
            continue
        first = x.get("first_name", "") or ""
        second = x.get("second_name", "") or ""
        rows.append({
            "element": int(x["id"]),
            "Player": x.get("web_name") or f"{first} {second}".strip() or f"Player {x['id']}",
            "Position": position_names.get(x.get("element_type"), ""),
        })
    return pd.DataFrame(rows, columns=["element", "Player", "Position"])


def _extract_live_points(live_data, gw):
    """Normalize event/{gw}/live to element -> GW points."""
    rows = []
    for x in live_data.get("elements", []) if isinstance(live_data, dict) else []:
        element = x.get("id")
        stats = x.get("stats", {}) or {}
        if element is None:
            continue
        rows.append({
            "GW": int(gw),
            "element": int(element),
            "FPL points": int(stats.get("total_points", 0) or 0),
        })
    return rows


def _extract_entry_picks(entry_data, entry_id, manager, gw, point_map):
    """Normalize one manager's Draft squad for a GW.

    For the Draft ``entry/{entry_id}/event/{gw}`` endpoint, ``picks`` contains
    the FINAL lineup after automatic substitutions: positions 1--11 are the
    players whose points count and positions 12--15 are the final bench.

    ``subs`` records the automatic substitutions.  Therefore the INITIAL XI
    must be reconstructed by reversing those substitutions:
      * element_in  -> was initially on the bench, later counted
      * element_out -> was initially in the XI, later moved to the bench

    Output distinguishes initial starts from final counted appearances.
    """
    if not isinstance(entry_data, dict):
        return []

    raw_picks = entry_data.get("picks", []) or []
    automatic_subs = entry_data.get("subs", []) or []
    automatic_subs = [
        x for x in automatic_subs
        if isinstance(x, dict)
        and x.get("element_in") is not None
        and x.get("element_out") is not None
    ]

    auto_in = {int(x["element_in"]) for x in automatic_subs}
    auto_out = {int(x["element_out"]) for x in automatic_subs}

    rows = []
    for pick in raw_picks:
        if not isinstance(pick, dict) or pick.get("element") is None:
            continue

        try:
            element = int(pick["element"])
            position = int(pick["position"])
        except (TypeError, ValueError, KeyError):
            continue

        # The endpoint's positions are the FINAL post-autosub lineup.
        counted = 1 <= position <= 11

        # Reconstruct the INITIAL XI.  Normally it equals the final XI, except
        # that an autosub entrant started on the bench and an autosubbed-out
        # player started in the XI.
        selected = counted
        if element in auto_in:
            selected = False
        if element in auto_out:
            selected = True

        raw_points = point_map.get(element, pd.NA)
        points = int(raw_points) if pd.notna(raw_points) else pd.NA

        rows.append({
            "GW": int(gw),
            "entry_id": int(entry_id),
            "Manager": manager,
            "element": element,
            "Owned": True,
            "Selected XI": bool(selected),
            "Counted": bool(counted),
            "Autosub in": element in auto_in,
            "Autosub out": element in auto_out,
            "Unused bench": bool(not counted),
            "Squad position": position,
            "FPL points": points,
            "Counted points": (
                points if counted and pd.notna(points)
                else (0 if not counted else pd.NA)
            ),
            "Bench points": (
                points if (not counted) and pd.notna(points)
                else (0 if counted else pd.NA)
            ),
        })

    return rows


@st.cache_data(ttl=300, show_spinner=False)
def load_player_performance_data(league_id, entry_manager_pairs, max_gw):
    """Fetch historical GW squads and live player points for real managers."""
    api = FPLDraftAPI(league_id)
    squad_rows = []
    live_rows = []

    for gw in range(1, int(max_gw) + 1):
        live_data = api.event_live(gw)
        gw_live = _extract_live_points(live_data, gw)
        live_rows.extend(gw_live)
        point_map = {r["element"]: r["FPL points"] for r in gw_live}

        for entry_id, manager in entry_manager_pairs:
            entry_data = api.entry_event(int(entry_id), gw)
            squad_rows.extend(
                _extract_entry_picks(
                    entry_data,
                    int(entry_id),
                    manager,
                    gw,
                    point_map,
                )
            )

    squad = pd.DataFrame(squad_rows)
    live = pd.DataFrame(live_rows)
    return squad, live


def _build_ownership_spells(squad, choices_data, transactions):
    """Build consecutive manager/player ownership spells.

    A player can have multiple spells for the same manager: e.g. drafted,
    dropped, then reacquired later.  Each spell receives its own source.
    """
    if squad.empty:
        return pd.DataFrame()

    drafted = {
        (int(x["entry"]), int(x["element"]))
        for x in choices_data.get("choices", [])
        if x.get("entry") is not None and x.get("element") is not None
    }
    acquisition_source = {}
    completed = transactions[
        (transactions["result"] == "a") & transactions["kind"].isin(["w", "f"])
    ] if not transactions.empty else pd.DataFrame()
    if not completed.empty:
        for _, r in completed.sort_values(["GW", "Time"], na_position="last").iterrows():
            acquisition_source[(int(r["entry_id"]), int(r["element_in"]), int(r["GW"]))] = (
                "Waiver" if r["kind"] == "w" else "Free agent"
            )

    rows = []
    grouped = squad.groupby(["entry_id", "Manager", "element"], sort=False)
    for (entry_id, manager, element), g in grouped:
        gws = sorted(set(g["GW"].astype(int)))
        if not gws:
            continue
        chunks = [[gws[0]]]
        for gw in gws[1:]:
            if gw == chunks[-1][-1] + 1:
                chunks[-1].append(gw)
            else:
                chunks.append([gw])

        for spell_no, spell_gws in enumerate(chunks, 1):
            start_gw = spell_gws[0]
            if spell_no == 1 and (int(entry_id), int(element)) in drafted and start_gw == 1:
                source = "Draft"
            else:
                # Transaction event is normally the first GW in which the new
                # player belongs to the squad.  Also allow start_gw-1 for API
                # timing differences around a GW deadline.
                source = (
                    acquisition_source.get((int(entry_id), int(element), start_gw))
                    or acquisition_source.get((int(entry_id), int(element), start_gw - 1))
                    or "Acquired"
                )
            rows.append({
                "entry_id": int(entry_id),
                "Manager": manager,
                "element": int(element),
                "Spell": spell_no,
                "Source": source,
                "Start GW": start_gw,
                "End GW": spell_gws[-1],
                "GWs owned": len(spell_gws),
            })
    return pd.DataFrame(rows)


def build_player_contribution(squad, player_meta, choices_data, transactions):
    if squad.empty:
        return pd.DataFrame()

    spells = _build_ownership_spells(squad, choices_data, transactions)
    out = (
        squad.groupby(["entry_id", "Manager", "element"], as_index=False)
        .agg(**{
            "GWs owned": ("GW", "nunique"),
            "Selected XI": ("Selected XI", "sum"),
            "Starts": ("Selected XI", "sum"),
            "Counted apps": ("Counted", "sum"),
            "Autosub in": ("Autosub in", "sum"),
            "Autosub out": ("Autosub out", "sum"),
            "Unused bench": ("Unused bench", "sum"),
            "Points in XI": ("Counted points", "sum"),
            "Bench points": ("Bench points", "sum"),
        })
    )
    out["Avg/counted app"] = out["Points in XI"] / out["Counted apps"].replace(0, pd.NA)
    out["Avg/GW owned"] = out["Points in XI"] / out["GWs owned"].replace(0, pd.NA)

    spell_summary = (
        spells.groupby(["entry_id", "Manager", "element"], as_index=False)
        .agg(
            Spells=("Spell", "max"),
            Sources=("Source", lambda x: " + ".join(dict.fromkeys(x))),
        )
    ) if not spells.empty else pd.DataFrame()
    if not spell_summary.empty:
        out = out.merge(spell_summary, on=["entry_id", "Manager", "element"], how="left")
        out["Source"] = out["Sources"]
        out.loc[out["Spells"] > 1, "Source"] = out.loc[out["Spells"] > 1].apply(
            lambda r: f"{r['Sources']} ({int(r['Spells'])} spells)", axis=1
        )
    else:
        out["Source"] = "Owned"

    out = out.merge(player_meta, on="element", how="left")
    out["Player"] = out["Player"].fillna(out["element"].map(lambda x: f"Player {x}"))
    return out[[
        "Manager", "Player", "Position", "Source", "GWs owned",
        "Starts", "Counted apps", "Autosub in", "Autosub out", "Unused bench",
        "Points in XI", "Avg/counted app",
        "Avg/GW owned", "Bench points", "entry_id", "element"
    ]]


def _ownership_spell(squad, entry_id, element, start_gw, max_gw):
    """Consecutive owned GWs beginning at/after start_gw."""
    owned = set(
        squad.loc[
            (squad["entry_id"] == int(entry_id)) & (squad["element"] == int(element)),
            "GW",
        ].astype(int)
    )
    first = next((g for g in range(int(start_gw), int(max_gw) + 1) if g in owned), None)
    if first is None:
        return []
    spell = []
    for gw in range(first, int(max_gw) + 1):
        if gw not in owned:
            break
        spell.append(gw)
    return spell


def build_acquisition_impact(transactions, squad, player_meta, live, max_gw):
    """One row per successful waiver/free-agent acquisition and ownership spell."""
    completed = transactions[
        (transactions["result"] == "a") & (transactions["kind"].isin(["w", "f"]))
    ].copy()
    if completed.empty or squad.empty:
        return pd.DataFrame()

    raw_lookup = {
        (int(r["GW"]), int(r["element"])): int(r["FPL points"])
        for _, r in live.iterrows()
    } if not live.empty else {}
    counted_lookup = {
        (int(r["GW"]), int(r["entry_id"]), int(r["element"])): int(r["Counted points"])
        for _, r in squad.dropna(subset=["Counted points"]).iterrows()
    }

    rows = []
    for _, move in completed.iterrows():
        entry = int(move["entry_id"])
        gw = int(move["GW"])
        incoming = int(move["element_in"])
        outgoing = int(move["element_out"])
        spell = _ownership_spell(squad, entry, incoming, gw, max_gw)
        if not spell:
            # Allow for transaction/event timing where ownership first appears
            # in the following GW.
            spell = _ownership_spell(squad, entry, incoming, gw + 1, max_gw)
        if not spell:
            continue
        first_gw = spell[0]
        first3 = spell[:3]

        def counted_sum(gws, element=incoming):
            return sum(counted_lookup.get((g, entry, element), 0) for g in gws)

        def raw_sum(gws, element):
            return sum(raw_lookup.get((g, element), 0) for g in gws)

        rows.append({
            "Manager": move["Manager"],
            "GW": first_gw,
            "Type": "Waiver" if move["kind"] == "w" else "Free agent",
            "Player in": move["Player in"],
            "Player out": move["Player out"],
            "First GW counted": counted_sum([first_gw]),
            "First 3 counted": counted_sum(first3),
            "Total counted": counted_sum(spell),
            "First GW FPL": raw_sum([first_gw], incoming),
            "First 3 FPL": raw_sum(first3, incoming),
            "Total FPL while owned": raw_sum(spell, incoming),
            "GWs kept": len(spell),
            "Counted pts/GW": counted_sum(spell) / len(spell) if spell else pd.NA,
            "1-GW in-out": raw_sum([first_gw], incoming) - raw_sum([first_gw], outgoing),
            "3-GW in-out": raw_sum(list(range(first_gw, min(first_gw + 2, max_gw) + 1)), incoming)
                - raw_sum(list(range(first_gw, min(first_gw + 2, max_gw) + 1)), outgoing),
            "5-GW in-out": raw_sum(list(range(first_gw, min(first_gw + 4, max_gw) + 1)), incoming)
                - raw_sum(list(range(first_gw, min(first_gw + 4, max_gw) + 1)), outgoing),
        })
    return pd.DataFrame(rows)


def _valid_fpl_xi(elements, position_lookup):
    """Return whether 11 elements form a legal FPL XI."""
    positions = [position_lookup.get(int(e), "") for e in elements]
    counts = {p: positions.count(p) for p in ["GKP", "DEF", "MID", "FWD"]}
    return (
        len(elements) == 11
        and counts["GKP"] == 1
        and 3 <= counts["DEF"] <= 5
        and 2 <= counts["MID"] <= 5
        and 1 <= counts["FWD"] <= 3
    )


def _counterfactual_draft_xi(gw_squad, draft_elements, position_lookup, mode="adjusted"):
    """Choose a no-transactions XI without using that GW's player points.

    Both modes preserve actual counted players who still belong to the original
    draft squad.  The difference is how holes created by undoing transactions
    are filled:

    * direct: prefer returned original-draft players;
    * adjusted: prefer eligible players from the manager's actual bench first.

    The adjusted version captures the idea that a manager who waivered out a
    player may have benched that player anyway and started an existing bench
    alternative.  No GW points are used to choose the XI.
    """
    draft_elements = {int(e) for e in draft_elements}
    if len(draft_elements) < 11:
        return []

    actual_counted = set(
        gw_squad.loc[gw_squad["Counted"], "element"].astype(int)
    )
    actual_owned = set(gw_squad["element"].astype(int))
    retained_counted = actual_counted & draft_elements
    actual_bench = [
        int(r.element)
        for r in gw_squad.sort_values("Squad position").itertuples()
        if not bool(r.Counted) and int(r.element) in draft_elements
    ]
    returned = list(draft_elements - actual_owned)

    # Preference scores encode the counterfactual rule, not hindsight points.
    preference = {}
    for e in draft_elements:
        preference[e] = 0
    for e in retained_counted:
        preference[e] = 10000

    if mode == "adjusted":
        # Existing actual bench alternatives get first refusal for open slots.
        for rank, e in enumerate(actual_bench):
            preference[e] = max(preference[e], 5000 - rank)
        for e in returned:
            preference[e] = max(preference[e], 1000)
    else:
        # Mechanical/direct view: returned players are preferred over bench cover.
        for e in returned:
            preference[e] = max(preference[e], 5000)
        for rank, e in enumerate(actual_bench):
            preference[e] = max(preference[e], 1000 - rank)

    best = None
    best_key = None
    ordered = sorted(draft_elements)
    for combo in combinations(ordered, 11):
        if not _valid_fpl_xi(combo, position_lookup):
            continue
        retained = len(set(combo) & retained_counted)
        pref = sum(preference[e] for e in combo)
        # Deterministic tie-break only; never use player points.
        key = (retained, pref, tuple(-e for e in combo))
        if best_key is None or key > best_key:
            best_key = key
            best = list(combo)
    return best or []


def build_cumulative_transaction_impact(
    choices_data, squad, live, scores, matchups, entries, player_meta, max_gw
):
    """Counterfactual H2H record if each manager had made no squad transactions.

    Opponents remain at their actual official scores.  Counterfactual manager
    scores are based on the original draft squad, while actual lineup choices
    are preserved wherever possible.  Two variants are returned:

    Direct   - holes prefer the original-draft players who were moved out.
    Adjusted - holes prefer eligible players from the manager's actual bench
               before restoring a moved-out player to the XI.

    This is intentionally a transparent heuristic rather than an optimized
    hindsight XI: GW player points are never used when selecting the XI.
    """
    if squad.empty or live.empty or scores.empty or matchups.empty:
        return pd.DataFrame(), pd.DataFrame()

    position_lookup = {
        int(r.element): r.Position for r in player_meta.itertuples()
    }
    point_lookup = {
        (int(r["GW"]), int(r["element"])): int(r["FPL points"])
        for _, r in live.iterrows()
    }

    entry_to_league = {
        int(r.entry_id): int(r.league_entry)
        for r in entries.itertuples()
        if pd.notna(r.entry_id) and r.manager != "Average"
    }
    entry_to_manager = {
        int(r.entry_id): r.manager
        for r in entries.itertuples()
        if pd.notna(r.entry_id) and r.manager != "Average"
    }
    score_lookup = {
        (int(r.GW), int(r.league_entry)): float(r.score)
        for r in scores.itertuples()
    }
    opponent_lookup = {}
    for m in matchups.itertuples():
        opponent_lookup[(int(m.GW), int(m.entry_a))] = int(m.entry_b)
        opponent_lookup[(int(m.GW), int(m.entry_b))] = int(m.entry_a)

    draft_rosters = {}
    for c in choices_data.get("choices", []):
        if c.get("entry") is None or c.get("element") is None:
            continue
        draft_rosters.setdefault(int(c["entry"]), set()).add(int(c["element"]))

    def h2h_points(a, b):
        return 3 if a > b else (1 if a == b else 0)

    rows = []
    for entry_id, manager in entry_to_manager.items():
        league_entry = entry_to_league.get(entry_id)
        draft = draft_rosters.get(entry_id, set())
        if league_entry is None or len(draft) < 11:
            continue

        for gw in range(1, int(max_gw) + 1):
            gw_squad = squad[
                (squad["entry_id"] == entry_id) & (squad["GW"] == gw)
            ].copy()
            if gw_squad.empty:
                continue
            actual_score = score_lookup.get((gw, league_entry))
            opponent = opponent_lookup.get((gw, league_entry))
            opponent_score = score_lookup.get((gw, opponent)) if opponent is not None else None
            if actual_score is None or opponent_score is None:
                continue

            actual_lineup_sum = int(
                gw_squad.loc[gw_squad["Counted"], "Counted points"].fillna(0).sum()
            )
            direct_xi = _counterfactual_draft_xi(
                gw_squad, draft, position_lookup, mode="direct"
            )
            adjusted_xi = _counterfactual_draft_xi(
                gw_squad, draft, position_lookup, mode="adjusted"
            )
            if not direct_xi or not adjusted_xi:
                continue

            direct_lineup_sum = sum(point_lookup.get((gw, e), 0) for e in direct_xi)
            adjusted_lineup_sum = sum(point_lookup.get((gw, e), 0) for e in adjusted_xi)

            # Anchor to the official Draft score and apply only the lineup delta.
            direct_score = actual_score + direct_lineup_sum - actual_lineup_sum
            adjusted_score = actual_score + adjusted_lineup_sum - actual_lineup_sum
            actual_h2h = h2h_points(actual_score, opponent_score)
            direct_h2h = h2h_points(direct_score, opponent_score)
            adjusted_h2h = h2h_points(adjusted_score, opponent_score)

            rows.append({
                "Manager": manager,
                "GW": gw,
                "Actual score": actual_score,
                "Opponent score": opponent_score,
                "Direct no-moves score": direct_score,
                "Adjusted no-moves score": adjusted_score,
                "Squad pts impact": actual_score - adjusted_score,
                "Actual H2H pts": actual_h2h,
                "Direct no-moves H2H": direct_h2h,
                "Adjusted no-moves H2H": adjusted_h2h,
                "Direct H2H impact": actual_h2h - direct_h2h,
                "Adjusted H2H impact": actual_h2h - adjusted_h2h,
                "Result changed": actual_h2h != adjusted_h2h,
            })

    detail = pd.DataFrame(rows)
    if detail.empty:
        return detail, pd.DataFrame()

    detail["Cumulative squad pts impact"] = detail.groupby("Manager")["Squad pts impact"].cumsum()
    detail["Cumulative direct H2H impact"] = detail.groupby("Manager")["Direct H2H impact"].cumsum()
    detail["Cumulative adjusted H2H impact"] = detail.groupby("Manager")["Adjusted H2H impact"].cumsum()

    summary = (
        detail.groupby("Manager", as_index=False)
        .agg(**{
            "Actual H2H pts": ("Actual H2H pts", "sum"),
            "Direct no-moves H2H": ("Direct no-moves H2H", "sum"),
            "Adjusted no-moves H2H": ("Adjusted no-moves H2H", "sum"),
            "Direct H2H impact": ("Direct H2H impact", "sum"),
            "Adjusted H2H impact": ("Adjusted H2H impact", "sum"),
            "Squad pts impact": ("Squad pts impact", "sum"),
            "Results changed": ("Result changed", "sum"),
        })
    )
    return detail, summary

def build_painful_drops(transactions, squad, live, matchups, entries, max_gw):
    """Track released players who subsequently produce for another manager."""
    completed = transactions[
        (transactions["result"] == "a") & (transactions["kind"].isin(["w", "f"]))
    ].copy()
    if completed.empty or squad.empty:
        return pd.DataFrame(), pd.DataFrame()

    entry_to_manager = {
        int(r.entry_id): r.manager
        for r in entries.itertuples()
        if pd.notna(r.entry_id) and r.manager != "Average"
    }
    league_to_entry = {
        int(r.league_entry): int(r.entry_id)
        for r in entries.itertuples()
        if pd.notna(r.entry_id)
    }
    live_lookup = {
        (int(r["GW"]), int(r["element"])): int(r["FPL points"])
        for _, r in live.iterrows()
    } if not live.empty else {}

    pain_rows = []
    revenge_rows = []

    for _, drop in completed.iterrows():
        former_entry = int(drop["entry_id"])
        element = int(drop["element_out"])
        drop_gw = int(drop["GW"])

        later = squad[
            (squad["element"] == element)
            & (squad["entry_id"] != former_entry)
            & (squad["GW"] >= drop_gw)
        ].sort_values("GW")
        if later.empty:
            continue

        pickup_gw = int(later.iloc[0]["GW"])
        new_entry = int(later.iloc[0]["entry_id"])
        spell = _ownership_spell(squad, new_entry, element, pickup_gw, max_gw)
        spell_rows = squad[
            (squad["entry_id"] == new_entry)
            & (squad["element"] == element)
            & (squad["GW"].isin(spell))
        ]
        later_counted = int(spell_rows["Counted points"].sum())
        post_drop_raw = sum(
            live_lookup.get((g, element), 0)
            for g in range(drop_gw, int(max_gw) + 1)
        )

        pain_rows.append({
            "Dropped by": drop["Manager"],
            "Player": drop["Player out"],
            "Dropped GW": drop_gw,
            "Picked up by": entry_to_manager.get(new_entry, "Unknown"),
            "Pickup GW": pickup_gw,
            "1st GW pts": int(spell_rows.loc[spell_rows["GW"] == pickup_gw, "Counted points"].sum()),
            "First 3 pts": int(spell_rows.loc[spell_rows["GW"].between(pickup_gw, pickup_gw + 2), "Counted points"].sum()),
            "Pts for new manager": later_counted,
            "Post-drop FPL pts": post_drop_raw,
        })

        # Former-player H2H returns: counted points for the new owner in a GW
        # where that new owner faced the former owner.
        for _, pr in spell_rows[spell_rows["Counted"]].iterrows():
            gw = int(pr["GW"])
            pts = int(pr["Counted points"])
            if pts == 0:
                continue
            for m in matchups[matchups["GW"] == gw].itertuples():
                a = league_to_entry.get(int(m.entry_a))
                b = league_to_entry.get(int(m.entry_b))
                if {a, b} != {former_entry, new_entry}:
                    continue
                # Get final H2H scores from the match record if already played.
                revenge_rows.append({
                    "Former owner": drop["Manager"],
                    "Player": drop["Player out"],
                    "New owner": entry_to_manager.get(new_entry, "Unknown"),
                    "GW": gw,
                    "Player pts": pts,
                })

    pain = pd.DataFrame(pain_rows).drop_duplicates(
        ["Dropped by", "Player", "Dropped GW", "Picked up by", "Pickup GW"]
    ) if pain_rows else pd.DataFrame()
    revenge = pd.DataFrame(revenge_rows).drop_duplicates() if revenge_rows else pd.DataFrame()
    return pain, revenge


def build_draft_performance(choices_data, squad, player_meta, max_gw):
    """Performance of the *original draft spell* only.

    If a manager drafts a player, drops him and later reacquires him, the later
    spell belongs to Acquisition Impact rather than being credited back to the
    original draft pick.
    """
    rows = []
    if squad.empty:
        return pd.DataFrame()
    manager_map = (
        squad[["entry_id", "Manager"]]
        .drop_duplicates()
        .set_index("entry_id")["Manager"]
        .to_dict()
    )
    for c in choices_data.get("choices", []):
        if c.get("entry") is None or c.get("element") is None:
            continue
        entry = int(c["entry"])
        element = int(c["element"])
        all_owned = squad[(squad["entry_id"] == entry) & (squad["element"] == element)].copy()

        # Original spell = consecutive ownership beginning in GW1.  If the
        # first observed GW is later, keep the first observed consecutive spell
        # as a defensive fallback for incomplete historical API data.
        owned_gws = sorted(set(all_owned["GW"].astype(int)))
        original_gws = []
        if owned_gws:
            first = 1 if 1 in owned_gws else owned_gws[0]
            for gw in range(first, int(max_gw) + 1):
                if gw not in owned_gws:
                    break
                original_gws.append(gw)
        owned = all_owned[all_owned["GW"].isin(original_gws)]

        rows.append({
            "Manager": manager_map.get(entry, c.get("entry_name", "Unknown")),
            "Draft pick": c.get("index"),
            "Round": c.get("round"),
            "element": element,
            "GWs owned": int(owned["GW"].nunique()),
            "Selected XI": int(owned["Selected XI"].sum()),
            "Starts": int(owned["Selected XI"].sum()),
            "Counted apps": int(owned["Counted"].sum()),
            "Unused bench": int(owned["Unused bench"].sum()),
            "Points in XI": int(owned["Counted points"].sum()),
            "Still owned": bool(original_gws and original_gws[-1] == int(max_gw)),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.merge(player_meta, on="element", how="left")
    out["Player"] = out["Player"].fillna(out["element"].map(lambda x: f"Player {x}"))
    out["Avg/counted app"] = out["Points in XI"] / out["Counted apps"].replace(0, pd.NA)
    return out[[
        "Manager", "Draft pick", "Round", "Player", "Position", "GWs owned",
        "Starts", "Counted apps", "Unused bench", "Points in XI", "Avg/counted app",
        "Still owned"
    ]]


# ============================================================
# Load league
# ============================================================

@st.cache_data(
    ttl=300,
    show_spinner=False,
)
def load_league(
    league_id,
):
    api = FPLDraftAPI(
        league_id
    )

    details = (
        api.details()
    )

    entries = parse_entries(
        details
    )

    if entries.empty:
        raise ValueError(
            "Could not find league entries "
            "in the Draft API response."
        )

    scores = (
        get_scores_from_matches(
            details
        )
    )

    if scores.empty:
        raise ValueError(
            "No started matches were found "
            "in the Draft API response."
        )

    # --------------------------------------------------------
    # Detect Average from all match data
    # --------------------------------------------------------

    match_ids = set()

    for match in details.get(
        "matches",
        [],
    ):
        entry_1 = match.get(
            "league_entry_1"
        )

        entry_2 = match.get(
            "league_entry_2"
        )

        if entry_1 is not None:
            match_ids.add(
                int(entry_1)
            )

        if entry_2 is not None:
            match_ids.add(
                int(entry_2)
            )

    known_ids = set(
        entries[
            "league_entry"
        ].astype(int)
    )

    special_ids = (
        match_ids
        - known_ids
    )

    for league_entry in sorted(
        special_ids
    ):

        entries = pd.concat(
            [
                entries,
                pd.DataFrame([
                    {
                        "league_entry":
                            league_entry,
                        "entry_id":
                            pd.NA,
                        "manager":
                            "Average",
                        "team_name":
                            "Average",
                    }
                ]),
            ],
            ignore_index=True,
        )

    generic_entry_mask = (
        entries[
            "manager"
        ]
        .astype(str)
        .str.startswith(
            "Entry ",
            na=False,
        )
    )

    entries.loc[
        generic_entry_mask,
        "manager",
    ] = "Average"

    entries.loc[
        generic_entry_mask,
        "team_name",
    ] = "Average"

    matchups = parse_matchups(
        details
    )

    choices_data = (
        api.choices()
    )

    transaction_data = (
        api.transactions()
    )

    bootstrap_data = (
        api.bootstrap_static()
    )

    return (
        details,
        entries,
        scores,
        matchups,
        choices_data,
        transaction_data,
        bootstrap_data,
    )


# ============================================================
# Sidebar
# ============================================================

with st.sidebar:

    league_id = (
        st.number_input(
            "League ID",
            min_value=1,
            value=DEFAULT_LEAGUE_ID,
            step=1,
        )
    )

    if st.button(
        "Refresh API data",
        type="primary",
    ):
        load_league.clear()
        st.rerun()


# ============================================================
# Fetch
# ============================================================

try:

    with st.spinner(
        f"Loading league "
        f"{league_id}…"
    ):

        (
            details,
            entries,
            scores,
            matchups,
            choices_data,
            transaction_data,
            bootstrap_data,
        ) = load_league(
            league_id
        )

except Exception as exc:

    st.error(
        "The Draft API could "
        "not be loaded."
    )

    st.exception(
        exc
    )

    st.stop()


# ============================================================
# League name
# ============================================================

league_info = (
    details.get(
        "league",
        {},
    )
)

if isinstance(
    league_info,
    dict,
):
    league_name = (
        league_info.get(
            "name"
        )
        or f"League {league_id}"
    )

else:
    league_name = (
        f"League {league_id}"
    )

st.title(
    f"FPL Draft H2H — "
    f"{league_name}"
)


# ============================================================
# Names / order
# ============================================================

names = display_names(
    entries
)

participant_order = (
    get_participant_order(
        entries,
        choices_data,
    )
)

player_names = (
    build_player_names(
        bootstrap_data
    )
)


# ============================================================
# Derived data
# ============================================================

actual = (
    compute_actual_points(
        scores,
        matchups,
    )
)

expected = (
    compute_expected_points(
        scores
    )
)

league_table = (
    compute_league_table(
        scores,
        actual,
        expected,
        entries,
        matchups,
    )
)

best_worst = (
    compute_best_worst(
        scores,
        entries,
    )
)

best_worst = (
    order_by_draft(
        best_worst,
        "Manager",
        participant_order,
        names,
    )
)

consistency = (
    compute_consistency(
        scores,
        entries,
    )
)

consistency = (
    order_by_draft(
        consistency,
        "Manager",
        participant_order,
        names,
    )
)

transactions = parse_transactions(
    transaction_data,
    entries,
    player_names,
)

transactions, contested_waivers = analyse_waivers(
    transactions,
    choices_data,
)



# ============================================================
# Player-performance data
# ============================================================

max_played_gw = int(scores["GW"].max())
real_entry_manager_pairs = tuple(
    (int(r.entry_id), r.manager)
    for r in entries.itertuples()
    if pd.notna(r.entry_id) and r.manager != "Average"
)

player_meta = build_player_metadata(bootstrap_data)

try:
    player_squad_gw, player_live_gw = load_player_performance_data(
        int(league_id),
        real_entry_manager_pairs,
        max_played_gw,
    )
except Exception:
    # Player Performance should never prevent the existing league tracker from
    # loading if an undocumented player endpoint changes temporarily.
    player_squad_gw = pd.DataFrame()
    player_live_gw = pd.DataFrame()

player_contribution = build_player_contribution(
    player_squad_gw, player_meta, choices_data, transactions
)
acquisition_impact = build_acquisition_impact(
    transactions, player_squad_gw, player_meta, player_live_gw, max_played_gw
)
painful_drops, former_player_h2h = build_painful_drops(
    transactions, player_squad_gw, player_live_gw, matchups, entries, max_played_gw
)
draft_performance = build_draft_performance(
    choices_data, player_squad_gw, player_meta, max_played_gw
)
cumulative_transaction_detail, cumulative_transaction_summary = build_cumulative_transaction_impact(
    choices_data, player_squad_gw, player_live_gw, scores, matchups, entries,
    player_meta, max_played_gw
)

# Exhaustive schedule what-if analysis: for six fixture slots this is all 6! = 720 draws.
schedule_results, schedule_assignments, schedule_valid_gws = enumerate_schedule_outcomes(
    scores, matchups, participant_order, names
)
schedule_summary = build_schedule_summary(schedule_results, participant_order, names)
finish_distribution = build_finish_distribution(schedule_results, participant_order, names)
all_season_h2h_matrix = build_all_season_h2h_matrix(scores, participant_order, names)

# ============================================================
# Tabs
# ============================================================

(
    tab1,
    tab2,
    tab3,
    tab4,
    tab5,
    tab6,
    tab7,
    tab8,
) = st.tabs([
    "Gameweek Scores",
    "5-GW Periods",
    "H2H",
    "League Analysis",
    "Schedule Analysis",
    "Squad Activity",
    "Player Performance",
    "Charts",
])


# ============================================================
# TAB 1 — Gameweek Scores
# ============================================================

with tab1:

    st.subheader(
        "League table"
    )

    st.dataframe(
        format_league_table(
            league_table
        ),
        hide_index=True,
        use_container_width=True,
    )


    # --------------------------------------------------------
    # Scores
    # --------------------------------------------------------

    st.subheader(
        "Gameweek scores"
    )

    score_table = (
        build_score_table(
            scores,
            participant_order,
            names,
        )
    )

    st.dataframe(
        style_score_rows(
            score_table
        ),
        hide_index=True,
        use_container_width=True,
    )


    # --------------------------------------------------------
    # Finishing positions
    # --------------------------------------------------------

    st.subheader(
        "Gameweek finishing positions"
    )

    finish_table = (
        build_finish_table(
            scores,
            participant_order,
            names,
        )
    )

    st.dataframe(
        finish_table,
        hide_index=True,
        use_container_width=True,
    )


# ============================================================
# TAB 2 — 5-GW Periods
# ============================================================

with tab2:

    latest_gw = int(
        scores["GW"].max()
    )

    current_period_start = (
        (
            (latest_gw - 1)
            // 5
        )
        * 5
        + 1
    )

    period_options = []

    for period_start in range(
        1,
        current_period_start + 1,
        5,
    ):
        period_options.append(
            (
                period_start,
                period_start + 4,
            )
        )

    selected_period = (
        st.selectbox(
            "Gameweeks",
            options=period_options,
            index=(
                len(period_options)
                - 1
            ),
            format_func=lambda period:
                (
                    f"GW "
                    f"{period[0]}–"
                    f"{period[1]}"
                ),
        )
    )

    selected_start = (
        selected_period[0]
    )

    selected_end = (
        selected_period[1]
    )

    selected_gameweeks = list(
        range(
            selected_start,
            selected_end + 1,
        )
    )

    period_scores = (
        scores[
            scores[
                "GW"
            ].between(
                selected_start,
                selected_end,
            )
        ]
        .copy()
    )

    period_actual = (
        actual[
            actual[
                "GW"
            ].between(
                selected_start,
                selected_end,
            )
        ]
        .copy()
    )

    period_expected = (
        expected[
            expected[
                "GW"
            ].between(
                selected_start,
                selected_end,
            )
        ]
        .copy()
    )

    period_matchups = (
        matchups[
            matchups[
                "GW"
            ].between(
                selected_start,
                selected_end,
            )
        ]
        .copy()
    )


    # --------------------------------------------------------
    # Period league table
    # --------------------------------------------------------

    st.subheader(
        f"League table — "
        f"GW {selected_start}–"
        f"{selected_end}"
    )

    period_league_table = (
        compute_league_table(
            period_scores,
            period_actual,
            period_expected,
            entries,
            period_matchups,
        )
    )

    st.dataframe(
        format_league_table(
            period_league_table
        ),
        hide_index=True,
        use_container_width=True,
    )


    # --------------------------------------------------------
    # Period scores
    # --------------------------------------------------------

    st.subheader(
        "Gameweek scores"
    )

    period_score_table = (
        build_score_table(
            period_scores,
            participant_order,
            names,
            gameweeks=
                selected_gameweeks,
        )
    )

    st.dataframe(
        style_score_rows(
            period_score_table
        ),
        hide_index=True,
        use_container_width=True,
    )


    # --------------------------------------------------------
    # Period positions
    # --------------------------------------------------------

    st.subheader(
        "Gameweek finishing positions"
    )

    period_finish_table = (
        build_finish_table(
            period_scores,
            participant_order,
            names,
        )
    )

    st.dataframe(
        period_finish_table,
        hide_index=True,
        use_container_width=True,
    )


# ============================================================
# TAB 3 — H2H
# ============================================================

with tab3:
    
    # --------------------------------------------------------
    # H2H matrix
    # --------------------------------------------------------

    st.subheader(
        "H2H matrix"
    )

    h2h_matrix = (
        compute_h2h_matrix(
            scores,
            matchups,
            participant_order,
            names,
        )
    )

    st.dataframe(
        h2h_matrix,
        use_container_width=True,
    )


    # --------------------------------------------------------
    # Close games
    # --------------------------------------------------------

    st.subheader(
        "Close games"
    )

    close_threshold = (
        st.selectbox(
            "Maximum score difference",
            options=[
                3,
                5,
                10,
            ],
            index=1,
            format_func=lambda x:
                f"≤ {x} points",
        )
    )

    close_games = (
        compute_close_games(
            scores,
            matchups,
            entries,
            close_threshold,
        )
    )

    close_games = (
        order_by_draft(
            close_games,
            "Manager",
            participant_order,
            names,
        )
    )

    st.dataframe(
        close_games,
        hide_index=True,
        use_container_width=True,
    )


    # --------------------------------------------------------
    # Fixtures
    # --------------------------------------------------------

    st.subheader(
        "Head-to-head schedule"
    )

    if matchups.empty:

        st.warning(
            "No matchup data "
            "is available."
        )

    else:

        score_map = {
            (
                int(row.GW),
                int(
                    row.league_entry
                ),
            ):
                row.score
            for row
            in scores.itertuples()
        }

        gameweeks = sorted(
            matchups[
                "GW"
            ].unique()
        )

        for gw in gameweeks:

            gw_matches = (
                matchups[
                    matchups[
                        "GW"
                    ] == gw
                ]
            )

            match_rows = []

            for match in (
                gw_matches
                .itertuples()
            ):

                entry_a = int(
                    match.entry_a
                )

                entry_b = int(
                    match.entry_b
                )

                score_a = (
                    score_map.get(
                        (
                            int(gw),
                            entry_a,
                        )
                    )
                )

                score_b = (
                    score_map.get(
                        (
                            int(gw),
                            entry_b,
                        )
                    )
                )

                match_rows.append({
                    "Player 1":
                        names.get(
                            entry_a,
                            str(entry_a),
                        ),
                    "Score 1":
                        (
                            int(score_a)
                            if score_a
                            is not None
                            else ""
                        ),
                    "Score 2":
                        (
                            int(score_b)
                            if score_b
                            is not None
                            else ""
                        ),
                    "Player 2":
                        names.get(
                            entry_b,
                            str(entry_b),
                        ),
                })

            if match_rows:

                st.markdown(
                    f"### GW "
                    f"{int(gw)}"
                )

                st.dataframe(
                    pd.DataFrame(
                        match_rows
                    ),
                    hide_index=True,
                    use_container_width=True,
                )

                st.divider()


# ============================================================
# TAB 4 — League Analysis
# ============================================================

with tab4:

    # --------------------------------------------------------
    # Opponent strength
    # --------------------------------------------------------

    st.subheader(
        "Opponent strength"
    )

    opponent_strength = (
        compute_opponent_strength(
            scores,
            matchups,
        )
    )

    opponent_strength = (
        opponent_strength.merge(
            entries[
                [
                    "league_entry",
                    "manager",
                ]
            ],
            on="league_entry",
            how="right",
        )
    )

    opponent_strength[
        "Opponent avg"
    ] = (
        opponent_strength[
            "Opponent avg"
        ]
        .fillna(0)
        .round(2)
    )

    opponent_strength[
        "Opponent FPL points"
    ] = (
        opponent_strength[
            "Opponent FPL points"
        ]
        .fillna(0)
        .astype(int)
    )

    opponent_strength = (
        opponent_strength[
            [
                "manager",
                "Opponent avg",
                "Opponent FPL points",
            ]
        ]
    )

    opponent_strength.columns = [
        "Manager",
        "Opponent avg",
        "Opponent FPL points",
    ]

    opponent_strength = (
        order_by_draft(
            opponent_strength,
            "Manager",
            participant_order,
            names,
        )
    )

    st.dataframe(
        opponent_strength,
        hide_index=True,
        use_container_width=True,
    )


    # --------------------------------------------------------
    # Best / worst
    # --------------------------------------------------------

    st.subheader(
        "Best / worst weeks"
    )

    st.dataframe(
        best_worst,
        hide_index=True,
        use_container_width=True,
    )


    # --------------------------------------------------------
    # Consistency
    # --------------------------------------------------------

    st.subheader(
        "Consistency"
    )

    st.dataframe(
        consistency,
        hide_index=True,
        use_container_width=True,
    )


    # ----------------------------------------------------
    # Position contribution & formation usage
    # ----------------------------------------------------
    st.subheader("Position contribution")

    position_rows = player_squad_gw.merge(
        player_meta[["element", "Position"]], on="element", how="left"
    )
    position_rows = position_rows[position_rows["Counted"] == True].copy()
    if position_rows.empty:
        st.info("No counted lineup data found for this selection.")
    else:
        # Draft bootstrap uses GKP for goalkeepers; normalize the display/analysis label.
        position_rows["Position"] = position_rows["Position"].replace({"GKP": "GK"})
        position_view = (
            position_rows.groupby(["Manager", "Position"], as_index=False)
            .agg(
                **{
                    "Counted points": ("Counted points", "sum"),
                    "Played slots": ("element", "size"),
                }
            )
        )
        position_view["Pts/played slot"] = (
            position_view["Counted points"] / position_view["Played slots"]
        )
        manager_totals = (
            position_view.groupby("Manager")["Counted points"]
            .transform("sum")
            .replace(0, pd.NA)
        )
        position_view["Share of team pts"] = (
            100 * position_view["Counted points"] / manager_totals
        )
        position_order = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
        position_view["_position_order"] = position_view["Position"].map(position_order).fillna(99)
        position_view = position_view.sort_values(
            ["Manager", "_position_order"]
        ).drop(columns="_position_order")
        position_columns = ["GK", "DEF", "MID", "FWD"]

        counted_points_table = (
            position_view.pivot(index="Manager", columns="Position", values="Counted points")
            .reindex(columns=position_columns)
            .reset_index()
        )
        pts_per_slot_table = (
            position_view.pivot(index="Manager", columns="Position", values="Pts/played slot")
            .reindex(columns=position_columns)
            .reset_index()
        )

        # Manager-comparison tables use the original draft order.
        counted_points_table = order_by_draft(
            counted_points_table, "Manager", participant_order, names
        )
        pts_per_slot_table = order_by_draft(
            pts_per_slot_table, "Manager", participant_order, names
        )

        st.markdown("**Counted points by position**")
        st.dataframe(
            counted_points_table.round(2),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Total points contributed to each manager's counted XI by goalkeepers, defenders, "
            "midfielders and forwards, using the final lineup after autosubs."
        )

        st.markdown("**Points per played slot**")
        st.dataframe(
            pts_per_slot_table.round(2),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Average points produced by one counted lineup slot at each position. For example, MID "
            "is total counted midfielder points divided by the total number of midfielder slots used "
            "in the final counted XI across gameweeks."
        )

    st.subheader("Formation usage")
    formation_rows = player_squad_gw.merge(
        player_meta[["element", "Position"]], on="element", how="left"
    )
    formation_rows = formation_rows[formation_rows["Counted"] == True].copy()
    if formation_rows.empty:
        st.info("No formation data found for this selection.")
    else:
        formation_counts = (
            formation_rows[formation_rows["Position"].isin(["DEF", "MID", "FWD"])]
            .groupby(["Manager", "GW", "Position"])
            .size()
            .unstack(fill_value=0)
            .reset_index()
        )
        for pos in ["DEF", "MID", "FWD"]:
            if pos not in formation_counts.columns:
                formation_counts[pos] = 0
        formation_counts["Formation"] = formation_counts.apply(
            lambda r: f"{int(r['DEF'])}-{int(r['MID'])}-{int(r['FWD'])}", axis=1
        )
        formation_usage = (
            formation_counts.groupby(["Manager", "Formation"], as_index=False)
            .agg(**{"GWs used": ("GW", "nunique")})
        )
        total_gws = formation_counts.groupby("Manager")["GW"].nunique().rename("Total GWs")
        formation_usage = formation_usage.merge(total_gws, on="Manager", how="left")
        formation_usage["% of GWs"] = 100 * formation_usage["GWs used"] / formation_usage["Total GWs"]
        formation_usage = formation_usage.sort_values(
            ["Manager", "GWs used", "Formation"], ascending=[True, False, True]
        )
        most_played = formation_usage.groupby("Manager", as_index=False).first()
        most_played = most_played[["Manager", "Formation", "GWs used", "% of GWs"]]
        most_played = most_played.rename(columns={"Formation": "Most played formation"})
        most_played = order_by_draft(
            most_played, "Manager", participant_order, names
        )
        st.dataframe(
            most_played.round(2),
            hide_index=True,
            use_container_width=True,
        )
    st.caption(
        "Most played formation is based on each manager's final counted XI after autosubs. "
        "The goalkeeper is omitted from conventional formation notation, so 4-4-2 means four "
        "defenders, four midfielders and two forwards."
    )


# ============================================================
# TAB 5 — Schedule Analysis
# ============================================================

with tab5:

    st.subheader("Schedule summary")

    if schedule_results.empty:
        st.warning(
            "Schedule analysis requires exactly six fixture slots (including Average, if used by "
            "the league). No schedule simulation was produced for the current league structure."
        )
    else:
        st.dataframe(
            schedule_summary.round({
                "Mean H2H": 2,
                "Median H2H": 2,
                "H2H percentile": 1,
                "Avg position": 2,
                "1st-place %": 1,
            }),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            f"All {schedule_results['Schedule'].nunique()} valid fixture assignments are enumerated "
            "exhaustively; this is not a random simulation. Every manager keeps the FPL score they "
            "actually recorded in each GW and only the fixture draw changes. Mean, median, minimum "
            "and maximum H2H points therefore measure schedule sensitivity. H2H percentile is the "
            "share of schedules producing H2H points less than or equal to the actual draw. Final "
            "positions use H2H points first and total FPL points as the tie-break."
        )

        st.subheader("Finishing-position distribution")
        st.dataframe(
            finish_distribution,
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Each cell shows count (percentage) across all 720 schedules. Because every schedule is "
            "enumerated, these are exact frequencies for the alternative fixture draws rather than "
            "Monte Carlo estimates."
        )

        st.subheader("All-season H2H matrix")
        st.dataframe(
            all_season_h2h_matrix,
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Each cell shows W-D-L from the row manager's perspective if that manager had played "
            "the column opponent in every completed GW, using the scores actually recorded. "
            "Average is included as a full participant. This is schedule-independent and shows "
            "how each pair of season-long scoring records compares directly."
        )

        st.subheader("Alternative schedule explorer")
        real_entries = [int(e) for e in participant_order]
        selected_entry = st.selectbox(
            "Manager",
            options=real_entries,
            format_func=lambda e: names.get(e, str(e)),
            key="schedule_explorer_manager",
        )
        scenario = st.selectbox(
            "Scenario",
            options=["Highest H2H points", "Lowest H2H points", "Finishes 1st"],
            key="schedule_explorer_scenario",
        )
        manager_name = names.get(selected_entry, str(selected_entry))
        manager_schedules = schedule_results[
            schedule_results["league_entry"] == selected_entry
        ].copy()

        chosen = pd.DataFrame()
        if scenario == "Highest H2H points":
            chosen = manager_schedules.sort_values(
                ["H2H points", "Rank", "Schedule"], ascending=[False, True, True]
            ).head(1)
        elif scenario == "Lowest H2H points":
            chosen = manager_schedules.sort_values(
                ["H2H points", "Rank", "Schedule"], ascending=[True, False, True]
            ).head(1)
        else:
            winners = manager_schedules[manager_schedules["Rank"] == 1]
            if not winners.empty:
                chosen = winners.sort_values(
                    ["H2H points", "Schedule"], ascending=[False, True]
                ).head(1)

        if chosen.empty:
            st.info(f"{manager_name} does not finish 1st in any of the 720 schedules.")
        else:
            chosen_row = chosen.iloc[0]
            chosen_schedule = int(chosen_row["Schedule"])
            st.markdown(
                f"**Schedule {chosen_schedule}: {int(chosen_row['H2H points'])} H2H points, "
                f"{ordinal(int(chosen_row['Rank']))} place**"
            )

            fixture_view = schedule_fixture_view(
                chosen_schedule, selected_entry, schedule_assignments,
                matchups, scores, schedule_valid_gws, names,
            )
            st.dataframe(fixture_view, hide_index=True, use_container_width=True)

            schedule_table = schedule_results[
                schedule_results["Schedule"] == chosen_schedule
            ][["Manager", "W", "D", "L", "FPL points", "H2H points", "Rank"]].copy()
            schedule_table = schedule_table.sort_values("Rank")
            st.markdown("**Resulting standings**")
            st.dataframe(schedule_table, hide_index=True, use_container_width=True)
            st.caption(
                "The explorer shows one concrete valid fixture draw from the same exhaustive set. "
                "Scores are never changed: only opponents are reassigned according to the existing "
                "fixture template. 'Finishes 1st' selects a first-place schedule with the highest H2H "
                "total for the chosen manager when such a schedule exists."
            )


# ============================================================
# TAB 8 — Charts
# ============================================================

with tab8:

    # No st.caption() calls in this tab.

    st.subheader(
        "Cumulative H2H points"
    )

    if not actual.empty:

        cumulative_h2h = (
            actual
            .pivot(
                index="GW",
                columns=
                    "league_entry",
                values=
                    "actual_points",
            )
            .fillna(0)
            .sort_index()
            .cumsum()
        )

        cumulative_h2h = (
            cumulative_h2h
            .reindex(
                columns=
                    participant_order
            )
            .rename(
                columns=names
            )
        )

        st.line_chart(
            cumulative_h2h
        )


    st.subheader(
        "Cumulative expected H2H points"
    )

    if not expected.empty:

        cumulative_expected = (
            expected
            .pivot(
                index="GW",
                columns=
                    "league_entry",
                values=
                    "expected_points",
            )
            .fillna(0)
            .sort_index()
            .cumsum()
        )

        cumulative_expected = (
            cumulative_expected
            .reindex(
                columns=
                    participant_order
            )
            .rename(
                columns=names
            )
        )

        st.line_chart(
            cumulative_expected
        )


    st.subheader(
        "Cumulative FPL points"
    )

    cumulative_fpl = (
        scores
        .pivot(
            index="GW",
            columns=
                "league_entry",
            values="score",
        )
        .fillna(0)
        .sort_index()
        .cumsum()
    )

    cumulative_fpl = (
        cumulative_fpl
        .reindex(
            columns=
                participant_order
        )
        .rename(
            columns=names
        )
    )

    st.line_chart(
        cumulative_fpl
    )




    st.subheader("H2H points across all fixture schedules")

    if not schedule_results.empty:
        distribution = (
            schedule_results.groupby(["H2H points", "Manager"])
            .size()
            .rename("Schedules")
            .reset_index()
            .pivot(index="H2H points", columns="Manager", values="Schedules")
            .fillna(0)
            .sort_index()
        )
        manager_columns = [
            names[e] for e in participant_order
            if names.get(e) in distribution.columns
        ]
        distribution = distribution.reindex(columns=manager_columns)
        st.line_chart(distribution)

# ============================================================
# TAB 5 — Squad Activity
# ============================================================

with tab6:

    st.subheader("Squad activity")

    if transactions.empty:
        st.info("No transaction data was returned by the Draft transactions endpoint.")
    else:
        activity_summary = build_squad_activity_summary(
            transactions,
            contested_waivers,
            participant_order,
            names,
        )

        st.dataframe(
            activity_summary,
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Tracks how managers have changed their squads through waivers and free agents. "
            "This summary counts only completed moves. Contested waivers use the waiver processing "
            "order to distinguish genuine wins and losses; Contested win % is wins divided by "
            "genuine contested waiver decisions and is blank when a manager has had none."
        )

        st.subheader("Contested waivers")
        if contested_waivers.empty:
            st.info("No genuinely contested waivers have been identified.")
        else:
            st.dataframe(
                contested_waivers
                .drop(columns=["_losing_managers"], errors="ignore")
                .sort_values(["GW", "Player"], ascending=[False, True]),
                hide_index=True,
                use_container_width=True,
            )
            st.caption(
            "Waiver claims where more than one manager could genuinely have received the "
            "same player at processing time. Failed claims caused by an already-invalid "
            "incoming or outgoing player are not treated as contested losses."
        )

        # ----------------------------------------------------
        # Cumulative transaction impact
        # ----------------------------------------------------
        st.subheader("Cumulative waiver/free-agent impact")
        cumulative_summary_view = cumulative_transaction_summary.copy()
        cumulative_detail_view = cumulative_transaction_detail.copy()

        if cumulative_summary_view.empty:
            st.info("No cumulative transaction-impact data available for this selection.")
        else:
            cumulative_summary_view = order_by_draft(
                cumulative_summary_view, "Manager", participant_order, names
            )
            st.dataframe(
                cumulative_summary_view.round(2),
                hide_index=True,
                use_container_width=True,
            )
            st.caption(
            "Season-to-date counterfactual: what would your H2H record look like with the original "
            "draft squad and no successful waivers/free-agent moves? Direct mechanically restores "
            "moved-out players into affected roles. Adjusted preserves your actual lineup choices "
            "where possible and prefers an eligible player from your actual bench before assuming "
            "the moved-out player would have started. Neither method chooses players using hindsight "
            "GW points. H2H impact = actual league points minus counterfactual league points, so a "
            "positive value means the moves improved the recorded H2H outcome under that model."
        )

            with st.expander("GW-by-GW counterfactual audit"):
                audit_columns = [
                    "Manager", "GW", "Actual score", "Opponent score",
                    "Direct no-moves score", "Adjusted no-moves score",
                    "Squad pts impact", "Actual H2H pts",
                    "Direct no-moves H2H", "Adjusted no-moves H2H",
                    "Direct H2H impact", "Adjusted H2H impact",
                    "Cumulative adjusted H2H impact", "Result changed",
                ]
                draft_manager_order = [
                    names.get(entry_id, str(entry_id)) for entry_id in participant_order
                ]
                manager_rank = {manager: rank for rank, manager in enumerate(draft_manager_order)}
                cumulative_detail_view["_manager_order"] = (
                    cumulative_detail_view["Manager"].map(manager_rank).fillna(999)
                )
                cumulative_detail_view["_gw_order"] = pd.to_numeric(
                    cumulative_detail_view["GW"], errors="coerce"
                )
                cumulative_detail_view = (
                    cumulative_detail_view
                    .sort_values(["_manager_order", "_gw_order"])
                    .drop(columns=["_manager_order", "_gw_order"])
                )
                st.dataframe(
                    cumulative_detail_view[audit_columns].round(2),
                    hide_index=True,
                    use_container_width=True,
                )
                st.caption(
                    "Audit trail behind the cumulative totals. Result changed flags a GW where the "
                    "adjusted no-moves scenario changes win/draw/loss versus the actual result. "
                    "Cumulative adjusted H2H impact is the running difference in league points."
                )

        st.subheader("Completed squad changes")
        completed = transactions[
            (transactions["result"] == "a")
            & (transactions["kind"].isin(["w", "f"]))
            & (transactions["Manager"] != "Unknown")
        ].copy()
        completed["Type"] = completed["kind"].map({"w": "Waiver", "f": "Free agent"})

        manager_options = ["All"] + [
            names[e] for e in participant_order if names.get(e) != "Average"
        ]
        selected_manager = st.selectbox("Manager", manager_options)
        if selected_manager != "All":
            completed = completed[completed["Manager"] == selected_manager]

        completed = completed.sort_values(["GW", "Time"], ascending=[False, False])
        st.dataframe(
            completed[["GW", "Manager", "Type", "Player in", "Player out"]],
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Accepted waivers and free-agent moves, newest first. Player in joined the "
            "manager's squad; Player out was released in the same move."
        )


# ============================================================
# TAB 6 — Player Performance
# ============================================================

with tab7:
    st.subheader("Player performance")

    if player_squad_gw.empty:
        st.warning(
            "Draft lineup data could not be loaded from the entry/event endpoint. "
            "The regular FPL event/live endpoint is used separately for player GW points."
        )
    else:
        manager_options = ["All"] + [
            names[e] for e in participant_order if names.get(e) != "Average"
        ]
        player_manager = st.selectbox(
            "Manager",
            manager_options,
            key="player_performance_manager",
        )

        # ----------------------------------------------------
        # Player contribution
        # ----------------------------------------------------
        st.subheader("Player contribution")
        contribution_view = player_contribution.copy()
        if player_manager != "All":
            contribution_view = contribution_view[
                contribution_view["Manager"] == player_manager
            ]

        contribution_view = contribution_view.sort_values(
            ["Points in XI", "Avg/counted app"], ascending=[False, False]
        )
        st.dataframe(
            contribution_view.drop(columns=["entry_id", "element"], errors="ignore").round(2),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Evaluates player contribution while owned. Each row is a manager-player pairing across "
            "all ownership spells. Starts means initially selected in the XI; Counted apps means the "
            "player ultimately counted after automatic substitutions. Points in XI includes only those "
            "counted points, and Source can contain multiple spells when a player was dropped and later reacquired."
        )

        # ----------------------------------------------------
        # Acquisition impact
        # ----------------------------------------------------
        st.subheader("Acquisition impact")
        acquisition_view = acquisition_impact.copy()
        if player_manager != "All" and not acquisition_view.empty:
            acquisition_view = acquisition_view[
                acquisition_view["Manager"] == player_manager
            ]
        if acquisition_view.empty:
            st.info("No completed acquisitions for this selection.")
        else:
            impact_columns = [
                "Manager", "GW", "Type", "Player in", "Player out",
                "First GW counted", "First 3 counted", "Total counted",
                "First GW FPL", "First 3 FPL", "Total FPL while owned",
                "GWs kept", "Counted pts/GW",
            ]
            st.dataframe(
                acquisition_view[impact_columns]
                .sort_values(["Total counted", "Counted pts/GW"], ascending=[False, False])
                .round(2),
                hide_index=True,
                use_container_width=True,
            )
            st.caption(
                "One row per successful waiver or free-agent acquisition. Counted columns measure "
                "points that actually entered the manager's XI; FPL columns show the player's raw "
                "score whether started or benched. GWs kept refers only to that acquisition spell."
            )

            st.subheader("Transaction comparison")
            comparison_columns = [
                "Manager", "GW", "Type", "Player in", "Player out",
                "1-GW in-out", "3-GW in-out", "5-GW in-out",
            ]
            st.dataframe(
                acquisition_view[comparison_columns]
                .sort_values(["3-GW in-out", "1-GW in-out"], ascending=[False, False]),
                hide_index=True,
                use_container_width=True,
            )
            st.caption(
                "Compares the raw FPL output of Player in with Player out over the next 1, 3 and "
                "5 GWs. Positive values favour the incoming player. This is a player-performance "
                "comparison, not a claim that the transaction changed the H2H result."
            )

            short_stays = acquisition_view[
                acquisition_view["GWs kept"].between(1, 3)
            ].copy()
            if not short_stays.empty:
                st.subheader("Short-stay returns")
                short_stay_columns = [
                    "Manager", "Player in", "Player out", "GW", "Type",
                    "GWs kept", "Total counted", "Counted pts/GW",
                ]
                st.dataframe(
                    short_stays[short_stay_columns]
                    .sort_values(["Counted pts/GW", "Total counted"], ascending=[False, False])
                    .round(2),
                    hide_index=True,
                    use_container_width=True,
                )
                st.caption(
                    "Acquisitions kept for only 1–3 GWs. This highlights brief pickups that still "
                    "returned useful counted points; Counted pts/GW is calculated within that spell."
                )

        # ----------------------------------------------------
        # Painful drops
        # ----------------------------------------------------
        st.subheader("Painful drops")
        pain_view = painful_drops.copy()
        if player_manager != "All" and not pain_view.empty:
            pain_view = pain_view[pain_view["Dropped by"] == player_manager]
        if pain_view.empty:
            st.info("No released players were subsequently owned by another manager for this selection.")
        else:
            st.dataframe(
                pain_view.sort_values(
                    ["Pts for new manager", "First 3 pts"], ascending=[False, False]
                ),
                hide_index=True,
                use_container_width=True,
            )
        st.caption(
            "Players you released who were later acquired by another manager. The table measures "
            "what the new manager received after the pickup, separating post-drop performance from "
            "points that actually counted for the opponent."
        )

        st.subheader("Former players against their old manager")
        revenge_view = former_player_h2h.copy()
        if player_manager != "All" and not revenge_view.empty:
            revenge_view = revenge_view[
                revenge_view["Former owner"] == player_manager
            ]
        if revenge_view.empty:
            st.info("No former-player H2H returns found for this selection.")
        else:
            st.dataframe(
                revenge_view.sort_values(["Player pts", "GW"], ascending=[False, False]),
                hide_index=True,
                use_container_width=True,
            )
        st.caption(
            "Former players who later produced counted points while facing their previous owner in "
            "H2H. This identifies notable returns against an old manager; it does not by itself mean "
            "the drop caused the match result."
        )

        # ----------------------------------------------------
        # Draft performance
        # ----------------------------------------------------
        st.subheader("Draft performance")
        draft_view = draft_performance.copy()
        if player_manager != "All" and not draft_view.empty:
            draft_view = draft_view[draft_view["Manager"] == player_manager]
        if player_manager == "All":
            draft_view = draft_view.sort_values(
                ["Draft pick", "Points in XI"], ascending=[True, False]
            )
        else:
            draft_view = draft_view.sort_values("Draft pick", ascending=True)
        st.dataframe(
            draft_view.round(2),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Performance of the original draft ownership spell only. If a drafted player was dropped "
            "and later reacquired, the later spell is excluded here and appears as an acquisition instead."
        )

        # ----------------------------------------------------
        # Lineup decisions / bench regret
        # ----------------------------------------------------
        st.subheader("Lineup decisions")
        bench = player_contribution.copy()
        if player_manager != "All":
            bench = bench[bench["Manager"] == player_manager]
        bench = bench[bench["Bench points"] > 0].sort_values(
            "Bench points", ascending=False
        )
        if bench.empty:
            st.info("No unused bench points found for this selection.")
        else:
            st.dataframe(
                bench[["Manager", "Player", "Position", "GWs owned", "Starts", "Counted apps", "Autosub in", "Autosub out", "Unused bench", "Bench points"]],
                hide_index=True,
                use_container_width=True,
            )
        st.caption(
            "Shows points left outside the counted XI while a player was owned. Starts refers to the "
            "initial XI before autosubs; Counted apps reflects the final XI after autosubs. Autosub in/out "
            "helps distinguish manager selection from automatic substitution effects."
        )

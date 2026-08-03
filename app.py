import json
import math
from pathlib import Path

import pandas as pd
import streamlit as st

ATP_FILE = "data/atp_matches_database.csv"
WTA_FILE = "data/wta_matches_database.csv"
ATP_PLAYERS_FILE = "atp_players.csv"
WTA_PLAYERS_FILE = "wta_players.csv"

PLAYER_SELECTION_LIMIT = 300
REFERENCE_RANK_LIMIT = 200
EXCLUDED_TOURNAMENTS = "Davis Cup|Laver Cup"

SETTINGS_FILE = "last_search.json"
TOLERANCES = [0.1, 0.2, 0.3]

st.set_page_config(page_title="Tennis Prediction", layout="wide")
st.title("🎾 Tennis Prediction")

if Path("last_update.txt").exists():
    last_update_text = Path("last_update.txt").read_text(encoding="utf-8").strip()
else:
    last_update_text = "neznáme"

atp_rows = sum(1 for _ in open(ATP_FILE, encoding="utf-8-sig")) - 1
wta_rows = sum(1 for _ in open(WTA_FILE, encoding="utf-8-sig")) - 1

st.caption(
    f"📅 Posledná aktualizácia: {last_update_text} | "
    f"ATP: {atp_rows:,}".replace(",", " ") + " | "
    f"WTA: {wta_rows:,}".replace(",", " ")
)


def load_settings():
    if Path(SETTINGS_FILE).exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return {
        "tour": "ATP",
        "player1": "",
        "player2": "",
        "surface": "Hard",
        "period": "Last 104 weeks",
        "year_from": 2024,
        "year_to": 2026,
        "level": "ATP",
        "include_qual": False,
        "og": 22.0,
    }


def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def to_number(x):
    if pd.isna(x):
        return None
    if isinstance(x, str):
        x = x.replace(",", ".")
    return pd.to_numeric(x, errors="coerce")


def short_name(name):
    parts = str(name).split()
    return parts[-1] if parts else str(name)


def fmt(x):
    if x is None or pd.isna(x):
        return ""
    return f"{x:.2f}"


def fmt4(x):
    if x is None or pd.isna(x):
        return ""
    return f"{x:.4f}"


def level_filter(df, tour, level):
    if level == "All":
        return df

    if tour == "ATP" and level == "ATP":
        return df[df["Level"].isin(["A", "M", "G", "D"])]

    if tour == "WTA" and level == "WTA":
        return df[df["Level"].isin(["G", "PM", "P", "W", "F"])]

    return df[df["Level"] == level]


@st.cache_data
def load_database(tour):
    file = ATP_FILE if tour == "ATP" else WTA_FILE

    df = pd.read_csv(
        file,
        sep=";",
        decimal=",",
        encoding="utf-8-sig"
    )

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Year"] = df["Date"].dt.year

    for col in ["A%", "vA%", "Pts/SG", "DF%"]:
        if col in df.columns:
            df[col] = df[col].apply(to_number)

    if "IsTop100" in df.columns:
        df["IsTop100"] = df["IsTop100"].astype(str).str.upper().isin(["TRUE", "1", "YES", "ÁNO", "ANO"])
    else:
        df["IsTop100"] = False

    return df


@st.cache_data
def load_rankings(tour):
    file = ATP_PLAYERS_FILE if tour == "ATP" else WTA_PLAYERS_FILE
    rankings = pd.read_csv(file, encoding="utf-8-sig")

    required = {"rank", "name"}
    missing = required - set(rankings.columns)
    if missing:
        raise ValueError(
            f"V súbore {file} chýbajú stĺpce: {', '.join(sorted(missing))}. "
            "Najprv spusti update_rankings.py."
        )

    rankings["rank"] = pd.to_numeric(rankings["rank"], errors="coerce")
    rankings["name"] = (
        rankings["name"]
        .astype(str)
        .str.replace("\xa0", " ", regex=False)
        .str.strip()
    )

    return (
        rankings.dropna(subset=["rank", "name"])
        .sort_values("rank")
        .drop_duplicates(subset=["name"], keep="first")
        .reset_index(drop=True)
    )


def resolve_period(period, year_from, year_to):
    today = pd.Timestamp.today().normalize()

    rolling_weeks = {
        "Last 26 weeks": 26,
        "Last 52 weeks": 52,
        "Last 104 weeks": 104,
    }

    if period in rolling_weeks:
        date_to = today
        date_from = today - pd.Timedelta(weeks=rolling_weeks[period])
        label = f"{period} ({date_from:%d.%m.%Y}–{date_to:%d.%m.%Y})"
        return date_from, date_to, label

    date_from = pd.Timestamp(year=int(year_from), month=1, day=1)
    date_to = pd.Timestamp(year=int(year_to), month=12, day=31)
    label = f"{int(year_from)}–{int(year_to)}"
    return date_from, date_to, label


def calculate_reference_averages(df, reference_names, surface):
    reference_df = df[
        df["Player"].isin(reference_names)
        & df["Opponent"].isin(reference_names)
    ].copy()

    if reference_df.empty:
        return None, None, None, 0

    avg_a = reference_df["A%"].mean()
    avg_va = reference_df["vA%"].mean()

    grass_avg_va = None
    if surface == "Grass":
        grass_reference = reference_df[
            reference_df["Surface"] == "Grass"
        ]
        grass_avg_va = grass_reference["vA%"].mean()

    return avg_a, avg_va, grass_avg_va, len(reference_df)


def get_profile(profiles, player):
    row = profiles[profiles["Player"] == player]
    if row.empty:
        return None
    return row.iloc[0]
    
def build_profiles(df_all, tour, level, surface, date_from, date_to, include_qual):
    df_base = df_all.copy()
    df_base = df_base[(df_base["Date"] >= date_from) & (df_base["Date"] <= date_to)]
    df_base = level_filter(df_base, tour, level)
    
    if not include_qual:
        df_base = df_base[
            ~df_base["Round"].isin(["Q1", "Q2", "Q3"])
            & ~df_base["Tournament"].astype(str).str.contains(EXCLUDED_TOURNAMENTS, case=False, na=False)
        ]

    if surface != "Grass":
        if surface != "All":
            df_base = df_base[df_base["Surface"] == surface]

        profiles = (
            df_base.groupby("Player")
            .agg(
                AvgA=("A%", "mean"),
                AvgvA=("vA%", "mean"),
                AvgPtsSG=("Pts/SG", "mean"),
                AvgDF=("DF%", "mean"),
                Matches=("Player", "count"),
            )
            .reset_index()
        )
        return profiles, df_base

    grass_df = df_base[df_base["Surface"] == "Grass"]
    hard_df = df_base[df_base["Surface"] == "Hard"]

    players = sorted(set(grass_df["Player"].dropna()) | set(hard_df["Player"].dropna()))
    rows = []

    for player in players:
        g = grass_df[grass_df["Player"] == player]
        h = hard_df[hard_df["Player"] == player]

        G = len(g)
        H = len(h)

        if G == 0 and H == 0:
            continue

        def hybrid(col):
            g_val = g[col].mean()
            h_val = h[col].mean()

            if G == 0:
                return h_val

            if H == 0:
                return g_val

            return (G / (G + H)) * g_val + (H / (G + H)) * h_val

        rows.append({
            "Player": player,
            "AvgA": hybrid("A%"),
            "AvgvA": hybrid("vA%"),
            "AvgPtsSG": hybrid("Pts/SG"),
            "AvgDF": hybrid("DF%"),
            "GrassAvgA": g["A%"].mean(),
            "GrassAvgvA": g["vA%"].mean(),
            "GrassAvgPtsSG": g["Pts/SG"].mean(),
            "GrassAvgDF": g["DF%"].mean(),
            "HardAvgA": h["A%"].mean(),
            "HardAvgvA": h["vA%"].mean(),
            "HardAvgPtsSG": h["Pts/SG"].mean(),
            "HardAvgDF": h["DF%"].mean(),
            "Matches": G + H,
            "GrassMatches": G,
            "HardMatches": H,
        })

    profiles = pd.DataFrame(rows)

    match_df = df_base[df_base["Surface"].isin(["Grass", "Hard"])].copy()
    return profiles, match_df

def calc_service(df, profiles, player, opponent, tolerance, surface):
    opp_profile = get_profile(profiles, opponent)
    if opp_profile is None:
        return None, 0

    target = opp_profile["AvgvA"]

    similar_players = profiles[
        (profiles["AvgvA"] >= target - tolerance)
        & (profiles["AvgvA"] <= target + tolerance)
    ]["Player"]

    sample = df[
        (df["Player"] == player)
        & (df["Opponent"].isin(similar_players))
    ]

    if surface != "All":
        sample = sample[sample["Surface"] == surface]

    return sample["A%"].mean(), len(sample)


def calc_return(df, profiles, player, opponent, tolerance, surface):
    opp_profile = get_profile(profiles, opponent)
    if opp_profile is None:
        return None, 0

    target = opp_profile["AvgA"]
    
    similar_players = profiles[
        (profiles["AvgA"] >= target - tolerance)
        & (profiles["AvgA"] <= target + tolerance)
    ]["Player"]

    sample = df[
        (df["Player"] == player)
        & (df["Opponent"].isin(similar_players))
    ]

    if surface != "All":
        sample = sample[sample["Surface"] == surface]

    return sample["vA%"].mean(), len(sample)


def pred_aces(og, ptsg, pct):
    if pct is None or pd.isna(pct):
        return None
    return og * ptsg * pct / 200


def ace_models(og, player_a, player_ptsg, opponent_va, reference_avg_va):
    base = og / 2 * player_ptsg * player_a / 100

    if reference_avg_va is None or pd.isna(reference_avg_va) or reference_avg_va == 0:
        return base, None, None

    ratio = opponent_va / reference_avg_va

    full = base * ratio
    sqrt_model = base * math.sqrt(ratio) if ratio >= 0 else None

    return base, full, sqrt_model


def pred_df(og, ptsg, df_pct):
    if df_pct is None or pd.isna(df_pct):
        return None
    return og / 2 * ptsg * df_pct / 100


def section(title):
    st.markdown(
        f"""
        <div style="
            background:#1F4E78;
            color:white;
            padding:8px;
            font-weight:bold;
            text-align:center;
            margin-top:18px;
            border-radius:4px;">
            {title}
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_table(df):
    st.table(df)


def option_index(options, value, default=0):
    return options.index(value) if value in options else default


def player_header_with_rank(rankings, player):
    rank = rankings.loc[rankings["name"] == player, "rank"]
    if rank.empty or pd.isna(rank.iloc[0]):
        return player
    return f"{player} (#{int(rank.iloc[0])})"


settings = load_settings()

left, right = st.columns([1, 4])

with left:
    st.subheader("Výber")

    tour_options = ["ATP", "WTA"]
    tour = st.selectbox(
        "Tour",
        tour_options,
        index=option_index(tour_options, settings.get("tour", "ATP")),
    )

    df_all = load_database(tour)
    rankings = load_rankings(tour)

    player_rankings = rankings[rankings["rank"] <= PLAYER_SELECTION_LIMIT].copy()
    players = player_rankings["name"].tolist()

    if not players:
        st.error("Aktuálny ranking neobsahuje žiadnych hráčov.")
        st.stop()

    p1_index = option_index(players, settings.get("player1", ""), 0)
    p2_index = option_index(players, settings.get("player2", ""), 1 if len(players) > 1 else 0)

    player1 = st.selectbox("Player 1", players, index=p1_index)
    player2 = st.selectbox("Player 2", players, index=p2_index)

    surface_options = ["Hard", "Clay", "Grass", "All"]
    surface = st.selectbox(
        "Surface",
        surface_options,
        index=option_index(surface_options, settings.get("surface", "Hard")),
    )

    period_options = [
        "Last 26 weeks",
        "Last 52 weeks",
        "Last 104 weeks",
        "Custom years",
    ]
    period = st.selectbox(
        "Obdobie",
        period_options,
        index=option_index(
            period_options,
            settings.get("period", "Last 104 weeks"),
            2,
        ),
    )

    if period == "Custom years":
        year_from = st.number_input(
            "From Year",
            value=int(settings.get("year_from", 2024)),
            step=1,
        )

        year_to = st.number_input(
            "To Year",
            value=int(settings.get("year_to", 2026)),
            step=1,
        )
    else:
        year_from = int(settings.get("year_from", 2024))
        year_to = int(settings.get("year_to", 2026))

    if tour == "ATP":
        level_options = ["ATP", "All", "G", "M", "A", "C", "D"]
        default_level = "ATP"
    else:
        level_options = ["WTA", "All", "G", "PM", "P", "W", "C", "I", "100", "75", "50", "35", "15"]
        default_level = "WTA"

    level = st.selectbox(
        "Level",
        level_options,
        index=option_index(level_options, settings.get("level", default_level)),
    )
    
    include_qual = st.checkbox(
        "Include Qualifying Matches",
        value=bool(settings.get("include_qual", False)),
    )

    og = st.number_input(
        "Odhad gemov",
        value=float(settings.get("og", 22.0)),
        step=1.0,
    )

    run = st.button("Vypočítať")


with right:
    if run:
        save_settings(
            {
                "tour": tour,
                "player1": player1,
                "player2": player2,
                "surface": surface,
                "period": period,
                "year_from": int(year_from),
                "year_to": int(year_to),
                "level": level,
                "include_qual": bool(include_qual),
                "og": float(og),
            }
        )

        if period == "Custom years" and int(year_from) > int(year_to):
            st.error("From Year nemôže byť vyšší ako To Year.")
            st.stop()

        date_from, date_to, period_label = resolve_period(
            period,
            year_from,
            year_to,
        )

        profiles, df = build_profiles(
            df_all,
            tour,
            level,
            surface,
            date_from,
            date_to,
            include_qual,
        )

        p1 = get_profile(profiles, player1)
        p2 = get_profile(profiles, player2)

        if p1 is None or p2 is None:
            st.error("Niektorý hráč/hráčka nemá dáta pre zvolené filtre.")
            st.stop()

        p1_aces_header = player_header_with_rank(rankings, player1)
        p2_aces_header = player_header_with_rank(rankings, player2)

        reference_names = set(
            rankings[rankings["rank"] <= REFERENCE_RANK_LIMIT]["name"]
        )

        (
            reference_avg_a,
            reference_avg_va,
            reference_grass_avg_va,
            reference_matches,
        ) = calculate_reference_averages(
            df,
            reference_names,
            surface,
        )

        if reference_matches == 0:
            st.error(
                "Pre aktuálny Top 200 sa pri zvolených filtroch nenašli žiadne zápasy."
            )
            st.stop()

        p1_base, p1_full, p1_sqrt = ace_models(
            og,
            p1["AvgA"],
            p1["AvgPtsSG"],
            p2["AvgvA"],
            reference_avg_va,
        )

        p2_base, p2_full, p2_sqrt = ace_models(
            og,
            p2["AvgA"],
            p2["AvgPtsSG"],
            p1["AvgvA"],
            reference_avg_va,
        )

        p1_grass_base, p1_grass_full, p1_grass_sqrt = (None, None, None)
        p2_grass_base, p2_grass_full, p2_grass_sqrt = (None, None, None)

        if surface == "Grass":
            if p1.get("GrassMatches", 0) >= 5:
                p1_grass_base, p1_grass_full, p1_grass_sqrt = ace_models(
                    og,
                    p1["GrassAvgA"],
                    p1["GrassAvgPtsSG"],
                    p2["GrassAvgvA"],
                    reference_grass_avg_va,
                )

            if p2.get("GrassMatches", 0) >= 5:
                p2_grass_base, p2_grass_full, p2_grass_sqrt = ace_models(
                    og,
                    p2["GrassAvgA"],
                    p2["GrassAvgPtsSG"],
                    p1["GrassAvgvA"],
                    reference_grass_avg_va,
                )

        p1_pred_df = pred_df(og, p1["AvgPtsSG"], p1["AvgDF"])
        p2_pred_df = pred_df(og, p2["AvgPtsSG"], p2["AvgDF"])

        p1_grass_pred_df = None
        p2_grass_pred_df = None

        if surface == "Grass":
            if p1.get("GrassMatches", 0) >= 5:
                p1_grass_pred_df = pred_df(
                    og,
                    p1["GrassAvgPtsSG"],
                    p1["GrassAvgDF"],
                )

            if p2.get("GrassMatches", 0) >= 5:
                p2_grass_pred_df = pred_df(
                    og,
                    p2["GrassAvgPtsSG"],
                    p2["GrassAvgDF"],
                )

        st.markdown(
            f"""
            <h3 style="text-align:center;">
                {player1} vs {player2} | {surface} | {period_label} | {level}
            </h3>
            """,
            unsafe_allow_html=True,
        )

        section("Základné priemery")

        base_parameters = [
            "A%",
            "vA%",
            "Pts/G",
            "DF%",
        ]

        p1_values = [
            fmt(p1["AvgA"]),
            fmt(p1["AvgvA"]),
            fmt(p1["AvgPtsSG"]),
            fmt(p1["AvgDF"]),
        ]

        p2_values = [
            fmt(p2["AvgA"]),
            fmt(p2["AvgvA"]),
            fmt(p2["AvgPtsSG"]),
            fmt(p2["AvgDF"]),
        ]

        if surface == "Grass":
            base_parameters.extend([
                "vA% (Grass)",
                "Grass zápasy",
                "Hard zápasy",
            ])  

            p1_values.extend([
                fmt(p1["GrassAvgvA"]),
                str(int(p1.get("GrassMatches", 0))),
                str(int(p1.get("HardMatches", 0))),
            ])

            p2_values.extend([
                fmt(p2["GrassAvgvA"]),
                str(int(p2.get("GrassMatches", 0))),
                str(int(p2.get("HardMatches", 0))),
            ])
        else:
            base_parameters.append("Zápasy")

            p1_values.append(str(int(p1["Matches"])))
            p2_values.append(str(int(p2["Matches"])))    

        base_parameters.extend([
            "Top200 avg A% (match-weighted)",
            "Top200 avg vA% (match-weighted)",
            "Top200 ref. zápasy",
        ])

        p1_values.extend([
            fmt4(reference_avg_a),
            fmt4(reference_avg_va),
            str(reference_matches),
        ])

        p2_values.extend([
            fmt4(reference_avg_a),
            fmt4(reference_avg_va),
            str(reference_matches),
        ])

        base = pd.DataFrame(
            {
                "Parameter": base_parameters,
                player1: p1_values,
                player2: p2_values,
            }
        )

        show_table(base)

        section("Model es")

        if surface == "Grass":
            aces_model = pd.DataFrame(
                {
                    "Model": [
                        "Bez korekcie - Hybrid",
                        "Bez korekcie - Grass",
                        "Plná korekcia - Hybrid",
                        "Plná korekcia - Grass",
                        "Odmocnina - Hybrid",
                        "Odmocnina - Grass",
                    ],
                    p1_aces_header: [
                        fmt(p1_base),
                        fmt(p1_grass_base),
                        fmt(p1_full),
                        fmt(p1_grass_full),
                        fmt(p1_sqrt),
                        fmt(p1_grass_sqrt),
                    ],
                    p2_aces_header: [
                        fmt(p2_base),
                        fmt(p2_grass_base),
                        fmt(p2_full),
                        fmt(p2_grass_full),
                        fmt(p2_sqrt),
                        fmt(p2_grass_sqrt),
                    ],
                }
            )
        else:
            aces_model = pd.DataFrame(
                {
                    "Model": ["Bez korekcie", "Plná korekcia", "Odmocnina"],
                    p1_aces_header: [fmt(p1_base), fmt(p1_full), fmt(p1_sqrt)],
                    p2_aces_header: [fmt(p2_base), fmt(p2_full), fmt(p2_sqrt)],
                }
            )

        show_table(aces_model)

        p1_short = short_name(player1)
        p2_short = short_name(player2)

        section("Opponent model service")

        service_rows = []

        for tol in TOLERANCES:
            p1_pct, p1_matches = calc_service(df, profiles, player1, player2, tol, surface)
            p2_pct, p2_matches = calc_service(df, profiles, player2, player1, tol, surface)

            service_rows.append(
                {
                    "Tol": tol,
                    f"{p1_short} záp.": p1_matches,
                    f"{p1_short} esá": fmt(pred_aces(og, p1["AvgPtsSG"], p1_pct)),
                    f"{p2_short} záp.": p2_matches,
                    f"{p2_short} esá": fmt(pred_aces(og, p2["AvgPtsSG"], p2_pct)),
                }
            )

        show_table(pd.DataFrame(service_rows))

        section("Opponent model return")

        return_rows = []

        for tol in TOLERANCES:
            p1_received_pct, p1_received_matches = calc_return(df, profiles, player1, player2, tol, surface)
            p2_received_pct, p2_received_matches = calc_return(df, profiles, player2, player1, tol, surface)

            return_rows.append(
                {
                    "Tol": tol,
                    f"{p1_short} záp.": p2_received_matches,
                    f"{p1_short} esá": fmt(pred_aces(og, p1["AvgPtsSG"], p2_received_pct)),
                    f"{p2_short} záp.": p1_received_matches,
                    f"{p2_short} esá": fmt(pred_aces(og, p2["AvgPtsSG"], p1_received_pct)),
                }
            )

        show_table(pd.DataFrame(return_rows))

        section("Dvojchyby")

        if surface == "Grass":
            df_table = pd.DataFrame(
                {
                    "Parameter": [
                        "%DF - Hybrid",
                        "%DF - Grass",
                        "Pred DF - Hybrid",
                        "Pred DF - Grass",
                    ],
                    player1: [
                        fmt(p1["AvgDF"]),
                        fmt(p1["GrassAvgDF"]) if p1.get("GrassMatches", 0) >= 5 else "",
                        fmt(p1_pred_df),
                        fmt(p1_grass_pred_df),
                    ],
                    player2: [
                        fmt(p2["AvgDF"]),
                        fmt(p2["GrassAvgDF"]) if p2.get("GrassMatches", 0) >= 5 else "",
                        fmt(p2_pred_df),
                        fmt(p2_grass_pred_df),
                    ],
                }
            )
        else:
            df_table = pd.DataFrame(
                {
                    "Parameter": ["%DF", "Pred DF"],
                    player1: [fmt(p1["AvgDF"]), fmt(p1_pred_df)],
                    player2: [fmt(p2["AvgDF"]), fmt(p2_pred_df)],
                }
            )

        show_table(df_table)

    else:
        st.info("Vyber hráčov a klikni na Vypočítať.")

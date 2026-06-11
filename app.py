import json
import math
from pathlib import Path

import pandas as pd
import streamlit as st

ATP_FILE = "data/atp_matches_database.csv"
WTA_FILE = "data/wta_matches_database.csv"
EXCLUDED_TOURNAMENTS = "Davis Cup|Laver Cup"

SETTINGS_FILE = "last_search.json"
TOLERANCES = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]

st.set_page_config(page_title="Tennis Prediction", layout="wide")
st.title("🎾 Tennis Prediction")


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
        "year_from": 2024,
        "year_to": 2026,
        "level": "ATP",
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


def get_profile(profiles, player):
    row = profiles[profiles["Player"] == player]
    if row.empty:
        return None
    return row.iloc[0]
    
def build_profiles(df_all, tour, level, surface, year_from, year_to, include_qual,):
    df_base = df_all.copy()
    df_base = df_base[(df_base["Year"] >= year_from) & (df_base["Year"] <= year_to)]
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

            if G <= 3:
                if H > 0:
                    return h_val
                return g_val

            if H == 0:
                return g_val

            return (G / (G + H)) * g_val + (H / (G + H)) * h_val

        rows.append({
            "Player": player,
            "AvgA": hybrid("A%"),
            "AvgvA": hybrid("vA%"),
            "AvgPtsSG": hybrid("Pts/SG"),
            "AvgDF": hybrid("DF%"),
            "Matches": G,
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

    if surface != "Grass":
        return sample["A%"].mean(), len(sample)

    grass = sample[sample["Surface"] == "Grass"]
    hard = sample[sample["Surface"] == "Hard"]

    G = len(grass)
    H = len(hard)

    grass_avg = grass["A%"].mean()
    hard_avg = hard["A%"].mean()

    if G <= 3:
        if H > 0:
            return hard_avg, H
        return grass_avg, G

    if H == 0:
        return grass_avg, G

    hybrid = (
        (G / (G + H)) * grass_avg
        + (H / (G + H)) * hard_avg
    )

    return hybrid, G + H


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

    if surface != "Grass":
        return sample["vA%"].mean(), len(sample)

    grass = sample[sample["Surface"] == "Grass"]
    hard = sample[sample["Surface"] == "Hard"]

    G = len(grass)
    H = len(hard)

    grass_avg = grass["vA%"].mean()
    hard_avg = hard["vA%"].mean()

    if G <= 3:
        if H > 0:
            return hard_avg, H
        return grass_avg, G

    if H == 0:
        return grass_avg, G

    hybrid = (
        (G / (G + H)) * grass_avg
        + (H / (G + H)) * hard_avg
    )

    return hybrid, G + H


def pred_aces(og, ptsg, pct):
    if pct is None or pd.isna(pct):
        return None
    return og * ptsg * pct / 200


def ace_models(og, player_a, player_ptsg, opponent_va, top100_avg_va):
    base = og / 2 * player_ptsg * player_a / 100

    if top100_avg_va is None or pd.isna(top100_avg_va) or top100_avg_va == 0:
        return base, None, None

    ratio = opponent_va / top100_avg_va

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
    players = sorted(df_all["Player"].dropna().unique())

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
        value=False)

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
                "year_from": int(year_from),
                "year_to": int(year_to),
                "level": level,
                "og": float(og),
            }
        )

        profiles, df = build_profiles(
            df_all,
            tour,
            level,
            surface,
            year_from,
            year_to,
            include_qual,
        )

        p1 = get_profile(profiles, player1)
        p2 = get_profile(profiles, player2)

        if p1 is None or p2 is None:
            st.error("Niektorý hráč/hráčka nemá dáta pre zvolené filtre.")
            st.stop()

        if surface == "Grass":
            top100_players = df[df["IsTop100"] == True]["Player"].unique()
            top100_profiles = profiles[profiles["Player"].isin(top100_players)]

            top100_avg_a = top100_profiles["AvgA"].mean()
            top100_avg_va = top100_profiles["AvgvA"].mean()
        else:
            top100_mask = df["IsTop100"] == True
            top100_avg_a = df[top100_mask]["A%"].mean()
            top100_avg_va = df[top100_mask]["vA%"].mean()

        p1_base, p1_full, p1_sqrt = ace_models(
            og,
            p1["AvgA"],
            p1["AvgPtsSG"],
            p2["AvgvA"],
            top100_avg_va,
        )

        p2_base, p2_full, p2_sqrt = ace_models(
            og,
            p2["AvgA"],
            p2["AvgPtsSG"],
            p1["AvgvA"],
            top100_avg_va,
        )

        p1_pred_df = pred_df(og, p1["AvgPtsSG"], p1["AvgDF"])
        p2_pred_df = pred_df(og, p2["AvgPtsSG"], p2["AvgDF"])

        st.markdown(
            f"""
            <h3 style="text-align:center;">
                {player1} vs {player2} | {surface} | {year_from}-{year_to} | {level}
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
                "Grass zápasy",
                "Hard zápasy",
            ])  

            p1_values.extend([
                str(int(p1.get("GrassMatches", 0))),
                str(int(p1.get("HardMatches", 0))),
            ])

            p2_values.extend([
                str(int(p2.get("GrassMatches", 0))),
                str(int(p2.get("HardMatches", 0))),
            ])
        else:
            base_parameters.append("Zápasy")

            p1_values.append(str(int(p1["Matches"])))
            p2_values.append(str(int(p2["Matches"])))    

        base_parameters.extend([
            "Top100 avg A%",
            "Top100 avg vA%",
        ])

        p1_values.extend([
            fmt(top100_avg_a),
            fmt(top100_avg_va),
        ])

        p2_values.extend([
            fmt(top100_avg_a),
            fmt(top100_avg_va),
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

        aces_model = pd.DataFrame(
            {
                "Model": ["Bez korekcie", "Plná korekcia", "Odmocnina"],
                player1: [fmt(p1_base), fmt(p1_full), fmt(p1_sqrt)],
                player2: [fmt(p2_base), fmt(p2_full), fmt(p2_sqrt)],
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
import json
import math
from pathlib import Path

import pandas as pd
import streamlit as st

ATP_FILE = "data/Prediction.xlsx"
WTA_FILE = "data/Prediction_WTA.xlsx"

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
        return df[df["Level"].isin(["A", "M", "G"])]

    if tour == "WTA" and level == "WTA":
        return df[df["Level"].isin(["G", "PM", "P", "W"])]

    return df[df["Level"] == level]


@st.cache_data
def load_database(tour):
    file = ATP_FILE if tour == "ATP" else WTA_FILE
    sheet = "atp_matches_database" if tour == "ATP" else "wta_matches_database"

    df = pd.read_excel(file, sheet_name=sheet)

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Year"] = df["Date"].dt.year

    for col in ["A%", "vA%", "Pts/SG", "DF%"]:
        if col in df.columns:
            df[col] = df[col].apply(to_number)

    return df


def get_profile(profiles, player):
    row = profiles[profiles["Player"] == player]
    if row.empty:
        return None
    return row.iloc[0]


def calc_service(df, profiles, player, opponent, tolerance):
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

    return sample["A%"].mean(), len(sample)


def calc_return(df, profiles, player, opponent, tolerance):
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

    return sample["vA%"].mean(), len(sample)


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

    og = st.number_input(
        "Odhad gemov",
        value=float(settings.get("og", 22.0)),
        step=0.5,
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

        df = df_all.copy()

        df = df[(df["Year"] >= year_from) & (df["Year"] <= year_to)]

        if surface != "All":
            df = df[df["Surface"] == surface]

        df = level_filter(df, tour, level)

        profiles = (
            df.groupby("Player")
            .agg(
                AvgA=("A%", "mean"),
                AvgvA=("vA%", "mean"),
                AvgPtsSG=("Pts/SG", "mean"),
                AvgDF=("DF%", "mean"),
                Matches=("Player", "count"),
            )
            .reset_index()
        )

        p1 = get_profile(profiles, player1)
        p2 = get_profile(profiles, player2)

        if p1 is None or p2 is None:
            st.error("Niektorý hráč/hráčka nemá dáta pre zvolené filtre.")
            st.stop()

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

        base = pd.DataFrame(
            {
                "Parameter": [
                    "A%",
                    "vA%",
                    "Pts/G",
                    "DF%",
                    "Zápasy",
                    "Top100 avg A%",
                    "Top100 avg vA%",
                ],
                player1: [
                    fmt(p1["AvgA"]),
                    fmt(p1["AvgvA"]),
                    fmt(p1["AvgPtsSG"]),
                    fmt(p1["AvgDF"]),
                    str(int(p1["Matches"])),
                    fmt(top100_avg_a),
                    fmt(top100_avg_va),
                ],
                player2: [
                    fmt(p2["AvgA"]),
                    fmt(p2["AvgvA"]),
                    fmt(p2["AvgPtsSG"]),
                    fmt(p2["AvgDF"]),
                    str(int(p2["Matches"])),
                    fmt(top100_avg_a),
                    fmt(top100_avg_va),
                ],
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
            p1_pct, p1_matches = calc_service(df, profiles, player1, player2, tol)
            p2_pct, p2_matches = calc_service(df, profiles, player2, player1, tol)

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
            p1_pct, p1_matches = calc_return(df, profiles, player2, player1, tol)
            p2_pct, p2_matches = calc_return(df, profiles, player1, player2, tol)

            return_rows.append(
                {
                    "Tol": tol,
                    f"{p1_short} záp.": p1_matches,
                    f"{p1_short} esá": fmt(pred_aces(og, p1["AvgPtsSG"], p1_pct)),
                    f"{p2_short} záp.": p2_matches,
                    f"{p2_short} esá": fmt(pred_aces(og, p2["AvgPtsSG"], p2_pct)),
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
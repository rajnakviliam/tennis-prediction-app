import pandas as pd
from pathlib import Path

END_DATE = pd.Timestamp.today().normalize()

TOURS = {
    "ATP": {
        "database": "data/atp_matches_database.csv",
        "players": "atp_players.csv",
        "tour_levels": ["A", "M", "G", "D"],
        "tour_name": "ATP",
    },
    "WTA": {
        "database": "data/wta_matches_database.csv",
        "players": "wta_players.csv",
        "tour_levels": ["G", "PM", "P", "W", "F"],
        "tour_name": "WTA",
    },
}

WEEKS = [26, 52, 104]
SURFACES = ["All", "Hard", "Clay", "Grass"]

EXCLUDED_ROUNDS = ["Q1", "Q2", "Q3", "Q4"]
EXCLUDED_TOURNAMENTS = "Davis Cup|Laver Cup"

rows = []

for tour, cfg in TOURS.items():

    print(f"\n=== {tour} ===")

    d = pd.read_csv(
        cfg["database"],
        sep=";",
        decimal=",",
        encoding="utf-8-sig",
        low_memory=False,
    )

    players = pd.read_csv(
        cfg["players"],
        encoding="utf-8-sig",
    )

    player_names = set(
        players["name"]
        .astype(str)
        .str.strip()
        .str.replace("\xa0", " ", regex=False)
    )

    d["Player"] = (
        d["Player"]
        .astype(str)
        .str.strip()
        .str.replace("\xa0", " ", regex=False)
    )

    d["Date"] = pd.to_datetime(d["Date"], errors="coerce")

    numeric_cols = [
        "Aces",
        "DoubleFaults",
        "ServePoints",
        "ServiceGames",
        "OppAces",
        "OppServePoints",
    ]

    for col in numeric_cols:
        d[col] = pd.to_numeric(d[col], errors="coerce")

    # Rovnaké ako include_qual=False v app.py
    d = d[
        ~d["Round"].isin(EXCLUDED_ROUNDS)
        & ~d["Tournament"]
            .astype(str)
            .str.contains(
                EXCLUDED_TOURNAMENTS,
                case=False,
                na=False,
            )
    ].copy()

    # Stačia nám hráči z aktuálneho player listu
    d = d[d["Player"].isin(player_names)].copy()

    for weeks in WEEKS:

        # Presne rovnaká logika ako resolve_period() v app.py
        start_date = END_DATE - pd.Timedelta(weeks=weeks)

        period = d[
            (d["Date"] >= start_date)
            & (d["Date"] <= END_DATE)
        ].copy()

        for surface in SURFACES:

            if surface == "All":
                surface_df = period.copy()
            else:
                surface_df = period[
                    period["Surface"] == surface
                ].copy()

            for level_group in ["Tour", "All"]:

                if level_group == "Tour":
                    base = surface_df[
                        surface_df["Level"].isin(
                            cfg["tour_levels"]
                        )
                    ].copy()
                else:
                    base = surface_df.copy()

                for player, p_df in base.groupby("Player"):

                    raw = p_df.dropna(
                        subset=numeric_cols
                    )

                    if raw.empty:
                        continue

                    serve_points = raw["ServePoints"].sum()
                    service_games = raw["ServiceGames"].sum()
                    opp_serve_points = raw["OppServePoints"].sum()

                    if (
                        serve_points <= 0
                        or service_games <= 0
                        or opp_serve_points <= 0
                    ):
                        continue

                    a_pct = (
                        raw["Aces"].sum()
                        / serve_points
                        * 100
                    )

                    va_pct = (
                        raw["OppAces"].sum()
                        / opp_serve_points
                        * 100
                    )

                    df_pct = (
                        raw["DoubleFaults"].sum()
                        / serve_points
                        * 100
                    )

                    pts_g = (
                        serve_points
                        / service_games
                    )

                    rows.append({
                        "Tour": tour,
                        "Player": player,
                        "Weeks": weeks,
                        "Surface": surface,
                        "Filter": (
                            cfg["tour_name"]
                            if level_group == "Tour"
                            else "ALL"
                        ),
                        # app.py používa len(p_df),
                        # nie len(raw)
                        "Matches": len(p_df),
                        "A%": round(a_pct, 4),
                        "vA%": round(va_pct, 4),
                        "DF%": round(df_pct, 4),
                        "Pts/G": round(pts_g, 4),
                        "StartDate": start_date.date(),
                        "EndDate": END_DATE.date(),
                    })


out = pd.DataFrame(rows)

Path("data").mkdir(exist_ok=True)

output_file = "data/player_prediction_stats.csv"

out.to_csv(
    output_file,
    index=False,
    sep=";",
    decimal=",",
    encoding="utf-8-sig",
)

print("\n================================")
print("HOTOVO")
print("================================")
print("Riadkov:", len(out))
print("Súbor:", output_file)
print("End date:", END_DATE.date())

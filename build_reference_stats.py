import pandas as pd
from pathlib import Path

END_DATE = pd.Timestamp.today().normalize()
REFERENCE_RANK_LIMIT = 200

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

    rankings = pd.read_csv(
        cfg["players"],
        encoding="utf-8-sig",
    )

    rankings["rank"] = pd.to_numeric(
        rankings["rank"],
        errors="coerce",
    )

    rankings["name"] = (
        rankings["name"]
        .astype(str)
        .str.replace("\xa0", " ", regex=False)
        .str.strip()
    )

    reference_names = set(
        rankings[
            rankings["rank"] <= REFERENCE_RANK_LIMIT
        ]["name"]
    )

    d["Player"] = (
        d["Player"]
        .astype(str)
        .str.replace("\xa0", " ", regex=False)
        .str.strip()
    )

    d["Opponent"] = (
        d["Opponent"]
        .astype(str)
        .str.replace("\xa0", " ", regex=False)
        .str.strip()
    )

    d["Date"] = pd.to_datetime(
        d["Date"],
        errors="coerce",
    )

    numeric_cols = [
        "Aces",
        "ServePoints",
        "OppAces",
        "OppServePoints",
    ]

    for col in numeric_cols:
        d[col] = pd.to_numeric(
            d[col],
            errors="coerce",
        )

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

    for weeks in WEEKS:

        start_date = (
            END_DATE
            - pd.Timedelta(weeks=weeks)
        )

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

                    filter_name = cfg["tour_name"]

                else:
                    base = surface_df.copy()
                    filter_name = "ALL"

                # Presne calculate_reference_averages()
                reference_df = base[
                    base["Player"].isin(reference_names)
                    & base["Opponent"].isin(reference_names)
                ].copy()

                raw = reference_df.dropna(
                    subset=[
                        "Aces",
                        "ServePoints",
                        "OppAces",
                        "OppServePoints",
                    ]
                )

                if raw.empty:
                    continue

                serve_points = raw["ServePoints"].sum()
                opp_serve_points = raw["OppServePoints"].sum()

                if serve_points <= 0 or opp_serve_points <= 0:
                    continue

                avg_a = (
                    raw["Aces"].sum()
                    / serve_points
                    * 100
                )

                avg_va = (
                    raw["OppAces"].sum()
                    / opp_serve_points
                    * 100
                )

                rows.append({
                    "Tour": tour,
                    "Weeks": weeks,
                    "Surface": surface,
                    "Filter": filter_name,
                    "ReferenceMatches": len(raw),
                    "ReferenceA%": round(avg_a, 4),
                    "ReferencevA%": round(avg_va, 4),
                    "StartDate": start_date.date(),
                    "EndDate": END_DATE.date(),
                })


out = pd.DataFrame(rows)

Path("data").mkdir(exist_ok=True)

output_file = "data/prediction_reference_stats.csv"

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

import time
from pathlib import Path

import pandas as pd
import update_wta


FAILED_FILE = "wta_failed_players.csv"
CSV_OUTPUT_FILE = "data/wta_matches_database.csv"
OUTPUT_FILE = "wta_matches_database.xlsx"

KEY = [
    "Player",
    "Opponent",
    "Date",
    "Round",
    "Score",
    "Result",
]

NUMERIC_COLS = [
    "Aces",
    "DoubleFaults",
    "ServePoints",
    "ServiceGames",
    "OppAces",
    "OppServePoints",
    "A%",
    "DF%",
    "vA%",
    "Pts/SG",
]


def main():
    if not Path(FAILED_FILE).exists():
        print("wta_failed_players.csv neexistuje.")
        return

    if not Path(CSV_OUTPUT_FILE).exists():
        print("Databáza neexistuje:", CSV_OUTPUT_FILE)
        return

    failed = pd.read_csv(FAILED_FILE)

    old_df = pd.read_csv(
        CSV_OUTPUT_FILE,
        sep=";",
        decimal=",",
        encoding="utf-8-sig",
        low_memory=False,
    )

    old_df["Date"] = pd.to_datetime(
        old_df["Date"],
        errors="coerce",
    )

    all_rows = []
    still_failed = []

    for _, p in failed.iterrows():
        player_code = str(p["code"]).strip()
        player_name = (
            str(p["name"])
            .strip()
            .replace("\xa0", " ")
        )

        js_text = update_wta.download_player_page(
            player_code,
            player_name,
            retries=5,
            wait_seconds=6,
        )

        if js_text is None:
            still_failed.append({
                "code": player_code,
                "name": player_name,
            })
            continue

        rows = update_wta.parse_player_matches(
            player_name,
            js_text,
        )

        print("  Zápasy so štatistikami:", len(rows))

        if not rows:
            still_failed.append({
                "code": player_code,
                "name": player_name,
            })
            continue

        all_rows.extend(rows)
        time.sleep(4)

    if all_rows:
        new_df = pd.DataFrame(all_rows)

        new_df["Date"] = pd.to_datetime(
            new_df["Date"],
            format="%Y%m%d",
            errors="coerce",
        )

        for col in NUMERIC_COLS:
            if col in new_df.columns:
                new_df[col] = pd.to_numeric(
                    new_df[col],
                    errors="coerce",
                )

        combined = pd.concat(
            [old_df, new_df],
            ignore_index=True,
        )

        combined["Player"] = (
            combined["Player"]
            .astype(str)
            .str.replace("\xa0", " ", regex=False)
        )

        combined["Opponent"] = (
            combined["Opponent"]
            .astype(str)
            .str.replace("\xa0", " ", regex=False)
        )

        for col in NUMERIC_COLS:
            if col in combined.columns:
                combined[col] = pd.to_numeric(
                    combined[col],
                    errors="coerce",
                )

        combined = combined.drop_duplicates(
            subset=KEY,
            keep="last",
        )

        combined = combined.sort_values(
            ["Player", "Date"],
            ascending=[True, False],
        )

        combined["Year"] = pd.to_datetime(
            combined["Date"],
            errors="coerce",
        ).dt.year

        top100 = pd.read_csv("wta_top100.csv")
        top100_names = set(
            top100["name"].astype(str).str.strip()
        )

        combined["IsTop100"] = (
            combined["Player"]
            .astype(str)
            .str.strip()
            .isin(top100_names)
        )

        combined.to_excel(
            OUTPUT_FILE,
            index=False,
        )

        combined.to_csv(
            CSV_OUTPUT_FILE,
            index=False,
            encoding="utf-8-sig",
            sep=";",
            decimal=",",
        )

        print("Databáza doplnená.")
        print("Počet riadkov:", len(combined))

    else:
        print("Nepodarilo sa doplniť žiadne nové dáta.")

    if still_failed:
        pd.DataFrame(still_failed).to_csv(
            FAILED_FILE,
            index=False,
            encoding="utf-8-sig",
        )

        print("Stále zlyhali hráčky:", len(still_failed))
        print("Zostávajú v:", FAILED_FILE)

    else:
        if Path(FAILED_FILE).exists():
            Path(FAILED_FILE).unlink()

        print(
            "Všetky zlyhané hráčky boli úspešne doplnené."
        )


if __name__ == "__main__":
    main()

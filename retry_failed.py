import re
import ast
import time
from pathlib import Path

import requests
import pandas as pd


FAILED_FILE = "failed_players.csv"
OUTPUT_FILE = "atp_matches_database.xlsx"
CSV_OUTPUT_FILE = "data/atp_matches_database.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def download_player_page(player_code, player_name, retries=5, wait_seconds=6):
    url = f"https://www.tennisabstract.com/cgi-bin/player-classic.cgi?p={player_code}&f=B1"

    for attempt in range(1, retries + 1):
        print(f"Sťahujem {player_name} - pokus {attempt}/{retries}")

        try:
            response = requests.get(url, headers=HEADERS, timeout=40)
            print("  Status:", response.status_code)

            if response.status_code == 200 and "var matchmx" in response.text:
                return response.text

        except Exception as e:
            print("  Chyba:", e)

        time.sleep(wait_seconds)

    return None


def parse_player_matches(player_name, html):
    match = re.search(r"var matchmx = (\[.*?\]);", html, re.S)

    if not match:
        return []

    matches = ast.literal_eval(match.group(1))
    rows = []

    for row in matches:
        try:
            if (
                row[21] == ""
                or row[23] == ""
                or row[27] == ""
                or row[30] == ""
                or row[32] == ""
            ):
                continue

            aces = int(row[21])
            double_faults = int(row[22])
            serve_points = int(row[23])
            service_games = int(row[27])

            opp_aces = int(row[30])
            opp_serve_points = int(row[32])

            if serve_points == 0 or opp_serve_points == 0 or service_games == 0:
                continue

            rows.append({
                "Player": player_name.replace("\xa0", " "),
                "Date": row[0],
                "Tournament": row[1],
                "Surface": row[2],
                "Level": row[3],
                "Result": row[4],
                "Round": row[8],
                "Score": row[9],
                "Opponent": row[11].replace("\xa0", " "),
                "A%": round(aces / serve_points * 100, 2),
                "DF%": round(double_faults / serve_points * 100, 2),
                "vA%": round(opp_aces / opp_serve_points * 100, 2),
                "Pts/SG": round(serve_points / service_games, 2),
                "MatchID": row[43],
            })

        except Exception:
            continue

    return rows


def main():
    if not Path(FAILED_FILE).exists():
        print("failed_players.csv neexistuje.")
        return

    if not Path(OUTPUT_FILE).exists():
        print("Databáza neexistuje:", OUTPUT_FILE)
        return

    failed = pd.read_csv(FAILED_FILE)

    old_df = pd.read_excel(OUTPUT_FILE)

    all_rows = []
    still_failed = []

    for _, p in failed.iterrows():
        player_code = str(p["code"]).strip()
        player_name = str(p["name"]).strip().replace("\xa0", " ")

        html = download_player_page(player_code, player_name)

        if html is None:
            still_failed.append({
                "code": player_code,
                "name": player_name
            })
            continue

        rows = parse_player_matches(player_name, html)
        print("  Zápasy so štatistikami:", len(rows))
        all_rows.extend(rows)

        time.sleep(4)

    if all_rows:
        new_df = pd.DataFrame(all_rows)

        new_df["Date"] = pd.to_datetime(new_df["Date"], format="%Y%m%d", errors="coerce")

        for col in ["A%", "DF%", "vA%", "Pts/SG"]:
            new_df[col] = pd.to_numeric(new_df[col], errors="coerce")

        combined = pd.concat([old_df, new_df], ignore_index=True)

        combined["Player"] = combined["Player"].astype(str).str.replace("\xa0", " ", regex=False)
        combined["Opponent"] = combined["Opponent"].astype(str).str.replace("\xa0", " ", regex=False)

        for col in ["A%", "DF%", "vA%", "Pts/SG"]:
            combined[col] = pd.to_numeric(combined[col], errors="coerce")

        combined = combined.drop_duplicates(subset=["Player", "MatchID"], keep="last")
        combined = combined.sort_values(["Player", "Date"], ascending=[True, False])

        Path("data").mkdir(exist_ok=True)

        combined.to_excel(OUTPUT_FILE, index=False)

        combined.to_csv(
            CSV_OUTPUT_FILE,
            index=False,
            encoding="utf-8-sig",
            sep=";",
            decimal=","
        )

        print("Databáza doplnená.")
        print("Počet riadkov:", len(combined))
    else:
        print("Nepodarilo sa doplniť žiadne nové dáta.")

    if still_failed:
        pd.DataFrame(still_failed).to_csv(
            FAILED_FILE,
            index=False,
            encoding="utf-8-sig"
        )
        print("Stále zlyhali hráči:", len(still_failed))
        print("Zostávajú v:", FAILED_FILE)
    else:
        Path(FAILED_FILE).unlink()
        print("Všetci zlyhaní hráči boli úspešne doplnení.")


if __name__ == "__main__":
    main()
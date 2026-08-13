import re
import ast
import time
from pathlib import Path

import requests
import pandas as pd


PLAYERS_FILE = "atp_players.csv"
OUTPUT_FILE = "atp_matches_database.xlsx"
CSV_OUTPUT_FILE = "data/atp_matches_database.csv"
FAILED_FILE = "failed_players.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def download_player_page(player_code, player_name, retries=3, wait_seconds=4):
    url = f"https://www.tennisabstract.com/cgi-bin/player-classic.cgi?p={player_code}&f=B1"

    for attempt in range(1, retries + 1):
        print(f"  Pokus {attempt}/{retries}")

        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            print("  Status:", response.status_code)

            if response.status_code == 200 and "var matchmx" in response.text:
                return response.text

        except Exception as e:
            print("  Chyba pri sťahovaní:", e)

        time.sleep(wait_seconds)

    print("  Dáta nenájdené:", player_name)
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

            pts_sg = round(serve_points / service_games, 2)

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

                "Aces": aces,
                "DoubleFaults": double_faults,
                "ServePoints": serve_points,
                "ServiceGames": service_games,
                "OppAces": opp_aces,
                "OppServePoints": opp_serve_points,

                "A%": round(aces / serve_points * 100, 2),
                "DF%": round(double_faults / serve_points * 100, 2),
                "vA%": round(opp_aces / opp_serve_points * 100, 2),
                "Pts/SG": pts_sg,
                "MatchID": row[43],
            })

        except Exception:
            continue

    return rows


def main():
    players = pd.read_csv(PLAYERS_FILE)

    all_rows = []
    failed_players = []

    for _, p in players.iterrows():
        player_code = str(p["code"]).strip()
        player_name = str(p["name"]).strip().replace("\xa0", " ")

        print("Sťahujem:", player_name)

        html = download_player_page(player_code, player_name)

        if html is None:
            failed_players.append({
                "code": player_code,
                "name": player_name
            })
            time.sleep(2)
            continue

        player_rows = parse_player_matches(player_name, html)
        print("  Zápasy so štatistikami:", len(player_rows))

        all_rows.extend(player_rows)

        time.sleep(3)

    new_df = pd.DataFrame(all_rows)

    if new_df.empty:
        print("Nenašli sa žiadne nové dáta.")
        return

    new_df["Date"] = pd.to_datetime(
        new_df["Date"],
        format="%Y%m%d",
        errors="coerce"
    )

    numeric_cols = [
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

    for col in numeric_cols:
        if col in new_df.columns:
            new_df[col] = pd.to_numeric(
                new_df[col],
                errors="coerce"
            )

    if Path(OUTPUT_FILE).exists():
        old_df = pd.read_excel(OUTPUT_FILE)
        combined = pd.concat([old_df, new_df], ignore_index=True)
    else:
        combined = new_df

    combined["Player"] = combined["Player"].astype(str).str.replace("\xa0", " ", regex=False)
    combined["Opponent"] = combined["Opponent"].astype(str).str.replace("\xa0", " ", regex=False)

    for col in numeric_cols:
        if col in combined.columns:
            combined[col] = pd.to_numeric(
                combined[col],
                errors="coerce"
            )

    combined = combined.drop_duplicates(
        subset=[
            "Player",
            "Opponent",
            "Date",
            "Round",
            "Score",
            "Result",
        ],
        keep="last"
    )
    combined = combined.sort_values(["Player", "Date"], ascending=[True, False])
    
    combined["Year"] = pd.to_datetime(combined["Date"], errors="coerce").dt.year

    top100 = pd.read_csv("atp_top100.csv")
    top100_names = set(top100["name"].astype(str).str.strip())

    combined["IsTop100"] = combined["Player"].astype(str).str.strip().isin(top100_names)
    
    Path("data").mkdir(exist_ok=True)

    combined.to_excel(OUTPUT_FILE, index=False)

    combined.to_csv(
        CSV_OUTPUT_FILE,
        index=False,
        encoding="utf-8-sig",
        sep=";",
        decimal=","
    )

    if failed_players:
        pd.DataFrame(failed_players).to_csv(FAILED_FILE, index=False, encoding="utf-8-sig")
        print("Nepodarilo sa stiahnuť niektorých hráčov. Zoznam je v:", FAILED_FILE)
    else:
        if Path(FAILED_FILE).exists():
            Path(FAILED_FILE).unlink()

    print("Hotovo.")
    print("Počet riadkov v databáze:", len(combined))
    print("Súbor:", OUTPUT_FILE)
    print("CSV súbor:", CSV_OUTPUT_FILE)


if __name__ == "__main__":
    main()

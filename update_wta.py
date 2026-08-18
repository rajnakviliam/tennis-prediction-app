import re
import ast
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
import pandas as pd


PLAYERS_FILE = "wta_players.csv"
OUTPUT_FILE = "wta_matches_database.xlsx"
CSV_OUTPUT_FILE = "data/wta_matches_database.csv"
FAILED_FILE = "wta_failed_players.csv"

BASE_URL = "https://www.tennisabstract.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def download_player_page(player_code, player_name, retries=3, wait_seconds=4):
    page_url = f"{BASE_URL}/cgi-bin/wplayer-classic.cgi?p={player_code}&f=ACareerqq"

    for attempt in range(1, retries + 1):
        print(f"  Pokus {attempt}/{retries}")

        try:
            response = requests.get(page_url, headers=HEADERS, timeout=30)
            print("  Status HTML:", response.status_code)

            if response.status_code != 200:
                time.sleep(wait_seconds)
                continue

            html = response.text

            js_matches = re.findall(
                r'<script[^>]+src="([^"]*jsmatches/[^"]+\.js)"',
                html
            )

            if not js_matches:
                print("  Nenašiel som jsmatches súbor.")
                with open("debug_wta.html", "w", encoding="utf-8") as f:
                    f.write(html)
                time.sleep(wait_seconds)
                continue

            all_js_text = ""

            for js_path in js_matches:
                js_url = urljoin(BASE_URL, js_path)
                print("  JS:", js_url)

                js_response = requests.get(js_url, headers=HEADERS, timeout=30)
                print("  Status JS:", js_response.status_code)
                print("  Dĺžka JS:", len(js_response.text))
                print("  Obsahuje matchmx:", "matchmx" in js_response.text)

                if js_response.status_code == 200:
                    all_js_text += "\n" + js_response.text

            if "matchmx" in all_js_text:
                return all_js_text

        except Exception as e:
            print("  Chyba pri sťahovaní:", e)

        time.sleep(wait_seconds)

    print("  Dáta nenájdené:", player_name)
    return None


def parse_player_matches(player_name, js_text):
    matches = []

    for m in re.finditer(
        r"var\s+(?:matchmx|morematchmx)\s*=\s*(\[.*?\]);",
        js_text,
        re.S
    ):
        matches.extend(ast.literal_eval(m.group(1)))

    print("  Celkový počet zápasov:", len(matches))

    if not matches:
        return []

    rows = []

    for row in matches:
        try:
            if (
                row[21] == ""
                or row[22] == ""
                or row[23] == ""
                or row[27] == ""
            ):
                continue

            aces = int(row[21])
            double_faults = int(row[22])
            serve_points = int(row[23])
            service_games = int(row[27])

            opp_aces = int(row[30]) if row[30] != "" else 0
            opp_serve_points = int(row[32]) if row[32] != "" else 0

            if serve_points == 0 or service_games == 0:
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

                "Aces": aces,
                "DoubleFaults": double_faults,
                "ServePoints": serve_points,
                "ServiceGames": service_games,
                "OppAces": opp_aces,
                "OppServePoints": opp_serve_points,

                "A%": round(aces / serve_points * 100, 2),
                "DF%": round(double_faults / serve_points * 100, 2),
                "vA%": round(opp_aces / opp_serve_points * 100, 2)
                    if opp_serve_points != 0 else None,
                "Pts/SG": round(serve_points / service_games, 2),
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

        js_text = download_player_page(player_code, player_name)

        if js_text is None:
            failed_players.append({
                "code": player_code,
                "name": player_name
            })
            time.sleep(2)
            continue

        player_rows = parse_player_matches(player_name, js_text)
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

    if Path(CSV_OUTPUT_FILE).exists():
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

        combined = pd.concat(
            [old_df, new_df],
            ignore_index=True,
        )
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

    top100 = pd.read_csv("wta_top100.csv")
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
        print("Nepodarilo sa stiahnuť niektoré hráčky. Zoznam je v:", FAILED_FILE)
    else:
        if Path(FAILED_FILE).exists():
            Path(FAILED_FILE).unlink()

    print("Hotovo.")
    print("Počet riadkov v databáze:", len(combined))
    print("Súbor:", OUTPUT_FILE)
    print("CSV súbor:", CSV_OUTPUT_FILE)


if __name__ == "__main__":
    main()

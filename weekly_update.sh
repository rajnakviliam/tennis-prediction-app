#!/bin/bash
set -e

cd /home/vilo/tennis-prediction-app
source venv/bin/activate

echo "=== Aktualizujem ATP/WTA rankingy ==="
python update_rankings.py

echo "=== Aktualizujem ATP databázu ==="
python update.py
python retry_failed.py

echo "=== Aktualizujem WTA databázu ==="
python update_wta.py
python retry_failed_wta.py

echo "=== Kontrola raw pokrytia ==="

python - <<'PY'
import pandas as pd

TOURS = {
    "ATP": ("data/atp_matches_database.csv", "atp_players.csv"),
    "WTA": ("data/wta_matches_database.csv", "wta_players.csv"),
}

for tour, (db_file, players_file) in TOURS.items():
    d = pd.read_csv(
        db_file,
        sep=";",
        decimal=",",
        encoding="utf-8-sig",
        low_memory=False,
    )

    r = pd.read_csv(players_file, encoding="utf-8-sig")
    names = set(r["name"].astype(str).str.strip())

    x = (
        d[d["Player"].astype(str).str.strip().isin(names)]
        .groupby("Player")
        .agg(
            All=("Player", "size"),
            Raw=("ServePoints", "count"),
        )
    )

    x["Missing"] = x["All"] - x["Raw"]
    x["RawPct"] = x["Raw"] / x["All"] * 100

    bad = x[
        (x["RawPct"] < 95) |
        (x["Missing"] > 10)
    ].sort_values(["RawPct", "Missing"])

    print(f"\n{tour} raw audit:")

    if bad.empty:
        print("OK - žiadny problémový hráč.")
    else:
        print("WARNING - problémoví hráči:")
        print(bad.to_string())
PY

date +"%d.%m.%Y %H:%M" > last_update.txt

git add \
  data/atp_matches_database.csv \
  data/wta_matches_database.csv \
  atp_players.csv \
  atp_top100.csv \
  wta_players.csv \
  wta_top100.csv \
  last_update.txt

if ! git diff --cached --quiet; then
  git commit -m "Weekly ATP and WTA database update"

  echo "Synchronizing with GitHub..."
  git pull --rebase origin main

  echo "Pushing changes..."
  git push
else
  echo "No changes."
fi

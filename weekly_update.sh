#!/bin/bash
cd /home/vilo/tennis-prediction-app
source venv/bin/activate

python update.py
python retry_failed.py
python update_wta.py
python retry_failed_wta.py

date +"%d.%m.%Y %H:%M" > last_update.txt

git add data/atp_matches_database.csv data/wta_matches_database.csv last_update.txt

if ! git diff --cached --quiet; then
  git commit -m "Weekly ATP and WTA database update"

  echo "Synchronizing with GitHub..."
  git pull --rebase origin main

  echo "Pushing changes..."
  git push
else
  echo "No changes."
fi

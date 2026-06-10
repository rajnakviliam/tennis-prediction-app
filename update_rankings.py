import re
import requests
import pandas as pd

ATP_URL = "https://tennisabstract.com/reports/atpRankings.html"
WTA_URL = "https://tennisabstract.com/reports/wtaRankings.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.tennisabstract.com/",
}


def clean_name(name):
    return (
        str(name)
        .replace("&nbsp;", " ")
        .replace("\xa0", " ")
        .strip()
    )


def download_rankings(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()

    html = response.text

    pattern = re.compile(
        r'<tr><td align="right">(\d+)</td>'
        r'<td align="left"><a href="[^"]*\?p=([^"]+)">(.+?)</a></td>'
        r'<td align="left">([^<]*)</td>'
        r'<td align="left">([^<]*)</td></tr>',
        re.S
    )

    rows = []

    for match in pattern.finditer(html):
        rank = int(match.group(1))
        code = match.group(2).strip()
        name = clean_name(match.group(3))
        country = match.group(4).strip()
        birthdate = match.group(5).strip()

        rows.append({
            "rank": rank,
            "name": name,
            "code": code,
            "country": country,
            "birthdate": birthdate
        })

    df = pd.DataFrame(rows)

    if df.empty:
        raise ValueError("Nepodarilo sa načítať ranking tabuľku.")

    return df


def save_files(df, prefix):
    players = df[df["rank"] <= 200].copy()
    top100 = df[df["rank"] <= 100].copy()

    players[["code", "name"]].to_csv(
        f"{prefix}_players.csv",
        index=False,
        encoding="utf-8-sig"
    )

    top100[["name"]].to_csv(
        f"{prefix}_top100.csv",
        index=False,
        encoding="utf-8-sig"
    )

    df.to_csv(
        f"{prefix}_rankings_full.csv",
        index=False,
        encoding="utf-8-sig"
    )

    print(f"{prefix.upper()} players:", len(players))
    print(f"{prefix.upper()} top100:", len(top100))


def main():
    print("Sťahujem ATP ranking...")
    atp = download_rankings(ATP_URL)
    save_files(atp, "atp")

    print("Sťahujem WTA ranking...")
    wta = download_rankings(WTA_URL)
    save_files(wta, "wta")

    print("Hotovo.")


if __name__ == "__main__":
    main()

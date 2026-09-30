from pathlib import Path
from datetime import datetime, timezone
import json

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/world_bank"
OUT = ROOT / "data/processed"
META = ROOT / "data/metadata"
for folder in [RAW, OUT, META]:
    folder.mkdir(parents=True, exist_ok=True)

indicators = {
    "NY.GDP.MKTP.PP.KD": "gdp",
    "NY.GDP.PCAP.PP.KD": "gdp_per_capita",
    "SP.POP.TOTL": "population",
}

session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)))

rows = []
metadata = {}
snapshots = {}
current_year = datetime.now(timezone.utc).year

for code, metric in indicators.items():
    print(f"Fetching {metric}...")
    meta_response = session.get(
        f"https://api.worldbank.org/v2/indicator/{code}",
        params={"format": "json", "source": 2},
        timeout=90,
    )
    meta_response.raise_for_status()
    meta_payload = meta_response.json()
    if (
        not isinstance(meta_payload, list)
        or len(meta_payload) != 2
        or not meta_payload[1]
    ):
        raise ValueError(f"Invalid indicator metadata: {code}")
    metadata[code] = meta_payload[1]

    pages = []
    page = 1
    while True:
        response = session.get(
            f"https://api.worldbank.org/v2/country/IND;CHN;USA/indicator/{code}",
            params={
                "format": "json",
                "source": 2,
                "date": f"1960:{current_year}",
                "per_page": 1000,
                "page": page,
            },
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        if (
            not isinstance(payload, list)
            or len(payload) != 2
            or not isinstance(payload[0], dict)
            or not isinstance(payload[1], list)
        ):
            raise ValueError(f"Invalid data response: {code}")
        pages.append(payload)

        for observation in payload[1]:
            rows.append({
                "country_id": observation["countryiso3code"],
                "country": observation["country"]["value"],
                "year": int(observation["date"]),
                "metric": metric,
                "value": observation["value"],
                "indicator_code": code,
                "indicator_name": observation["indicator"]["value"],
                "source_id": "WORLD_BANK_WDI",
                "database_updated": payload[0].get("lastupdated"),
                "observation_status": observation.get("obs_status", ""),
            })

        if page >= int(payload[0]["pages"]):
            break
        page += 1

    snapshots[code] = pages

df = pd.DataFrame(rows)
df["value"] = pd.to_numeric(df["value"], errors="raise")
if df.duplicated(["country_id", "year", "metric"]).any():
    raise ValueError("Duplicate observations.")

valid = df.dropna(subset=["value"])
if not np.isfinite(valid["value"]).all() or (valid["value"] <= 0).any():
    raise ValueError("Invalid indicator values.")

for country in ["IND", "CHN", "USA"]:
    for metric in indicators.values():
        if valid[
            (valid["country_id"] == country) & (valid["metric"] == metric)
        ].empty:
            raise ValueError(f"No data for {country}/{metric}")

# Preserve missing values and source metadata.
df = df.sort_values(["country_id", "metric", "year"])
df.to_parquet(OUT / "world_bank_history.parquet", index=False)
df.to_csv(OUT / "world_bank_history.csv", index=False)

for code, payload in snapshots.items():
    (RAW / f"{code}.json").write_text(json.dumps(payload, indent=2))

(META / "world_bank_indicators.json").write_text(
    json.dumps(metadata, indent=2)
)
(META / "world_bank_manifest.json").write_text(json.dumps({
    "retrieved_utc": datetime.now(timezone.utc).isoformat(),
    "source_id": "WORLD_BANK_WDI",
    "source_url": "https://data.worldbank.org/",
    "processing": "No interpolation; null observations preserved",
    "historical_series": "Stored separately from MPD2023",
}, indent=2))

print("\nLatest available observation for each metric:")
latest = valid.sort_values("year").groupby(
    ["country_id", "metric"], as_index=False
).tail(1)
print(latest[[
    "country_id", "metric", "year", "value", "indicator_name"
]].to_string(index=False))

print("\nWorld Bank dataset saved.")

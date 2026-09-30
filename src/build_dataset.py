from pathlib import Path
import hashlib
import json

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/raw/maddison2023.xlsx"
OUTPUT = ROOT / "data/processed"
METADATA = ROOT / "data/metadata"

OUTPUT.mkdir(parents=True, exist_ok=True)
METADATA.mkdir(parents=True, exist_ok=True)

df = pd.read_excel(SOURCE, sheet_name="Full data")
required = ["countrycode", "country", "region", "year", "gdppc", "pop"]
missing = set(required) - set(df.columns)
if missing:
    raise ValueError(f"Missing columns: {sorted(missing)}")

df = df[required].copy()
df["countrycode"] = df["countrycode"].astype("string").str.strip()
selected = df[df["countrycode"].isin(["IND", "CHN", "USA"])].copy()

if set(selected["countrycode"]) != {"IND", "CHN", "USA"}:
    raise ValueError("One or more target countries are missing.")

for column in ["year", "gdppc", "pop"]:
    selected[column] = pd.to_numeric(selected[column], errors="raise")

if selected["year"].isna().any():
    raise ValueError("Missing years.")
if not np.isfinite(selected["year"]).all():
    raise ValueError("Non-finite years.")
if (selected["year"] % 1 != 0).any():
    raise ValueError("Non-integer years.")

selected["year"] = selected["year"].astype(int)

if selected.duplicated(["countrycode", "year"]).any():
    raise ValueError("Duplicate country/year observations.")

for column in ["gdppc", "pop"]:
    values = selected[column].dropna()
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError(f"Invalid values in {column}.")

# Retain source units until workbook documentation is verified.
selected = selected.rename(columns={
    "countrycode": "country_id",
    "gdppc": "gdp_per_capita_source_units",
    "pop": "population_source_units",
})
selected["source_id"] = "MPD2023"
selected = selected.sort_values(["country_id", "year"])

selected.to_parquet(OUTPUT / "country_history.parquet", index=False)
selected.to_csv(OUTPUT / "country_history.csv", index=False)

with duckdb.connect(str(OUTPUT / "economic_history.duckdb")) as connection:
    connection.register("observations", selected)
    connection.execute(
        "CREATE OR REPLACE TABLE country_history AS "
        "SELECT * FROM observations"
    )

# Keep documentation and citations with the dataset.
for sheet in ["Notes", "Sources", "Maddison original sources"]:
    document = pd.read_excel(SOURCE, sheet_name=sheet, header=None)
    filename = sheet.lower().replace(" ", "_") + ".csv"
    document.to_csv(METADATA / filename, index=False, header=False)

manifest = {
    "source_id": "MPD2023",
    "source_file": SOURCE.name,
    "sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    "countries": ["IND", "CHN", "USA"],
    "rows": len(selected),
    "units_status": "Pending documentation verification",
    "missing_values": "Preserved; no interpolation",
    "world_gdp_share": "Not calculated",
}
(METADATA / "source_manifest.json").write_text(
    json.dumps(manifest, indent=2)
)

print("\nCoverage:")
print(selected.groupby("country_id").agg(
    first_year=("year", "min"),
    last_year=("year", "max"),
    gdp_pc_observations=("gdp_per_capita_source_units", "count"),
    population_observations=("population_source_units", "count"),
).to_string())

print("\nRecent observations:")
print(selected.groupby("country_id").tail(2).to_string(index=False))

print("\nWorkbook notes:")
notes = pd.read_excel(SOURCE, sheet_name="Notes", header=None)
for row in notes.itertuples(index=False, name=None):
    text = " | ".join(str(value) for value in row if pd.notna(value))
    if text:
        print(text)

print("\nCreated CSV, Parquet, DuckDB table, and source metadata.")

from pathlib import Path
import json

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/processed"

df = pd.read_parquet(OUTPUT / "country_history.parquet")

df["gdp_per_capita"] = df["gdp_per_capita_source_units"]
df["population"] = df["population_source_units"] * 1000
df["gdp"] = df["gdp_per_capita"] * df["population"]

df["gdp_unit"] = "2011 international dollars"
df["population_unit"] = "persons"
df["gdp_method"] = "GDP per capita multiplied by population"

df.to_parquet(OUTPUT / "country_history.parquet", index=False)
df.to_csv(OUTPUT / "country_history.csv", index=False)

with duckdb.connect(str(OUTPUT / "economic_history.duckdb")) as connection:
    connection.register("observations", df)
    connection.execute(
        "CREATE OR REPLACE TABLE country_history AS "
        "SELECT * FROM observations"
    )

manifest_path = ROOT / "data/metadata/source_manifest.json"
manifest = json.loads(manifest_path.read_text())
manifest["units_status"] = "Verified against workbook Notes sheet"
manifest["units"] = {
    "gdp_per_capita": "2011 international dollars per person",
    "population": "persons; source thousands multiplied by 1000",
    "gdp": "2011 international dollars; derived",
}
manifest_path.write_text(json.dumps(manifest, indent=2))

print("\nValid observation coverage:")
for metric in ["gdp_per_capita", "population", "gdp"]:
    valid = df.dropna(subset=[metric])
    print(f"\n{metric}")
    print(valid.groupby("country_id")["year"].agg(
        ["min", "max", "count"]
    ).to_string())

latest = df[df["year"] == 2022].copy()
latest["population_millions"] = latest["population"] / 1e6
latest["gdp_trillions"] = latest["gdp"] / 1e12

print("\n2022 comparison:")
print(latest[[
    "country_id", "gdp_per_capita",
    "population_millions", "gdp_trillions"
]].round(2).to_string(index=False))

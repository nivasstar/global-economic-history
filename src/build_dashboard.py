from pathlib import Path
import html
import re

import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dashboard"
OUT.mkdir(exist_ok=True)

df = pd.read_parquet(ROOT / "data/processed/country_history.parquet")
countries = {"IND": "India", "CHN": "China", "USA": "United States"}
colors = {"IND": "#d97706", "CHN": "#dc2626", "USA": "#2563eb"}
metrics = [
    ("gdp_per_capita", "GDP per person", 1, "2011 international dollars"),
    ("population", "Population", 1e6, "Millions of people"),
    ("gdp", "Total GDP (derived)", 1e12, "Trillions of 2011 international dollars"),
]

fig = go.Figure()
for metric_index, (metric, label, scale, unit) in enumerate(metrics):
    for code, name in countries.items():
        series = df[df["country_id"] == code].set_index("year")[metric]
        # Insert missing calendar years so lines cannot bridge data gaps.
        annual = series.reindex(range(1800, 2023)) / scale
        values = [None if pd.isna(value) else float(value) for value in annual]
        fig.add_trace(go.Scatter(
            x=list(annual.index),
            y=values,
            name=name,
            mode="lines+markers",
            connectgaps=False,
            visible=metric_index == 0,
            line={"color": colors[code], "width": 2},
            marker={"size": 4},
            hovertemplate=f"{name}<br>Year: %{{x}}<br>{label}: %{{y:,.2f}}<extra></extra>",
        ))

# Modern World Bank series, stored separately from Maddison.
wb = pd.read_parquet(ROOT / "data/processed/world_bank_history.parquet")
wb_valid = wb.dropna(subset=["value"])
latest_year = int(wb_valid["year"].max())

for metric_index, (metric, label, scale, _) in enumerate(metrics):
    for code, name in countries.items():
        observations = wb[
            (wb["country_id"] == code) & (wb["metric"] == metric)
        ].set_index("year")["value"]
        annual = observations.reindex(range(1960, latest_year + 1)) / scale
        fig.add_trace(go.Scatter(
            x=list(annual.index),
            y=[None if pd.isna(value) else float(value) for value in annual],
            name=name,
            mode="lines+markers",
            connectgaps=False,
            visible=False,
            line={"color": colors[code], "width": 2},
            marker={"size": 4},
            hovertemplate=(
                f"{name}<br>Year: %{{x}}<br>{label}: %{{y:,.2f}}"
                "<extra>World Bank WDI</extra>"
            ),
        ))

buttons = []
for index, (_, label, _, unit) in enumerate(metrics):
    buttons.append({
        "label": f"Maddison: {label}",
        "method": "update",
        "args": [
            {"visible": [i // 3 == index for i in range(18)]},
            {
                "yaxis.title.text": unit,
                "yaxis.autorange": True,
                "xaxis.range": [1800, 2022],
            },
        ],
    })

for index, (metric, label, _, _) in enumerate(metrics):
    unit = (
        "Millions of people" if metric == "population"
        else (
            "Trillions of constant 2021 international dollars"
            if metric == "gdp"
            else "Constant 2021 international dollars per person"
        )
    )
    start = int(wb_valid[wb_valid["metric"] == metric]["year"].min())
    buttons.append({
        "label": f"World Bank: {label}",
        "method": "update",
        "args": [
            {"visible": [i // 3 == index + 3 for i in range(18)]},
            {
                "yaxis.title.text": unit,
                "yaxis.autorange": True,
                "xaxis.range": [start, latest_year],
            },
        ],
    })

fig.update_layout(
    template="plotly_white",
    height=650,
    margin={"t": 100},
    updatemenus=[{"buttons": buttons, "x": 0, "y": 1.16}],
    legend={"orientation": "h", "y": 1.06},
    xaxis={
        "title": "Year",
        "range": [1800, 2022],
        "rangeslider": {"visible": True},
    },
    yaxis={"title": metrics[0][3], "rangemode": "tozero"},
)

# Extract each country's source block, including continuation rows.
citation_sections = []
for sheet in ["Sources", "Maddison original sources"]:
    source = pd.read_excel(
        ROOT / "data/raw/maddison2023.xlsx",
        sheet_name=sheet,
        header=None,
    )
    active_country = None
    collected = []
    for row in source.itertuples(index=False, name=None):
        first = str(row[0]).strip() if pd.notna(row[0]) else ""
        if re.fullmatch(r"[A-Z]{3}", first):
            active_country = first
        if active_country in countries:
            cells = [str(value).strip() for value in row if pd.notna(value)]
            if cells:
                collected.append(
                    f"<li><strong>{countries[active_country]}</strong>: "
                    + html.escape(" | ".join(cells)) + "</li>"
                )
    if not collected:
        raise ValueError(f"No country citations extracted from {sheet}")
    citation_sections.append(
        f"<h3>{html.escape(sheet)}</h3><ul>"
        + "".join(collected) + "</ul>"
    )
    # Include dataset-wide source notes preceding the country blocks.
    intro = []
    for row in source.itertuples(index=False, name=None):
        first = str(row[0]).strip() if pd.notna(row[0]) else ""
        if re.fullmatch(r"[A-Z]{3}", first):
            break
        cells = [str(value).strip() for value in row if pd.notna(value)]
        if cells:
            intro.append(html.escape(" | ".join(cells)))
    citation_sections.append("<p>" + "<br>".join(intro) + "</p>")

latest = wb_valid.sort_values("year").groupby(
    ["country_id", "metric"], as_index=False
).tail(1)

table_rows = []
for row in latest.sort_values(["metric", "country_id"]).itertuples():
    scale = 1e6 if row.metric == "population" else (
        1e12 if row.metric == "gdp" else 1
    )
    unit = "million people" if row.metric == "population" else (
        "trillion 2021 international $" if row.metric == "gdp"
        else "2021 international $ per person"
    )
    table_rows.append(
        f"<tr><td>{html.escape(row.country)}</td>"
        f"<td>{html.escape(row.metric.replace('_', ' '))}</td>"
        f"<td>{row.year}</td><td>{row.value / scale:,.2f}</td>"
        f"<td>{unit}</td></tr>"
    )

modern_section = (
    "<h2>Latest World Bank observations</h2>"
    "<p>Published annual data; the observation year is shown below. "
    "World Bank monetary series use constant 2021 international dollars. "
    "Maddison uses a 2011 basis. The two sources are displayed separately "
    "without splicing or rebasing their monetary values.</p>"
    "<table><thead><tr><th>Country</th><th>Metric</th><th>Year</th>"
    "<th>Value</th><th>Unit</th></tr></thead><tbody>"
    + "".join(table_rows)
    + "</tbody></table>"
    "<p>Source: World Bank, World Development Indicators. "
    "<a href='https://data.worldbank.org/indicator/NY.GDP.MKTP.PP.KD'>GDP</a> · "
    "<a href='https://data.worldbank.org/indicator/NY.GDP.PCAP.PP.KD'>"
    "GDP per person</a> · "
    "<a href='https://data.worldbank.org/indicator/SP.POP.TOTL'>Population</a>"
    "</p>"
)

chart = fig.to_html(full_html=False, include_plotlyjs=True)
page = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Global Economic History</title>
<style>
body{font-family:Arial,sans-serif;max-width:1200px;margin:30px auto;
padding:20px;color:#172033;line-height:1.6}
.note{background:#f1f5f9;padding:18px;border-radius:10px}
li{margin-bottom:10px}a{color:#2563eb}
</style></head><body>
<h1>Global Economic History</h1>
<p>India, China, and the United States — historical output and population.</p>
<div class="note">
Choose a metric from the dropdown. Drag the slider to change the year range.
Dots show available observations; lines break where annual data is missing.
GDP measures economic output. Maddison monetary values use the source's 2011
international-dollar basis. Total GDP is derived from GDP per person and
population. Historical geography follows the source definitions.
Coverage varies by country and metric; no missing values were interpolated.
</div>
""" + chart + modern_section + """
<h2>Sources and methodology</h2>
<p>Maddison Project Database 2023. Bolt, Jutta and Jan Luiten van Zanden
(2024), “Maddison style estimates of the evolution of the world economy:
A new 2023 update”, Journal of Economic Surveys.
<a href="https://doi.org/10.1111/joes.12618">Research paper</a> ·
<a href="https://doi.org/10.34894/INZBF2">Dataset</a>.
Licensed under CC BY 4.0. Data transformed and charted for this dashboard.</p>
<p>Country-specific source entries are reproduced below, including the
original Maddison source references.</p>
""" + "".join(citation_sections) + "</body></html>"

(OUT / "index.html").write_text(page, encoding="utf-8")
print("Dashboard created:", OUT / "index.html")
print("Chart traces:", len(fig.data))
print("Open it and check all three metrics and the source notes.")

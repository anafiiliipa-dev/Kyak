"""
Kayak Destination Recommender — Streamlit dashboard.

Run with:
    streamlit run app/streamlit_app.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Kayak Destination Recommender",
    page_icon="🗺️",
    layout="wide",
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# ── CSS tweaks ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .metric-label { font-size: 0.75rem; color: #6b7280; }
    .stTabs [data-baseweb="tab"] { font-size: 0.9rem; }
    .block-container { padding-top: 1.5rem; }
</style>
""", unsafe_allow_html=True)


# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def load_cities() -> pd.DataFrame | None:
    path = DATA_DIR / "cities_enriched.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


@st.cache_data(ttl=3600)
def load_hotels() -> pd.DataFrame | None:
    path = DATA_DIR / "top_hotels.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


city_df  = load_cities()
hotel_df = load_hotels()

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🗺️ Kayak Destination Recommender")
st.caption(
    "Real-time ranking of 35 French destinations "
    "based on 7-day weather forecast and nearby hotel quality."
)

if city_df is None:
    st.warning(
        "No data found in `data/`. "
        "Run the pipeline first:  `python -m kayak.pipeline`"
    )
    st.stop()

# ── Sidebar — filters ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")
    top_n = st.slider("Show top N destinations", min_value=3, max_value=35, value=10)
    min_temp = st.slider(
        "Min avg temperature (°C)",
        min_value=int(city_df["avg_temp_7d"].min()) - 1,
        max_value=int(city_df["avg_temp_7d"].max()) + 1,
        value=int(city_df["avg_temp_7d"].min()) - 1,
    )
    max_rain = st.slider(
        "Max total rain (mm)",
        min_value=0,
        max_value=int(city_df["total_rain_7d"].max()) + 10,
        value=int(city_df["total_rain_7d"].max()) + 10,
    )
    st.divider()
    st.caption("Data source: Open-Meteo · Nominatim · OpenStreetMap")

# ── Apply filters ─────────────────────────────────────────────────────────────
filtered = city_df[
    (city_df["avg_temp_7d"]  >= min_temp) &
    (city_df["total_rain_7d"] <= max_rain)
].nsmallest(top_n, "destination_rank")

# ── KPI row ───────────────────────────────────────────────────────────────────
best = filtered.iloc[0] if not filtered.empty else city_df.iloc[0]
col1, col2, col3, col4 = st.columns(4)
col1.metric("🏆 Top destination",    best["city_name"])
col2.metric("🌡️ Avg temp (7d)",      f"{best['avg_temp_7d']:.1f} °C")
col3.metric("🌧️ Total rain (7d)",    f"{best['total_rain_7d']:.1f} mm")
col4.metric("⭐ Weather score",       f"{best['weather_score']:.1f}")

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_map, tab_weather, tab_hotels, tab_ask = st.tabs(
    ["🗺️ Map", "☀️ Weather ranking", "🏨 Hotels", "🤖 Ask the data"]
)

# ── TAB 1 — Map ───────────────────────────────────────────────────────────────
with tab_map:
    st.subheader(f"Top {top_n} destinations")

    fig_map = px.scatter_map(
        filtered,
        lat="latitude",
        lon="longitude",
        hover_name="city_name",
        hover_data={
            "weather_score":    ":.2f",
            "avg_temp_7d":      ":.1f",
            "total_rain_7d":    ":.1f",
            "destination_rank": True,
            "latitude":         False,
            "longitude":        False,
        },
        color="weather_score",
        color_continuous_scale="RdYlGn",
        size="weather_score",
        size_max=20,
        zoom=5,
        height=500,
        map_style="open-street-map",
    )
    fig_map.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0})
    st.plotly_chart(fig_map, use_container_width=True)

# ── TAB 2 — Weather ranking ───────────────────────────────────────────────────
with tab_weather:
    st.subheader("Weather score breakdown")

    fig_bar = px.bar(
        filtered.sort_values("weather_score", ascending=True),
        x="weather_score",
        y="city_name",
        orientation="h",
        color="avg_temp_7d",
        color_continuous_scale="RdYlGn",
        labels={
            "weather_score": "Weather score",
            "city_name":     "City",
            "avg_temp_7d":   "Avg temp (°C)",
        },
        height=max(400, top_n * 36),
    )
    fig_bar.update_layout(coloraxis_showscale=True)
    st.plotly_chart(fig_bar, use_container_width=True)

    st.subheader("Detailed table")
    display_cols = [
        "destination_rank", "city_name",
        "weather_score", "avg_temp_7d",
        "total_rain_7d", "avg_pop_7d", "avg_humidity_7d",
    ]
    existing = [c for c in display_cols if c in filtered.columns]
    st.dataframe(
        filtered[existing].rename(columns={
            "destination_rank": "Rank",
            "city_name":        "City",
            "weather_score":    "Score",
            "avg_temp_7d":      "Avg temp °C",
            "total_rain_7d":    "Rain mm",
            "avg_pop_7d":       "Precip prob",
            "avg_humidity_7d":  "Humidity %",
        }),
        use_container_width=True,
        hide_index=True,
    )

# ── TAB 3 — Hotels ────────────────────────────────────────────────────────────
with tab_hotels:
    if hotel_df is None:
        st.info("Hotel data not yet available. Run the pipeline first.")
    else:
        st.subheader("Top hotels by city")

        city_filter = st.selectbox(
            "Filter by city",
            ["All cities"] + sorted(hotel_df["city_name"].unique().tolist()),
        )

        h_display = hotel_df if city_filter == "All cities" else \
            hotel_df[hotel_df["city_name"] == city_filter]

        hotel_cols = [
            "city_name", "hotel_name",
            "hotel_score", "hotel_overall_rating",
            "distance_to_city_center_km", "hotel_rank",
        ]
        existing_h = [c for c in hotel_cols if c in h_display.columns]
        st.dataframe(
            h_display[existing_h].rename(columns={
                "city_name":                  "City",
                "hotel_name":                 "Hotel",
                "hotel_score":                "Score",
                "hotel_overall_rating":       "Stars",
                "distance_to_city_center_km": "Distance (km)",
                "hotel_rank":                 "Rank",
            }),
            use_container_width=True,
            hide_index=True,
        )

        if not h_display.empty and "hotel_latitude" in h_display.columns:
            fig_hotels = px.scatter_map(
                h_display,
                lat="hotel_latitude",
                lon="hotel_longitude",
                hover_name="hotel_name",
                hover_data={"hotel_score": ":.2f", "hotel_overall_rating": True},
                color="hotel_score",
                color_continuous_scale="Blues",
                zoom=5,
                height=400,
                map_style="open-street-map",
            )
            fig_hotels.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0})
            st.plotly_chart(fig_hotels, use_container_width=True)

# ── TAB 4 — Ask the data (simple pandas Q&A) ─────────────────────────────────
with tab_ask:
    st.subheader("🤖 Ask the data")
    st.caption(
        "Powered by Claude via Anthropic API — answers questions "
        "grounded in the pipeline's output CSVs."
    )

    question = st.text_input(
        "Ask a question about the destinations or hotels:",
        placeholder="Which city has the best weather and low rainfall?",
    )

    if question:
        # Build a compact context string from the data
        city_context = city_df.nsmallest(35, "destination_rank")[
            ["city_name", "destination_rank", "weather_score",
             "avg_temp_7d", "total_rain_7d"]
        ].to_string(index=False)

        hotel_context = ""
        if hotel_df is not None:
            hotel_context = hotel_df.nsmallest(20, "hotel_rank")[
                ["city_name", "hotel_name", "hotel_score", "hotel_overall_rating"]
            ].to_string(index=False)

        prompt = f"""You are a travel assistant. Answer the user's question using ONLY the data below.
Be concise and specific. Cite city names and numbers from the data.

--- DESTINATION DATA (ranked by weather score) ---
{city_context}

--- TOP HOTEL DATA ---
{hotel_context}

USER QUESTION: {question}"""

        try:
            import anthropic  # type: ignore[import]
            client = anthropic.Anthropic()
            with st.spinner("Thinking …"):
                message = client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=512,
                    messages=[{"role": "user", "content": prompt}],
                )
            st.markdown(message.content[0].text)
        except ImportError:
            st.error(
                "`anthropic` package not installed. "
                "Run: `pip install anthropic`"
            )
        except Exception as exc:
            st.error(f"API error: {exc}")

import time
import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import requests
import urllib.parse
import json
import altair as alt
import calendar
from dateutil.relativedelta import relativedelta
from datetime import datetime
from datetime import date
from io import StringIO
from pathlib import Path

# Instantiate
current_path = Path.cwd()
datasets = [  # These datasets are from 'Resale Flat Prices' https://data.gov.sg/collections/189/view
    # "d_ebc5ab87086db484f88045b47411ebc5",
    # "d_43f493c6c50d54243cc1eab0df142d6a",
    # "d_2d5ff9ea31397b66239f245f57751537",
    # "d_ea9ed51da2787afaf8e51f827c304208",
    "d_8b84c4ee58e3cfc0ece0d773c8ca6abc"  # you only need the latest file, since only past 12 months
]
today = datetime.today()


# Download datasets
@st.cache_data
def download_resale_hdb_dataset():
    temp_dfs = []
    for dataset in datasets:
        response = requests.get(
            "https://api-open.data.gov.sg/v1/public/api/datasets/"
            + dataset
            + "/initiate-download",
            headers={"Content-Type": "application/json"},
        )
        response = requests.get(response.json().get("data").get("url"))
        response = response.content.decode("utf-8")
        temp_df = pd.read_csv(StringIO(response))
        temp_dfs.append(temp_df)
        time.sleep(5) 
    return_df = pd.concat(temp_dfs, ignore_index=True)
    return_df["flat_type"] = return_df["flat_type"].str.replace(
        "MULTI GENERATION", "MULTI-GENERATION", case=False, regex=True
    )
    columns_to_remove = ["storey_range", "flat_model", "remaining_lease"]
    return_df["lease_commence_date"] = 99 - (
        today.year - return_df["lease_commence_date"]
    )
    return_df = return_df.drop(columns=columns_to_remove)
    return return_df


def price_to_rgb(x: float):
    midpoint = 0.5  # set this to 0.66 or 0.75 as needed
    if x < midpoint:
        # green to yellow
        r = int((x / midpoint) * 255)
        g = 255
        b = 0
    else:
        # yellow to red
        r = 255
        g = int(((1 - x) / (1 - midpoint)) * 255)
        b = 0
    return f"rgb({r}, {g}, {b})"


def extract_price_bin_value(x: str):
    if x == "≥ $1M":
        return float("inf")  # push to the end
    else:
        return int(x.replace("$", "").replace(",", ""))


def rgb_str_to_pydeck_color(rgba_str: str):
    parts = rgba_str.strip("rgb()").split(",")
    r, g, b = map(int, parts[:3])
    return [r, g, b]


@st.cache_data
def collate_past_transactions(df: pd.DataFrame):
    # Sort once beforehand instead of in every group
    df_sorted = df.sort_values("month", ascending=False).copy()
    # Zip month and resale_price into dicts
    df_sorted["txn"] = list(zip(df_sorted["month"], df_sorted["resale_price"]))
    # Group and convert each txn to desired format
    collapsed_df = (
        df_sorted.groupby(["town", "flat_type", "block", "street_name"])["txn"]
        .apply(lambda txns: [{"month": m, "resale_price": p} for m, p in txns])
        .reset_index(name="past_transactions")
    )

    return collapsed_df


@st.cache_data
def intro():
    st.title("How much is resale HDB?")
    latest_date = pd.to_datetime(hdb_df["month"].max())
    past_date = latest_date - pd.DateOffset(months=13)
    st.text(
        "Property data is from "
        + past_date.strftime("%b")
        + " "
        + str(past_date.year)
        + " to "
        + latest_date.strftime("%b")
        + " "
        + str(latest_date.year)
        + ", from https://data.gov.sg/collections/189/view"
    )
    st.divider()


def filters_type_town(hdb_df: pd.DataFrame):
    # Filtering ############################################################################################
    hdb_df["month_dt"] = pd.to_datetime(hdb_df["month"], format="%Y-%m")
    cutoff_date = datetime.today() - relativedelta(months=12)
    hdb_df = hdb_df[hdb_df["month_dt"] >= cutoff_date]

    flat_types = sorted(hdb_df["flat_type"].unique())
    selected_flat_type = st.pills(
        "Desired Flat Types",
        options=flat_types,
        default=flat_types,
        selection_mode="multi",
    )
    hdb_df = hdb_df[(hdb_df["flat_type"].isin(selected_flat_type))]
    towns = sorted(hdb_df["town"].unique())
    selected_town = st.pills(
        "Desired Towns", options=towns, default=towns, selection_mode="multi"
    )
    hdb_df = hdb_df[(hdb_df["town"].isin(selected_town))]
    return hdb_df


def filters_price_bin(hdb_df: pd.DataFrame):
    # Show price distribution ##############################################################################
    # Define bin width and threshold
    bin_width = 50000

    def bin_price(price: float):
        return f"${int((price // bin_width) * bin_width):,}"

    def extract_bin_midpoint(bin_str: str):
        base = int(bin_str.replace("$", "").replace(",", ""))
        return base + bin_width / 2

    hdb_df["price_bin"] = hdb_df["resale_price"].apply(bin_price)
    # Count entries per bin and sort (custom sort to put "≥ $1M" last)
    price_data = hdb_df["price_bin"].value_counts().reset_index()
    price_data.columns = ["price_bin", "count"]
    price_data = price_data.sort_values(
        by="price_bin", key=lambda col: col.map(extract_price_bin_value)
    )
    # Create a sorted list of categories based on your mapped numeric values
    sorted_bins = price_data["price_bin"].tolist()
    st.markdown(
        "<label style='font-weight: 500; font-size: 0.875rem;'>Filter by Price Distribution</label>",
        unsafe_allow_html=True,
    )
    price_data["mid_price"] = price_data["price_bin"].apply(extract_bin_midpoint)
    # price_data["norm_price"] = (price_data["mid_price"] - min_val) / med_val
    # price_data["color"] = price_data["norm_price"].apply(price_to_rgb)
    chart = (
        alt.Chart(price_data)
        .mark_bar()
        .encode(
            x=alt.X(
                "price_bin:N", sort=sorted_bins, title=None, axis=alt.Axis(labelAngle=0)
            ),
            y=alt.Y("count:Q", title=None, axis=alt.Axis(labels=False, ticks=False)),
            # color=alt.Color("color:N", scale=None),  # disable Altair scale
            tooltip=["price_bin", "count"],
        )
        .properties(height=100)
    )
    st.altair_chart(chart, use_container_width=True)
    # Range of resale_price
    min_price = int(hdb_df["resale_price"].min() // bin_width * bin_width)
    max_price = int(hdb_df["resale_price"].max() // bin_width * bin_width) + bin_width

    # Streamlit slider for price range
    highlight_range = st.slider(
        "Highlight range",
        label_visibility="collapsed",
        min_value=min_price,
        max_value=max_price,
        value=(min_price, max_price),
        step=bin_width,
        format="$%d",
    )
    return highlight_range


def filters_lease_range(hdb_df: pd.DataFrame):
    # Get min and max lease values
    min_lease = int(hdb_df["lease_commence_date"].min())
    max_lease = int(hdb_df["lease_commence_date"].max())
    # Count occurrences of each lease year
    lease_counts = hdb_df["lease_commence_date"].value_counts().reset_index()
    lease_counts.columns = ["lease_years", "count"]
    lease_counts = lease_counts.sort_values("lease_years")
    # Display label
    st.markdown(
        "<label style='font-weight: 500; font-size: 0.875rem;'>Filter by Remaining Lease (Years)</label>",
        unsafe_allow_html=True,
    )
    # Show bar chart
    chart = (
        alt.Chart(lease_counts)
        .mark_bar()
        .encode(
            x=alt.X("lease_years:O", title=None, sort="ascending"),
            y=alt.Y("count:Q", title=None, axis=alt.Axis(labels=False, ticks=False)),
            tooltip=["lease_years", "count"],
        )
        .properties(height=100)
    )
    st.altair_chart(chart, use_container_width=True)
    # Add slider filter
    if min_lease == max_lease:
        lease_range = (min_lease, max_lease)
        st.select_slider(
            "Lease range",
            label_visibility="collapsed",
            options=[min_lease, max_lease],
            value=min_lease,
            disabled=True,
        )
    else:
        lease_range = st.slider(
            "Lease range",
            label_visibility="collapsed",
            min_value=min_lease,
            max_value=max_lease,
            value=(min_lease, max_lease),
            step=1,
            format="%d years",
        )
    return lease_range


def add_lat_long(hdb_df: pd.DataFrame, df: pd.DataFrame):
    past_prices_df = collate_past_transactions(hdb_df)
    columns_to_remove = ["month", "month_dt", "price_bin"]
    hdb_df = hdb_df.drop(columns=columns_to_remove)
    hdb_df = hdb_df.groupby(
        ["town", "flat_type", "block", "street_name"], as_index=False
    ).mean()
    hdb_df = hdb_df.round().astype(
        {col: "int" for col in hdb_df.select_dtypes("float").columns}
    )
    hdb_df = hdb_df.merge(  # merging for coordinates
        df[["block", "street_name", "lat", "lon"]],
        on=["block", "street_name"],
        how="left",
    )
    hdb_df = hdb_df.merge(  # merging for past transactions
        past_prices_df[["flat_type", "block", "street_name", "past_transactions"]],
        on=["flat_type", "block", "street_name"],
        how="left",
    )
    # st.dataframe(hdb_df)
    # Clean up those missing coordinates
    missing_coords_df = hdb_df[hdb_df["lat"].isna() | hdb_df["lon"].isna()]
    hdb_df = hdb_df.dropna(subset=["lat", "lon"])
    return (hdb_df, missing_coords_df)


def colour_nodes(
    hdb_df: pd.DataFrame, min_price: float, med_price: float, max_price: float
):
    def normalize_price(price, min_price, med_price, max_price):
        if price <= med_price:
            return 0.5 * (price - min_price) / (med_price - min_price)
        else:
            return 0.5 + 0.5 * (price - med_price) / (max_price - med_price)

    hdb_df["norm_price"] = hdb_df["resale_price"].apply(
        lambda x: normalize_price(x, min_price, med_price, max_price)
    )
    # hdb_df["norm_price"] = (hdb_df["resale_price"] - min_price) / med_price
    hdb_df["color"] = hdb_df["norm_price"].apply(price_to_rgb)
    hdb_df["color"] = hdb_df["color"].apply(rgb_str_to_pydeck_color)


def offset_coords(hdb_df: pd.DataFrame):
    # Step 1: Map each (block, street_name) to room_types
    offsets = hdb_df.groupby(["block", "street_name"])["flat_type"].cumcount()
    # Step 2: Create a mapping of (block, street_name, flat_type) → offset
    hdb_df["lat"] -= offsets.mul(0.000075)
    hdb_df["resale_price_formatted"] = hdb_df["resale_price"].map("{:,}".format)
    hdb_df["past_transactions_html"] = hdb_df["past_transactions"].map(
        lambda txns: "<br>".join(
            [f"{t['month']}: ${t['resale_price']:,.0f}" for t in txns]
        )
    )
    return hdb_df


def render_map(hdb_df: pd.DataFrame):
    hdb_df = hdb_df.drop(
        columns=[
            "floor_area_sqm",
            "resale_price",
            "highlight",
            "norm_price",
            "past_transactions",
        ]
    )
    layer = pdk.Layer(
        "ScatterplotLayer",
        data=hdb_df,
        get_position="[lon, lat]",
        get_radius=10,
        get_fill_color="color",
        radiusMinPixels=1,  # minimum pixel size
        radiusMaxPixels=10,  # maximum pixel size
        radiusScale=1,  # scale factor (keep at 1 if using fixed pixels)
        pickable=True,
    )

    view_state = pdk.ViewState(
        latitude=hdb_df["lat"].mean(), longitude=hdb_df["lon"].mean(), zoom=11
    )
    st.pydeck_chart(
        pdk.Deck(
            map_style="mapbox://styles/mapbox/dark-v10",
            initial_view_state=view_state,
            layers=[layer],
            tooltip={
                "html": """
            <b>{town}</b><br>
            <b>{block}</b> <b>{street_name}</b><br>
            {flat_type} - ${resale_price_formatted}<br>
            Remaining Lease - {lease_commence_date} years<br>
            <hr style="margin:2px 0">
            <b>Past Transactions:</b><br>{past_transactions_html}
        """,
                "style": {"backgroundColor": "white", "color": "black"},
            },
        )
    )
    st.markdown(
        "<label style='font-weight: 500; font-size: 0.875rem;'>Price Legend</label>",
        unsafe_allow_html=True,
    )
    st.markdown(
        """
    <div style="display: flex; gap: 10px;">
    <div style="width: 20px; height: 20px; background-color: rgb(0,255,0);"></div> Low
    <div style="width: 20px; height: 20px; background-color: rgb(255,255,0);"></div> Mid
    <div style="width: 20px; height: 20px; background-color: rgb(255,0,0);"></div> High
    </div>
    """,
        unsafe_allow_html=True,
    )


# Get Data #############################################################################################
hdb_df = download_resale_hdb_dataset()
df = pd.read_csv("postal_code_latlong_all_latlong.csv")

# Header and such
intro()
# Filters Flat Type and Town
hdb_df = filters_type_town(hdb_df)


# More processing
highlight_range = filters_price_bin(hdb_df)  # Filters by Price
lease_range = filters_lease_range(hdb_df)
hdb_df, missing_coords_df = add_lat_long(hdb_df, df)  # Adds coordinates

# Set min max median of current filters
hdb_df["highlight"] = hdb_df["resale_price"].between(
    highlight_range[0], highlight_range[1]
) & hdb_df["lease_commence_date"].between(lease_range[0], lease_range[1])
hdb_df = hdb_df.loc[hdb_df["highlight"]]
min_price = hdb_df["resale_price"].min()
med_price = hdb_df["resale_price"].median()
max_price = hdb_df["resale_price"].max()

colour_nodes(hdb_df, min_price, med_price, max_price)
hdb_df = offset_coords(hdb_df)
# st.dataframe(hdb_df)

if len(hdb_df) > 20000:
    st.text(
        "Your current filters have too much results. Please reduce your selections. "
    )
else:
    with st.spinner("Loading map... Please wait"):
        render_map(hdb_df)

if not missing_coords_df.empty:
    st.divider()
    st.text(
        "Transactions for the following blocks are new and are missing coordinate data. They will not show up on the map. "
    )
    st.dataframe(missing_coords_df)

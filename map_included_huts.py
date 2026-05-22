from __future__ import annotations

import argparse
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd

from find_nearby_huts import (
    DEFAULT_INPUT,
    HUT_INCLUSION_COLUMN,
    WGS84_CRS,
    filter_huts_by_inclusion_column,
    load_huts,
    marker_points,
)


DEFAULT_OUTPUT = Path("included_huts_map.html")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Leaflet map for huts included in evaluation."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Pickled GeoDataFrame path. Defaults to {DEFAULT_INPUT}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output HTML map path. Defaults to {DEFAULT_OUTPUT}.",
    )
    return parser.parse_args()


def popup_html(row: pd.Series) -> str:
    lines = [f"<b>{row.get('name', 'Unnamed hut')}</b>"]
    for label, column in [
        ("Type", "tourism"),
        ("Elevation", "ele"),
        ("Capacity", "capacity"),
        ("Beds", "beds"),
        ("Website", "website"),
    ]:
        value = row.get(column)
        if pd.notna(value):
            lines.append(f"{label}: {value}")
    return "<br>".join(lines)


def create_map(huts: gpd.GeoDataFrame, output: Path) -> None:
    if huts.empty:
        raise ValueError(
            f"No huts have {HUT_INCLUSION_COLUMN!r} set to an included value."
        )

    points = marker_points(huts)
    center = [points.y.mean(), points.x.mean()]
    hut_map = folium.Map(location=center, zoom_start=8, tiles="OpenStreetMap")

    marker_group = folium.FeatureGroup(name="Included huts", show=True)
    for index, row in huts.iterrows():
        point = points.loc[index]
        folium.CircleMarker(
            location=[point.y, point.x],
            radius=5,
            color="#1f77b4",
            fill=True,
            fill_color="#1f77b4",
            fill_opacity=0.85,
            weight=1,
            tooltip=str(row.get("name", "Unnamed hut")),
            popup=folium.Popup(popup_html(row), max_width=320),
        ).add_to(marker_group)

    marker_group.add_to(hut_map)
    bounds = [[point.y, point.x] for point in points]
    hut_map.fit_bounds(bounds, padding=(30, 30))
    folium.LayerControl(collapsed=False).add_to(hut_map)

    output.parent.mkdir(parents=True, exist_ok=True)
    hut_map.save(output)


def main() -> None:
    args = parse_args()
    huts = load_huts(args.input)
    included_huts = filter_huts_by_inclusion_column(huts)
    create_map(included_huts.to_crs(WGS84_CRS), args.output)
    print(f"Mapped {len(included_huts)} included huts.")
    print(f"Map written to: {args.output}")


if __name__ == "__main__":
    main()

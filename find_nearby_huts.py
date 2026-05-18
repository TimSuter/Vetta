from __future__ import annotations

import argparse
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd


DEFAULT_HUT_NAME = "Vermigel Hütte"
DEFAULT_RADIUS_KM = 30.0
DEFAULT_INPUT = Path("my_geodataframe.pkl")
DEFAULT_OUTPUT = Path("nearby_huts_map.html")
METRIC_CRS = "EPSG:2056"
WGS84_CRS = "EPSG:4326"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find nearby huts by Euclidean distance and render them on a Folium map."
    )
    parser.add_argument(
        "--hut",
        default=DEFAULT_HUT_NAME,
        help=f"Input hut name. Defaults to {DEFAULT_HUT_NAME!r}.",
    )
    parser.add_argument(
        "--radius-km",
        type=float,
        default=DEFAULT_RADIUS_KM,
        help=f"Search radius in kilometers. Defaults to {DEFAULT_RADIUS_KM:g}.",
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


def load_huts(path: Path) -> gpd.GeoDataFrame:
    gdf = pd.read_pickle(path)
    if not isinstance(gdf, gpd.GeoDataFrame):
        raise TypeError(f"{path} did not contain a GeoDataFrame.")
    if "name" not in gdf.columns:
        raise ValueError("Expected a 'name' column in the hut data.")
    if gdf.geometry.name is None:
        raise ValueError("Expected an active geometry column in the hut data.")
    if gdf.crs is None:
        gdf = gdf.set_crs(WGS84_CRS)
    return gdf.dropna(subset=["geometry"]).reset_index(drop=True)


def find_input_hut(gdf: gpd.GeoDataFrame, hut_name: str) -> pd.Series:
    exact_matches = gdf[gdf["name"].fillna("").str.casefold() == hut_name.casefold()]
    if not exact_matches.empty:
        return exact_matches.iloc[0]

    partial_matches = gdf[
        gdf["name"].fillna("").str.contains(hut_name, case=False, regex=False)
    ]
    if len(partial_matches) == 1:
        return partial_matches.iloc[0]
    if len(partial_matches) > 1:
        names = ", ".join(partial_matches["name"].dropna().head(10).astype(str))
        raise ValueError(f"Multiple huts matched {hut_name!r}: {names}")

    raise ValueError(f"No hut found matching {hut_name!r}.")


def points_for_distance(gdf: gpd.GeoDataFrame) -> gpd.GeoSeries:
    metric = gdf.to_crs(METRIC_CRS)
    return metric.geometry.representative_point()


def nearest_huts(
    gdf: gpd.GeoDataFrame, input_hut: pd.Series, radius_km: float
) -> gpd.GeoDataFrame:
    metric_points = points_for_distance(gdf)
    input_point = metric_points.loc[input_hut.name]
    result = gdf.copy()
    result["distance_km"] = metric_points.distance(input_point) / 1000
    return result[result["distance_km"] <= radius_km].sort_values("distance_km")


def marker_points(gdf: gpd.GeoDataFrame) -> gpd.GeoSeries:
    return gdf.to_crs(WGS84_CRS).geometry.representative_point()


def make_popup(row: pd.Series) -> str:
    name = row.get("name")
    tourism = row.get("tourism")
    ele = row.get("ele")
    distance = row.get("distance_km")

    lines = [f"<b>{name}</b>"]
    if pd.notna(distance):
        lines.append(f"Distance: {distance:.1f} km")
    if pd.notna(tourism):
        lines.append(f"Type: {tourism}")
    if pd.notna(ele):
        lines.append(f"Elevation: {ele} m")
    return "<br>".join(lines)


def create_map(
    nearby: gpd.GeoDataFrame, input_hut: pd.Series, output_path: Path
) -> None:
    points = marker_points(nearby)
    input_point = points.loc[input_hut.name]
    map_center = [input_point.y, input_point.x]

    hut_map = folium.Map(location=map_center, zoom_start=11, tiles="OpenStreetMap")

    for index, row in nearby.iterrows():
        point = points.loc[index]
        is_input = index == input_hut.name
        folium.Marker(
            location=[point.y, point.x],
            popup=folium.Popup(make_popup(row), max_width=300),
            tooltip=str(row.get("name", "Unnamed hut")),
            icon=folium.Icon(
                color="red" if is_input else "blue",
                icon="home" if is_input else "info-sign",
            ),
        ).add_to(hut_map)

    bounds = [[point.y, point.x] for point in points]
    if len(bounds) > 1:
        hut_map.fit_bounds(bounds, padding=(30, 30))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    hut_map.save(output_path)


def main() -> None:
    args = parse_args()
    huts = load_huts(args.input)
    input_hut = find_input_hut(huts, args.hut)
    nearby = nearest_huts(huts, input_hut, args.radius_km)

    create_map(nearby, input_hut, args.output)

    neighbors = nearby[nearby.index != input_hut.name]
    print(f"Input hut: {input_hut['name']}")
    print(f"Found {len(neighbors)} neighboring huts within {args.radius_km:g} km.")
    print(f"Map written to: {args.output}")
    if not neighbors.empty:
        print("\nNearest huts:")
        for _, row in neighbors.head(15).iterrows():
            print(f"- {row['name']}: {row['distance_km']:.1f} km")


if __name__ == "__main__":
    main()

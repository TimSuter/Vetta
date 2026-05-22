from __future__ import annotations

import argparse
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd


DEFAULT_HUT_NAME = "Vermigel Hütte"
DEFAULT_RADIUS_KM = 30.0
DEFAULT_INPUT = Path("my_geodataframe.pkl")
DEFAULT_INCLUSION_CSV = Path("hut_inclusion.csv")
DEFAULT_OUTPUT = Path("nearby_huts_map.html")
METRIC_CRS = "EPSG:2056"
WGS84_CRS = "EPSG:4326"
HUT_INCLUSION_COLUMN = "include_in_evaluation"
HUT_REVIEW_COLUMNS = [
    "hut_index",
    "name",
    "latitude",
    "longitude",
    "tourism",
    "capacity",
    "beds",
    "capacity:persons",
    "access",
    "operator",
    "website",
    "reservation",
    "opening_hours",
    HUT_INCLUSION_COLUMN,
]


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
    parser.add_argument(
        "--inclusion-csv",
        type=Path,
        help=(
            "Optional CSV with a column named include_in_evaluation. "
            "Rows set to 1/true/yes are kept."
        ),
    )
    parser.add_argument(
        "--write-inclusion-template",
        type=Path,
        metavar="CSV",
        help=(
            "Write a hut review CSV with names, coordinates, metadata, and "
            "include_in_evaluation initialized to 1."
        ),
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


def truthy_inclusion_mask(values: pd.Series) -> pd.Series:
    normalized = values.fillna(0).astype(str).str.strip().str.casefold()
    return normalized.isin({"1", "true", "t", "yes", "y", "include"})


def filter_huts_by_inclusion_column(
    gdf: gpd.GeoDataFrame,
    include_column: str = HUT_INCLUSION_COLUMN,
) -> gpd.GeoDataFrame:
    if include_column not in gdf.columns:
        raise ValueError(
            f"Expected an {include_column!r} column in the hut data. "
            f"Update {DEFAULT_INPUT} from {DEFAULT_INCLUSION_CSV} first."
        )
    return gdf[truthy_inclusion_mask(gdf[include_column])].copy()


def filter_huts_by_inclusion_csv(
    gdf: gpd.GeoDataFrame,
    path: Path,
    include_column: str = HUT_INCLUSION_COLUMN,
) -> gpd.GeoDataFrame:
    selections = pd.read_csv(path)
    if include_column not in selections.columns:
        raise ValueError(f"{path} must contain an {include_column!r} column.")

    included = selections[truthy_inclusion_mask(selections[include_column])]
    if "hut_index" in included.columns:
        hut_indices = pd.to_numeric(included["hut_index"], errors="coerce").dropna().astype(int)
        result = gdf[gdf.index.isin(hut_indices)]
    elif "name" in included.columns:
        names = set(included["name"].dropna().astype(str))
        result = gdf[gdf["name"].astype(str).isin(names)]
    else:
        raise ValueError(f"{path} must contain either a 'hut_index' or 'name' column.")

    return result


def write_hut_inclusion_template(gdf: gpd.GeoDataFrame, path: Path) -> None:
    points = marker_points(gdf)
    review = pd.DataFrame(
        {
            "hut_index": gdf.index.astype(int),
            "name": gdf["name"],
            "latitude": points.y,
            "longitude": points.x,
            HUT_INCLUSION_COLUMN: 1,
        }
    )

    for column in HUT_REVIEW_COLUMNS:
        if column in review.columns:
            continue
        if column in gdf.columns:
            review[column] = gdf[column]
        else:
            review[column] = pd.NA

    path.parent.mkdir(parents=True, exist_ok=True)
    review[HUT_REVIEW_COLUMNS].sort_values(
        ["name", "hut_index"], na_position="last"
    ).to_csv(path, index=False)


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
    if args.write_inclusion_template:
        write_hut_inclusion_template(huts, args.write_inclusion_template)
        print(f"Hut inclusion template written to: {args.write_inclusion_template}")
        return

    before_count = len(huts)
    if args.inclusion_csv:
        huts = filter_huts_by_inclusion_csv(huts, args.inclusion_csv)
        print(f"Loaded {len(huts)} of {before_count} huts included by: {args.inclusion_csv}")
    else:
        huts = filter_huts_by_inclusion_column(huts)
        print(f"Loaded {len(huts)} of {before_count} huts included by: {args.input}")

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

from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
from pathlib import Path
from typing import Any

import geopandas as gpd

from find_hiking_routes import (
    DEFAULT_GPKG,
    DEFAULT_GRAPH,
    DEFAULT_ZIP,
    SWISSTOPO_WANDERWEGE_URL,
    build_routes_for_source,
    hut_points_metric,
    load_or_build_graph,
    nearest_graph_nodes,
)
from find_nearby_huts import (
    DEFAULT_INPUT,
    filter_huts_by_inclusion_column,
    filter_huts_by_inclusion_csv,
    load_huts,
)


DEFAULT_DATABASE = Path("data") / "hiking_routes.sqlite"
DEFAULT_MIN_HOURS = 2.0
DEFAULT_MAX_HOURS = 14.0
DEFAULT_NEIGHBOR_RADIUS_KM = 30.0
DEFAULT_WALKING_SPEED_KMH = 4.0
DEFAULT_ASCENT_M_PER_HOUR = 400.0
DEFAULT_DESCENT_M_PER_HOUR = 800.0
SCHEMA_VERSION = "1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Precompute single-day hut-to-hut hiking routes for included huts "
            "and write them to a SQLite database."
        )
    )
    parser.add_argument("--huts", type=Path, default=DEFAULT_INPUT)
    parser.add_argument(
        "--inclusion-csv",
        type=Path,
        help=(
            "Optional hut review CSV with include_in_evaluation. "
            "Rows set to 1/true/yes are included in routing."
        ),
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--wanderwege-url", default=SWISSTOPO_WANDERWEGE_URL)
    parser.add_argument("--zip-path", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--gpkg-path", type=Path, default=DEFAULT_GPKG)
    parser.add_argument("--graph-path", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--min-hours", type=float, default=DEFAULT_MIN_HOURS)
    parser.add_argument("--max-hours", type=float, default=DEFAULT_MAX_HOURS)
    parser.add_argument("--neighbor-radius-km", type=float, default=DEFAULT_NEIGHBOR_RADIUS_KM)
    parser.add_argument("--walking-speed-kmh", type=float, default=DEFAULT_WALKING_SPEED_KMH)
    parser.add_argument("--ascent-m-per-hour", type=float, default=DEFAULT_ASCENT_M_PER_HOUR)
    parser.add_argument("--descent-m-per-hour", type=float, default=DEFAULT_DESCENT_M_PER_HOUR)
    parser.add_argument(
        "--rebuild-graph",
        action="store_true",
        help="Rebuild the cached NetworkX graph from the swisstopo GeoPackage.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Keep existing route rows instead of clearing the generated routes table first.",
    )
    return parser.parse_args()


def initialize_database(path: Path, append: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS route_database_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS routes (
                start_hut TEXT NOT NULL,
                destination_hut TEXT NOT NULL,
                duration_h REAL NOT NULL,
                distance_km REAL NOT NULL,
                ascent_m REAL NOT NULL,
                descent_m REAL NOT NULL,
                max_hiking_category TEXT NOT NULL,
                difficulty_status TEXT NOT NULL,
                geometry_wkt TEXT NOT NULL,
                PRIMARY KEY (start_hut, destination_hut)
            );

            CREATE INDEX IF NOT EXISTS idx_routes_start_hut
                ON routes(start_hut);
            CREATE INDEX IF NOT EXISTS idx_routes_start_duration
                ON routes(start_hut, duration_h);
            CREATE INDEX IF NOT EXISTS idx_routes_start_category
                ON routes(start_hut, max_hiking_category, duration_h);
            """
        )
        if not append:
            connection.execute("DELETE FROM routes")
        connection.execute(
            """
            INSERT INTO route_database_metadata(key, value)
            VALUES ('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (SCHEMA_VERSION,),
        )


def write_database_metadata(path: Path, args: argparse.Namespace, huts: gpd.GeoDataFrame) -> None:
    metadata = {
        "last_filled_at": dt.datetime.now(dt.UTC).isoformat(),
        "huts_path": str(args.huts),
        "included_hut_count": str(len(huts)),
        "min_hours": str(args.min_hours),
        "max_hours": str(args.max_hours),
        "neighbor_radius_km": str(args.neighbor_radius_km),
        "graph_path": str(args.graph_path),
    }
    with sqlite3.connect(path) as connection:
        connection.executemany(
            """
            INSERT INTO route_database_metadata(key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            metadata.items(),
        )


def route_row_values(routes: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        (
            route["source_hut"],
            route["destination_hut"],
            route["duration_h"],
            route["distance_km"],
            route["ascent_m"],
            route["descent_m"],
            route["max_hiking_category"],
            route["difficulty_status"],
            route["geometry_wkt"],
        )
        for route in routes
    ]


def write_routes(path: Path, routes: list[dict[str, Any]]) -> None:
    if not routes:
        return

    with sqlite3.connect(path) as connection:
        connection.executemany(
            """
            INSERT OR REPLACE INTO routes (
                start_hut,
                destination_hut,
                duration_h,
                distance_km,
                ascent_m,
                descent_m,
                max_hiking_category,
                difficulty_status,
                geometry_wkt
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            route_row_values(routes),
        )


def load_included_huts(args: argparse.Namespace) -> gpd.GeoDataFrame:
    print(f"Loading huts from: {args.huts}")
    huts = load_huts(args.huts)
    before_count = len(huts)

    if args.inclusion_csv:
        huts = filter_huts_by_inclusion_csv(huts, args.inclusion_csv)
        print(f"Included {len(huts)} of {before_count} huts from: {args.inclusion_csv}")
    else:
        huts = filter_huts_by_inclusion_column(huts)
        print(f"Included {len(huts)} of {before_count} huts from: {args.huts}")

    if huts.empty:
        raise ValueError("No huts are included for routing.")
    return huts


def main() -> None:
    args = parse_args()
    if args.min_hours < 0:
        raise ValueError("--min-hours must be at least 0.")
    if args.max_hours < args.min_hours:
        raise ValueError("--max-hours must be greater than or equal to --min-hours.")
    if args.neighbor_radius_km <= 0:
        raise ValueError("--neighbor-radius-km must be greater than 0.")

    print("Starting hiking route database fill.")
    print(
        "Route constraints: "
        f"{args.min_hours:g}-{args.max_hours:g} h, "
        f"{args.neighbor_radius_km:g} km neighbor radius."
    )
    print(f"SQLite database: {args.database}")

    huts = load_included_huts(args)
    initialize_database(args.database, args.append)
    write_database_metadata(args.database, args, huts)

    graph = load_or_build_graph(args)

    print("Snapping included huts to the trail graph.")
    snapped_nodes = nearest_graph_nodes(graph, hut_points_metric(huts))

    source_indices = huts.index.astype(int).tolist()
    total_routes = 0
    for count, source_index in enumerate(source_indices, start=1):
        source_name = huts.loc[source_index].get("name")
        print(
            f"[{count}/{len(source_indices)}] Routing from {source_name!r}; "
            f"{total_routes} routes written so far."
        )
        routes = build_routes_for_source(
            graph,
            huts,
            source_index,
            max_hours=args.max_hours,
            min_hours=args.min_hours,
            neighbor_radius_km=args.neighbor_radius_km,
            snapped_nodes=snapped_nodes,
        )
        write_routes(args.database, routes)
        total_routes += len(routes)
        print(
            f"[{count}/{len(source_indices)}] Wrote {len(routes)} routes for "
            f"{source_name!r}; {total_routes} total routes."
        )

    write_database_metadata(args.database, args, huts)
    print("Route database fill complete.")
    print(f"Routes written: {total_routes}")
    print(f"Database: {args.database}")


if __name__ == "__main__":
    main()

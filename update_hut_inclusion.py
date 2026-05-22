from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from find_nearby_huts import (
    DEFAULT_INCLUSION_CSV,
    DEFAULT_INPUT,
    HUT_INCLUSION_COLUMN,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update my_geodataframe.pkl with include_in_evaluation from CSV."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Pickled GeoDataFrame path. Defaults to {DEFAULT_INPUT}.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_INCLUSION_CSV,
        help=f"Hut inclusion CSV path. Defaults to {DEFAULT_INCLUSION_CSV}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output pickle path. Defaults to overwriting --input.",
    )
    return parser.parse_args()


def normalized_include_values(values: pd.Series) -> pd.Series:
    normalized = values.fillna(0).astype(str).str.strip().str.casefold()
    include_values = normalized.map(
        {
            "1": 1,
            "true": 1,
            "t": 1,
            "yes": 1,
            "y": 1,
            "include": 1,
            "0": 0,
            "false": 0,
            "f": 0,
            "no": 0,
            "n": 0,
            "exclude": 0,
        }
    )
    if include_values.isna().any():
        invalid = sorted(values[include_values.isna()].dropna().astype(str).unique())
        raise ValueError(
            f"{HUT_INCLUSION_COLUMN!r} contains unsupported values: {invalid}"
        )
    return include_values.astype("Int64")


def update_hut_inclusion(input_path: Path, csv_path: Path, output_path: Path) -> None:
    selections = pd.read_csv(csv_path)
    gdf = pd.read_pickle(input_path)

    required_columns = {"hut_index", HUT_INCLUSION_COLUMN}
    missing = required_columns - set(selections.columns)
    if missing:
        raise ValueError(f"{csv_path} is missing columns: {sorted(missing)}")

    hut_indices = pd.to_numeric(selections["hut_index"], errors="raise").astype(int)
    if not hut_indices.is_unique:
        raise ValueError("'hut_index' values must be unique.")
    if hut_indices.min() < 0 or hut_indices.max() >= len(gdf):
        raise ValueError("'hut_index' values do not fit the GeoDataFrame row count.")

    include_values = normalized_include_values(selections[HUT_INCLUSION_COLUMN])
    aligned = pd.Series(pd.NA, index=range(len(gdf)), dtype="Int64")
    aligned.loc[hut_indices.to_numpy()] = include_values.to_numpy()
    if aligned.isna().any():
        missing_count = int(aligned.isna().sum())
        raise ValueError(f"{missing_count} GeoDataFrame rows were not present in the CSV.")

    updated = gdf.copy()
    updated[HUT_INCLUSION_COLUMN] = aligned.to_numpy()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    updated.to_pickle(output_path)

    counts = updated[HUT_INCLUSION_COLUMN].value_counts(dropna=False).sort_index()
    print(f"Updated {output_path} from {csv_path}.")
    print(f"Rows kept in GeoDataFrame: {len(updated)}")
    print(counts.to_string())


def main() -> None:
    args = parse_args()
    output_path = args.output or args.input
    update_hut_inclusion(args.input, args.csv, output_path)


if __name__ == "__main__":
    main()

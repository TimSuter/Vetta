import osmnx as ox
import pandas

place_name = "Switzerland"

# Provide a list of values for the 'tourism' key
tags = {"tourism": ["alpine_hut", "wilderness_hut", "chalet"]}

print(f"Fetching huts and chalets for {place_name}...")
huts_gdf = ox.features_from_place(place_name, tags)

print(f"Found {len(huts_gdf)} locations.")

huts_gdf.to_pickle("my_geodataframe.pkl")
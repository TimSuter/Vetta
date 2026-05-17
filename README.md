Vetta
=====

Vetta is a local-first multiday hiking planner between Swiss mountain huts.

The first version uses precomputed hut-to-hut route edges. During offline
preprocessing, Vetta loads hut data, loads or builds a hiking trail graph,
precomputes feasible daily hiking legs between nearby huts, and saves those
route legs to disk.

The live app does not calculate OSM routes during user requests. It searches a
precomputed graph of feasible hut-to-hut hiking legs.

Users can plan itineraries by specifying:

- number of days
- maximum hiking duration per day
- maximum ascent per day
- maximum descent per day
- maximum SAC trail difficulty
- optional start hut
- optional end hut

## Architecture

### Offline preprocessing

- Load huts from the existing `.pkl` file.
- Load or build a hiking trail graph.
- Precompute feasible hut-to-hut routes between nearby huts.
- Save route legs to disk in a simple, reproducible format.

### Local planner

- Read the precomputed route-leg table.
- Build a hut graph where nodes are huts and edges are feasible daily hikes.
- Search for multiday itineraries that satisfy user constraints.

### Later

- Wrap the planner in FastAPI.
- Add a web UI and map.
- Deploy on one low-cost server.
- Convert the web UI to a PWA for mobile and desktop installation.

## Development principles

- Keep business logic pure Python.
- Keep data formats simple and reproducible.
- Make the prototype testable without a web server.
- Avoid paid APIs during local development.

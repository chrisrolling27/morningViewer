# Morning Viewer

A 3D map of the farm in Morning View, Kentucky, built only from free public data: KyFromAbove lidar,
county and state aerial photos (1962–2026), county parcels, buildings and roads, USGS creeks, FEMA flood zones,
USDA soils and OpenStreetMap driveways. One static page (`index.html`, three.js) plus its data in `data/area-3/`.

- **Today**: the 2026 photo with 3D trees and buildings · **Topo** / **Slope**: drawn from the lidar · **History**: one photo per year back to 1962
- Folder: `~/dev/morningViewer` · run locally: `python3 -m http.server 8000`, then open http://localhost:8000
- Rebuild the data: `python3 scripts/fetch_data.py` (on a Mac with normal internet), then `python3 scripts/build_data.py` (needs Pillow + numpy)
- Deploys as a static site on Vercel (no build step). `.vercelignore` keeps scripts and notes out of the deploy.

Project notes and history: `HANDOFF.md`.

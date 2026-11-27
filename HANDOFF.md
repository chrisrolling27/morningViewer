# Morning Viewer: project handoff

*Updated Nov 27, 2026. This replaces the earlier running log, which is still in git history (commit `d23bea5`).*
*For a new session: connect `~/dev/morningViewer` (Claude desktop app, "Add folder"), then point Claude at this file.*

## What it is

A 3D, interactive map of Chris's parents' farm in Morning View, Kentucky (Kenton County), for the family and for
hunting trips. It's one static web page (`index.html`, three.js 0.170 from jsDelivr) plus pre-built data in
`data/area-3/`. It's built only from free public data, and nothing is fetched from the source servers at runtime.

Chris is fine with it being public, since it's all public data. The house tag was removed from the map at his request.

## Where things live

| What | Where |
|---|---|
| Project folder | `~/dev/morningViewer` on Chris's Mac (was `~/dev/farm-map`) |
| GitHub | `chrisrolling27/morningViewer`, private (assumed: Chris created it; confirm), branch `main`, 2 commits pushed Nov 25 |
| Vercel | **Live** at https://morningviewer.vercel.app (confirmed Nov 27, 2026): Git deploy from `main`, preset "Other", no build command. Pushes to `main` redeploy. All 50 manifest files serve 200 (~101 MB), `/data/` cached 1 day. |
| Claude-hosted copy | https://claude.ai/artifact/JZWSfWNi99VV9tBon5mVND (slug `8e354d6c-47e0-4e07-bd2b-1c1a9670907e`, last version `1795658341-ef26`, title "Morning Viewer"). Private unless Chris shares it. |
| Run locally | `cd ~/dev/morningViewer && python3 -m http.server 8000`, then open http://localhost:8000. Double-clicking `index.html` doesn't work: browsers block `data/` on `file://`. |

## Chris's wishes and decisions (keep these)

- **Name:** "Morning Viewer" everywhere (tab, header, preview image, docs); `morningViewer` for folder and repo.
- **Simple UI.** One switch: **Today / Topo / Slope / History.**
  - **Today** is the main, best view: the newest photo (county 2026), 3D trees and 3D buildings.
  - **History** reveals a single timeline slider back to 1962, with no "photo sets". It starts at 2026; play runs oldest to newest.
  - Topo and Slope are drawn from the lidar.
- **Removed on purpose; don't bring back unless asked:**
  - isometric camera
  - height-boost slider (fixed at 2× relief)
  - the old tree surface toggle (draped DSM: slow and ugly)
  - pixel art, sun slider (fixed afternoon SW light)
  - photo-set picker, land cover view, lidar relief view
  - wetlands layer
  - driveways toggle (driveways are always drawn now)
  - Floodplain layer (removed Nov 27; flood zone still shows in the tap readout)
  - the house tag (was "House", then "13299", then removed)
- **Orientation:** opens on the farm close-up looking straight up **Madison Pike** (bearing 3.7°). The compass toggles road-up / north-up.
- **Farm quality matters most:** sharpest photos and terrain in the mile around the house.
- **Trees:** individual low-poly 3D trees from lidar treetops, as a **Trees layer checkbox** (on by default; hidden in History).
- **Mac-friendly turning:**
  - two-finger sideways swipe
  - shift-drag
  - ← → turn and ↑ ↓ tilt
  - hold ⟲ ⟳ buttons
  - Safari rotate gesture
- **Slow 360° spin** button (~100 s per turn).
- **Tap marker:** a pulsing HTML dot, not a 3D cylinder.
- **Layers kept:** Trees, Roads (with names), Creeks & ponds (with names), Property lines, Soils, then **Waypoint** in the last slot. Driveways are always on.
  - Waypoint is a greyed-out "soon" placeholder (`'soon'` as the 5th item in its `LAYERS` entry, which disables the checkbox). Next feature: users create waypoints on the map.
- **Tap readout:** ground ft, trees/roof ft, distance and direction from the house, soil (name, farmland class, drainage), flood zone, parcel acres.
- **Hosting:** GitHub → Vercel (Git deploy). Private repo. Chris pushes from his own Terminal.

## The app (`index.html`, all in one file, commented)

- **Area:** fixed 3-mile square centred on `FARM={lat:38.878617,lon:-84.535389}`, in Web Mercator (EPSG:3857).
  - World units are ground metres: x east, z south, y up, house at (0,0).
  - Ground metres = Mercator metres × cos(lat).
- **Terrain:**
  - Base grid 1024² (~4.7 m) over 3 mi, with a shader `discard` hole where the farm close-up goes.
  - Inset grid 1366² (~1.18 m) over the middle third (1 mi), from the 2 ft lidar.
  - Phones (coarse pointer, small screen) halve the inset grid.
  - Heights are computed once at load (`heights()`).
- **Textures:**
  - The 3-mile photo on both grids.
  - A sharper inset photo on the inner grid when the manifest has one, via repeat/offset into the inset.
  - Desktops with `maxTextureSize ≥ 8192` (`BIG`) get the 8192 px inset where available.
  - Topo/Slope are painted in-browser for both grids (`paintGrid`).
- **Layers:** drawn onto two transparent 2048 canvases (3-mile + inset) laid over the terrain (`drawLayers`). Road and creek names are written along the lines.
- **3D buildings:** county footprints extruded from bare ground to the lidar roof height (60th percentile of canopy samples; 11 ft if lidar shows none; max 40 ft). Hidden in History.
- **3D trees:**
  - `InstancedMesh` icosahedron crowns, plus trunks near the farm on desktop.
  - Positions and heights come from `data/area-3/trees.txt`; colours are varied greens.
  - Phones get low-detail crowns and half the outer trees.
- **History list:** built from the manifest. `SERIES.hires` + `COUNTY` + `SERIES.summer`, one per year label; the sharper flight wins (listed first). Sorted by `yk()`: 1990s→1995, 2019–22→2020.5, 2022–24→2022.5.
- **Keep the `summer:mk([...])`, `hires:mk([...])` and `nlcd:mk([...])` lines in their current shape.** `fetch_data.py` parses them with regexes, and also `FARM={lat:…,lon:…}`.
- **Constants:** `EX=2`, `SUN=225`, `ROAD=3.7`, `TODAY='linkgis:Basemaps/AerialBase_2026_HighScale_CC_KC'`.

## Data (`data/area-3/`, ~105 MB used by the page)

- `manifest.json` lists every file, the exact Mercator `bbox`, the inset `bbox`, and the grid encodings.
  - `layers[svc]` = file name, or `false` = blank here.
  - `inset.layers` = 4096 close-ups; `inset.layers8k` = 8192 close-ups; `trees`.
- **Grids** `dem.txt`, `canopy.txt`, `inset-dem.txt`, `inset-canopy.txt`:
  - gzip, stored as **base64 text**, because Claude artifacts won't serve `.bin`.
  - DEM is uint16 steps of 0.05 ft above `base`, each stored as the difference from the previous value.
  - Canopy is uint8 × 0.6 ft (clipped to 130 ft).
- **Photos (WebP):**
  - 3-mile versions: q80 at 2048, q76 at 4096, light unsharp mask.
  - `inset-*.webp`: 13 years at 4096 px over 1 mi, about 0.4 m/px.
  - `inset8k-ky-kyaped-phase3-3in.webp`: 8192 px, about 0.2 m/px. This is the only one worth it; the county 2025/2026 8k copies showed no gain, so `KEEP_8K` in the build drops them.
- `overlays.json` holds flat coordinate arrays in Mercator metres from the house: parcels (**shapes only, no owner data**), buildings, roads (with names), creeks (with names), ponds, flood zones, wetlands (not shown), soils, OSM tracks and field edges.
- `trees.txt`: gzip int16 triplets (x dm, z dm, height in 0.1 ft), base64. 9,332 in the close-up and 39,616 elsewhere.
- **Unused but present (small):** NLCD PNGs, `relief.webp`, `ky-naip-2012-1m.webp` (2012 is shown from the 6-inch flight instead).
- **Gaps:**
  - 1962 has a gap over the farm, so it has no close-up.
  - 1999 is blank here and left out.
  - NOAA April 2025 flood imagery doesn't cover the area.
  - OSM has no fences mapped.

### Photo timeline (oldest → newest)

1962, 1973, 1989 (county archive, B&W) · 1990s (USGS B&W) · 2004, 2006, 2008, 2010, 2014, 2016, 2018, 2020, 2022 (USDA NAIP summers)
· 2007 (Northern KY planning, 6 in) · 2009 (USGS, 1 ft) · 2012 (KyFromAbove, 6 in) · 2019–22 (KyFromAbove Phase 2, 6 in)
· 2022–24 (KyFromAbove Phase 3, 3 in, leaf-off; sharpest) · 2023, 2025, 2026 (county; 2026 is Today).
The 2026 service's own description says "2018"; the layer names say 2026, and the picture clearly differs from the others.

## Rebuilding the data

1. **Download** (`scripts/fetch_data.py`, stdlib + curl, resumable):
   - Must run on **Chris's Mac with normal internet**: Terminal, or double-click `Update Morning Viewer data.command`.
   - Claude's sandboxes can't reach the map servers (egress allowlist).
   - Writes `data/_raw/area-3/` (~300 MB, gitignored; **includes parcel owner names**, so never publish it).
   - Re-running skips files it already has.
2. **Build** (`scripts/build_data.py`, Pillow + numpy):
   - Claude can run this in the Mac sandbox shell.
   - That shell caps each call at ~180 s and kills background jobs. So use `python3 -u scripts/build_data.py --budget 105` and repeat until it exits 0 (exit 3 = more to do).
   - Outputs newer than their raw inputs are skipped.

**Sources and endpoints** (all in `fetch_data.py`):

- **kyraster.ky.gov** (ImageServer `exportImage`):
  - 2 ft DEM Phase 3 (Phase 2 as backup) at 4096²; 5 ft DEM; DSM first return 2 ft (Phase 2) at 2048².
  - State photos, NLCD, hillshade.
- **maps.linkgis.org** (MapServer `export`/`query`):
  - Aerials: `Archive_Aerials/ArchiveAerial_1962|1973|1989|1999` (hide layer 0), `Basemaps/AerialBase_2023`, `…2025_HighScale_CC_KC_PC`, `…2026_HighScale_CC_KC`.
  - Parcels: `CC_KC_PCTheme` layers 13 / 7 / 18 (Kenton / Campbell / Pendleton).
  - Buildings 1 / 3 / 5; road centerlines `Street_Centerlines` 63 / 62 / 64.
  - The box is entirely in Kenton County.
- **hydro.nationalmap.gov:** NHD layers 6 (creeks) and 12 (ponds).
- **Flood:** FEMA NFHL layer 28 (hazards.fema.gov), with the Kentucky copy as backup.
- **Wetlands:** fwspublicservices.wim.usgs.gov (NWI).
- **Soils:** sdmdataaccess.sc.egov.usda.gov (SSURGO via SQL).
- **OpenStreetMap:** overpass-api.de.
- **Farm close-up photos:** the middle third of the 4096 lidar grid, pixel-exact, at 4096 px. The 8k versions are 2×2 tiles of 4096, stitched in the build.

## Gotchas for working on this with Claude

- **Network:** Claude's cloud workspace and the Mac sandbox shell can only reach allowlisted hosts. Downloads need Chris's Terminal, or the domains added under claude.ai Settings → Capabilities. Computer use can't type into Terminal; it can only click there.
- **File handoff:** after `device_commit_files`, wait a few seconds before relying on the file. The staged copy can be stale, which caused two silent mistakes.
- **Deleting:** the connected folder doesn't allow deletes or git lock-file cleanup without permission. Chris runs git himself.
- **Claude artifacts:**
  - No `.bin`; ≤ 32 MB per file and 64 MB per publish call (patch mode keeps other files).
  - Outside requests are limited to the allowed CDNs (jsDelivr is fine).
  - Images load via fetch → blob.
- **Vercel Hobby:** CLI uploads are capped at 100 MB, and the data is ~105 MB, so deploy through Git. GitHub orgs aren't allowed on Hobby; use the personal account.
- **Headless test recipe:**
  - Playwright + Chrome with `--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader`.
  - Serve the folder with `python3 -m http.server`, and route `cdn.jsdelivr.net` three.js requests to a local `npm i three@0.170.0`.
  - Software rendering is very slow: use long screenshot timeouts, and drive the controls with `page.evaluate` clicks.

## Ideas not done yet (only if Chris wants them)

- Check it on a real phone (memory and frame rate with ~49k trees). Deploy is confirmed, and a 375×812 emulated view on the Mac loads with no errors, but that says nothing about real phone GPUs.
- Trim unused files from the repo (NLCD, relief, NAIP 2012) to get under 100 MB.
- Full-resolution zoom tiles (true 3-inch detail everywhere; ~1.5–3 GB, e.g. on Cloudflare R2).
- **Waypoint (next up):** let users drop their own waypoints on the map. The layer slot is already there as a placeholder.
- A private hunting layer (stands, blinds, trails, gates) kept out of the public site.
- Sharper first-return lidar (DSM at 4096) for better tree detection near the farm; needs a new download.
- Chris once said he'd rework the UI menu himself; the simplified panel above is the current state.

# Morning Viewer (formerly "farm map"): handoff for the next chat (Nov 25, 2026)

Project folder: `~/dev/morningViewer` (on Chris's Mac; was `~/dev/farm-map`). Main file: `index.html` (single-page three.js app, commented).

## Where things stand
- `index.html` works: 3D lidar terrain (1 mi or 3 mi square around the house), drag/scroll/rotate,
  views: Photo (summer NAIP 2004–2022, sharp 1990s–KyFromAbove Ph3), Land cover (NLCD 1992–2021), Topo (10 ft contours),
  Lidar relief; Bare earth ↔ With trees morph (DSM − DEM); Pixel-art post shader; Isometric ortho camera; time-lapse play;
  NHD creeks/ponds; click for elevation readout. 5-mile option removed (3 mi is enough).
- `samples/` has screenshots from the first session.
- Chris is fine with the site being public (public data); he'll make the house location less obvious himself.
- Plan: host on **Vercel Hobby** (free, static, `npx vercel --prod`), probably via a GitHub repo.
- Chris will rework the UI menu later.

## Next task: bundle the data so the site doesn't depend on kyraster.ky.gov at runtime
Right now every visitor's browser pulls data live from:
- `https://kyraster.ky.gov/arcgis/rest/services/...` (ArcGIS ImageServer `exportImage`, bbox in EPSG:3857)
  - elevation: `ElevationServices/Ky_DEM_KYAPED_5FT_WGS84WM` and `ElevationServices/Ky_DSM_First_Return_2FT_Phase2`
    as `format=bsq&pixelType=F32` (n×n float32 values, then a trailing no-data bitmask of n×n/8 bytes)
  - photos / land cover / hillshade: the layer lists in `SERIES` and `reliefTex()` in index.html
- `https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/{6,12}/query` (creeks, ponds as GeoJSON)

Goal: a script on the Mac (shell needs network access to those two hosts) that downloads everything for the
1 mi and 3 mi boxes into `data/` (elevation as compressed binary or 16-bit PNG, images as JPEG/WebP, water as GeoJSON),
then switch index.html to load from `data/` (falling back to live servers if a file is missing). Target ≲ 50 MB.
Then deploy to Vercel.

## Update (Nov 25, later): bundling built, waiting on the download
- Neither Claude's cloud workspace nor the Mac sandbox shell can reach kyraster.ky.gov / hydro.nationalmap.gov
  (egress allowlist), so the download runs in Chris's own Terminal.
- `scripts/fetch_data.py` (stdlib + curl only): downloads everything for the 1 mi and 3 mi boxes into `data/_raw/`
  (resumable; box and layer lists are read from index.html).
- `scripts/build_data.py` (Pillow + numpy; Claude can run it in the sandbox shell): writes `data/area-{1,3}/`
  with manifest.json, dem.bin / canopy.bin (gzip, delta-coded 16-bit ground + 8-bit canopy), WebP photos, PNG land cover,
  relief.webp, water.json. Blank years are marked false in the manifest.
- index.html now loads from `data/area-N/` when its manifest's bbox matches, falling back per file to the live servers.
  The leftover 5-mile button was removed. Added vercel.json (1-day cache on /data), .vercelignore (skips _raw, samples, scripts), .gitignore.
- Next: run fetch, then build, check total size (target ≲ 50 MB, tune with `--q` / `--q-big`), test, deploy.

## Update 2 (Nov 25): 3-mile only, much bigger download
- Chris: the map is always the 3-mile view. Add property lines, sharper ground, roads/buildings/fences/fields,
  newer photos, soils, floodplain, wetlands.
- fetch_data.py rewritten (53 downloads into data/_raw/area-3/): 2 ft lidar DEM at 4096 (Phase3, Phase2 backup) + 5 ft,
  2 ft first return at 2048; state photos + 2025 NOAA flood imagery; LINK-GIS county aerials 1962/1973/1989/1999/2023/2025/2026;
  LINK-GIS parcels (geometry only, no owner fields), buildings, road centerlines for Kenton/Campbell/Pendleton;
  NHD; FEMA NFHL layer 28 (KY portal copy as backup); NWI wetlands; SSURGO soils via Soil Data Access SQL; OSM via Overpass.
- build_data.py still targets the OLD raw layout: rewrite it against the real download, then the app work
  (new overlay views, 2048 terrain + lidar detail, drop the 1-mile button). Chris has app suggestions to fold in.

## Update 3 (Nov 25 evening): v1 live as a Claude artifact
- Live (private until Chris shares): https://claude.ai/artifact/JZWSfWNi99VV9tBon5mVND (slug 8e354d6c-47e0-4e07-bd2b-1c1a9670907e)
- build_data.py rewritten: data/area-3/ (~40 MB): base 1024 grid + 1-mile inset at 1.18 m from 2 ft lidar;
  grids are gzip stored as base64 .txt (artifacts don't serve .bin; old .bin files are leftovers, in .vercelignore);
  WebP photos incl. LINK-GIS 1962/1973/1989/2023/2025/2026 (1999 blank); overlays.json (parcels shapes only, buildings,
  roads w/ names, creeks/ponds, flood (KY copy), wetlands, soils) in Mercator metres from the house.
- index.html rewritten: 3 mi only, base grid with shader hole + fine inset grid, layer toggles, tap readout
  (ground/tree height, soil, flood zone, wetland, parcel acres), opens with Madison Pike up (ROAD=3.7°), compass toggles
  road-up / north-up, phones halve the inset grid. No live-server fallback anymore.
- Tested headless (Chrome + SwiftShader): loads in ~16 s, readout works, no console errors.
- Next: sharper inset photos (1-mile square at 4096 px) need kyraster.ky.gov + maps.linkgis.org (+ overpass-api.de)
  allowed in claude.ai Settings > Capabilities, or a Terminal run on the Mac; build picks up raw files named inset-<raw>.
  Then Vercel (GitHub repo + import), optional.

## Update 4 (Nov 25, ~5:30pm ET): v2 republished (artifact version 1795645714-f912)
- Photos rebuilt clearer: WebP q80 (2048) / q76 (4096) + light unsharp mask (data/area-3 now ~58 MB).
- New: 3D buildings (county footprints extruded to lidar roof height, on bare ground; 11 ft where lidar shows none),
  road + creek names drawn along the lines (roads on by default), Slope map (with legend), crisp farm close-up
  textures for Topo/Slope from the 1.2 m lidar, "Go to: Whole 3 miles / The farm, up close" buttons.
- Sharper close-up PHOTOS still pending: fetch_data.py now also fetches inset-*.img (15 layers, 1-mile square at 4096 px)
  + retries OSM/FEMA. Needs Chris's Mac network: double-click "Update Morning Viewer data.command" in this folder,
  or allow kyraster.ky.gov / maps.linkgis.org / overpass-api.de in claude.ai Settings > Capabilities. Then run
  build_data.py (sandbox) and republish (inset photos are wired in the app already via manifest.inset.layers).

## Update 5 (Nov 25, ~5:30pm CT): farm close-up photos live (artifact version 1795649427-acc0)
- Chris ran the fetch on his Mac. Farm close-up (1-mile square) now has 13 photo years at 4096 px (~0.4 m/px);
  KyFromAbove 3-inch also at 8192 px (~0.2 m/px) for desktops (BIG = maxTextureSize>=8192 && fine pointer).
  County 2025/2026 8k copies were built but dropped (no visible gain; KEEP_8K in build_data.py; in .vercelignore).
  1962 has a gap over the farm, so it has no close-up. NOAA 2025 flood imagery doesn't cover the area.
- build_data.py is now resumable: `--budget 105` stops starting new images after N s and exits 3; re-run to continue
  (the Mac sandbox shell kills background jobs and caps calls at 180 s). Outputs newer than their raw inputs are skipped.
- OSM: 234 driveways/service roads, 2 tracks, 54 field/wood outlines, no fences -> layer "Driveways & tracks".
  FEMA NFHL now downloaded (same zones as the KY copy).
- App: opens on the farm close-up (road-up), phones start with the panel folded, cache limit 3 on desktops,
  link-preview thumbnail (thumb.jpg).
- Data to deploy (excluding .bin and unused 8k) is ~107 MB: over Vercel Hobby's documented 100 MB CLI upload cap,
  so for Vercel either drop some inset years or deploy via GitHub (git LFS not needed; largest file ~14 MB).

## Update 6 (Nov 25, ~5:45pm CT): simplified app (artifact version 1795650294-e161)
- Chris asked to simplify. One switch: Today / Topo / Slope / History.
  Today = 2026 county photo + trees (first-return surface) + 3D buildings. Topo/Slope = bare earth + buildings.
  History = one timeline, one photo per year (sharper flight wins when two share a year), 1962 -> 2026, bare earth,
  no buildings; slider starts at 2026, play runs oldest -> newest. Phase 2 labelled 2019–22 (from its metadata).
- Removed: tree toggle, isometric camera, height boost (fixed EX=2), pixel art, sun slider (fixed SW), orbit,
  photo sets, land cover, lidar relief, flat buildings layer, 3D buildings toggle. Layers left: roads, creeks,
  property lines, driveways, floodplain, wetlands, soils. Go-to: The farm / Whole 3 miles. Compass stays.
- SERIES summer/hires/nlcd lines kept in index.html because fetch_data.py parses them.
- Unused files still in data/area-3 (NLCD PNGs, relief.webp, county 8k): fine to leave out of a Vercel deploy.

## Update 7 (Nov 25, ~5:55pm CT): trees removed (artifact version 1795650813-2f39)
- Chris: trees were slow and ugly. Surface is always bare earth now; heights() runs once at start. Canopy data still
  drives 3D building heights and the tap readout (trees/roof ft).

## Update 8 (Nov 25, ~6:05pm CT): 3D trees, pin 13299 (artifact version 1795651646-7fec)
- Pin label is the house number 13299.
- Trees: build_data.py finds lidar treetops (5x5 local max >= 15 ft on the 1.2 m close-up grid; 3x3 on the 4.7 m grid
  elsewhere; building footprints masked out) -> data/area-3/trees.txt (gzip int16 x,z dm + height 0.1 ft, base64).
  9,332 close-up + 39,616 elsewhere. App draws them as instanced low-poly crowns (+ trunks near the farm on desktop),
  Today view only. Phones: low-detail crowns, half the outer trees.
- Wetlands layer removed (readout line too). Driveways always drawn (no toggle).

## Update 9 (Nov 25, ~6:10pm CT, from a separate chat): turning without a right mouse button
- Chris's Mac trackpad couldn't right-drag. Added to index.html (on disk only, NOT yet republished to the artifact):
  Orbit button (controls.autoRotate, speed .5, stops on any pointerdown), ⟲ ⟳ buttons + Q/E keys (eased 45° turns
  via face()), O key toggles orbit, sideways two-finger trackpad swipe spins (capture-phase wheel listener ahead of
  MapControls; vertical scroll still zooms). Shift/Cmd+drag already rotated (built into MapControls). Hint text updated.
  Buttons sit in #turn above the compass. Syntax-checked but not yet tested in a browser; please keep it when editing.

## Update 9 (Nov 25, ~6:30pm CT): controls polish (artifact version 1795653062-1a3d)
- House tag removed entirely. Tap marker is an HTML pin (dot + pulsing ring) instead of a 3D cylinder.
- Trees are a layer (on by default; hidden in History). Spin 360° button (autoRotate, ~100 s per turn, frame-rate independent).
- Mac turning: sideways two-finger swipe (wheel deltaX) turns; shift-drag; arrow keys turn/tilt; hold ⟲ ⟳ buttons;
  Safari rotate gesture.

## Update 10 (Nov 25, ~7:45pm CT): shipping
- Chris will create the GitHub repo himself ("morning viewer") and push from Terminal; then import on Vercel (Git deploy;
  the 100 MB Hobby limit only applies to CLI uploads). Assumed a PRIVATE repo. Added README.md and a fuller .gitignore
  (data/_raw with owner names, .bin leftovers, unused county 8k, build.log).

## Update 11 (Nov 25, ~8pm CT): renamed to Morning Viewer
- Display name "Morning Viewer" (tab, header, preview image, artifact title); folder ~/dev/morningViewer; GitHub repo
  morningViewer (Vercel lowercases project names: morningviewer); launcher "Update Morning Viewer data.command".

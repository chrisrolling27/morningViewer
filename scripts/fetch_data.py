#!/usr/bin/env python3
"""
Morning Viewer data, step 1 of 2: download everything the page needs into data/_raw/area-3/.

Run it in Terminal from the morningViewer folder:

    python3 scripts/fetch_data.py

It uses only the Python that comes with macOS, plus curl. You can run it again safely:
files it already has are skipped, so a second run only retries what failed.
(To start over, delete data/_raw.) The raw download is large (a few hundred MB) but stays
on your Mac; step 2, scripts/build_data.py, shrinks it into what the website ships.

The box around the house and the state photo / land-cover lists are read from index.html.

Sources
  kyraster.ky.gov         Kentucky lidar (2 ft and 5 ft bare earth, 2 ft first return), state photos,
                          NLCD land cover, lidar hillshade
  maps.linkgis.org        Northern Kentucky county GIS: aerials (1962-2026), parcels, buildings, road centerlines
  hydro.nationalmap.gov   USGS creeks and ponds (NHD)
  hazards.fema.gov        FEMA flood zones (Kentucky's copy on kygisportalservices.ky.gov as a backup)
  fwspublicservices.wim.usgs.gov   US Fish & Wildlife National Wetlands Inventory
  sdmdataaccess.sc.egov.usda.gov   USDA soil survey (SSURGO)
  overpass-api.de         OpenStreetMap: driveways, farm tracks, fences, field and woods outlines
"""
import concurrent.futures as cf
import json
import math
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, 'data', '_raw')
AREA = 3                         # miles per side; the map is always the 3-mile square
G_HI, G, TEX = 4096, 2048, 4096  # 2 ft lidar grid, first-return grid, photo size
KY = 'https://kyraster.ky.gov/arcgis/rest/services/'
LINK = 'https://maps.linkgis.org/server/rest/services/'
NHD = 'https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/'
FEMA = 'https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28'
KY_FLOOD = 'https://kygisportalservices.ky.gov/server/rest/services/EconDev/KY_NFHL_Flood_Hazard_Zones/MapServer/1'
NWI = 'https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0'
SDA = 'https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest'
OVERPASS = 'https://overpass-api.de/api/interpreter'

# Extra photo layers beyond the lists in index.html. Years that don't cover the farm are dropped by build_data.py.
KY_EXTRA = [('Ky_NOAA_2025_April_Post_Flood_Imagery', '2025 (April flood)')]
LINK_AERIALS = [  # (map service, year, layers to hide, e.g. a watermark)
    ('Archive_Aerials/ArchiveAerial_1962', '1962', '0'),
    ('Archive_Aerials/ArchiveAerial_1973', '1973', '0'),
    ('Archive_Aerials/ArchiveAerial_1989', '1989', '0'),
    ('Archive_Aerials/ArchiveAerial_1999', '1999', '0'),
    ('Basemaps/AerialBase_2023', '2023', ''),
    ('Basemaps/AerialBase_2025_HighScale_CC_KC_PC', '2025', ''),
    ('Basemaps/AerialBase_2026_HighScale_CC_KC', '2026', ''),
]
COUNTIES = ['kenton', 'campbell', 'pendleton']
PARCELS = {'kenton': 13, 'campbell': 7, 'pendleton': 18}    # CC_KC_PCTheme layers
BUILDINGS = {'kenton': 1, 'campbell': 3, 'pendleton': 5}    # Buildings layers
ROADS = {'kenton': 63, 'campbell': 62, 'pendleton': 64}     # Street_Centerlines layers
PAGE = 500
INSET_SUMMERS = ['2020', '2022']
SHARPEST = ['linkgis:Basemaps/AerialBase_2026_HighScale_CC_KC', 'linkgis:Basemaps/AerialBase_2025_HighScale_CC_KC_PC',
            'ImageServices/Ky_KYAPED_Phase3_3IN']   # also fetched at 8192 px for the farm close-up   # summer photos also fetched sharper for the farm close-up


# ---------------------------------------------------------------- where
def page_config():
    """Read the house location and the photo / land-cover layer lists out of index.html."""
    src = open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
    m = re.search(r'FARM=\{lat:(-?[\d.]+),lon:(-?[\d.]+)\}', src)
    if not m:
        sys.exit("Couldn't find FARM={lat:...,lon:...} in index.html")
    series = {}
    for key in ('summer', 'hires', 'nlcd'):
        line = re.search(r'^\s*' + key + r':mk\(\[(.*)$', src, re.M)
        layers = re.findall(r"\['([A-Za-z0-9_]+)','([^']+)'\]", line[1]) if line else []
        if not layers:
            sys.exit("Couldn't find the '%s' layer list in index.html" % key)
        series[key] = layers
    return float(m[1]), float(m[2]), series


def bbox(lat, lon, miles):
    """Same maths as index.html: a square of `miles` per side, centred on the house, in Web Mercator metres."""
    R = 6378137
    cos_l = math.cos(lat * math.pi / 180)
    cx = R * lon * math.pi / 180
    cy = R * math.log(math.tan(math.pi / 4 + lat * math.pi / 360))
    hm = miles * 1609.34 / 2 / cos_l
    return [cx - hm, cy - hm, cx + hm, cy + hm]


def to_lonlat(x, y):
    R = 6378137
    return x / R * 180 / math.pi, (2 * math.atan(math.exp(y / R)) - math.pi / 2) * 180 / math.pi


# ---------------------------------------------------------------- what
def plan(lat, lon, series):
    box = bbox(lat, lon, AREA)
    bb = ','.join('%.2f' % v for v in box)
    (w, s), (e, n) = to_lonlat(box[0], box[1]), to_lonlat(box[2], box[3])
    jobs = []
    info = {'area': AREA, 'lat': lat, 'lon': lon, 'bbox': box, 'G_HI': G_HI, 'G': G, 'TEX': TEX,
            'photos': [], 'vectors': {}}

    def img(svc, n, extra):
        return (KY + svc + '/ImageServer/exportImage?bbox=' + bb + '&bboxSR=3857&imageSR=3857'
                + '&size=%d,%d&f=image' % (n, n) + extra)

    def f32(name, svc, n):
        jobs.append((name, 'get', img(svc, n, '&format=bsq&pixelType=F32&interpolation=RSP_BilinearInterpolation'),
                     ('f32', n)))

    # elevation: 2 ft bare earth (Phase 3, Phase 2 as backup), 5 ft bare earth (backup), 2 ft first return
    f32('dem-2ft-p3.f32', 'ElevationServices/Ky_DEM_KYAPED_2FT_Phase3_WGS84WM', G_HI)
    f32('dem-2ft-p2.f32', 'ElevationServices/Ky_DEM_KYAPED_2FT_Phase2_WGS84WM', G_HI)
    f32('dem-5ft.f32', 'ElevationServices/Ky_DEM_KYAPED_5FT_WGS84WM', 1024)
    f32('dsm-2ft.f32', 'ElevationServices/Ky_DSM_First_Return_2FT_Phase2', G)
    info['dem'] = {'dem-2ft-p3.f32': G_HI, 'dem-2ft-p2.f32': G_HI, 'dem-5ft.f32': 1024}
    info['dsm'] = 'dsm-2ft.f32'

    # state photos and land cover (lists from index.html), plus extras
    sizes = {'summer': 2048, 'hires': TEX, 'nlcd': 512}
    for key, items in list(series.items()) + [('hires', KY_EXTRA)]:
        nearest = key == 'nlcd'
        for name, year in items:
            svc = 'ImageServices/' + name
            extra = ('&format=png&interpolation=RSP_NearestNeighbor' if nearest
                     else '&format=jpgpng&compressionQuality=92')
            jobs.append((name + '.img', 'get', img(svc, sizes[key], extra), ('img',)))
            info['photos'].append({'key': key, 'svc': svc, 'year': year, 'raw': name + '.img', 'nearest': nearest})

    # county aerials (these are map services, so "export" instead of "exportImage")
    for path, year, hide in LINK_AERIALS:
        raw = 'linkgis-' + path.split('/')[-1] + '.img'
        u = (LINK + path + '/MapServer/export?bbox=' + bb + '&bboxSR=3857&imageSR=3857&size=%d,%d' % (TEX, TEX)
             + '&format=jpg&transparent=false&f=image' + ('&layers=hide:' + hide if hide else ''))
        jobs.append((raw, 'get', u, ('img',)))
        info['photos'].append({'key': 'county', 'svc': 'linkgis:' + path, 'year': year, 'raw': raw, 'nearest': False})

    # sharper photos of the 1-mile square around the house (the middle third of the 3-mile square, pixel-exact
    # with the lidar inset that build_data.py cuts), 4096 px across = about 0.4 m per pixel
    i0, i1 = round(G_HI / 3), round(2 * G_HI / 3)
    px = (box[2] - box[0]) / G_HI
    ib = ','.join('%.2f' % v for v in [box[0] + i0 * px, box[3] - i1 * px, box[0] + i1 * px, box[3] - i0 * px])
    for ph in list(info['photos']):
        if ph['key'] == 'nlcd' or (ph['key'] == 'summer' and ph['year'] not in INSET_SUMMERS) or ph['year'] == '1999':
            continue
        if ph['svc'].startswith('linkgis:'):
            path, hide = ph['svc'][8:], ('&layers=hide:0' if 'Archive' in ph['svc'] else '')
            u = (LINK + path + '/MapServer/export?bbox=' + ib + '&bboxSR=3857&imageSR=3857&size=%d,%d' % (TEX, TEX)
                 + '&format=jpg&transparent=false&f=image' + hide)
        else:
            u = (KY + ph['svc'] + '/ImageServer/exportImage?bbox=' + ib + '&bboxSR=3857&imageSR=3857'
                 + '&size=%d,%d&f=image&format=jpgpng&compressionQuality=92' % (TEX, TEX))
        jobs.append(('inset-' + ph['raw'], 'get', u, ('img',), 'optional'))
        # extra-sharp (8192 px, ~0.2 m per pixel) copies of the best recent photos, fetched as 2 x 2 tiles of 4096
        if ph['svc'] in SHARPEST:
            b4 = [float(v) for v in ib.split(',')]
            mx, my = (b4[0] + b4[2]) / 2, (b4[1] + b4[3]) / 2
            for r, (ya, yb) in enumerate([(my, b4[3]), (b4[1], my)]):        # row 0 = north half
                for c, (xa, xb) in enumerate([(b4[0], mx), (mx, b4[2])]):    # col 0 = west half
                    tb = '%.2f,%.2f,%.2f,%.2f' % (xa, ya, xb, yb)
                    jobs.append(('inset8k-%d%d-%s' % (r, c, ph['raw']), 'get', u.replace('bbox=' + ib, 'bbox=' + tb),
                                 ('img',), 'optional'))
    info['inset_bbox'] = [float(v) for v in ib.split(',')]

    # lidar hillshade for the "Lidar relief" view
    info['relief'] = []
    for i, svc in enumerate(['ElevationServices/Ky_DEM_KYAPED_2FT_Phase3_MultiDirectionalHillshade',
                             'ElevationServices/Ky_DEM_KYAPED_5FT_MultiDirectionalHillshade']):
        jobs.append(('relief-%d.img' % i, 'get', img(svc, TEX, '&format=jpgpng&compressionQuality=92'), ('img',)))
        info['relief'].append('relief-%d.img' % i)

    # vector layers from ArcGIS servers, cut to the box (fetched in pages)
    def query(layer_url, fields):
        return (layer_url + '/query?geometry=' + bb + '&geometryType=esriGeometryEnvelope&inSR=3857&outSR=3857'
                '&spatialRel=esriSpatialRelIntersects&outFields=' + fields
                + '&returnGeometry=true&geometryPrecision=2&f=geojson')

    def feat(group, name, layer_url, fields='*', optional=False):
        jobs.append((name, 'paged', query(layer_url, fields), ('json',)) + (('optional',) if optional else ()))
        info['vectors'].setdefault(group, []).append(name)

    feat('water', 'nhd-6.json', NHD + '6', 'gnis_name')
    feat('water', 'nhd-12.json', NHD + '12', 'gnis_name')
    for c in COUNTIES:  # shapes only (empty outFields): never owner names or addresses
        feat('parcels', 'parcels-%s.json' % c, LINK + 'CC_KC_PCTheme/MapServer/%d' % PARCELS[c], '')
        feat('buildings', 'buildings-%s.json' % c, LINK + 'Buildings/MapServer/%d' % BUILDINGS[c], '')
        feat('roads', 'roads-%s.json' % c, LINK + 'Street_Centerlines/MapServer/%d' % ROADS[c])
    # flood zones: either source is enough (main() checks that at least one arrived)
    feat('flood', 'flood-fema.json', FEMA, 'FLD_ZONE,ZONE_SUBTY,SFHA_TF', optional=True)
    feat('flood', 'flood-ky.json', KY_FLOOD, '*', optional=True)
    feat('wetlands', 'wetlands.json', NWI)

    # soils: SQL against USDA Soil Data Access, clipped to the box (lon/lat)
    poly = 'POLYGON((%f %f, %f %f, %f %f, %f %f, %f %f))' % (w, s, e, s, e, n, w, n, w, s)
    sql = ("SELECT mp.mukey, mu.musym, mu.muname, mu.farmlndcl, ma.drclassdcd, ma.hydclprs, "
           "mp.mupolygongeo.STIntersection(geometry::STGeomFromText('%s', 4326)).STAsText() AS wkt "
           "FROM mupolygon mp JOIN mapunit mu ON mu.mukey = mp.mukey LEFT JOIN muaggatt ma ON ma.mukey = mp.mukey "
           "WHERE mp.mupolygongeo.STIntersects(geometry::STGeomFromText('%s', 4326)) = 1") % (poly, poly)
    jobs.append(('soils.json', 'post-json', (SDA, {'query': sql, 'format': 'JSON+COLUMNNAME'}), ('json',)))
    info['vectors']['soils'] = ['soils.json']

    # OpenStreetMap: roads incl. driveways and farm tracks, buildings, fences/hedges/gates, fields, woods
    b = '({s},{w},{n},{e})'.format(s=s, w=w, n=n, e=e)
    oq = ('[out:json][timeout:180];(way["highway"]%s;way["building"]%s;way["barrier"]%s;node["barrier"="gate"]%s;'
          'way["landuse"]%s;way["natural"]%s;way["leisure"]%s;);out geom;') % ((b,) * 7)
    jobs.append(('osm.json', 'post-form', (OVERPASS, {'data': oq}), ('json',)))
    info['vectors']['osm'] = ['osm.json']
    return jobs, info


# ---------------------------------------------------------------- how
def looks_ok(path, check):
    """Servers sometimes answer an error with HTTP 200, so check the bytes are what we asked for."""
    size = os.path.getsize(path)
    head = open(path, 'rb').read(16)
    if check[0] == 'f32':
        return size >= check[1] * check[1] * 4 and not head.startswith(b'{')
    if check[0] == 'img':
        return head.startswith(b'\xff\xd8') or head.startswith(b'\x89PNG')
    try:
        j = json.load(open(path, encoding='utf-8'))
        return isinstance(j, dict) and 'error' not in j
    except ValueError:
        return False


def curl(out, url, post=None, form=None):
    cmd = ['curl', '-fsS', '--retry', '3', '--retry-delay', '5', '--connect-timeout', '20', '--max-time', '600',
           '-A', 'morning-viewer-fetch/1 (personal family map)', '-o', out]
    if post is not None:
        cmd += ['-H', 'Content-Type: application/json', '--data-binary', json.dumps(post)]
    if form is not None:
        for k, v in form.items():
            cmd += ['--data-urlencode', k + '=' + v]
    r = subprocess.run(cmd + [url], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return r.returncode == 0, r.stderr.strip()


def fetch_paged(tmp, url):
    """ArcGIS feature query, PAGE records at a time, merged into one GeoJSON file."""
    feats, seen = [], set()
    for page in range(60):
        ok, err = curl(tmp, url + '&resultOffset=%d&resultRecordCount=%d' % (page * PAGE, PAGE))
        if not ok:
            return False, err
        try:
            j = json.load(open(tmp, encoding='utf-8'))
        except ValueError:
            return False, 'not JSON'
        if 'error' in j:
            return False, json.dumps(j['error'])[:200]
        fs = j.get('features') or []
        key = json.dumps(fs[0].get('geometry'))[:300] if fs else None
        if key in seen:  # server ignored the offset and sent the same page again
            break
        seen.add(key)
        feats += fs
        more = j.get('exceededTransferLimit') or (j.get('properties') or {}).get('exceededTransferLimit')
        if len(fs) < PAGE and not more:
            break
    json.dump({'type': 'FeatureCollection', 'features': feats}, open(tmp, 'w'))
    return True, ''


def run(folder, job):
    name, kind, spec, check = job[:4]
    optional = len(job) > 4
    dest = os.path.join(folder, name)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return name, 'had it', False
    tmp = dest + '.part'
    if kind == 'get':
        ok, err = curl(tmp, spec)
    elif kind == 'paged':
        ok, err = fetch_paged(tmp, spec)
    elif kind == 'post-json':
        ok, err = curl(tmp, spec[0], post=spec[1])
    else:
        ok, err = curl(tmp, spec[0], form=spec[1])
    if not ok or not os.path.exists(tmp) or not looks_ok(tmp, check):
        if os.path.exists(tmp):
            os.remove(tmp)
        why = (err or 'unexpected reply')[:160]
        return name, ('not available (optional): ' if optional else 'FAILED ') + why, not optional
    os.replace(tmp, dest)
    extra = ''
    if check[0] == 'json':
        j = json.load(open(dest, encoding='utf-8'))
        extra = ', %d features' % len(j.get('features') or j.get('elements') or j.get('Table') or [])
    return name, '%.1f MB%s' % (os.path.getsize(dest) / 1e6, extra), False


def main():
    lat, lon, series = page_config()
    jobs, info = plan(lat, lon, series)
    folder = os.path.join(RAW, 'area-%d' % AREA)
    os.makedirs(folder, exist_ok=True)
    json.dump(info, open(os.path.join(folder, 'fetch.json'), 'w'), indent=1)
    print('House at %.6f, %.6f · %d-mile box · %d downloads (the big lidar grids take a minute or two each)\n'
          % (lat, lon, AREA, len(jobs)))
    failed = 0
    with cf.ThreadPoolExecutor(4) as pool:
        for f in cf.as_completed([pool.submit(run, folder, j) for j in jobs]):
            name, msg, bad = f.result()
            failed += bad
            print('  %-46s %s' % (name, msg), flush=True)
    if not any(os.path.exists(os.path.join(folder, f)) for f in info['vectors']['flood']):
        print('  Neither flood-zone source answered.')
        failed += 1
    total = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(RAW) for f in fs)
    print('\nRaw download: %.0f MB in data/_raw' % (total / 1e6))
    if failed:
        print('%d download(s) failed. Run this again to retry just those.' % failed)
        sys.exit(1)
    print('All done. Next step: scripts/build_data.py (Claude can run that part).')


if __name__ == '__main__':
    main()

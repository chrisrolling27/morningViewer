#!/usr/bin/env python3
"""
Morning Viewer data, step 2 of 2: turn data/_raw/area-3/ (from fetch_data.py) into the compact
files the page loads, in data/area-3/.

    python3 scripts/build_data.py            # needs Pillow and numpy; no network

What it writes (data/area-3/):
  manifest.json      which files exist, how the elevation is packed, the exact boxes they cover
  dem.txt            3-mile ground, 1024 x 1024, from the 2 ft lidar (gzip of 16-bit steps of 0.05 ft,
                     each stored as the change from the previous value so it compresses well; base64 text)
  canopy.txt         3-mile tree / roof height (first return minus ground), 8-bit, 0.6 ft steps
  inset-dem.txt      the 1-mile square around the house at full download detail (~1.2 m spacing)
  inset-canopy.txt   same for trees / roofs
  *.webp / *.png     photos (WebP), land cover (PNG, exact colours), lidar hillshade
  inset-*.webp       sharper photos of the 1-mile square, when data/_raw has them
  overlays.json      property lines, buildings, roads, creeks, ponds, flood zones, wetlands, soils,
                     in metres from the house (Web Mercator). Shapes only: no owner names or addresses.
Photo years that don't cover the farm (blank or all white) are left out.
"""
import argparse
import base64
import datetime
import gzip
import json
import math
import os
import re

import numpy as np
from PIL import Image, ImageFilter

Image.MAX_IMAGE_PIXELS = None
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'data', '_raw', 'area-3')
DST = os.path.join(ROOT, 'data', 'area-3')
DEM_STEP, CANOPY_STEP, CANOPY_MAX = 0.05, 0.6, 130   # feet
G_BASE = 1024
# 8192 px farm close-ups are only worth their size where the source is sharper than ~0.4 m (the 3-inch state flight);
# the county's 2025/2026 photos look the same at 4096
KEEP_8K = ['ImageServices/Ky_KYAPED_Phase3_3IN']
R = 6378137


# ---------------------------------------------------------------- helpers
def blank(im):
    """Mostly transparent, black or white when shrunk to 16 x 16 = this year doesn't cover the farm."""
    a = np.asarray(im.convert('RGBA').resize((16, 16), Image.BILINEAR)).astype(int)
    s = a[..., :3].sum(-1)
    return int(((a[..., 3] < 20) | (s < 12) | (s > 750)).sum()) > 100


T0 = __import__('time').time()
BUDGET = [None]   # seconds; when set, stop starting new images after this long (the next run carries on)


class OutOfTime(Exception):
    pass


def fresh(out, *srcs):
    """True if `out` exists and is newer than every source, so it needn't be encoded again."""
    return os.path.exists(out) and all(os.path.getmtime(out) > os.path.getmtime(s) for s in srcs if os.path.exists(s))


def save_photo(im, path, q, lossless=False, sharpen=True):
    if BUDGET[0] and __import__('time').time() - T0 > BUDGET[0]:
        raise OutOfTime()
    im = im.convert('RGB')
    if lossless:
        im.save(path, 'PNG', optimize=True)
        return
    if sharpen:  # light unsharp mask: undoes some of the softening from resampling, without halos
        im = im.filter(ImageFilter.UnsharpMask(radius=1.4, percent=55, threshold=2))
    im.save(path, 'WEBP', quality=q, method=6)


def read_f32(path, n):
    with open(path, 'rb') as f:
        a = np.frombuffer(f.read(n * n * 4), dtype='<f4').astype(np.float64)
    return a.reshape(n, n)


def write_dem(dem, name):
    base = math.floor(dem.min())
    q = np.round((dem - base) / DEM_STEP).astype(np.int64).ravel()
    if q.max() >= 65536:
        raise ValueError('elevation range too large for 16 bits')
    d = (np.diff(q, prepend=0) % 65536).astype('<u2')
    put(name, gzip.compress(d.tobytes(), 9, mtime=0))
    return {'file': name, 'base': base, 'step': DEM_STEP, 'n': dem.shape[0]}


def write_canopy(can, name):
    u = np.round(np.clip(can, 0, CANOPY_MAX) / CANOPY_STEP).astype('u1')
    put(name, gzip.compress(u.tobytes(), 9, mtime=0))
    return {'file': name, 'step': CANOPY_STEP}


def put(name, data):
    """Binary grids are stored as base64 text (.txt) so any static host, including Claude artifacts, serves them."""
    open(os.path.join(DST, name), 'w').write(base64.b64encode(data).decode())


def clean(dem, dsm):
    good = dem > 1
    dem = dem.copy()
    dem[~good] = dem[good].min()
    can = dsm - dem
    can[~(can >= 0)] = 0
    return dem, np.minimum(can, CANOPY_MAX)


# ---------------------------------------------------------------- trees
def peaks(c, win, thr):
    """Treetops: cells at least `thr` ft tall that are the highest within a win x win window."""
    pad = win // 2
    c = c + np.random.default_rng(1).random(c.shape) * 1e-3   # break ties on flat canopy
    P = np.pad(c, pad, mode='edge')
    m = np.full(c.shape, -1.0)
    for dy in range(win):
        for dx in range(win):
            m = np.maximum(m, P[dy:dy + c.shape[0], dx:dx + c.shape[1]])
    return (c >= m) & (c >= thr)


def building_mask(n, box, px):
    """Building footprints rasterised on the n x n lidar grid (so no 'trees' are placed on roofs), grown by ~2 cells."""
    from PIL import ImageDraw
    im = Image.new('L', (n, n), 0)
    d = ImageDraw.Draw(im)
    for c in ('kenton', 'campbell', 'pendleton'):
        for f in load('buildings-%s.json' % c):
            for ring in rings_of(f.get('geometry') or {'type': '', 'coordinates': []}):
                pts = [((x - box[0]) / px, (box[3] - y) / px) for x, y, *_ in ring]
                if len(pts) >= 3:
                    d.polygon(pts, fill=255)
    a = np.asarray(im) > 0
    g = a.copy()
    for dy in (-2, -1, 0, 1, 2):
        for dx in (-2, -1, 0, 1, 2):
            g |= np.roll(np.roll(a, dy, 0), dx, 1)
    return g


def build_trees(can, box, i0, i1, cx, cy, cos_l):
    """Individual trees for the 3D view: fine detail in the farm close-up, coarser across the rest.
    Written as gzip'd int16 triplets (x, z in decimetres of ground east/south of the house; height in 0.1 ft)."""
    n = can.shape[0]
    px = (box[2] - box[0]) / n
    mask = building_mask(n, box, px)
    can = np.where(mask, 0, can)
    out = []
    ins = peaks(can[i0:i1, i0:i1], 5, 15)                       # ~6 m apart in the close-up
    r, c = np.nonzero(ins)
    out.append((r + i0, c + i0, can[i0:i1, i0:i1][r, c], 1))
    k = 4
    cb = can.reshape(n // k, k, n // k, k).max((1, 3))
    bp = peaks(cb, 3, 15)                                        # ~14 m apart elsewhere
    b0, b1 = i0 // k, -(-i1 // k)
    bp[b0:b1, b0:b1] = False                                     # the close-up has its own
    r, c = np.nonzero(bp)
    out.append((r * k + k / 2, c * k + k / 2, cb[r, c], k))
    arrs = []
    for rr, cc, h, _ in out:
        X = box[0] + (cc + .5) * px
        Y = box[3] - (rr + .5) * px
        arrs.append(np.stack([np.round((X - cx) * cos_l * 10), np.round(-(Y - cy) * cos_l * 10), np.round(h * 10)], 1))
    a = np.concatenate(arrs).astype('<i2')
    put('trees.txt', gzip.compress(a.tobytes(), 9, mtime=0))
    return {'file': 'trees.txt', 'inset': int(len(arrs[0])), 'base': int(len(arrs[1]))}


# ---------------------------------------------------------------- vectors
def clip_ring(ring, box):
    """Sutherland-Hodgman: clip one polygon ring to an axis-aligned box."""
    x0, y0, x1, y1 = box
    for edge in range(4):
        out = []
        if not ring:
            break
        def inside(p):
            return [p[0] >= x0, p[0] <= x1, p[1] >= y0, p[1] <= y1][edge]
        def cross(p, q):
            if edge < 2:
                x = x0 if edge == 0 else x1
                t = (x - p[0]) / (q[0] - p[0])
                return [x, p[1] + t * (q[1] - p[1])]
            y = y0 if edge == 2 else y1
            t = (y - p[1]) / (q[1] - p[1])
            return [p[0] + t * (q[0] - p[0]), y]
        prev = ring[-1]
        for cur in ring:
            if inside(cur):
                if not inside(prev):
                    out.append(cross(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cross(prev, cur))
            prev = cur
        ring = out
    return ring if len(ring) >= 3 else None


def rings_of(geom):
    t, c = geom['type'], geom['coordinates']
    if t == 'Polygon':
        return c
    if t == 'MultiPolygon':
        return [r for p in c for r in p]
    return []


def lines_of(geom):
    t, c = geom['type'], geom['coordinates']
    if t == 'LineString':
        return [c]
    if t == 'MultiLineString':
        return c
    return []


class Vec:
    def __init__(self, box, cx, cy):
        self.box, self.cx, self.cy = box, cx, cy
        pad = 50
        self.pbox = [box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad]

    def flat(self, pts):
        """[[x,y],...] Mercator -> flat [dx,dy,...] metres from the house, 0.1 m, near-duplicates dropped."""
        out, last = [], None
        for p in pts:
            q = (round(p[0] - self.cx, 1), round(p[1] - self.cy, 1))
            if last is None or abs(q[0] - last[0]) + abs(q[1] - last[1]) >= 0.3:
                out += q
                last = q
        return out

    def touches(self, pts):
        x0, y0, x1, y1 = self.pbox
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return not (max(xs) < x0 or min(xs) > x1 or max(ys) < y0 or min(ys) > y1)

    def polys(self, geom, clip):
        out = []
        for r in rings_of(geom):
            r = [p[:2] for p in r]
            if not r or not self.touches(r):
                continue
            if clip:
                r = clip_ring(r, self.pbox)
            if r:
                f = self.flat(r)
                if len(f) >= 6:
                    out.append(f)
        return out

    def lines(self, geom):
        return [self.flat([p[:2] for p in l]) for l in lines_of(geom) if l and self.touches(l)]


def load(name):
    p = os.path.join(SRC, name)
    return json.load(open(p)).get('features', []) if os.path.exists(p) else []


def wkt_rings(wkt):
    """All rings in a POLYGON / MULTIPOLYGON / GEOMETRYCOLLECTION WKT string (lon lat)."""
    rings = []
    for body in re.findall(r'\(([^()]+)\)', wkt or ''):
        pts = []
        for pair in body.split(','):
            v = pair.split()
            if len(v) >= 2:
                lon, lat = float(v[0]), float(v[1])
                pts.append([R * lon * math.pi / 180, R * math.log(math.tan(math.pi / 4 + lat * math.pi / 360))])
        if len(pts) >= 3:
            rings.append(pts)
    return rings


def build_overlays(box, cx, cy):
    V = Vec(box, cx, cy)
    out = {}
    out['parcels'] = [r for f in load('parcels-kenton.json') + load('parcels-campbell.json') + load('parcels-pendleton.json')
                      if f.get('geometry') for r in V.polys(f['geometry'], False)]
    out['buildings'] = [r for f in load('buildings-kenton.json') + load('buildings-campbell.json') + load('buildings-pendleton.json')
                        if f.get('geometry') for r in V.polys(f['geometry'], False)]
    roads = []
    for f in load('roads-kenton.json') + load('roads-campbell.json') + load('roads-pendleton.json'):
        if f.get('geometry'):
            p = f.get('properties') or {}
            name = (p.get('FULLNAME') or '').strip().title()
            roads += [{'n': name, 'c': l} for l in V.lines(f['geometry'])]
    out['roads'] = roads
    creeks = []
    for f in load('nhd-6.json'):
        if f.get('geometry'):
            p = f.get('properties') or {}
            creeks += [{'n': p.get('gnis_name') or p.get('GNIS_NAME') or '', 'c': l} for l in V.lines(f['geometry'])]
    out['creeks'] = creeks
    out['ponds'] = [r for f in load('nhd-12.json') if f.get('geometry') for r in V.polys(f['geometry'], True)]
    flood = []
    for f in load('flood-fema.json') or load('flood-ky.json'):
        if f.get('geometry'):
            p = f.get('properties') or {}
            rs = V.polys(f['geometry'], True)
            if rs:
                flood.append({'z': p.get('FLD_ZONE') or '', 's': p.get('ZONE_SUBTY') or '', 'r': rs})
    out['flood'] = flood
    wet = []
    for f in load('wetlands.json'):
        if f.get('geometry'):
            p = f.get('properties') or {}
            g = lambda k: p.get(k) or p.get('Wetlands.' + k) or ''
            rs = V.polys(f['geometry'], True)
            if rs:
                wet.append({'t': g('WETLAND_TYPE'), 'a': g('ATTRIBUTE'), 'r': rs})
    out['wetlands'] = wet
    soils = []
    sp = os.path.join(SRC, 'soils.json')
    if os.path.exists(sp):
        t = json.load(open(sp)).get('Table') or []
        cols = t[0] if t else []
        for row in t[1:]:
            d = dict(zip(cols, row))
            rs = []
            for ring in wkt_rings(d.get('wkt')):
                c = clip_ring(ring, V.pbox)
                if c:
                    f = V.flat(c)
                    if len(f) >= 6:
                        rs.append(f)
            if rs:
                soils.append({'n': d.get('muname') or '', 's': d.get('musym') or '', 'f': d.get('farmlndcl') or '',
                              'd': d.get('drclassdcd') or '', 'r': rs})
    out['soils'] = soils
    tracks, fences, fields = [], [], []
    op = os.path.join(SRC, 'osm.json')
    if os.path.exists(op):
        for el in json.load(open(op)).get('elements', []):
            t, geo = el.get('tags') or {}, el.get('geometry')
            if el.get('type') != 'way' or not geo:
                continue
            pts = [[R * g['lon'] * math.pi / 180, R * math.log(math.tan(math.pi / 4 + g['lat'] * math.pi / 360))] for g in geo]
            if not V.touches(pts):
                continue
            hw = t.get('highway')
            if hw in ('track', 'service', 'path', 'footway', 'bridleway', 'unclassified') and hw:
                tracks.append({'t': hw, 'n': t.get('name', ''), 'c': V.flat(pts)})
            elif t.get('barrier') in ('fence', 'wall', 'hedge', 'hedge_bank', 'retaining_wall'):
                fences.append({'t': t['barrier'], 'c': V.flat(pts)})
            elif t.get('landuse') in ('farmland', 'meadow', 'orchard', 'farmyard', 'grass') or t.get('natural') in ('wood', 'scrub'):
                if len(pts) > 3:
                    fields.append({'t': t.get('landuse') or t.get('natural'), 'c': V.flat(pts)})
    out['tracks'], out['fences'], out['fields'] = tracks, fences, fields
    json.dump(out, open(os.path.join(DST, 'overlays.json'), 'w'), separators=(',', ':'))
    return {k: len(v) for k, v in out.items()}


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--q', type=int, default=80, help='WebP quality for 2048 px photos')
    ap.add_argument('--q-big', type=int, default=76, help='WebP quality for 4096 px photos')
    ap.add_argument('--q-8k', type=int, default=72, help='WebP quality for the 8192 px farm close-ups')
    ap.add_argument('--budget', type=float, default=0, help='stop starting new images after this many seconds (resume by running again)')
    a = ap.parse_args()
    BUDGET[0] = a.budget or None
    info = json.load(open(os.path.join(SRC, 'fetch.json')))
    os.makedirs(DST, exist_ok=True)
    box = info['bbox']
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    man = {'version': 2, 'made': datetime.date.today().isoformat(), 'area': info['area'], 'bbox': box,
           'center': [cx, cy], 'layers': {}, 'inset': {}}

    # ---- elevation: best 2 ft grid with fewest gaps, then a 1024 base and a full-detail 1-mile inset
    n_hi = info['G_HI']
    best = None
    for f, n in info['dem'].items():
        p = os.path.join(SRC, f)
        if n == n_hi and os.path.exists(p):
            d = read_f32(p, n)
            if best is None or (d > 1).mean() > (best > 1).mean():
                best = d
    dsm = read_f32(os.path.join(SRC, info['dsm']), info['G'])
    up = n_hi // info['G']
    dsm_hi = np.repeat(np.repeat(dsm, up, 0), up, 1)
    dem, can = clean(best, dsm_hi)
    k = n_hi // G_BASE
    dem_b = dem.reshape(G_BASE, k, G_BASE, k).mean((1, 3))
    can_b = can.reshape(G_BASE, k, G_BASE, k).max((1, 3)) * 0.85  # tallest point in each cell, eased
    man['dem'] = write_dem(dem_b, 'dem.txt')
    man['canopy'] = write_canopy(can_b, 'canopy.txt')
    # inset: the middle third of the 3-mile square (= the 1-mile square around the house), pixel-exact
    i0, i1 = round(n_hi / 3), round(2 * n_hi / 3)
    px = (box[2] - box[0]) / n_hi
    ibox = [box[0] + i0 * px, box[3] - i1 * px, box[0] + i1 * px, box[3] - i0 * px]
    man['inset'] = {'bbox': ibox, 'dem': write_dem(dem[i0:i1, i0:i1], 'inset-dem.txt'),
                    'canopy': write_canopy(can[i0:i1, i0:i1], 'inset-canopy.txt'), 'layers': {}}
    man['trees'] = build_trees(can, box, i0, i1, cx, cy, math.cos(info['lat'] * math.pi / 180))
    print('trees      %d in the farm close-up, %d elsewhere' % (man['trees']['inset'], man['trees']['base']))
    print('elevation  ground %.0f-%.0f ft · base %d² · inset %d² at %.2f m' % (
        dem.min(), dem.max(), G_BASE, i1 - i0, px * math.cos(info['lat'] * math.pi / 180)))

    # ---- photos and land cover
    done = True
    try:
      for L in info['photos']:
          p = os.path.join(SRC, L['raw'])
          if not os.path.exists(p):
              continue
          name = re.sub(r'[^a-z0-9]+', '-', L['svc'].split('/')[-1].lower()).strip('-') + ('.png' if L['nearest'] else '.webp')
          im = Image.open(p)
          if blank(im):
              man['layers'][L['svc']] = False
              print('  %-50s blank here, left out' % L['svc'])
              continue
          if not fresh(os.path.join(DST, name), p):
              save_photo(im, os.path.join(DST, name), a.q_big if im.width > 2048 else a.q, L['nearest'])
          man['layers'][L['svc']] = name
          # sharper copy of the 1-mile square, if fetched (raw file "inset-<raw>")
          ip = os.path.join(SRC, 'inset-' + L['raw'])
          if os.path.exists(ip):
              iim = Image.open(ip)
              if not blank(iim):
                  if not fresh(os.path.join(DST, 'inset-' + name.replace('.png', '.webp')), ip):
                      save_photo(iim, os.path.join(DST, 'inset-' + name.replace('.png', '.webp')), a.q_big)
                  man['inset']['layers'][L['svc']] = 'inset-' + name.replace('.png', '.webp')
          # extra-sharp close-up: four 4096 tiles (inset8k-RC-<raw>) stitched into one 8192 image, for desktop browsers
          tiles = [os.path.join(SRC, 'inset8k-%d%d-%s' % (r, c, L['raw'])) for r in (0, 1) for c in (0, 1)]
          n8 = 'inset8k-' + name.replace('.png', '.webp')
          if L['svc'] not in KEEP_8K:
              pass
          elif all(os.path.exists(t) for t in tiles) and fresh(os.path.join(DST, n8), *tiles):
              man['inset'].setdefault('layers8k', {})[L['svc']] = n8
          elif all(os.path.exists(t) for t in tiles):
              big = Image.new('RGB', (8192, 8192))
              for t in tiles:
                  r, c = int(os.path.basename(t)[8]), int(os.path.basename(t)[9])
                  big.paste(Image.open(t).convert('RGB').resize((4096, 4096)), (c * 4096, r * 4096))
              if not blank(big):
                  save_photo(big, os.path.join(DST, n8), a.q_8k)
                  man['inset'].setdefault('layers8k', {})[L['svc']] = n8
          print('  %-50s %s%s%s' % (L['svc'], name, ' + inset' if L['svc'] in man['inset']['layers'] else '',
                                    ' + 8k' if L['svc'] in man['inset'].get('layers8k', {}) else ''))
    except OutOfTime:
        done = False
        print('  ... time budget used up; run again to carry on')
    for r in info['relief']:
        p = os.path.join(SRC, r)
        if os.path.exists(p):
            im = Image.open(p)
            im.load()
            if not blank(im):
                if not fresh(os.path.join(DST, 'relief.webp'), p):
                    BUDGET[0] = None
                    save_photo(im.convert('L'), os.path.join(DST, 'relief.webp'), a.q_big, sharpen=False)
                man['relief'] = 'relief.webp'
                break

    # ---- vectors
    counts = build_overlays(box, cx, cy)
    man['overlays'] = 'overlays.json'
    print('overlays  ', counts)

    json.dump(man, open(os.path.join(DST, 'manifest.json'), 'w'), indent=1)
    if not done:
        print('NOT FINISHED: run build_data.py again to encode the rest')
        raise SystemExit(3)
    total = sum(os.path.getsize(os.path.join(DST, f)) for f in os.listdir(DST))
    print('Total bundled data: %.1f MB in data/area-3' % (total / 1e6))


if __name__ == '__main__':
    main()

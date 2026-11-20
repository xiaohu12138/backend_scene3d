"""Allowlisted, read-only source data and the original terrain tile encoding."""
from functools import lru_cache
import json
import math
from pathlib import Path
import numpy as np

class Dataset:
    def __init__(self, root: Path):
        self.root = root
        self.assets = root / 'cesium_data'
        self.manifest = json.loads((self.assets / 'wrf3d/manifest.json').read_text())
        self.terrain = json.loads((self.assets / 'terrain_global/manifest.json').read_text())

    def describe(self):
        return {'id': 'nanjing', 'name': '南京三维风场与输电线路',
                'dimensions': self.manifest['dimensions'], 'times': self.manifest['times'],
                'bounds': self.manifest['bounds'], 'format': self.manifest['format'],
                'simulated_lines': True}

    @lru_cache(maxsize=256)
    def tile(self, z, x, y):
        path = self.assets / f'terrain_global/{z}/{x}/{y}.bin'
        n = self.terrain['samples']
        raw = np.fromfile(path, dtype='<u2')
        if raw.size != n*n:
            raise ValueError('地形瓦片损坏')
        return raw.reshape(n, n).astype(float)*self.terrain['heightScaleMetres']

    def elevation(self, lon, lat):
        z = self.terrain['maximumLevel']; n = self.terrain['samples']
        cols, rows = 2*(2**z), 2**z
        gx, gy = (lon+180)/360*cols, (90-lat)/180*rows
        x, y = math.floor(gx), math.floor(gy)
        values = self.tile(z, x, y)
        sx, sy = (gx-x)*(n-1), (gy-y)*(n-1)
        x0, y0 = min(n-2, int(sx)), min(n-2, int(sy))
        fx, fy = sx-x0, sy-y0
        # Cesium HeightmapTerrainData uses two triangles per grid cell.
        nw, ne, sw, se = values[y0,x0], values[y0,x0+1], values[y0+1,x0], values[y0+1,x0+1]
        if fy < 1-fx:
            return float(nw+(ne-nw)*fx+(sw-nw)*fy)
        return float(se+(sw-se)*(1-fx)+(ne-se)*(1-fy))

    @lru_cache(maxsize=4)
    def wind(self, index):
        frame = self.manifest['frames'][index]
        dims = self.manifest['dimensions']; active = min(32, dims['level'])
        result = {}
        for name in ('u','v','w','height_agl'):
            parts = []
            for chunk in frame['chunks']:
                if chunk['levelStart'] >= active: break
                path = (self.assets / 'wrf3d' / chunk['files'][name]).resolve()
                if not path.is_relative_to((self.assets/'wrf3d').resolve()):
                    raise ValueError('风场资产路径无效')
                raw = np.fromfile(path, dtype='<u2').reshape(chunk['levelCount'],dims['y'],dims['x'])
                spec = self.manifest['variables'][name]
                values = spec['minimum'] + raw.astype(np.float32)/self.manifest['quantizedMaximum']*(spec['maximum']-spec['minimum'])
                values[raw == self.manifest['nodata']] = np.nan
                parts.append(values)
            result[name] = np.concatenate(parts)[:active]
        return result

    def sample(self, index, lon, lat, height=60):
        b=self.manifest['bounds']; d=self.manifest['dimensions']
        # Match the original browser's bounds-nearest-neighbour sampling.
        x=max(0,min(d['x']-1,math.floor((lon-b['west'])/(b['east']-b['west'])*(d['x']-1)+0.5)))
        y=max(0,min(d['y']-1,math.floor((lat-b['south'])/(b['north']-b['south'])*(d['y']-1)+0.5)))
        field=self.wind(index); z=int(np.nanargmin(abs(field['height_agl'][:,y,x]-height)))
        u,v,w=(float(field[k][z,y,x]) for k in ('u','v','w'))
        if not all(math.isfinite(v) for v in (u,v,w)): raise ValueError('该位置风场数据缺测')
        return {'u':u,'v':v,'w':w,'speed':math.sqrt(u*u+v*v+w*w),'level':z,
                'heightAgl':float(field['height_agl'][z,y,x]),'frame':index}

    def maximum(self, index, height=60):
        f=self.wind(index); level=np.nanargmin(abs(f['height_agl']-height),axis=0)
        yy,xx=np.indices(level.shape)
        speed=np.sqrt(sum(f[k][level,yy,xx]**2 for k in ('u','v','w')))
        y,x=np.unravel_index(np.nanargmax(speed),speed.shape)
        b=self.manifest['bounds']; d=self.manifest['dimensions']
        lon=b['west']+(b['east']-b['west'])*int(x)/(d['x']-1)
        lat=b['south']+(b['north']-b['south'])*int(y)/(d['y']-1)
        wind=self.sample(index,lon,lat,height)
        return dict(wind,longitude=lon,latitude=lat,directionDegrees=math.degrees(math.atan2(wind['v'],wind['u'])))

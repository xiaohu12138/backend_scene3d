#!/usr/bin/env python3
"""Convert a WRF output file into browser-friendly, chunked 3D fields."""

import argparse
import json
import math
from pathlib import Path

import numpy as np
from netCDF4 import Dataset, chartostring


CHUNK_LEVELS = 8
NODATA = 65535
QUANTIZED_MAX = 65534
RANGES = {
    "u": (-60.0, 60.0, "m s-1"),
    "v": (-60.0, 60.0, "m s-1"),
    "w": (-20.0, 20.0, "m s-1"),
    "temperature": (180.0, 330.0, "K"),
    "pressure": (1000.0, 110000.0, "Pa"),
    "relative_humidity": (0.0, 100.0, "%"),
    "cloud_fraction": (0.0, 1.0, "1"),
    "height_agl": (0.0, 25000.0, "m"),
}


def quantize(values, minimum, maximum):
    values = np.asarray(values, dtype=np.float32)
    valid = np.isfinite(values)
    clipped = np.clip(values, minimum, maximum)
    result = np.full(values.shape, NODATA, dtype="<u2")
    scaled = np.rint((clipped[valid] - minimum) * QUANTIZED_MAX / (maximum - minimum))
    result[valid] = scaled.astype(np.uint16)
    return result


def relative_humidity(temperature_k, pressure_pa, mixing_ratio):
    temperature_c = temperature_k - 273.15
    saturation_pa = 611.2 * np.exp(17.67 * temperature_c / (temperature_c + 243.5))
    vapor_pa = mixing_ratio * pressure_pa / (0.622 + mixing_ratio)
    return np.clip(100.0 * vapor_pa / saturation_pa, 0.0, 100.0)


def write_float32(path, values):
    np.asarray(values, dtype="<f4").tofile(str(path))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("wrfout", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    if args.output.exists():
        raise SystemExit("Output already exists; choose a new version directory")
    args.output.mkdir(parents=True)

    with Dataset(str(args.wrfout)) as ds:
        nx = len(ds.dimensions["west_east"])
        ny = len(ds.dimensions["south_north"])
        nz = len(ds.dimensions["bottom_top"])
        nt = len(ds.dimensions["Time"])

        times = [str(value) for value in chartostring(ds.variables["Times"][:])]
        lat = np.asarray(ds.variables["XLAT"][0], dtype=np.float32)
        lon = np.asarray(ds.variables["XLONG"][0], dtype=np.float32)
        terrain = np.asarray(ds.variables["HGT"][0], dtype=np.float32)
        write_float32(args.output / "latitude.f32", lat)
        write_float32(args.output / "longitude.f32", lon)
        write_float32(args.output / "terrain_height.f32", terrain)

        manifest = {
            "format": "wrf3d-chunked-u16-v1",
            "source": args.wrfout.name,
            "dimensions": {"time": nt, "level": nz, "y": ny, "x": nx},
            "layout": "level-y-x, C-order, little-endian uint16",
            "chunkLevels": CHUNK_LEVELS,
            "nodata": NODATA,
            "quantizedMaximum": QUANTIZED_MAX,
            "times": times,
            "projection": {
                "mapProj": int(getattr(ds, "MAP_PROJ", 0)),
                "dx": float(getattr(ds, "DX", 0.0)),
                "dy": float(getattr(ds, "DY", 0.0)),
                "centerLatitude": float(getattr(ds, "CEN_LAT", np.nan)),
                "centerLongitude": float(getattr(ds, "CEN_LON", np.nan)),
            },
            "bounds": {
                "west": float(np.nanmin(lon)), "south": float(np.nanmin(lat)),
                "east": float(np.nanmax(lon)), "north": float(np.nanmax(lat)),
            },
            "static": {
                "latitude": {"file": "latitude.f32", "dtype": "float32", "shape": [ny, nx]},
                "longitude": {"file": "longitude.f32", "dtype": "float32", "shape": [ny, nx]},
                "terrainHeight": {"file": "terrain_height.f32", "dtype": "float32", "shape": [ny, nx], "units": "m"},
            },
            "variables": {},
            "frames": [],
        }
        for name, (minimum, maximum, units) in RANGES.items():
            manifest["variables"][name] = {
                "minimum": minimum, "maximum": maximum, "units": units,
                "decode": f"minimum + value / {QUANTIZED_MAX} * (maximum - minimum)",
            }

        for ti, timestamp in enumerate(times):
            print(f"[{ti + 1}/{nt}] {timestamp}", flush=True)
            u_stag = np.asarray(ds.variables["U"][ti], dtype=np.float32)
            v_stag = np.asarray(ds.variables["V"][ti], dtype=np.float32)
            w_stag = np.asarray(ds.variables["W"][ti], dtype=np.float32)
            u = 0.5 * (u_stag[:, :, :-1] + u_stag[:, :, 1:])
            v = 0.5 * (v_stag[:, :-1, :] + v_stag[:, 1:, :])
            w = 0.5 * (w_stag[:-1] + w_stag[1:])
            pressure = np.asarray(ds.variables["P"][ti] + ds.variables["PB"][ti], dtype=np.float32)
            theta = np.asarray(ds.variables["T"][ti], dtype=np.float32) + 300.0
            temperature = theta * np.power(pressure / 100000.0, 287.05 / 1004.0)
            qvapor = np.asarray(ds.variables["QVAPOR"][ti], dtype=np.float32)
            rh = relative_humidity(temperature, pressure, qvapor)
            cloud = np.asarray(ds.variables["CLDFRA"][ti], dtype=np.float32)
            geopotential = np.asarray(ds.variables["PH"][ti] + ds.variables["PHB"][ti], dtype=np.float32) / 9.81
            height_msl = 0.5 * (geopotential[:-1] + geopotential[1:])
            height_agl = np.maximum(height_msl - terrain[None, :, :], 0.0)

            fields = {
                "u": u, "v": v, "w": w, "temperature": temperature,
                "pressure": pressure, "relative_humidity": rh,
                "cloud_fraction": cloud, "height_agl": height_agl,
            }
            frame_dir = args.output / f"t{ti:03d}"
            frame_dir.mkdir()
            chunks = []
            for start in range(0, nz, CHUNK_LEVELS):
                count = min(CHUNK_LEVELS, nz - start)
                chunk_entry = {"levelStart": start, "levelCount": count, "files": {}}
                for name, values in fields.items():
                    minimum, maximum, _ = RANGES[name]
                    filename = f"{name}_z{start:03d}_{start + count - 1:03d}.u16"
                    quantize(values[start:start + count], minimum, maximum).tofile(str(frame_dir / filename))
                    chunk_entry["files"][name] = f"t{ti:03d}/{filename}"
                chunks.append(chunk_entry)
            manifest["frames"].append({"index": ti, "time": timestamp, "chunks": chunks})

    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    expected_chunks = math.ceil(nz / CHUNK_LEVELS)
    print(f"Created {args.output}: {nt} frames, {expected_chunks} chunks/frame", flush=True)


if __name__ == "__main__":
    main()

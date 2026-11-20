#!/usr/bin/env python3
"""Build georeferenced wind-speed isosurfaces from a WRF output file."""

import argparse
import json
from pathlib import Path

import numpy as np
from netCDF4 import Dataset, chartostring
from scipy.ndimage import map_coordinates
from skimage.measure import marching_cubes


ISO_LEVELS = (3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5)
MAX_HEIGHT_AGL = 4500.0


def sample3d(field, vertices_zyx):
    return map_coordinates(
        field,
        [vertices_zyx[:, 0], vertices_zyx[:, 1], vertices_zyx[:, 2]],
        order=1,
        mode="nearest",
    )


def sample2d(field, vertices_zyx):
    return map_coordinates(
        field,
        [vertices_zyx[:, 1], vertices_zyx[:, 2]],
        order=1,
        mode="nearest",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("wrfout", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    if args.output.exists():
        raise SystemExit("Output already exists; choose a new version directory")
    args.output.mkdir(parents=True)

    manifest = {
        "format": "wrf-wind-isosurface-v1",
        "source": args.wrfout.name,
        "maximumHeightAgl": MAX_HEIGHT_AGL,
        "levels": list(ISO_LEVELS),
        "frames": [],
    }

    with Dataset(str(args.wrfout)) as ds:
        times = [str(value) for value in chartostring(ds.variables["Times"][:])]
        lat = np.asarray(ds.variables["XLAT"][0], dtype=np.float32)
        lon = np.asarray(ds.variables["XLONG"][0], dtype=np.float32)
        terrain = np.asarray(ds.variables["HGT"][0], dtype=np.float32)

        for ti, timestamp in enumerate(times):
            print(f"[{ti + 1}/{len(times)}] {timestamp}", flush=True)
            us = np.asarray(ds.variables["U"][ti], dtype=np.float32)
            vs = np.asarray(ds.variables["V"][ti], dtype=np.float32)
            ws = np.asarray(ds.variables["W"][ti], dtype=np.float32)
            u = 0.5 * (us[:, :, :-1] + us[:, :, 1:])
            v = 0.5 * (vs[:, :-1, :] + vs[:, 1:, :])
            w = 0.5 * (ws[:-1] + ws[1:])
            speed = np.sqrt(u * u + v * v + w * w)
            geopotential = np.asarray(ds.variables["PH"][ti] + ds.variables["PHB"][ti], dtype=np.float32) / 9.81
            height_msl = 0.5 * (geopotential[:-1] + geopotential[1:])
            height_agl = height_msl - terrain[None, :, :]
            level_count = int(np.count_nonzero(np.nanmedian(height_agl, axis=(1, 2)) <= MAX_HEIGHT_AGL))
            level_count = max(2, min(level_count, speed.shape[0]))
            speed = speed[:level_count]
            height_msl = height_msl[:level_count]

            frame_dir = args.output / f"t{ti:03d}"
            frame_dir.mkdir()
            frame = {"index": ti, "time": timestamp, "levelCount": level_count, "surfaces": []}
            for iso in ISO_LEVELS:
                if not (float(speed.min()) < iso < float(speed.max())):
                    continue
                vertices, faces, normals, _ = marching_cubes(
                    speed,
                    level=iso,
                    step_size=1,
                    allow_degenerate=False,
                )
                longitude = np.deg2rad(sample2d(lon, vertices)).astype(np.float32)
                latitude = np.deg2rad(sample2d(lat, vertices)).astype(np.float32)
                height = sample3d(height_msl, vertices).astype(np.float32)
                agl = sample3d(height_agl[:level_count], vertices).astype(np.float32)
                local_normals = np.column_stack((normals[:, 2], normals[:, 1], normals[:, 0])).astype(np.float32)
                local_normals /= np.maximum(np.linalg.norm(local_normals, axis=1, keepdims=True), 1e-6)
                packed = np.column_stack((longitude, latitude, height, local_normals, agl)).astype("<f4")
                stem = f"iso_{int(iso):02d}"
                packed.tofile(str(frame_dir / f"{stem}.vertices.f32"))
                np.asarray(faces, dtype="<u4").tofile(str(frame_dir / f"{stem}.indices.u32"))
                frame["surfaces"].append({
                    "value": iso,
                    "vertices": f"t{ti:03d}/{stem}.vertices.f32",
                    "indices": f"t{ti:03d}/{stem}.indices.u32",
                    "vertexCount": int(vertices.shape[0]),
                    "indexCount": int(faces.size),
                    "vertexStride": 28,
                })
                print(f"  {iso:g} m/s: {vertices.shape[0]} vertices, {faces.shape[0]} triangles", flush=True)
            manifest["frames"].append(frame)

    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Created {args.output}", flush=True)


if __name__ == "__main__":
    main()

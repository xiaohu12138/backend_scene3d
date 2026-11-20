#!/usr/bin/env python3
import json
import math
import argparse
from pathlib import Path

import numpy as np
from osgeo import gdal


gdal.UseExceptions()

DEM_SOURCE = ROOT = MANIFEST_PATH = None
TILE_SAMPLES = 65
MAXIMUM_LEVEL = 13
HEIGHT_SCALE_METRES = 0.1


def source_bounds(dataset):
    transform = dataset.GetGeoTransform()
    west = transform[0]
    north = transform[3]
    east = west + dataset.RasterXSize * transform[1]
    south = north + dataset.RasterYSize * transform[5]
    return [west, south, east, north]


def axis_interpolation(values, maximum):
    clipped = np.clip(values, 0.0, maximum - 1.0)
    lower = np.floor(clipped).astype(np.int32)
    upper = np.minimum(lower + 1, maximum - 1)
    weight = (clipped - lower).astype(np.float32)
    return lower, upper, weight


def reset_output():
    if ROOT.exists():
        raise SystemExit("Output already exists; choose a new version directory")
    ROOT.mkdir(parents=True)


def main():
    global DEM_SOURCE, ROOT, MANIFEST_PATH
    parser = argparse.ArgumentParser(description="Build geographic Cesium terrain from a WGS84 DEM")
    parser.add_argument("dem", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    DEM_SOURCE = args.dem.resolve()
    ROOT = args.output.resolve()
    MANIFEST_PATH = ROOT / "manifest.json"
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text())
        files = list(ROOT.rglob("*.bin"))
        if len(files) == manifest["tileCount"] and all(
            path.stat().st_size == TILE_SAMPLES * TILE_SAMPLES * 2
            for path in files
        ):
            print("[skip] global terrain tiles already exist", flush=True)
            print(json.dumps(manifest, indent=2), flush=True)
            return

    dataset = gdal.Open(str(DEM_SOURCE), gdal.GA_ReadOnly)
    transform = dataset.GetGeoTransform()
    bounds = source_bounds(dataset)
    west, south, east, north = bounds
    source = dataset.GetRasterBand(1).ReadAsArray().astype(np.float32)
    source[~np.isfinite(source)] = 0
    np.clip(source, 0, 6553.5, out=source)
    reset_output()

    tile_count = 0
    levels = []
    for level in range(MAXIMUM_LEVEL + 1):
        columns = 2 * (2 ** level)
        rows = 2 ** level
        longitude_span = 360.0 / columns
        latitude_span = 180.0 / rows
        x_min = max(0, int(math.floor((west + 180.0) / longitude_span)))
        x_max = min(
            columns - 1,
            int(math.floor((east + 180.0 - 1e-12) / longitude_span)),
        )
        y_min = max(0, int(math.floor((90.0 - north) / latitude_span)))
        y_max = min(
            rows - 1,
            int(math.floor((90.0 - south - 1e-12) / latitude_span)),
        )
        print(
            "[global terrain] level {}: x {}..{}, y {}..{}".format(
                level, x_min, x_max, y_min, y_max
            ),
            flush=True,
        )

        for y in range(y_min, y_max + 1):
            tile_north = 90.0 - y * latitude_span
            tile_south = tile_north - latitude_span
            latitudes = np.linspace(
                tile_north, tile_south, TILE_SAMPLES, dtype=np.float64
            )
            source_rows = (latitudes - transform[3]) / transform[5] - 0.5
            row0, row1, row_weight = axis_interpolation(
                source_rows, dataset.RasterYSize
            )
            row_weight = row_weight[:, np.newaxis]
            latitude_inside = (latitudes >= south) & (latitudes <= north)

            for x in range(x_min, x_max + 1):
                tile_west = -180.0 + x * longitude_span
                tile_east = tile_west + longitude_span
                longitudes = np.linspace(
                    tile_west, tile_east, TILE_SAMPLES, dtype=np.float64
                )
                source_columns = (
                    (longitudes - transform[0]) / transform[1] - 0.5
                )
                column0, column1, column_weight = axis_interpolation(
                    source_columns, dataset.RasterXSize
                )
                column_weight = column_weight[np.newaxis, :]
                longitude_inside = (longitudes >= west) & (longitudes <= east)

                upper_left = source[np.ix_(row0, column0)]
                upper_right = source[np.ix_(row0, column1)]
                lower_left = source[np.ix_(row1, column0)]
                lower_right = source[np.ix_(row1, column1)]
                upper = upper_left * (1 - column_weight) + upper_right * column_weight
                lower = lower_left * (1 - column_weight) + lower_right * column_weight
                values = upper * (1 - row_weight) + lower * row_weight
                inside = latitude_inside[:, np.newaxis] & longitude_inside[np.newaxis, :]
                values[~inside] = 0
                encoded = np.rint(values / HEIGHT_SCALE_METRES).astype("<u2")

                output_dir = ROOT / str(level) / str(x)
                output_dir.mkdir(parents=True, exist_ok=True)
                encoded.tofile(str(output_dir / "{}.bin".format(y)))
                tile_count += 1

        centre_latitude = math.radians((north + south) / 2)
        sample_x = (
            longitude_span
            * 111320.0
            * math.cos(centre_latitude)
            / (TILE_SAMPLES - 1)
        )
        sample_y = latitude_span * 110574.0 / (TILE_SAMPLES - 1)
        levels.append(
            {
                "level": level,
                "xRange": [x_min, x_max],
                "yRange": [y_min, y_max],
                "sampleSpacingMetres": [sample_x, sample_y],
            }
        )

    dataset = None
    manifest = {
        "version": 1,
        "name": "Global ellipsoid with Nanjing Copernicus DEM 30m",
        "dataRectangleDegrees": bounds,
        "url": "{z}/{x}/{y}.bin",
        "samples": TILE_SAMPLES,
        "heightEncoding": "uint16-le",
        "heightScaleMetres": HEIGHT_SCALE_METRES,
        "maximumLevel": MAXIMUM_LEVEL,
        "tileCount": tile_count,
        "levels": levels,
    }
    with MANIFEST_PATH.open("w") as handle:
        json.dump(manifest, handle, indent=2)

    files = list(ROOT.rglob("*.bin"))
    if len(files) != tile_count:
        raise RuntimeError("Global terrain tile count mismatch")
    print("[validate] OK: {} global terrain tiles".format(tile_count), flush=True)
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()

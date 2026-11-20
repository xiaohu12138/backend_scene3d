"""Check display prerequisites without preparing data or submitting work."""
import json
import re


def read_object(path):
    """Treat unreadable, malformed or non-object metadata as unavailable."""
    try:
        value = path.read_text(encoding="utf-8")
        value = json.loads(value)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def nonempty_file(path):
    """Require actual file content, not just a placeholder path."""
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def wind_chunks_ready(root, manifest):
    """Check the referenced wind chunks without loading their arrays."""
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        return False
    for frame in frames:
        if not isinstance(frame, dict):
            return False
        chunks = frame.get("chunks")
        if not isinstance(chunks, list) or not chunks:
            return False
        for chunk in chunks:
            files = chunk.get("files") if isinstance(chunk, dict) else None
            if not isinstance(files, dict):
                return False
            for name in ("u", "v", "w", "height_agl"):
                relative = files.get(name)
                if not isinstance(relative, str):
                    return False
                try:
                    path = (root / relative).resolve()
                    if not path.is_relative_to(
                        root.resolve()
                    ) or not nonempty_file(path):
                        return False
                except (OSError, ValueError):
                    return False
    return True


def display_readiness(settings):
    """Return named checks without disclosing private filesystem paths."""
    wrf_root = settings.data / "cesium_data/wrf3d"
    terrain = read_object(
        settings.data / "cesium_data/terrain_global/manifest.json"
    )
    wrf = read_object(wrf_root / "manifest.json")
    cesium = settings.data / "cesium-app/cesium"
    pointer = read_object(settings.runs / "baseline.json")
    identifier = pointer.get("run_id")
    valid_index = isinstance(identifier, str) and bool(
        re.fullmatch(r"s3d_[0-9a-f]{32}", identifier)
    )
    baseline = settings.runs / identifier if valid_index else None
    result = read_object(baseline / "result.json") if baseline else {}
    geometry = read_object(baseline / "geometry.json") if baseline else {}
    frames = result.get("frames")
    frames_ready = isinstance(frames, list) and bool(frames)
    if frames_ready:
        for frame in frames:
            index = frame.get("index") if isinstance(frame, dict) else None
            if (
                type(index) is not int
                or not 0 <= index < 10000
                or not nonempty_file(baseline / "frames" / f"{index:03}.json")
            ):
                frames_ready = False
                break
    checks = {
        "wrf_manifest": bool(wrf),
        "wind_chunks": wind_chunks_ready(wrf_root, wrf),
        "terrain_manifest": bool(terrain),
        "wrf_terrain_height": nonempty_file(wrf_root / "terrain_height.f32"),
        "cesium_script": nonempty_file(cesium / "Cesium.js"),
        "cesium_styles": nonempty_file(cesium / "Widgets/widgets.css"),
        "baseline_index": valid_index,
        "baseline_result": bool(result) and frames_ready,
        "baseline_geometry": bool(geometry),
        "baseline_frames": frames_ready,
    }
    return checks

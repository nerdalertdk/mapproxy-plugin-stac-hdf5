"""MapProxy source implementation for STAC HDF5 raster overlays."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import h5py
import numpy as np
from PIL import Image

from mapproxy.client.http import HTTPClient
from mapproxy.config.loader import ConfigurationError, SourceConfiguration
from mapproxy.image.opts import ImageOptions
from mapproxy.layer import MapExtent
from mapproxy.srs import SRS, SupportedSRS
from mapproxy.source.wms import WMSLikeSource


DEFAULT_EXTENT = (-180.0, -90.0, 180.0, 90.0)
CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StacHdf5Item:
    item_id: str
    href: str
    bbox: tuple[float, float, float, float]
    timestamp: str | None


class StacHdf5SourceConfiguration(SourceConfiguration):
    source_type = ("stac_hdf5",)

    def source(self, params=None):
        conf = dict(self.conf)
        conf["cache_dir"] = str(self.cache_dir())
        req = conf.get("req") or {}
        base_url = req.get("url") or conf.get("url")
        if not base_url:
            raise ConfigurationError("stac_hdf5 req.url is required")
        http_client, sanitized_base_url = self.http_client(base_url)
        conf["url"] = sanitized_base_url
        return StacHdf5Source(
            conf,
            coverage=self.coverage(),
            image_opts=self.image_opts("image/png"),
            http_client=http_client,
            error_handler=self.on_error_handler(),
        )

    def cache_dir(self) -> Path:
        if self.conf.get("cache_dir"):
            return Path(self.context.globals.abspath(self.conf["cache_dir"]))
        return Path(self.context.globals.get_path("cache.base_dir", {})) / self.conf.get("name", "stac_hdf5")


class StacHdf5Source(WMSLikeSource):
    """MapProxy compatible source that renders a STAC HDF5 asset."""

    def __init__(self, conf: dict[str, Any], coverage=None, image_opts=None, http_client=None, error_handler=None):
        image_opts = image_opts or ImageOptions(format="image/png", transparent=True)
        image_opts.transparent = True
        if image_opts.resampling is None:
            image_opts.resampling = "bilinear"
        WMSLikeSource.__init__(
            self,
            image_opts=image_opts,
            coverage=coverage,
            supported_srs=SupportedSRS([SRS(4326)]),
            supported_formats=["image/png"],
            error_handler=error_handler,
        )

        req = dict(conf.get("req") or {})
        self.base_url = conf.get("url") or req.get("url")
        self.collection = req.get("collection") or conf.get("collection")
        self.asset_key = req.get("asset_key") or conf.get("asset_key") or "data"
        self.query_bbox = req.get("bbox") or conf.get("bbox")
        self.bbox_crs = (
            req.get("bbox_crs")
            or req.get("bbox-crs")
            or conf.get("bbox_crs")
            or CRS84
        )
        self.req_params = dict(req.get("params") or conf.get("params") or {})
        self.cache_dir = Path(conf.get("cache_dir", ".mapproxy-stac-hdf5"))
        self.refresh_seconds = int(conf.get("refresh_minutes", 60)) * 60
        self.timeout = int(conf.get("timeout", 30))
        self.cache_max_files = int(conf.get("cache_max_files", 24))
        self.data_opacity = int(conf.get("opacity", 180))
        self.min_value = float(conf.get("min_value", 0.1))
        self.max_value = float(conf.get("max_value", 60.0))
        self.fallback_extent = tuple(conf.get("extent", DEFAULT_EXTENT))
        if coverage is None:
            self.extent = MapExtent(self.fallback_extent, SRS(4326))
        self.opacity = None
        self.http_client = http_client or HTTPClient(timeout=self.timeout)
        self._cached_item: StacHdf5Item | None = None
        self._checked_at: dt.datetime | None = None
        self._validate_config()

    def _retrieve(self, query, format):
        return self.render(query.bbox, query.size)

    def render(self, bbox, size):
        item = self.latest_item()
        source_file = self.download_item(item)
        data = read_hdf5_array(source_file)
        rgba = hdf5_data_to_rgba(data, self.min_value, self.max_value, self.data_opacity)
        return crop_to_bbox(rgba, item.bbox, bbox, size)

    def latest_item(self) -> StacHdf5Item:
        now = dt.datetime.now(dt.timezone.utc)
        if self._cached_item and self._checked_at:
            if (now - self._checked_at).total_seconds() < self.refresh_seconds:
                return self._cached_item

        params = dict(self.req_params)
        params.update({
            "limit": 1,
            "sortorder": "datetime,DESC",
        })
        bbox = self.query_bbox or self._coverage_query_bbox()
        if bbox:
            params["bbox"] = bbox
            params["bbox-crs"] = self.bbox_crs

        url = f"{self.base_url.rstrip('/')}/collections/{self.collection}/items"
        data = request_json(self.http_client, url, params)
        features = data.get("features") or []
        if not features:
            if self._cached_item:
                return self._cached_item
            raise RuntimeError("STAC API returned no items")

        feature = features[0]
        asset = feature.get("asset", {}).get(self.asset_key, {})
        href = asset.get("href")
        if not href:
            raise RuntimeError(f"STAC item did not include asset.{self.asset_key}.href")

        bbox = tuple(float(v) for v in feature.get("bbox", self.fallback_extent))
        item = StacHdf5Item(
            item_id=feature.get("id") or _hashed_name(href),
            href=href,
            bbox=bbox,
            timestamp=feature.get("properties", {}).get("datetime"),
        )
        log.info(
            "selected STAC HDF5 item id=%s timestamp=%s bbox=%s asset=%s",
            item.item_id,
            item.timestamp,
            item.bbox,
            item.href,
        )
        self._cached_item = item
        self._checked_at = now
        return item

    def _coverage_query_bbox(self) -> str | None:
        if not self.coverage:
            return None
        bbox = self.coverage.bbox
        return ",".join(_format_coord(value) for value in bbox)

    def _validate_config(self):
        if not self.base_url:
            raise ConfigurationError("stac_hdf5 req.url is required")
        if not self.collection:
            raise ConfigurationError("stac_hdf5 req.collection is required")
        if self.bbox_crs != CRS84:
            raise ConfigurationError("stac_hdf5 only supports CRS84 bbox queries")
        if self.query_bbox:
            _parse_bbox(self.query_bbox)
        if self.coverage and self.coverage.srs != SRS(4326):
            raise ConfigurationError("stac_hdf5 coverage must use EPSG:4326/CRS84 coordinates")
        if self.refresh_seconds <= 0:
            raise ConfigurationError("stac_hdf5 refresh_minutes must be greater than 0")
        if self.cache_max_files < 0:
            raise ConfigurationError("stac_hdf5 cache_max_files must be 0 or greater")
        if not 0 <= self.data_opacity <= 255:
            raise ConfigurationError("stac_hdf5 opacity must be between 0 and 255")
        if self.max_value <= self.min_value:
            raise ConfigurationError("stac_hdf5 max_value must be greater than min_value")

    def download_item(self, item: StacHdf5Item) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        filename = Path(item.item_id).name
        if not filename:
            filename = _hashed_name(item.href)
        path = self.cache_dir / filename
        if path.exists() and path.stat().st_size > 0:
            return path

        tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        with self.http_client.open(item.href, headers={"Accept": "application/x-hdf5,*/*"}) as resp:
            tmp_path.write_bytes(resp.read())
        if path.exists() and path.stat().st_size > 0:
            tmp_path.unlink(missing_ok=True)
            return path
        tmp_path.replace(path)
        self.cleanup_cache()
        return path

    def cleanup_cache(self):
        if self.cache_max_files <= 0:
            return
        files = [path for path in self.cache_dir.iterdir() if path.is_file() and path.suffix.lower() in {".h5", ".hdf5"}]
        stale_files = sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)[self.cache_max_files:]
        for path in stale_files:
            try:
                path.unlink()
            except OSError:
                log.warning("could not remove old STAC HDF5 cache file %s", path)


def request_json(http_client: HTTPClient, url: str, params: dict[str, Any]) -> dict[str, Any]:
    if params:
        query = "&".join(
            f"{quote(str(key), safe='')}={quote(str(value), safe='/:,')}"
            for key, value in params.items()
        )
        url = url + ("&" if "?" in url else "?") + query
    with http_client.open(url, headers={"Accept": "application/json"}) as resp:
        return json.load(resp)


def read_hdf5_array(path: Path) -> np.ndarray:
    with h5py.File(path, "r") as h5:
        dataset = _find_data_dataset(h5)
        raw = dataset[()].astype("float32")
        gain = _first_attr(dataset, ("gain", "what/gain"), 1.0)
        offset = _first_attr(dataset, ("offset", "what/offset"), 0.0)
        nodata = _first_attr(dataset, ("nodata", "what/nodata"), None)
        undetect = _first_attr(dataset, ("undetect", "what/undetect"), None)

    data = raw * float(gain) + float(offset)
    if nodata is not None:
        data[raw == float(nodata)] = np.nan
    if undetect is not None:
        data[raw == float(undetect)] = np.nan
    return data


def hdf5_data_to_rgba(data: np.ndarray, min_value: float, max_value: float, opacity: int) -> Image.Image:
    finite = np.isfinite(data)
    scaled = np.zeros(data.shape, dtype="float32")
    if max_value > min_value:
        scaled[finite] = (data[finite] - min_value) / (max_value - min_value)
    scaled = np.clip(scaled, 0.0, 1.0)

    rgba = np.zeros((data.shape[0], data.shape[1], 4), dtype="uint8")
    rgba[..., 0] = np.clip(255 * np.maximum(0, (scaled - 0.55) / 0.45), 0, 255)
    rgba[..., 1] = np.clip(255 * np.minimum(1, scaled * 1.5), 0, 255)
    rgba[..., 2] = np.clip(255 * np.maximum(0, 1 - scaled * 1.8), 0, 255)
    rgba[..., 3] = np.where(finite & (data > min_value), opacity, 0).astype("uint8")
    return Image.fromarray(rgba, mode="RGBA")


def crop_to_bbox(image: Image.Image, source_bbox, request_bbox, request_size) -> Image.Image:
    src_minx, src_miny, src_maxx, src_maxy = [float(v) for v in source_bbox]
    req_minx, req_miny, req_maxx, req_maxy = [float(v) for v in request_bbox]
    width, height = image.size

    if req_maxx <= src_minx or req_minx >= src_maxx or req_maxy <= src_miny or req_miny >= src_maxy:
        return Image.new("RGBA", tuple(request_size), (0, 0, 0, 0))

    inter_minx = max(req_minx, src_minx)
    inter_miny = max(req_miny, src_miny)
    inter_maxx = min(req_maxx, src_maxx)
    inter_maxy = min(req_maxy, src_maxy)

    left = round((inter_minx - src_minx) / (src_maxx - src_minx) * width)
    right = round((inter_maxx - src_minx) / (src_maxx - src_minx) * width)
    top = round((src_maxy - inter_maxy) / (src_maxy - src_miny) * height)
    bottom = round((src_maxy - inter_miny) / (src_maxy - src_miny) * height)

    crop = image.crop((left, top, right, bottom))

    out_width, out_height = tuple(request_size)
    paste_left = round((inter_minx - req_minx) / (req_maxx - req_minx) * out_width)
    paste_right = round((inter_maxx - req_minx) / (req_maxx - req_minx) * out_width)
    paste_top = round((req_maxy - inter_maxy) / (req_maxy - req_miny) * out_height)
    paste_bottom = round((req_maxy - inter_miny) / (req_maxy - req_miny) * out_height)

    resized = crop.resize((max(1, paste_right - paste_left), max(1, paste_bottom - paste_top)), Image.Resampling.BILINEAR)
    output = Image.new("RGBA", (out_width, out_height), (0, 0, 0, 0))
    output.alpha_composite(resized, (paste_left, paste_top))
    return output


def _find_data_dataset(h5: h5py.File) -> h5py.Dataset:
    candidates: list[h5py.Dataset] = []

    def visit(_name, obj):
        if isinstance(obj, h5py.Dataset) and obj.ndim == 2 and np.issubdtype(obj.dtype, np.number):
            candidates.append(obj)

    h5.visititems(visit)
    for dataset in candidates:
        if dataset.name.endswith("/data"):
            return dataset
    if candidates:
        return candidates[0]
    raise RuntimeError("No 2D numeric dataset found in HDF5 file")


def _first_attr(dataset: h5py.Dataset, names, default):
    for name in names:
        if "/" in name:
            group_name, attr_name = name.rsplit("/", 1)
            group = dataset.file.get(group_name)
            if group is not None and attr_name in group.attrs:
                return group.attrs[attr_name]
        if name in dataset.attrs:
            return dataset.attrs[name]
        parent = dataset.parent
        if name in parent.attrs:
            return parent.attrs[name]
    return default


def _hashed_name(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() + ".h5"


def _format_coord(value) -> str:
    return f"{float(value):.12g}"


def _parse_bbox(value) -> tuple[float, float, float, float]:
    if isinstance(value, str):
        parts = value.split(",")
    else:
        parts = list(value)
    if len(parts) != 4:
        raise ConfigurationError("stac_hdf5 bbox must contain four CRS84 coordinates")
    try:
        minx, miny, maxx, maxy = [float(part) for part in parts]
    except (TypeError, ValueError):
        raise ConfigurationError("stac_hdf5 bbox must contain numeric CRS84 coordinates")
    if minx >= maxx or miny >= maxy:
        raise ConfigurationError("stac_hdf5 bbox must be ordered as min_lon,min_lat,max_lon,max_lat")
    return minx, miny, maxx, maxy

import os
from pathlib import Path

import h5py
import numpy as np
from mapproxy.layer import MapQuery
from mapproxy.srs import SRS
import pytest

from mapproxy.config.loader import ConfigurationError
from mapproxy.config.loader import load_configuration
from mapproxy_stac_hdf5.plugin import plugin_entrypoint
from mapproxy_stac_hdf5.source import StacHdf5Item, StacHdf5Source, crop_to_bbox, hdf5_data_to_rgba, read_hdf5_array


class DummyCoverage:
    bbox = (7.0, 54.0, 16.0, 58.0)
    srs = SRS(4326)


def test_read_hdf5_array_applies_gain_offset_and_nodata(tmp_path: Path):
    path = tmp_path / "sample.h5"
    with h5py.File(path, "w") as h5:
        group = h5.create_group("dataset1/data1")
        data = group.create_dataset("data", data=np.array([[0, 1], [2, 255]], dtype="uint8"))
        group.attrs["gain"] = 2.0
        group.attrs["offset"] = -1.0
        group.attrs["nodata"] = 255

    result = read_hdf5_array(path)

    assert result[0, 0] == -1.0
    assert result[0, 1] == 1.0
    assert result[1, 0] == 3.0
    assert np.isnan(result[1, 1])


def test_hdf5_data_to_rgba_makes_low_and_nan_values_transparent():
    data = np.array([[0.0, 10.0], [np.nan, 60.0]], dtype="float32")

    image = hdf5_data_to_rgba(data, min_value=0.1, max_value=60.0, opacity=170)
    alpha = np.array(image)[..., 3]

    assert alpha[0, 0] == 0
    assert alpha[0, 1] == 170
    assert alpha[1, 0] == 0
    assert alpha[1, 1] == 170


def test_crop_to_bbox_returns_transparent_image_outside_extent():
    image = hdf5_data_to_rgba(np.ones((4, 4), dtype="float32"), 0.1, 2.0, 170)

    out = crop_to_bbox(image, (4, 52, 21, 60), (30, 52, 31, 53), (8, 8))

    assert out.size == (8, 8)
    assert np.array(out)[..., 3].max() == 0


def test_crop_to_bbox_places_intersection_in_requested_canvas():
    image = hdf5_data_to_rgba(np.ones((4, 4), dtype="float32"), 0.1, 2.0, 170)

    out = crop_to_bbox(image, (0, 0, 10, 10), (5, 0, 15, 10), (10, 10))
    alpha = np.array(out)[..., 3]

    assert alpha[:, :5].max() == 170
    assert alpha[:, 5:].max() == 0


def test_direct_source_reprojects_non_4326_requests(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("mapproxy_stac_hdf5.source.read_hdf5_array", lambda _path: np.ones((64, 64), dtype="float32"))

    class TestSource(StacHdf5Source):
        def latest_item(self):
            return StacHdf5Item(
                item_id="sample.h5",
                href="https://example.test/sample.h5",
                bbox=(7.0, 54.0, 16.0, 58.0),
                timestamp="2026-05-12T10:35:00Z",
            )

        def download_item(self, item):
            return tmp_path / item.item_id

    source = TestSource(
        {
            "req": {
                "url": "https://example.test/stac",
                "collection": "collection",
            }
        }
    )
    query = MapQuery(
        (779236.435552915, 7170156.2939999495, 1781111.8526923778, 7967317.535015908),
        (256, 256),
        SRS(3857),
        "image/png",
    )

    image = source.get_map(query).as_image()

    assert image.size == (256, 256)
    assert image.getbbox() is not None


def test_direct_source_supports_crs84_requests(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("mapproxy_stac_hdf5.source.read_hdf5_array", lambda _path: np.ones((64, 64), dtype="float32"))

    class TestSource(StacHdf5Source):
        def latest_item(self):
            return StacHdf5Item(
                item_id="sample.h5",
                href="https://example.test/sample.h5",
                bbox=(7.0, 54.0, 16.0, 58.0),
                timestamp="2026-05-12T10:35:00Z",
            )

        def download_item(self, item):
            return tmp_path / item.item_id

    source = TestSource(
        {
            "req": {
                "url": "https://example.test/stac",
                "collection": "collection",
            }
        }
    )
    query = MapQuery(
        (7.0, 54.0, 16.0, 58.0),
        (256, 256),
        SRS("CRS:84"),
        "image/png",
    )

    image = source.get_map(query).as_image()

    assert image.size == (256, 256)
    assert image.getbbox() is not None


def test_source_uses_req_options_and_coverage_bbox(monkeypatch, tmp_path: Path):
    calls = []

    def fake_request_json(http_client, url, params):
        calls.append((url, params))
        return {
            "features": [
                {
                    "id": "sample.h5",
                    "bbox": [4.0, 52.0, 21.0, 60.0],
                    "asset": {"data": {"href": "https://example.test/sample.h5"}},
                    "properties": {"datetime": "2026-05-12T10:35:00Z"},
                }
            ]
        }

    monkeypatch.setattr("mapproxy_stac_hdf5.source.request_json", fake_request_json)
    source = StacHdf5Source(
        {
            "req": {
                "url": "https://example.test/stac",
                "collection": "collection",
                "params": {"custom": "value", "scanType": "fullRange"},
            },
            "cache_dir": str(tmp_path),
        },
        coverage=DummyCoverage(),
    )

    item = source.latest_item()

    assert item.item_id == "sample.h5"
    assert calls == [
        (
            "https://example.test/stac/collections/collection/items",
            {
                "custom": "value",
                "scanType": "fullRange",
                "limit": 1,
                "sortorder": "datetime,DESC",
                "bbox": "7,54,16,58",
                "bbox-crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
            },
        )
    ]


def test_refresh_defaults_to_one_hour():
    source = StacHdf5Source({"req": {"url": "https://example.test/stac", "collection": "collection"}})

    assert source.refresh_seconds == 3600


def test_configuration_uses_mapproxy_cache_base_dir_by_default(tmp_path: Path):
    plugin_entrypoint()
    config_path = tmp_path / "mapproxy.yaml"
    config_path.write_text(
        """
globals:
  cache:
    base_dir: ./cache_data
sources:
  stac_hdf5_latest:
    type: stac_hdf5
    req:
      url: https://example.test/stac
      collection: collection
layers:
  - name: stac_hdf5
    title: STAC HDF5
    sources: [stac_hdf5_latest]
""",
        encoding="utf-8",
    )

    conf = load_configuration(str(config_path))
    source = conf.layers["stac_hdf5"].wms_layer().map_layers[0]

    assert source.cache_dir == tmp_path / "cache_data" / "stac_hdf5_latest"


def test_requires_url_and_collection():
    with pytest.raises(ConfigurationError, match="req.url"):
        StacHdf5Source({"req": {"collection": "collection"}})
    with pytest.raises(ConfigurationError, match="req.collection"):
        StacHdf5Source({"req": {"url": "https://example.test/stac"}})


def test_cleanup_cache_keeps_newest_hdf5_files(tmp_path: Path):
    source = StacHdf5Source(
        {"req": {"url": "https://example.test/stac", "collection": "collection"}, "cache_dir": str(tmp_path), "cache_max_files": 2}
    )
    files = [tmp_path / f"sample-{idx}.h5" for idx in range(3)]
    for idx, path in enumerate(files):
        path.write_bytes(b"data")
        mtime = 100 + idx
        os.utime(path, (mtime, mtime))
    ignored = tmp_path / "notes.txt"
    ignored.write_text("keep me", encoding="utf-8")

    source.cleanup_cache()

    assert not files[0].exists()
    assert files[1].exists()
    assert files[2].exists()
    assert ignored.exists()


@pytest.mark.parametrize(
    ("conf", "message"),
    [
        ({"req": {"bbox_crs": "EPSG:4326"}}, "only supports CRS84"),
        ({"req": {"bbox": "16,54,7,58"}}, "ordered as min_lon"),
        ({"refresh_minutes": 0}, "refresh_minutes"),
        ({"cache_max_files": -1}, "cache_max_files"),
        ({"opacity": 300}, "opacity"),
        ({"min_value": 10, "max_value": 1}, "max_value"),
    ],
)
def test_rejects_invalid_config(conf, message):
    conf.setdefault("req", {})
    conf["req"].setdefault("url", "https://example.test/stac")
    conf["req"].setdefault("collection", "collection")
    with pytest.raises(ConfigurationError, match=message):
        StacHdf5Source(conf)

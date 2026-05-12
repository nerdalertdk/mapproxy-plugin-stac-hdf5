# Changelog

## 0.1.1 - 2026-05-12

- Fixed direct `stac_hdf5` layer reprojection for non-`EPSG:4326` requests by using MapProxy's `SupportedSRS` wrapper and a default resampling mode.
- Added `CRS:84` WMS service support to the example config and a regression test for direct `CRS:84` requests.

## 0.1.0 - 2026-05-12

- Created a MapProxy plugin project for serving HDF5 raster assets from a STAC-style API as WMS overlays.
- Registered the generic `stac_hdf5` MapProxy source type.
- Refactored away DMI-specific plugin naming; DMI is now only used as an example STAC-style endpoint.
- Added STAC item discovery through `<req.url>/collections/<req.collection>/items`.
- Added configurable request options with `req.url`, `req.collection`, `req.asset_key`, `req.params`, `req.bbox`, and `req.bbox_crs`.
- Added HDF5 rendering with support for common metadata attributes: `gain`, `offset`, `nodata`, and `undetect`.
- Added transparent PNG rendering and bbox cropping for WMS `GetMap` requests.
- Integrated with MapProxy's `WMSLikeSource`, `coverage`, image options, `HTTPClient`, and `on_error` handling.
- Defaulted downloaded HDF5 cache files to MapProxy's `globals.cache.base_dir/<source-name>`.
- Added cache cleanup with `cache_max_files`.
- Added startup validation for required STAC options, CRS84 bbox queries, coverage SRS, refresh interval, opacity, cache retention, and value range.
- Added example MapProxy configs with cached and direct layers: `stac_hdf5` and `stac_hdf5_direct`.
- Added Docker Compose support with a local image that installs the plugin into the MapProxy container.
- Simplified Docker Compose development setup to mount `examples/` as the MapProxy config directory and keep cache data ephemeral inside the container.
- Added GitHub Actions workflow that runs tests, builds package artifacts, uploads build artifacts, and creates a GitHub Release when a tag is pushed.
- Added `AGENTS.md` with workflow notes and references for MapProxy, STAC API Core, and the DMI sample endpoint.
- Added tests for HDF5 parsing, image rendering, bbox clipping, request construction, cache defaults, cache cleanup, and config validation.
- Fixed concurrent HDF5 downloads by using unique temporary filenames and handling another worker completing the same download first.
- Verified local tests, MapProxy config loading, Docker image build, container startup, and WMS PNG responses for cached and direct layers.

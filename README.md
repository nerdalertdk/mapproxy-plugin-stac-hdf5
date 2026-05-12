# mapproxy-plugin-stac-hdf5

MapProxy plugin that exposes the latest HDF5 raster asset from a STAC-style API as a transparent WMS overlay.

The plugin registers a new MapProxy source type named `stac_hdf5`. It queries a STAC-style collection item endpoint, downloads the configured HDF5 asset, renders it into a transparent image, and lets MapProxy serve it through the normal WMS layer/capabilities machinery.

## Install

```sh
pip install -e .
```

MapProxy discovers the plugin through the `mapproxy` Python entry point.

## MapProxy configuration

```yaml
services:
  demo:
  wms:
    md:
      title: STAC HDF5 overlay
      abstract: Latest HDF5 raster asset from a STAC-style API.

sources:
  stac_hdf5_latest:
    type: stac_hdf5
    req:
      url: https://example.test/stac
      collection: raster
      asset_key: data
      params:
        sortorder: datetime,DESC
    refresh_minutes: 60
    cache_max_files: 24
    opacity: 170
    coverage:
      bbox: [-180.0, -90.0, 180.0, 90.0]
      srs: EPSG:4326
    on_error:
      other:
        response: transparent
        cache: false

layers:
  - name: stac_hdf5
    title: STAC HDF5
    sources: [stac_hdf5_latest]
```

Then start MapProxy as usual:

```sh
mapproxy-util serve-develop mapproxy.yaml
```

Example WMS request:

```text
http://localhost:8080/service?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=stac_hdf5&STYLES=&CRS=EPSG:4326&BBOX=54,7,58,16&WIDTH=1024&HEIGHT=768&FORMAT=image/png&TRANSPARENT=true
```

## DMI example

The included `examples/mapproxy.yaml` uses DMI's STAC-style radar API as a concrete sample endpoint:

```yaml
req:
  url: https://opendataapi.dmi.dk/v1/radardata
  collection: composite
  asset_key: data
  params:
    scanType: fullRange
coverage:
  bbox: [7.0, 54.0, 16.0, 58.0]
  srs: EPSG:4326
```

DMI references:

- Documentation: https://www.dmi.dk/friedata/dokumentation/radar-data-api
- Swagger UI: https://opendataapi.dmi.dk/v1/radardata/swagger-ui/index.html
- Denmark bbox in CRS84 order: `7.0,54.0,16.0,58.0`

## Source options

| Option | Default | Purpose |
| --- | --- | --- |
| `req.url` | required | Base STAC-style API URL. The source requests `<url>/collections/<collection>/items`. |
| `req.collection` | required | STAC collection id. |
| `req.params` | unset | Extra query parameters sent to the provider item endpoint. |
| `req.asset_key` | `data` | Asset entry containing the downloadable HDF5 `href`. |
| `req.bbox` | unset | Optional query bbox in CRS84 order `min_lon,min_lat,max_lon,max_lat`. If unset, plugin uses MapProxy `coverage.bbox` when configured. |
| `req.bbox_crs` | `http://www.opengis.net/def/crs/OGC/1.3/CRS84` | Provider bbox CRS query value. |
| `coverage` | unset | Standard MapProxy coverage. Use this to set the overlay bbox and limit WMS requests. |
| `cache_dir` | `<globals.cache.base_dir>/<source-name>` | Optional override for downloaded HDF5 files. By default this uses MapProxy's cache base directory. |
| `cache_max_files` | `24` | Maximum number of downloaded HDF5 files to keep in the source cache. Use `0` to disable cleanup. |
| `refresh_minutes` | `60` | Minimum age before checking the provider for a newer asset. |
| `opacity` | `180` | Alpha value for non-transparent data pixels, 0-255. |
| `min_value` | `0.1` | Values at or below this are rendered transparent. |
| `max_value` | `60.0` | Upper bound used to normalize the color ramp. |
| `extent` | `[-180.0, -90.0, 180.0, 90.0]` | Fallback WGS84 extent before the first STAC item is fetched. |

The previous top-level `collection`, `bbox`, `bbox_crs`, `url`, `asset_key`, and `params` keys still work, but new configurations should prefer `req`.

HTTP options and `on_error` use MapProxy's normal source configuration. For example, set `http.client_timeout`, `http.headers`, or `on_error.other.response: transparent` exactly as you would for a built-in MapProxy source.

For production, prefer routing the layer through a MapProxy cache. See `examples/mapproxy.yaml` for a cached `stac_hdf5` layer plus a `stac_hdf5_direct` layer that is useful while debugging.

## Docker compose

This repository includes a local compose setup that builds a MapProxy image with the plugin installed:

```sh
docker compose up --build
```

The container mounts `examples/mapproxy.yaml` as its MapProxy config. Cache files live inside the container and are discarded when the container is removed.
The compose file binds port `80`; change the port mapping if that port is already in use. Stop and remove the container with:

```sh
docker compose down
```

## Release

Create and push a version tag, for example `0.1.0`, to run the GitHub Actions build and create a GitHub Release with the wheel and source distribution attached.

## Notes

The renderer uses common HDF5/ODIM metadata (`gain`, `offset`, `nodata`, `undetect`) when present and falls back to the first 2D numeric dataset named `data` if the file layout varies.

This first version renders directly in the source's requested coordinate space by treating the STAC WGS84 bbox as the raster extent. For best results, request the WMS layer in `EPSG:4326` or let MapProxy reproject from a cache/grid configured for that SRS.

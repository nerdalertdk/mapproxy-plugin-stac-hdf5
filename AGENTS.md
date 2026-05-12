# Agent Notes

This repository contains a MapProxy plugin that registers the `stac_hdf5` source type.

## Local Workflow

- Use the project virtual environment: `.venv/bin/python`.
- Run tests with `.venv/bin/python -m pytest`.
- Keep provider request options under `req:` in examples and docs.
- Use MapProxy `coverage` for bbox/extent behavior instead of plugin-specific bbox settings.

## Implementation Preferences

- Keep the plugin source compatible with MapProxy's `WMSLikeSource` flow.
- Preserve backwards compatibility for existing top-level source options when adding new `req:` options.
- Avoid committing local runtime artifacts: `.venv/`, `.pytest_cache/`, `*.egg-info/`, and HDF5 cache files.

## STAC/HDF5 Notes

- The plugin is generic and white-label: do not add provider presets yet.
- STAC API Core reference: https://api.stacspec.org/v1.0.0-beta.4/core/
- STAC item discovery uses `<req.url>/collections/<req.collection>/items`.
- BBOX query parameters use CRS84 coordinate order: `min_lon,min_lat,max_lon,max_lat`.

## DMI Sample Endpoint

- The example configs use DMI's STAC-style radar API only as a sample endpoint; keep provider-specific details out of the generic plugin implementation.
- Documentation: https://www.dmi.dk/friedata/dokumentation/radar-data-api
- Swagger UI: https://opendataapi.dmi.dk/v1/radardata/swagger-ui/index.html
- Denmark bbox in CRS84 order: `7.0,54.0,16.0,58.0`

## MapProxy References

- Full MapProxy docs: https://mapproxy.github.io/mapproxy/latest/index.html
- Plugin development: https://mapproxy.github.io/mapproxy/latest/plugins.html
- Source configuration: https://mapproxy.github.io/mapproxy/latest/sources.html
- Coverages: https://mapproxy.github.io/mapproxy/latest/coverages.html

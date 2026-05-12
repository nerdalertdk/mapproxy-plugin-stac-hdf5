"""MapProxy entry point for the STAC HDF5 plugin."""

from mapproxy.config.loader import register_source_configuration
from mapproxy.config.spec import anything, http_opts, on_error

from .source import StacHdf5SourceConfiguration


def plugin_entrypoint():
    register_source_configuration(
        "stac_hdf5",
        StacHdf5SourceConfiguration,
        "stac_hdf5",
        {
            "req": anything(),
            "coverage": anything(),
            "image": anything(),
            "transparent": bool(),
            "http": http_opts,
            "on_error": on_error,
            "url": str(),
            "collection": str(),
            "asset_key": str(),
            "bbox": str(),
            "bbox_crs": str(),
            "params": anything(),
            "cache_dir": str(),
            "cache_max_files": int(),
            "refresh_minutes": int(),
            "timeout": int(),
            "opacity": int(),
            "min_value": float(),
            "max_value": float(),
            "extent": [float()],
        },
    )

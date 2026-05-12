FROM ghcr.io/mapproxy/mapproxy/mapproxy:6.0.1-nginx

COPY . /plugin
USER root
RUN python -m pip install --no-cache-dir /plugin
RUN chown -R mapproxy:mapproxy /plugin
USER mapproxy:mapproxy

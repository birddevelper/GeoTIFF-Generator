FROM mosymosy1400/gdalpy:py-3.13-slim-GDAL-3.7.2

ENV PYTHONUNBUFFERED=1
ENV LC_ALL=C.UTF-8
ARG DEBIAN_FRONTEND=noninteractive

USER root


WORKDIR /app

RUN python3 -m venv /root/venv && \
    /root/venv/bin/pip install --upgrade pip && \
    /root/venv/bin/pip install wheel && \
    /root/venv/bin/pip install --no-cache-dir GDAL==$(gdal-config --version)

ENV PATH=/root/venv/bin:${PATH}

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

RUN printf '%s\n' \
    '#!/bin/sh' \
    'exec python /app/make_geotiff.py "$@"' \
    > /usr/local/bin/geotiff_maker && \
    chmod +x /usr/local/bin/geotiff_maker

# Optional: keep a default shell for interactive use.
CMD ["bash"]

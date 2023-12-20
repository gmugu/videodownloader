FROM python:3.9

COPY rootfs /

RUN set -evu; \
    pip install aiohttp aiohttp-cors aiohttp_session[secure]; \
    apt update; \
    apt install -y aria2 ffmpeg jq; \
    apt clean; \
    rm -rf /var/lib/apt/lists/*; \
    if [ $(uname -m) = "x86_64" ]; then \
        mv /temp/amd64/N_m3u8DL-RE /usr/local/bin/; \
    elif [ $(uname -m) = "aarch64" ]; then \
        mv /temp/arm64/N_m3u8DL-RE /usr/local/bin/; \
    else \
        echo "Not compatible with "$(uname -m)" architecture."; \
        exit 1; \
    fi; \
    rm -rf /temp; \
    chmod a+x /usr/local/bin/N_m3u8DL-RE /usr/local/bin/downloader.sh;

WORKDIR /app/

CMD (aria2c --enable-rpc --quiet & python video_download.py)
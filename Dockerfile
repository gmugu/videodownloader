FROM python:3.9

COPY rootfs /

RUN set -evu; \
    pip install aiohttp aiohttp-cors aiohttp_session[secure]; \
    apt update; \
    apt install -y aria2 ffmpeg; \
    apt clean; \
    rm -rf /var/lib/apt/lists/*; \
    if [ $(uname -m) = "x86_64" ]; then \
        aria2c "https://github.com/nilaoda/N_m3u8DL-RE/releases/download/v0.2.0-beta/N_m3u8DL-RE_Beta_linux-x64_20230628.tar.gz" --out=N_m3u8DL-RE_Beta.tar.gz; \
        tar xzf N_m3u8DL-RE_Beta.tar.gz; \
        mv N_m3u8DL-RE_Beta_linux-x64/N_m3u8DL-RE /usr/local/bin/; \
        rm -rf N_m3u8DL-RE_Beta_linux-x64 N_m3u8DL-RE_Beta.tar.gz; \
    elif [ $(uname -m) = "aarch64" ]; then \
        aria2c "https://github.com/nilaoda/N_m3u8DL-RE/releases/download/v0.2.0-beta/N_m3u8DL-RE_Beta_linux-arm64_20230628.tar.gz" --out=N_m3u8DL-RE_Beta.tar.gz; \
        tar xzf N_m3u8DL-RE_Beta.tar.gz; \
        mv N_m3u8DL-RE_Beta_linux-arm64/N_m3u8DL-RE /usr/local/bin/; \
        rm -rf N_m3u8DL-RE_Beta_linux-arm64 N_m3u8DL-RE_Beta.tar.gz; \
    else \
        echo "Not compatible with "$(uname -m)" architecture."; \
        exit 1; \
    fi; \
    chmod a+x /usr/local/bin/N_m3u8DL-RE /usr/local/bin/downloader.sh;

WORKDIR /app/

CMD [ "python", "video_download.py" ]
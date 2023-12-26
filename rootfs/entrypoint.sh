#!/bin/bash

aria2c --enable-rpc --quiet &

python video_download.py
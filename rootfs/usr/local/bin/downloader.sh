#!/bin/bash

set -eu

type=$1
url=$2
tmp_dir=$3
name=$4

if [ "$type" = "m3u8" ] || [ "$type" = "m3u8" ]; then

# N_m3u8DL-RE输出的文件名为tmp.mp4
echo "------开始使用 N_m3u8DL-RE 下载: N_m3u8DL-RE $url --tmp-dir $tmp_dir --save-dir $tmp_dir --save-name "tmp" --check-segments-count=false --auto-select"

N_m3u8DL-RE $url --tmp-dir $tmp_dir --save-dir $tmp_dir --save-name "tmp" --check-segments-count=false --auto-select

echo "------下载完成, 开始转码: ffmpeg -i $tmp_dir/tmp.mp4 -c copy $tmp_dir/$name"

ffmpeg -hide_banner -i "$tmp_dir/tmp.mp4" -c copy "$tmp_dir/$name"

else

echo "------开始使用 aria2 下载: aria2c $url --dir=$tmp_dir --out=$name -x8"

aria2c $url --dir=$tmp_dir --out=$name -x8

fi

echo "------完成"

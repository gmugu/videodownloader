#!/bin/bash

set -eu

type=$1
url=$2
tmp_dir=$3
name=$4
useproxy=$5
transcode=$6

rm -rf "$tmp_dir"

if [ "$type" = "m3u8" ] || [ "$type" = "m3u8" ]; then

# N_m3u8DL-RE输出的文件名为tmp.mp4
echo "------开始使用 N_m3u8DL-RE 下载: N_m3u8DL-RE \"$url\" --tmp-dir \"$tmp_dir\" --save-dir \"$tmp_dir\" --save-name \"tmp_$name\" --use-system-proxy=$useproxy --check-segments-count=false --auto-select  -M format=mp4 --force-ansi-console --noansi"

N_m3u8DL-RE "$url" --tmp-dir "$tmp_dir" --save-dir "$tmp_dir" --save-name "tmp_$name" --use-system-proxy=$useproxy --check-segments-count=false --auto-select  -M format=mp4 --force-ansi-console --noansi & pid=$!; echo "N_m3u8DL-RE_PID $pid"; wait $pid

  if [ "$transcode" = "true" ]; then
    echo "------下载完成, 开始转码: ffmpeg -hide_banner -i \"$tmp_dir/tmp_$name.mp4\" -c copy \"$tmp_dir/$name\""
    ffmpeg -hide_banner -i "$tmp_dir/tmp_$name.mp4" -c copy "$tmp_dir/$name"
  else
    mv "$tmp_dir/tmp_$name.mp4" "$tmp_dir/$name"
  fi

else

echo "------开始使用 aria2 下载(useproxy: $useproxy): aria2c \"$url\" \"--dir=$tmp_dir\" \"--out=$name\" -x8"

# aria2c "$url" "--dir=$tmp_dir" "--out=$name" -x8

PROXY_CTL=""
if [ "$useproxy" = "false" ]; then
  PROXY_CTL="\"all-proxy\": \"\", \"http-proxy\": \"\", \"https-proxy\": \"\","
fi

aria2c_url="http://localhost:6800/jsonrpc"
data=$(cat <<EOF
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "aria2.addUri",
  "params": [
    ["$url"],
    {
      $PROXY_CTL
      "dir": "$tmp_dir",
      "out": "$name",
      "split": "8"
    }
  ]
}
EOF
)

# 发送RPC请求
response=$(curl -s -X POST -d "$data" "$aria2c_url" -x "")

error=$(echo "$response" | jq -r .error)
if [ "$error" != "null" ]; then
  echo "RPC请求错误: $response"
  exit 1
fi

gid=$(echo "$response" | jq -r .result)
if [ "$gid" == "null" ]; then
  echo "RPC请求错误, 无法获取任务GID: $response"
  exit 1
fi
echo "Aria2_GID $gid"
data=$(cat <<EOF
{
  "jsonrpc": "2.0",
  "id": "$gid",
  "method": "aria2.tellStatus",
  "params": [
    "$gid"
  ]
}
EOF
)

while true; do
  response=$(curl -s -X POST -d "$data" "$aria2c_url" -x "")
  status=$(echo "$response" | jq -r '.result.status')

  if [[ $status == "error" ]]; then
    echo "下载任务出错: $response"
    rm "$tmp_dir/$name"
    exit 1
  elif [[ $status == "removed" ]]; then
    echo "下载任务已移除: $response"
    rm "$tmp_dir/$name"
    exit 1
  elif [[ $status == "complete" ]]; then
    echo "下载任务已完成: $response"
    break
  fi
  
  completed_length=$(echo "$response" | jq -r '.result.completedLength')
  total_length=$(echo "$response" | jq -r '.result.totalLength')
  download_speed=$(echo "$response" | jq -r '.result.downloadSpeed')
  echo "ARIA2 $completed_length $total_length $download_speed"
  sleep 1
done

fi

echo "------完成"

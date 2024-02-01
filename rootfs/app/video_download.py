#!/usr/bin/python3

import subprocess
import re
import aiohttp
from aiohttp import web
import asyncio
import aiohttp_cors
import threading
import os
import base64
import traceback
import shutil
import time
import signal
import json
from cryptography import fernet
from aiohttp_session import get_session, session_middleware
from aiohttp_session.cookie_storage import EncryptedCookieStorage

m3u8_speed_pattern = re.compile(r'\(\d+\)')

USER = os.environ.get('USER') or 'admin'
PASSWORD = os.environ.get('PASSWORD') or '123456'
DOWNLOAD_DIR = os.environ.get('VIDEO_DIR') or '.'
DOWNLOAD_PATHS = DOWNLOAD_DIR.split(',')
MAX_DOWNLOAD_COUNT = os.environ.get('MAX_DOWNLOAD_COUNT')
MAX_DOWNLOAD_COUNT = int(MAX_DOWNLOAD_COUNT) if MAX_DOWNLOAD_COUNT else 3

PORT_NUMBER = 8094

COOKIE_EXPIRATION_DATE = 30 * 24 * 60 * 60

status_queue_map = []

download_ready = []
downloading = []
downloaded = []
download_failed = []

downloading_proc = {}

_cache_id = 0

def _getTmpDir(download_path):
    return f'{download_path}/.tmp'

def _sanitize_filename(filename):
    cleaned_filename = filename.strip()
    # 替换非法字符
    cleaned_filename = re.sub(r'[\\/:"*?<>|]', '_', cleaned_filename)
    # 缩短文件名长度
    max_length = 255  # 文件名长度限制
    if len(cleaned_filename) > max_length:
        cleaned_filename = cleaned_filename[:max_length]
    return cleaned_filename

def _genCacheId():
    global _cache_id
    _cache_id = _cache_id + 1
    return _cache_id


def _notiftRealtimeStatus(info):
    for status_queue in status_queue_map:
        status_queue.put_nowait(info)


async def status(request):
    response = web.StreamResponse()
    response.headers["Content-type"] = "text/event-stream"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    try:
        await response.prepare(request)
    except Exception as e:
        # traceback.print_exc()
        return response

    await response.write(bytes("event: message\n", "utf-8"))

    fileInfoList = {
        "type": "downloaded",
        "data": downloaded,
    }
    await response.write(bytes(f"data: {json.dumps(fileInfoList)}\n\n", "utf-8"))
    fileInfoList = {
        "type": "download_failed",
        "data": download_failed,
    }
    await response.write(bytes(f"data: {json.dumps(fileInfoList)}\n\n", "utf-8"))
    fileInfoList = {
        "type": "download_ready",
        "data": download_ready,
    }
    await response.write(bytes(f"data: {json.dumps(fileInfoList)}\n\n", "utf-8"))
    # fileInfoList = {
    #     "type": "downloading",
    #     "data": downloading,
    # }
    # await response.write(bytes(f"data: {json.dumps(fileInfoList)}\n\n", "utf-8"))

    status_queue = asyncio.Queue()
    try:
        status_queue_map.append(status_queue)
        while True:
            info = await status_queue.get()
            await response.write(bytes(f"data: {json.dumps(info)}\n\n", "utf-8"))
    except Exception as e:
        # traceback.print_exc()
        try:
            await response.write(bytes("event: error\n", "utf-8"))
            await response.write(bytes(f"data: {traceback.format_exc()}\n\n", "utf-8"))
        except Exception as e:
            # traceback.print_exc()
            return response
    finally:
        status_queue_map.remove(status_queue)


async def cache(request):
    data = await request.json()
    if "path" not in data or data["path"] not in DOWNLOAD_PATHS:
        return web.json_response({"status": "fail", "msg": "path not in DOWNLOAD_PATHS"})
    cache_id = _genCacheId()
    download_ready.append(
        {
            "cacheId": cache_id,
            "url": data["url"],
            "type": data["type"],
            "path": data["path"],
            "name": _sanitize_filename(data["name"]),
            "transcode": data.get("transcode", True),
            "useproxy": data.get("useproxy", True),
            "time": time.time(),
        }
    )
    _notiftRealtimeStatus(
        {
            "type": "download_ready",
            "data": download_ready,
        }
    )
    return web.json_response({"status": "success", "cacheId": cache_id})


async def cancel(request):
    data = await request.json()
    cache_id = data["cacheId"]
    try:
        for item in download_failed:
            if item["cacheId"] == cache_id:
                download_failed.remove(item)
                _notiftRealtimeStatus(
                    {
                        "type": "download_failed",
                        "data": download_failed,
                    }
                )
                return web.json_response({"status": "success"})
        for item in download_ready:
            if item["cacheId"] == cache_id:
                download_ready.remove(item)
                _notiftRealtimeStatus(
                    {
                        "type": "download_ready",
                        "data": download_ready,
                    }
                )
                return web.json_response({"status": "success"})

        proc = downloading_proc.get(cache_id)
        if proc:
            if proc["type"] == 1:#N_m3u8DL-RE
                os.kill(int(proc["PID"]), signal.SIGKILL)
            elif proc["type"] == 2:#Aric2
                gid = proc['GID']
                payload = {
                    'jsonrpc': '2.0',
                    'id': gid,
                    'method': 'aria2.forceRemove',
                    'params': [ gid ]
                }
                async with aiohttp.ClientSession() as session:
                    async with session.post('http://localhost:6800/jsonrpc', json=payload) as response:
                        data = await response.json()
                        print(data)
                        if response.status != 200:
                            return web.json_response({"status": "fail", "msg": "Failed to cancel task: response.status != 200"})
        else:
            return web.json_response({"status": "fail", "msg": "cacheId不存在"})
        return web.json_response({"status": "success"})
    except Exception as e:
        traceback.print_exc()
        return web.json_response({"status": "fail", "msg": traceback.format_exc()})

async def getpaths(request):
    return web.json_response({"status": "success", "paths": DOWNLOAD_PATHS})

async def refreshFileList(request):
    try:
        _updateDownloaded()
        _notiftRealtimeStatus(
            {
                "type": "downloaded",
                "data": downloaded,
            }
        )
        return web.json_response({"status": "success"})
    except Exception as e:
        traceback.print_exc()
        return web.json_response({"status": "fail", "msg": traceback.format_exc()})

async def deleteFile(request):
    try:
        data = await request.json()
        filepath = data["filename"]
        isPipei = False
        for path in DOWNLOAD_PATHS:
            if filepath.startswith(path + '/'):
                isPipei = True
                break
        if not isPipei:
            return web.json_response({"status": "fail", "msg": "path not in DOWNLOAD_PATHS"})

        if os.path.exists(filepath):
            if os.path.isfile(filepath):
                os.remove(filepath)
            else:
                os.rmdir(filepath)
            _updateDownloaded()
            _notiftRealtimeStatus(
                {
                    "type": "downloaded",
                    "data": downloaded,
                }
            )
            return web.json_response({"status": "success"})
        else:
            return web.json_response({"status": "fail", "msg": "file not exists"})
    except Exception as e:
        traceback.print_exc()
        return web.json_response({"status": "fail", "msg": traceback.format_exc()})

async def _cacheVideo(param):
    try:
        cache_id = param["cacheId"]
        url = param["url"]
        type = param["type"]
        path = param["path"]
        name = param["name"] if param["name"] else 'unnamed'
        transcode = param["transcode"]
        useproxy = param["useproxy"]

        file_name, file_ext = os.path.splitext(name)
        if not file_ext:
            file_ext = '.mp4'
            name = f"{name}{file_ext}"

        for p in downloaded:
            if p["isDir"] and p["name"] == path:
                for item in p["childs"]:
                    if item["name"] == name:
                        name = f"{file_name}.{cache_id}{file_ext}"
                        break
        for item in downloading:
            if item["name"] == name:
                name = f"{file_name}.{cache_id}{file_ext}"
                break


        param["name"] = name

        tmp_dir = f"{_getTmpDir(path)}_{cache_id}"

        print(f"try download {url}, filename: {name}", flush=True)

        proc = subprocess.Popen(
            [
                "downloader.sh",
                type,
                url,
                tmp_dir,
                name,
                "true" if useproxy else "false",
                "true" if transcode else "false",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        def run(param, proc):
            cache_id = param["cacheId"]
            path = param["path"]
            name = param["name"]
            type = param["type"]

            try:
                for line in iter(proc.stdout.readline, b""):
                    line = line.decode("utf-8")
                    line = line.replace("\n", "")
                    if line == '':
                        continue

                    if line.startswith("N_m3u8DL-RE_PID"):
                        ls = line.split(' ')
                        downloading_proc[cache_id] = {"type": 1, "PID": ls[1]}

                    if line.startswith("Aria2_GID"):
                        ls = line.split(' ')
                        downloading_proc[cache_id] = {"type": 2, "GID": ls[1]}

                    if line.startswith("Vid"):
                        line = line.replace("━", "")
                        ls = line.split(' ')
                        for item in reversed(ls):
                            if 'Bps' in item:
                                param["speed"] = m3u8_speed_pattern.sub('', item)
                                continue
                            if item.endswith('%'):
                                param["progress"] = item
                                break

                    if line.startswith("ARIA2"):
                        ls = line.split(' ')
                        completed_length = int(ls[1])
                        total_length = int(ls[2])
                        speed = int(ls[3])
                        if total_length > 0:
                            param["progress"] = f"{round(completed_length / total_length * 100, 2)}%"
                            if speed >= 1000000:
                                param["speed"] = f"{round(speed / 1000000, 2)}MBps"
                            elif speed >= 1000:
                                param["speed"] = f"{round(speed / 1000, 2)}KBps"
                            else:
                                param["speed"] = f"{speed}Bps"

                    print(line, flush=True)

            except Exception as e:
                traceback.print_exc()
            finally:
                tmp_file_path = f"{_getTmpDir(path)}_{cache_id}/{name}"

                if os.path.exists(tmp_file_path):
                    shutil.move(f"{tmp_file_path}", f"{path}/{name}")
                    if os.path.exists(f"{_getTmpDir(path)}_{cache_id}"):
                        shutil.rmtree(f"{_getTmpDir(path)}_{cache_id}")
                    _updateDownloaded()
                    _notiftRealtimeStatus(
                        {
                            "type": "downloaded",
                            "data": downloaded,
                        }
                    )
                else:
                    print("文件不存在，下载失败或下载取消", flush=True)
                    param["time_download_failed"] = time.time()
                    download_failed.append(param)
                    _notiftRealtimeStatus(
                        {
                            "type": "download_failed",
                            "data": download_failed,
                        }
                    )
                downloading.remove(param)
                _notiftRealtimeStatus(
                    {
                        "type": "downloading",
                        "data": downloading,
                    }
                )

                if cache_id in downloading_proc:
                    downloading_proc.pop(cache_id)
                if os.path.exists(f"{_getTmpDir(path)}_{cache_id}"):
                    shutil.rmtree(f"{_getTmpDir(path)}_{cache_id}")

        threading.Thread(target=run, args=(param, proc)).start()

    except Exception as e:
        traceback.print_exc()
        _notiftRealtimeStatus({"type": "error", "data": traceback.format_exc()})


async def _task():
    while True:
        await asyncio.sleep(1)
        try:
            if len(downloading) < MAX_DOWNLOAD_COUNT:
                if len(download_ready) > 0:
                    item = download_ready.pop(0)
                    _notiftRealtimeStatus(
                        {
                            "type": "download_ready",
                            "data": download_ready,
                        }
                    )

                    await _cacheVideo(item)
                    # item["time_downloading"] = time.time()
                    downloading.append(item)
                    _notiftRealtimeStatus({"type": "downloading", "data": downloading})

                    continue

            # _notiftRealtimeStatus({"type": "heard"})
            _notiftRealtimeStatus({"type": "downloading", "data": downloading})
        except:
            traceback.print_exc()

def _get_disk_free_space(path):
    stat = os.statvfs(path)
    # 获取每个块的大小
    block_size = stat.f_frsize
    # 获取可用块的数量
    available_blocks = stat.f_bavail
    # 计算剩余空间
    free_space = available_blocks * block_size
    return free_space
    
def _getDir(path, retList):
    for filename in os.listdir(path):
        file_path = os.path.join(path, filename)    # 获取文件路径
        file_stat = os.stat(file_path)              # 获取文件信息
        isDir = not os.path.isfile(file_path)

        childs = None
        if isDir:
            childs = []
            _getDir(file_path, childs)
        retList.append(
            {
                "name": filename,
                "time": file_stat.st_ctime,
                "size": file_stat.st_size,
                "isDir": isDir,
                "childs": childs,
            }
        )

def _updateDownloaded():
    downloaded.clear()
    downloaded.append(
        {
            "name": '__FREE_SIZE__',
            "time": 0,
            "size": _get_disk_free_space(DOWNLOAD_PATHS[0]),
            "isDir": False,
        }
    )

    for file_path in DOWNLOAD_PATHS:
        file_stat = os.stat(file_path)
        isDir = not os.path.isfile(file_path)

        childs = None
        if isDir:
            childs = []
            _getDir(file_path, childs)
        downloaded.append(
            {
                "name": file_path,
                "time": file_stat.st_ctime,
                "size": file_stat.st_size,
                "isDir": isDir,
                "childs": childs,
            }
        )

async def index(request):
    raise web.HTTPFound('/index.html')

login_failures = {}

@web.middleware
async def auth_middleware(request: web.Request, handler) -> web.StreamResponse:
    print(f'{request.method} {request.path}', flush=True)
    if request.method != 'OPTIONS':
        session = await get_session(request)
        last_visit = session['last_visit'] if 'last_visit' in session else None
        if (last_visit is None) or (time.time() - last_visit > COOKIE_EXPIRATION_DATE):
            
            ip_address = request.headers.get('X-Real-IP') or request.headers.get('X-Forwarded-For') or request.remote
            # print(f'rueqest ip: {ip_address}', flush=True)

            lf = login_failures.get(ip_address, {'login_fail_count': 0, 'login_fail_time': 0})
            login_fail_count = lf['login_fail_count']
            login_fail_time = lf['login_fail_time']
            if login_fail_count >= 5 and time.time() - login_fail_time < 300:
                return web.Response(status=401, text='Too many login attempts. Please wait for 5 minutes.')
            
            auth_header = request.headers.get('Authorization')
            if auth_header is None:
                return web.Response(status=401, headers={'WWW-Authenticate': 'Basic realm="Restricted Area"'}, text='Unauthorized')
            auth_bytes = base64.b64decode(auth_header.split(' ')[1])
            auth_string = auth_bytes.decode('utf-8')
            if ':' not in auth_string:
                return web.Response(status=401, text='Unauthorized: Invalid format')
            username, password = auth_string.split(':')
            if username != USER or password != PASSWORD:
                login_failures[ip_address] = {'login_fail_count': login_fail_count + 1, 'login_fail_time': time.time()}
                return web.Response(status=401, text='Unauthorized: Incorrect username or password.')
            else:
                session['last_visit'] = time.time()
                
                login_failures[ip_address] = {'login_fail_count': 0, 'login_fail_time': 0}

    # 调用下一个中间件或处理程序
    response = await handler(request)
    return response


if __name__ == "__main__":
    print("running", flush=True)

    _updateDownloaded()
    app = web.Application()
    
    routes = [
        web.get("/", index),
        web.get("/api/status", status),
        web.post("/api/cache", cache),
        web.post("/api/cancel", cancel),
        web.post("/api/getpaths", getpaths),
        web.post("/api/refreshFileList", refreshFileList),
        web.post("/api/deleteFile", deleteFile),
    ]
    for file_path in DOWNLOAD_PATHS:
        routes.append(web.static(f'/file{file_path}/', path=file_path))
    routes.append(web.static('/', path='static'))
    app.add_routes(routes)

    # session管理
    fernet_key = fernet.Fernet.generate_key()
    app.middlewares.append(session_middleware(EncryptedCookieStorage(fernet.Fernet(fernet_key), max_age=COOKIE_EXPIRATION_DATE)))
    
    app.middlewares.append(auth_middleware)

    cors = aiohttp_cors.setup(app, defaults={
        "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
            )
    })
    # 允许所有的跨域请求
    for route in list(app.router.routes()):
        cors.add(route)

    loop = asyncio.get_event_loop()

    loop.create_task(_task())

    web.run_app(app, port=PORT_NUMBER, loop=loop)


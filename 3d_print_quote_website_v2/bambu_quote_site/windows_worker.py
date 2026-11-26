"""Outbound-only Bambu Studio worker for the Render quote relay."""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

PRINTER_PRESETS = {
    "mini": ("Bambu Lab A1 mini 0.4 nozzle", "0.20mm Standard @BBL A1M", "Generic PETG @BBL A1M"),
    "a2l": ("Bambu Lab A2L 0.4 nozzle", "0.20mm Standard @BBL A2L", "Generic PETG @BBL A2L"),
}
KINDS = ("machine", "process", "filament")
MODEL_LIMIT = 35 * 1024 * 1024


def resolve_preset(folder, name, visited=()):
    if name in visited or any(char in name for char in "/\\"):
        raise ValueError("Bambu Studio 設定檔繼承無效。")
    with (folder / (name + ".json")).open(encoding="utf-8-sig") as stream:
        preset = json.load(stream)
    chain = (*visited, name)
    parent = preset.pop("inherits", None)
    includes = preset.pop("include", [])
    resolved = resolve_preset(folder, parent, chain) if parent else {}
    for key in includes:
        resolved.update(resolve_preset(folder, key, chain))
    resolved.update(preset)
    return resolved


def load_profiles(resource_folder):
    profiles = {}
    for printer, names in PRINTER_PRESETS.items():
        try:
            profiles[printer] = {
                kind: resolve_preset(resource_folder / kind, name)
                for kind, name in zip(KINDS, names)
            }
        except (OSError, ValueError, TypeError) as error:
            print(f"{printer} 的設定檔無法載入：{error}", flush=True)
    return profiles


def check_model(path):
    if path.suffix == ".stl":
        return
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 1024 or sum(item.file_size for item in entries) > 180 * 1024 * 1024:
            raise ValueError("3MF 內容過大，請簡化模型後再上傳。")
        for item in entries:
            name = item.filename.lower()
            if name.endswith(".gcode"):
                raise ValueError("請使用未切片的 3MF，或在網站匯入切片結果。")
            if name == "metadata/project_settings.config" and item.file_size < 2 * 1024 * 1024:
                config = json.loads(archive.read(item))
                if any(isinstance(config.get(k), list) and len(config[k]) > 1
                       for k in ("filament_type", "filament_settings_id")):
                    raise ValueError("自動切片目前支援單材料模型，請用單一耗材或匯出 STL。")


def read_metrics(path):
    with zipfile.ZipFile(path) as archive:
        entry = archive.getinfo("Metadata/slice_info.config")
        if entry.file_size > 1024 * 1024:
            raise ValueError("切片摘要超過可讀取大小。")
        root = ET.fromstring(archive.read(entry))
    grams = 0.0
    seconds = 0.0
    plates = 0
    for plate in root.findall("plate"):
        metadata = {row.get("key"): row.get("value") for row in plate.findall("metadata")}
        if not metadata.get("prediction") or not metadata.get("weight"):
            continue
        filaments = plate.findall("filament")
        if any(f.get("type", "").upper() != "PETG" for f in filaments):
            raise ValueError("切片包含 PETG 以外的材料，請檢查 3MF 設定或改用 STL。")
        grams += float(metadata["weight"])
        seconds += float(metadata["prediction"])
        plates += 1
    if not (plates and 0 < grams < 100000 and 0 < seconds < 604800):
        raise ValueError("Bambu Studio 切片缺少有效的重量與時間。")
    return {"grams": round(grams, 6), "seconds": round(seconds, 6)}


def slice_model(cli, profiles, data, filename, support):
    if filename not in {"model.stl", "model.3mf"} or len(data) > MODEL_LIMIT:
        raise ValueError("模型格式或大小不正確。")
    with tempfile.TemporaryDirectory(prefix="fdm-quote-") as temp:
        workdir = Path(temp)
        model = workdir / filename
        model.write_bytes(data)
        check_model(model)
        settings = {}
        for kind, profile in profiles.items():
            config = dict(profile)
            if kind == "process":
                config.update(layer_height="0.2", sparse_infill_density="15%",
                              enable_support="1" if support == "on" else "0")
            settings[kind] = workdir / (kind + ".json")
            settings[kind].write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        command = [
            str(cli), "--debug", "2", "--datadir", str(workdir / "cli-data"),
            "--load-settings", f"{settings['machine']};{settings['process']}",
            "--load-filaments", str(settings["filament"]), "--curr-bed-type", "Textured PEI Plate",
            "--arrange", "1", "--ensure-on-bed", "--slice", "0",
            "--outputdir", str(workdir), "--export-3mf", "sliced.3mf", str(model),
        ]
        completed = subprocess.run(command, cwd=cli.parent, capture_output=True, timeout=255, check=False)
        output = workdir / "sliced.3mf"
        if completed.returncode or not output.is_file():
            details = (completed.stderr + completed.stdout).decode("utf-8", "replace")
            print(details[-2400:], flush=True)
            raise ValueError("Bambu Studio 無法切片。請確認模型尺寸、朝向與完整性。")
        return read_metrics(output)


class Client:
    def __init__(self, origin, token, printers):
        self.origin = origin
        self.headers = {
            "Authorization": "Bearer " + token,
            "X-Worker-ID": uuid4().hex,
            "X-Worker-Printers": ",".join(printers),
        }

    def exchange(self, method, path, data=None):
        headers = dict(self.headers)
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.origin + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(MODEL_LIMIT + 1)
            return response.status, response.headers, payload


def run(client, cli, profiles):
    pending = None
    future = None
    with ThreadPoolExecutor(max_workers=1) as executor:
        while True:
            try:
                client.exchange("POST", "/api/worker/heartbeat", b"")
                if future and future.done():
                    try:
                        result = future.result()
                    except (ValueError, subprocess.TimeoutExpired, zipfile.BadZipFile, KeyError, ET.ParseError) as error:
                        print("切片工作失敗：" + str(error), flush=True)
                        result = {"error": "切片失敗或輸出缺少有效資料，請在 Windows 檢查模型與 Bambu Studio。"}
                        if isinstance(error, ValueError):
                            result["error"] = str(error)[:240]
                    try:
                        client.exchange("POST", "/api/worker/result/" + pending,
                                        json.dumps(result).encode("utf-8"))
                    except urllib.error.HTTPError as error:
                        if error.code != 404:
                            raise
                    print("工作已處理 " + pending[:8], flush=True)
                    pending = None
                    future = None
                if future is None:
                    status, headers, data = client.exchange("GET", "/api/worker/next")
                    if status == 200:
                        pending = headers["X-Job-ID"]
                        preset = profiles[headers["X-Printer"]]
                        future = executor.submit(slice_model, cli, preset, data,
                                                 headers["X-Filename"], headers["X-Support"])
            except (urllib.error.URLError, TimeoutError) as error:
                print("橋接連線失敗：" + str(error), flush=True)
            time.sleep(4)


def main():
    origin = os.getenv("QUOTE_SITE_URL", "https://threed-print-quote.onrender.com").rstrip("/")
    token = os.getenv("QUOTE_BRIDGE_TOKEN", "")
    default_cli = Path(os.getenv("ProgramFiles", r"C:\Program Files")) / "Bambu Studio" / "bambu-studio.exe"
    cli = Path(os.getenv("BAMBU_STUDIO_CLI", str(default_cli))).resolve()
    candidates = [cli.parent / "resources", cli.parent.parent / "resources"]
    default_resources = next((p for p in candidates if (p / "profiles" / "BBL").is_dir()), candidates[0])
    resources = Path(os.getenv("BAMBU_STUDIO_RESOURCES", str(default_resources)))
    if not cli.is_file() or not (resources / "profiles" / "BBL").is_dir():
        sys.exit("找不到 Bambu Studio 或機型資源。請確認安裝或設定 BAMBU_STUDIO_CLI、BAMBU_STUDIO_RESOURCES。")
    if (not origin.startswith("https://") and not origin.startswith("http://127.0.0.1:")) or len(token) < 32:
        sys.exit("請設定 HTTPS 網址與 Render 已有的 QUOTE_BRIDGE_TOKEN。")
    profiles = load_profiles(resources / "profiles" / "BBL")
    if not profiles:
        sys.exit("沒有可用的 Bambu Studio 機型設定。請更新到同時包含 A1 mini 與 A2L 的版本。")
    print("Bambu Studio 切片橋接已啟動：" + ", ".join(profiles), flush=True)
    try:
        run(Client(origin, token, profiles), cli, profiles)
    except KeyboardInterrupt:
        print("Windows 切片橋接已停止。", flush=True)


if __name__ == "__main__":
    main()

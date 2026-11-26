"""Render relay for the private Sites estimator and outbound slicer."""
import hashlib
import hmac
import math
import os
from pathlib import Path
from threading import Lock
from time import monotonic
from uuid import uuid4

from flask import Flask, Response, jsonify, request

app = Flask(__name__)
MAX_MODEL_BYTES = 35 * 1024 * 1024
app.config["MAX_CONTENT_LENGTH"] = MAX_MODEL_BYTES + 65536

PRINTERS = {"mini": "Bambu Lab A1 mini", "a2l": "Bambu Lab A2L"}
MODEL_FORMATS = {".stl", ".3mf", ".step", ".stp"}
BASE_FORMATS = {".stl", ".3mf"}
WORKER_TOKEN = os.getenv("QUOTE_BRIDGE_TOKEN", "")
# Verifier for the independent, randomly generated Sites credential.
SITE_VERIFIER = os.getenv("QUOTE_SITE_TOKEN_SHA256", "74bf75b2df58a3ca2603a97283abbde5064a5bffe03fb06bdd8a8e3732c578b6")
JOB_TTL = 12 * 60
WORK_TTL = 320
HEARTBEAT_TTL = 25
jobs = {}
workers = {}
lock = Lock()


def bearer():
    auth = request.headers.get("Authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else ""


def authorized_site():
    token = bearer()
    return bool(token) and hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), SITE_VERIFIER)


def authorized_worker():
    token = bearer()
    return bool(WORKER_TOKEN and token) and hmac.compare_digest(token.encode(), WORKER_TOKEN.encode())


def unauthorized():
    return jsonify(error="Unauthorized"), 401


def available_formats(now):
    for worker in list(workers):
        if now - workers[worker][0] > HEARTBEAT_TTL:
            del workers[worker]
    available = {}
    for _, printers, formats in workers.values():
        for printer in printers:
            if formats:
                available.setdefault(printer, set()).update(formats)
    return available


def maintain(now):
    available = available_formats(now)
    for job_id, job in list(jobs.items()):
        if now - job["created"] > JOB_TTL:
            del jobs[job_id]
        elif job["state"] == "working" and now - job["started"] > WORK_TTL:
            job.update(state="error", error="切片逾時，請確認 Windows 電腦後重新上傳。")
        elif (job["state"] == "queued" and now - job["created"] > 60
              and job["ext"] not in available.get(job["printer"], set())):
            job.update(state="error", error="Windows 切片電腦已離線，請重新上傳。", data=b"")
    return available


@app.after_request
def private_response(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/")
def index():
    return "", 204


@app.get("/healthz")
def health():
    return "", 204


@app.get("/api/status")
def status():
    if not authorized_site():
        return unauthorized()
    with lock:
        available = maintain(monotonic())
        code = None if available else "BRIDGE_UPDATE_REQUIRED" if workers else "BRIDGE_OFFLINE"
    return jsonify(mode="windows_bridge", slicing_ready=bool(available), printers=sorted(available),
                   step_printers=sorted(p for p, f in available.items() if ".step" in f), code=code)


@app.post("/api/quote")
def submit():
    if not authorized_site():
        return unauthorized()
    model = request.files.get("model")
    ext = Path(model.filename or "").suffix.lower() if model else ""
    if ext not in MODEL_FORMATS or model.filename.lower().endswith(".gcode.3mf"):
        return jsonify(error="請上傳 STL、未切片的 3MF 或 STEP（.step／.stp）。"), 400
    printer = request.form.get("printer")
    try:
        quantity = int(request.form.get("quantity", "1"))
    except ValueError:
        quantity = 0
    if printer not in PRINTERS or not 1 <= quantity <= 100:
        return jsonify(error="請確認機型與份數。"), 400
    data = model.stream.read(MAX_MODEL_BYTES + 1)
    if not data or len(data) > MAX_MODEL_BYTES:
        return jsonify(error="請上傳 35 MB 以內的非空模型。"), 413
    now = monotonic()
    with lock:
        available = maintain(now)
        if printer not in available:
            return jsonify(error="此機型的 Windows 切片電腦目前離線。"), 503
        if ext not in available[printer]:
            return jsonify(error="此機型的 STEP 轉檔元件尚未啟用。請在 Windows 啟動新版橋接時完成安裝。",
                           code="STEP_UNAVAILABLE"), 503
        if sum(job["state"] in {"queued", "working"} for job in jobs.values()) >= 2:
            return jsonify(error="切片佇列已滿，請稍後再試。"), 429
        job_id = uuid4().hex
        jobs[job_id] = dict(created=now, state="queued", printer=printer, ext=ext,
                            quantity=quantity, filename="model" + ext, data=data)
    return jsonify(job_id=job_id, state="queued"), 202


@app.get("/api/quote/<job_id>")
def result(job_id):
    if not authorized_site():
        return unauthorized()
    with lock:
        maintain(monotonic())
        job = jobs.get(job_id)
        if not job:
            return jsonify(error="此工作已失效，請重新上傳。"), 404
        response = {"state": job["state"]}
        if job["state"] == "done":
            response.update(job["metrics"], printer=PRINTERS[job["printer"]],
                            support="on", quantity=job["quantity"])
        elif job["state"] == "error":
            response["error"] = job["error"]
            if job.get("code"):
                response["code"] = job["code"]
    return jsonify(response)


def register_worker():
    worker = request.headers.get("X-Worker-ID", "")
    requested = request.headers.get("X-Worker-Printers", "").split(",")
    printers = set(requested).intersection(PRINTERS)
    if not worker or len(worker) > 64 or not printers:
        return "", set(), set()
    formats = set()
    if request.headers.get("X-Worker-Protocol") == "2":
        formats = MODEL_FORMATS if request.headers.get("X-Worker-Step") == "1" else BASE_FORMATS
    workers[worker] = (monotonic(), printers, formats)
    return worker, printers, formats


@app.post("/api/worker/heartbeat")
def heartbeat():
    if not authorized_worker():
        return unauthorized()
    with lock:
        maintain(monotonic())
        worker, _, _ = register_worker()
    if not worker:
        return jsonify(error="請更新 Windows 橋接並確認 Bambu Studio 機型參數。"), 409
    return jsonify(ok=True)


@app.get("/api/worker/next")
def next_job():
    if not authorized_worker():
        return unauthorized()
    with lock:
        now = monotonic()
        maintain(now)
        worker, printers, formats = register_worker()
        if not worker:
            return jsonify(error="請更新 Windows 橋接。"), 409
        for job_id, job in jobs.items():
            if job["state"] != "queued" or job["printer"] not in printers or job["ext"] not in formats:
                continue
            payload = job["data"]
            job.update(state="working", started=now, worker=worker, data=b"")
            return Response(payload, content_type="application/octet-stream", headers={
                "X-Job-ID": job_id, "X-Printer": job["printer"],
                "X-Filename": job["filename"],
            })
    return "", 204


@app.post("/api/worker/result/<job_id>")
def publish(job_id):
    if not authorized_worker():
        return unauthorized()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Invalid result"), 400
    with lock:
        maintain(monotonic())
        job = jobs.get(job_id)
        if not job or job.get("worker") != request.headers.get("X-Worker-ID"):
            return jsonify(error="Job expired"), 404
        if job["state"] in {"done", "error"}:
            return jsonify(ok=True)
        error = data.get("error")
        if isinstance(error, str) and error:
            job.update(state="error", error=error[:240])
            if data.get("code") == "OUTSIDE_BUILD_VOLUME":
                job["code"] = "OUTSIDE_BUILD_VOLUME"
        else:
            try:
                grams, seconds = float(data["grams"]), float(data["seconds"])
                if not (math.isfinite(grams) and math.isfinite(seconds) and 0 < grams < 100000 and 0 < seconds < 604800):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                return jsonify(error="Invalid result"), 400
            job.update(state="done", metrics=dict(grams=grams, seconds=seconds))
    return jsonify(ok=True)


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="模型上限為 35 MB。"), 413

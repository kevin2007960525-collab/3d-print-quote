import os, re, io, zipfile, tempfile, subprocess, math, time, uuid, threading, secrets
from pathlib import Path
from flask import Flask, request, jsonify, render_template, make_response
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 35 * 1024 * 1024
BASE = Path(__file__).resolve().parent
PRINTERS = {'mini': {'name':'A1 mini','volume':[180,180,180]}, 'a2l':{'name':'A2L','volume':[330,320,325]}}
ALLOWED = {'.stl','.3mf'}
# Single-process ephemeral queue for a hobby deployment. Jobs are lost if Render sleeps or restarts.
JOBS = {}
JOBS_LOCK = threading.Lock()
JOB_TTL = 12 * 60
BRIDGE_TOKEN = os.environ.get('QUOTE_BRIDGE_TOKEN','')

def prune_jobs():
    now=time.time()
    for k, j in list(JOBS.items()):
        if now-j['created']>JOB_TTL: JOBS.pop(k,None)

def authenticated_worker():
    given=request.headers.get('Authorization','').removeprefix('Bearer ').strip()
    return bool(BRIDGE_TOKEN and given and secrets.compare_digest(given,BRIDGE_TOKEN))


def quote(grams, minutes, quantity):
    unit = grams + minutes * 0.5
    total = unit * quantity
    return dict(material=round(grams*quantity,2),time=round(minutes*.5*quantity,2),unit_price=round(unit,2),total=round(total,2),deposit=round(total*.2,2) if grams*quantity>350 else 0,deposit_applicable=grams*quantity>350)

def parse_gcode_meta(text):
    def get(patterns):
        for pattern in patterns:
            match=re.search(pattern,text,re.I|re.M)
            if match: return float(match.group(1))
        return None
    gram=get([r'^;\s*total filament used\s*\[g\]\s*[:=]\s*([\d.]+)',r'^;\s*filament used\s*\[g\]\s*[:=]\s*([\d.]+)',r'^;\s*total filament weight\s*[:=]\s*([\d.]+)',r'^;\s*filament used\s*:\s*([\d.]+)\s*g'])
    sec=get([r'^;\s*estimated printing time\s*\[s\]\s*[:=]\s*([\d.]+)',r'^;\s*total estimated time\s*[:=]\s*([\d.]+)',r'^;\s*model printing time\s*[:=]\s*([\d.]+)'])
    if sec is None:
        m=re.search(r'^;\s*estimated printing time \(normal mode\)\s*=\s*(.+)$',text,re.I|re.M)
        if m:
            parts=re.findall(r'(\d+)\s*([dhms])',m.group(1),re.I)
            if parts: sec=sum(int(n)*{'d':86400,'h':3600,'m':60,'s':1}[u.lower()] for n,u in parts)
    return gram, sec

def read_result(file):
    # Extract only slicer-produced metadata; never infer filament weight from mesh volume.
    with zipfile.ZipFile(file) as z:
        names=z.namelist()
        gcode=[n for n in names if re.match(r'^Metadata/.*\.gcode$',n,re.I)]
        for name in gcode:
            if z.getinfo(name).file_size > 80_000_000: continue
            raw=z.read(name).decode('utf-8','replace')
            grams, seconds=parse_gcode_meta(raw[:250_000]+'\n'+raw[-250_000:])
            if grams is not None and seconds is not None and grams>0 and seconds>0:
                return grams, seconds/60
        # A 3mf may include printer-generated per-plate slice_info.config (varies by version).
        for name in names:
            if name.endswith('slice_info.config') and z.getinfo(name).file_size<1_000_000:
                raw=z.read(name).decode('utf-8','replace')
                grams, seconds=parse_gcode_meta(raw)
                if grams and seconds: return grams,seconds/60
    raise ValueError('切片已完成，但目前無法從輸出檔讀取耗材重量與時間；請檢查 Bambu Studio 版本及切片輸出。')

def profile_path(printer, kind):
    return BASE/'profiles'/f'{printer}_{kind}.json'

@app.get('/')
def index():
    response=make_response(render_template('index.html'))
    response.headers['X-Robots-Tag']='noindex, nofollow, noarchive'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    return response

@app.get('/robots.txt')
def robots():
    response=make_response('User-agent: *\nDisallow: /\n')
    response.mimetype='text/plain'
    return response

@app.get('/api/status')
def status():
    with JOBS_LOCK:
        prune_jobs()
        active=any(j.get('worker_seen') and time.time()-j['worker_seen']<90 for j in JOBS.values())
    # Heartbeat is tracked separately so a Windows computer can be online without jobs.
    active=bool(BRIDGE_TOKEN and time.time()-WORKER_HEARTBEAT[0]<90)
    return jsonify(slicing_ready=active, mode='windows_bridge', note='Windows 電腦必須持續執行橋接程式')

WORKER_HEARTBEAT=[0.0]

@app.post('/api/quote')
def api_quote():
    if not BRIDGE_TOKEN: return jsonify(error='店家尚未設定 Windows 切片橋接金鑰。'),503
    model=request.files.get('model'); printer=request.form.get('printer','mini')
    try: quantity=int(request.form.get('quantity','1'))
    except ValueError: return jsonify(error='數量必須是整數'),400
    if not model or not model.filename: return jsonify(error='請上傳 STL 或 3MF 模型。'),400
    if printer not in PRINTERS or not 1<=quantity<=100: return jsonify(error='機型或數量不正確'),400
    ext=Path(model.filename).suffix.lower()
    if ext not in ALLOWED: return jsonify(error='僅支援 STL 或 3MF'),400
    if time.time()-WORKER_HEARTBEAT[0]>90: return jsonify(error='店家切片電腦目前離線，請稍後再試或直接私訊。'),503
    data=model.read()
    if not data or len(data)>35*1024*1024: return jsonify(error='模型檔案無效或超過35MB'),400
    with JOBS_LOCK:
        prune_jobs()
        if sum(j['state'] in ('queued','working') for j in JOBS.values())>=3:
            return jsonify(error='目前估價人數較多，請稍後重試。'),429
        job_id=uuid.uuid4().hex
        JOBS[job_id]=dict(created=time.time(),state='queued',printer=printer,quantity=quantity,filename='model'+ext,data=data,result=None)
    return jsonify(job_id=job_id,state='queued'),202

@app.get('/api/quote/<job_id>')
def quote_status(job_id):
    with JOBS_LOCK:
        prune_jobs()
        j=JOBS.get(job_id)
        if not j: return jsonify(error='此估價工作已逾時或伺服器重新啟動，請重新上傳。'),404
        if j['state']=='done': return jsonify(state='done',**j['result'])
        if j['state']=='error': return jsonify(state='error',error=j['result']['error'])
        return jsonify(state=j['state'])

@app.post('/api/worker/heartbeat')
def worker_heartbeat():
    if not authenticated_worker(): return jsonify(error='Unauthorized'),401
    WORKER_HEARTBEAT[0]=time.time()
    return jsonify(ok=True)

@app.get('/api/worker/next')
def worker_next():
    if not authenticated_worker(): return jsonify(error='Unauthorized'),401
    WORKER_HEARTBEAT[0]=time.time()
    with JOBS_LOCK:
        prune_jobs()
        for ident,j in JOBS.items():
            if j['state']=='queued':
                j['state']='working'
                r=make_response(j['data']);r.headers['X-Job-ID']=ident
                r.headers['X-Printer']=j['printer']
                r.headers['X-Quantity']=str(j['quantity'])
                r.headers['X-Filename']=j['filename']
                r.headers['Content-Type']='application/octet-stream'
                return r
    return ('',204)

@app.post('/api/worker/result/<job_id>')
def worker_result(job_id):
    if not authenticated_worker(): return jsonify(error='Unauthorized'),401
    payload=request.get_json(silent=True) or {}
    with JOBS_LOCK:
        prune_jobs();j=JOBS.get(job_id)
        if not j or j['state']!='working': return jsonify(error='Job expired'),404
        if payload.get('error'):
            j['state']='error';j['result']={'error':str(payload['error'])[:240]}
        else:
            try:
                grams=float(payload['grams']); minutes=float(payload['minutes'])
                if not (0<grams<100000 and 0<minutes<100000): raise ValueError('out of range')
            except (ValueError,TypeError,KeyError): return jsonify(error='Invalid result'),400
            j['result']=dict(printer=PRINTERS[j['printer']]['name'],grams=round(grams,2),minutes=round(minutes,2),quantity=j['quantity'],**quote(grams,minutes,j['quantity']),note='切片初估，最終價格由店家確認')
            j['state']='done'
        j['data']=b''
    return jsonify(ok=True)

@app.errorhandler(413)
def too_large(e): return jsonify(error='檔案太大，請上傳不超過 35 MB 的模型。'),413

if __name__=='__main__':
    app.run(host='127.0.0.1',port=int(os.environ.get('PORT',5000)),debug=False)

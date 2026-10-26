import os, re, io, zipfile, tempfile, subprocess, math
from pathlib import Path
from flask import Flask, request, jsonify, render_template, make_response
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 35 * 1024 * 1024
BASE = Path(__file__).resolve().parent
PRINTERS = {'mini': {'name':'A1 mini','volume':[180,180,180]}, 'a2l':{'name':'A2L','volume':[330,320,325]}}
ALLOWED = {'.stl','.3mf'}

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
    binary=os.environ.get('BAMBU_STUDIO_CLI','').strip()
    ready=bool(binary and Path(binary).is_file() and all(profile_path(p,k).is_file() for p in PRINTERS for k in ('machine','process','filament')))
    return jsonify(slicing_ready=ready)


@app.post('/api/quote')
def api_quote():
    model=request.files.get('model')
    printer=request.form.get('printer','mini')
    try: quantity=int(request.form.get('quantity','1'))
    except ValueError: return jsonify(error='數量必須是整數'),400
    if not model or not model.filename: return jsonify(error='請上傳 STL 或 3MF 模型。'),400
    if printer not in PRINTERS: return jsonify(error='無效的機型'),400
    if quantity<1 or quantity>100: return jsonify(error='數量需介於 1 至 100'),400
    ext=Path(model.filename).suffix.lower()
    if ext not in ALLOWED: return jsonify(error='僅支援 STL 或 3MF'),400
    binary=os.environ.get('BAMBU_STUDIO_CLI','').strip()
    paths=[profile_path(printer,x) for x in ('machine','process','filament')]
    if not binary or not Path(binary).is_file() or not all(p.is_file() for p in paths):
        return jsonify(error='伺服器尚未完成 Bambu Studio 切片引擎與機型參數設定，目前無法提供可信的自動估價。',code='SLICER_NOT_CONFIGURED'),503
    with tempfile.TemporaryDirectory(prefix='bambuquote_') as d:
        tmp=Path(d)
        source=tmp/('model'+ext)
        model.save(source)
        if source.stat().st_size==0: return jsonify(error='模型檔為空'),400
        sliced=tmp/'sliced.3mf'
        cmd=[binary, '--debug','2','--load-settings',f'{paths[0]};{paths[1]}','--load-filaments',str(paths[2]),'--arrange','1','--slice','0','--export-3mf',str(sliced),str(source)]
        try:
            proc=subprocess.run(cmd,cwd=tmp,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180,check=False)
        except subprocess.TimeoutExpired:
            return jsonify(error='切片逾時，請改用較小的模型或私訊詢價。'),422
        except OSError:
            return jsonify(error='切片引擎無法啟動，請通知店家。'),503
        if proc.returncode or not sliced.exists():
            return jsonify(error='模型無法完成自動切片，可能需要修復、拆件或調整方向；請直接私訊詢價。'),422
        try: grams,minutes=read_result(sliced)
        except (ValueError,zipfile.BadZipFile) as ex: return jsonify(error=str(ex)),422
        q=quote(grams,minutes,quantity)
        return jsonify(printer=PRINTERS[printer]['name'],grams=round(grams,2),minutes=round(minutes,2),quantity=quantity,**q,note='僅為自動切片初估，最終費用、交期與修檔費用由店家確認。')

@app.errorhandler(413)
def too_large(e): return jsonify(error='檔案太大，請上傳不超過 35 MB 的模型。'),413

if __name__=='__main__':
    app.run(host='127.0.0.1',port=int(os.environ.get('PORT',5000)),debug=False)

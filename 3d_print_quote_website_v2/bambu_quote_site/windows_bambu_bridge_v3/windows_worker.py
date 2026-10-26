"""Windows outbound-only slicer worker. Never expose a local listening port."""
import os, sys, json, time, tempfile, subprocess, zipfile, re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE_URL=os.environ.get('QUOTE_SITE_URL','').rstrip('/')
TOKEN=os.environ.get('QUOTE_BRIDGE_TOKEN','')
CLI=os.environ.get('BAMBU_STUDIO_CLI','')
PROFILES=Path(os.environ.get('QUOTE_PROFILES',str(Path(__file__).parent/'profiles')))

def api(method,path,data=None,headers=None):
    req=Request(BASE_URL+path,data=data,method=method,headers={'Authorization':'Bearer '+TOKEN,**(headers or {})})
    with urlopen(req,timeout=60) as r:return r.status,dict(r.headers),r.read()

def meta(text):
    def read(patterns):
        for p in patterns:
            m=re.search(p,text,re.I|re.M)
            if m:return float(m.group(1))
        return None
    grams=read([r'^;\s*total filament used\s*\[g\]\s*[:=]\s*([\d.]+)',r'^;\s*filament used\s*\[g\]\s*[:=]\s*([\d.]+)',r'^;\s*total filament weight\s*[:=]\s*([\d.]+)'])
    secs=read([r'^;\s*estimated printing time\s*\[s\]\s*[:=]\s*([\d.]+)',r'^;\s*total estimated time\s*[:=]\s*([\d.]+)',r'^;\s*model printing time\s*[:=]\s*([\d.]+)'])
    if secs is None:
        m=re.search(r'^;\s*estimated printing time \(normal mode\)\s*=\s*(.+)$',text,re.I|re.M)
        if m:secs=sum(int(n)*{'d':86400,'h':3600,'m':60,'s':1}[unit.lower()] for n,unit in re.findall(r'(\d+)\s*([dhms])',m.group(1),re.I))
    return grams,secs

def slice_model(content,filename,printer):
    machine=PROFILES/f'{printer}_machine.json';process=PROFILES/f'{printer}_process.json';filament=PROFILES/f'{printer}_filament.json'
    if not all(p.is_file() for p in (machine,process,filament)):
        raise ValueError('缺少該機型的完整設定檔，請店家匯出 Bambu Studio 設定後再使用。')
    if not Path(CLI).is_file():raise ValueError('找不到 Bambu Studio 命令列執行檔。')
    with tempfile.TemporaryDirectory() as tmp:
        inp=Path(tmp)/filename;inp.write_bytes(content);out=Path(tmp)/'sliced.3mf'
        cmd=[CLI,'--debug','2','--load-settings',f'{machine};{process}','--load-filaments',str(filament),'--arrange','1','--slice','0','--export-3mf',str(out),str(inp)]
        res=subprocess.run(cmd,cwd=tmp,capture_output=True,timeout=240)
        if res.returncode or not out.is_file():raise ValueError('模型切片失敗，請私訊店家確認模型與參數。')
        with zipfile.ZipFile(out) as z:
            for name in z.namelist():
                if name.lower().endswith('.gcode') and z.getinfo(name).file_size<80_000_000:
                    with z.open(name) as f:
                        raw=f.read().decode('utf-8','replace')
                    grams,secs=meta(raw[:250000]+'\n'+raw[-250000:])
                    if grams and secs:return {'grams':grams,'minutes':secs/60}
        raise ValueError('切片完成，但目前無法解析 G-code 的耗材重量或時間。')

def main():
    if not (BASE_URL.startswith('https://') and len(TOKEN)>=32 and Path(CLI).is_file()):
        sys.exit('請設定 HTTPS 網站網址、至少32字元金鑰和正確的 Bambu Studio 程式路徑。')
    print('Windows 橋接程式已啟動。請保持此視窗和電腦開啟。',flush=True)
    while True:
        try:
            api('POST','/api/worker/heartbeat',b'')
            status,headers,data=api('GET','/api/worker/next')
            if status==200:
                job=headers['X-Job-ID'];filename=headers.get('X-Filename','model.stl');printer=headers['X-Printer']
                try: result=slice_model(data,filename,printer)
                except Exception as e: result={'error':str(e)[:200]}
                api('POST','/api/worker/result/'+job,json.dumps(result).encode(),{'Content-Type':'application/json'})
                print('估價工作處理完成：'+job[:8],flush=True)
        except (HTTPError,URLError,TimeoutError) as e:print('網站連線失敗：',e,flush=True)
        time.sleep(5)

if __name__=='__main__': main()

# Render this folder's SVGs to PNG icons via headless Chrome (usage: py render_icons.py)
# 이 폴더의 SVG를 헤드리스 크롬으로 PNG 아이콘으로 변환 (사용: py render_icons.py)
import base64, json, re, subprocess, sys, tempfile, pathlib
icons = pathlib.Path(__file__).resolve().parent
chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
src = {n: "data:image/svg+xml;base64," + base64.b64encode((icons / n).read_bytes()).decode() for n in ("icon.svg", "icon-small.svg")}
jobs = [(16, "icon-small.svg"), (32, "icon-small.svg"), (48, "icon.svg"), (128, "icon.svg")]
html = f"""<!doctype html><body><pre id=out></pre><script>
const src={json.dumps(src)}, jobs={json.dumps(jobs)}, res={{}};
Promise.all(jobs.map(([n,f])=>new Promise(ok=>{{const i=new Image();i.onload=()=>{{
 const c=document.createElement('canvas');c.width=c.height=n;const x=c.getContext('2d');
 x.imageSmoothingQuality='high';const p=n===128?16:0;x.drawImage(i,p,p,n-2*p,n-2*p);res[n]=c.toDataURL('image/png');ok();}};i.src=src[f];}})))
.then(()=>{{document.getElementById('out').textContent=JSON.stringify(res)}});
</script>"""
page = pathlib.Path(tempfile.gettempdir()) / "render_icons.html"
page.write_text(html, encoding="utf-8")
dom = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--virtual-time-budget=3000", "--dump-dom", page.as_uri()],
                     capture_output=True, text=True, encoding="utf-8").stdout
data = json.loads(re.search(r'<pre id="out">(.*?)</pre>', dom, re.S).group(1).replace("&quot;", '"'))
for n, url in data.items():
    (icons / f"{n}.png").write_bytes(base64.b64decode(url.split(",", 1)[1]))
    print("wrote", f"{n}.png")

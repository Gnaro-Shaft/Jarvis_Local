#!/usr/bin/env python3
"""Jarvis — serveur HTTP (accès distant via Tailscale).

Expose Jarvis en lecture sur le réseau (tailnet) : interroge les agents, consulte
l'historique, rappelle le journal — depuis n'importe quel appareil connecté à
Tailscale (iPhone, autre Mac…). Stdlib uniquement, aucune dépendance.

⚠️ LECTURE SEULE par conception : les écritures (`--write`/`--enrich`) et les
commandes (`--run`/`--fix`) ne sont PAS exposées — elles exigent une validation
interactive locale (aucune action critique ne doit être déclenchée à distance
sans validation, cf. règles de sécurité du projet).

Sécurité :
- Bind par défaut sur `127.0.0.1` (local). Pour l'accès tailnet, lance avec
  `JARVIS_BIND=<ip-tailscale-du-mac>` (ex. <ip-tailscale-mac>).
- Jeton optionnel `JARVIS_TOKEN` : si défini, requis en `?token=` ou header `X-Token`.

Usage:
    JARVIS_BIND=<ip-tailscale-mac> JARVIS_TOKEN=secret python3 server.py
    # puis depuis l'iPhone (Tailscale ON) : http://<ip-tailscale-mac>:8787/?token=secret
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jarvis  # noqa: E402
from common import ollama_stream, get_active_project, set_active_project  # noqa: E402
read_events = jarvis.read_events  # même module que le reste de Jarvis


def _workspace():
    return jarvis._load(os.path.join(jarvis.AGENTS_DIR, "workspace", "agent.py"), "workspace_agent")

BIND = os.environ.get("JARVIS_BIND", "127.0.0.1")
PORT = int(os.environ.get("JARVIS_PORT", "8787"))
TOKEN = os.environ.get("JARVIS_TOKEN", "")

PAGE = """<!doctype html><html lang=fr><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Jarvis</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<style>
 :root{color-scheme:dark}
 body{font-family:-apple-system,system-ui,sans-serif;max-width:780px;margin:0 auto;padding:1rem;background:#0d1117;color:#e6edf3}
 h1{font-size:1.25rem;margin:.2rem 0}
 .bar{color:#8b949e;font-size:.8rem;margin-bottom:.8rem}
 .row{display:flex;gap:.5rem;margin:.5rem 0}
 input{flex:1;font-size:1rem;padding:.6rem;border-radius:.6rem;border:1px solid #30363d;background:#161b22;color:#e6edf3}
 button{font-size:.95rem;padding:.6rem .8rem;border-radius:.6rem;border:1px solid #30363d;background:#161b22;color:#e6edf3;cursor:pointer}
 button.primary{background:#1f6feb;border:0}
 .tabs{display:flex;gap:.4rem;flex-wrap:wrap;margin:.4rem 0 .2rem}
 .a{white-space:pre-wrap;background:#161b22;border:1px solid #30363d;border-radius:.6rem;padding:.8rem;margin-top:.8rem;line-height:1.45}
 .meta{color:#8b949e;font-size:.8rem;margin-top:.4rem}
 .badge{display:inline-block;background:#1f6feb22;color:#58a6ff;border:1px solid #1f6feb55;border-radius:1rem;padding:.05rem .5rem;font-size:.75rem}
 table{width:100%;border-collapse:collapse;font-size:.85rem} td{border-bottom:1px solid #21262d;padding:.3rem .4rem;vertical-align:top}
 .ok{color:#3fb950} .ko{color:#f85149}
 .load{display:flex;align-items:center;gap:10px}
 .hg{display:inline-block;font-size:1.2rem;animation:flip 1.2s ease-in-out infinite}
 .el{margin-left:auto;font-variant-numeric:tabular-nums;color:#8b949e;font-size:.9rem}
 @keyframes flip{0%,100%{transform:rotate(0)}50%{transform:rotate(180deg)}}
 #out{display:flex;flex-direction:column}
 .turn{display:flex;flex-direction:column;padding:.4rem 0 .8rem;border-bottom:0.5px solid #21262d}
 .u{align-self:flex-end;max-width:85%;background:#1f6feb22;border:0.5px solid #1f6feb55;border-radius:.6rem;padding:.5rem .8rem;margin-top:.9rem;white-space:pre-wrap}
 .clearbtn{margin-top:.6rem;font-size:.8rem;color:#8b949e}
 pre{position:relative;background:#0b0f17;border:0.5px solid #30363d;border-radius:.5rem;padding:.7rem .8rem;overflow:auto;margin:.5rem 0}
 .cp{position:absolute;top:6px;right:6px;font-size:.72rem;padding:.12rem .45rem;opacity:.55;cursor:pointer}
 .cp:hover{opacity:1}
 .rb{margin-top:8px;align-self:flex-start;font-size:.72rem;padding:.15rem .5rem;opacity:.6;cursor:pointer}
 .rb:hover{opacity:1}
 #replybar{display:none;align-items:center;gap:8px;background:#1f6feb18;border-left:2px solid #1f6feb;border-radius:.4rem;padding:.4rem .6rem;margin:.4rem 0;font-size:.82rem;color:#8b949e}
 #replybar button{padding:.05rem .4rem;font-size:.75rem}
 pre code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85rem;background:none;padding:0}
 :not(pre)>code{font-family:ui-monospace,monospace;background:#30363d66;padding:.1rem .35rem;border-radius:.3rem;font-size:.88em}
</style>
<h1>🤖 Jarvis</h1>
<div class=bar>local-first · lecture seule (tailnet) · les écritures restent locales & validées</div>
<div class=row style="align-items:center">
 <label style="color:#8b949e;font-size:.85rem;white-space:nowrap">📁 Projet</label>
 <select id=proj onchange=useProj() style="flex:1;font-size:.95rem;padding:.5rem;border-radius:.6rem;border:1px solid #30363d;background:#161b22;color:#e6edf3"></select>
 <span id=projmsg style="color:#3fb950;font-size:.8rem;white-space:nowrap"></span>
</div>
<div class=row style="align-items:center">
 <input id=newproj placeholder="＋ nouveau projet (nom)" style="flex:1;font-size:.9rem;padding:.5rem;border-radius:.6rem;border:1px solid #30363d;background:#161b22;color:#e6edf3">
 <button onclick=newProj()>Créer</button>
</div>
<div id=replybar>↩ En réponse à : <span id=replysnip style="flex:1;color:#e6edf3;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span> <button onclick=cancelReply()>✕</button></div>
<div class=row><input id=q placeholder="Pose ta question (connaissances / code / serveur)…" autofocus>
 <button class=primary onclick=ask()>Envoyer</button></div>
<div class=tabs>
 <button onclick=infra()>⚡ État serveur</button>
 <button onclick=history()>🕘 Historique</button>
 <button onclick="document.getElementById('rq').focus()">🧠 Rappel</button>
 <button onclick=clearThread()>🧹 Effacer</button>
</div>
<div class=row><input id=rq placeholder="Rappel : qu'as-tu fait sur le serveur ?">
 <button onclick=recall()>Rappel</button></div>
<div id=out></div>
<script>
const tok=new URLSearchParams(location.search).get('token')||'';
const out=document.getElementById('out');
const esc=t=>(t||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const url=(p,extra='')=>p+'?token='+encodeURIComponent(tok)+extra;
function renderMD(t){
  const parts=(t||'').split('```'); let h='';
  for(let i=0;i<parts.length;i++){
    if(i%2===0){h+=esc(parts[i]).replace(/`([^`]+)`/g,'<code>$1</code>');}
    else{let c=parts[i],lang='';const nl=c.indexOf('\\n');
      if(nl>=0){const f=c.slice(0,nl).trim();if(/^[a-z0-9+#.\\-]{1,15}$/i.test(f)){lang=f;c=c.slice(nl+1);}}
      h+='<pre><code class="language-'+esc(lang)+'">'+esc(c.replace(/\\n$/,''))+'</code></pre>';}
  }
  return h;
}
let timer=null;
let thread=[]; try{thread=JSON.parse(localStorage.getItem('jarvis_thread')||'[]');}catch(_){thread=[];}
function stopTimer(){if(timer){clearInterval(timer);timer=null;}}
function newTurn(){const d=document.createElement('div');d.className='turn';out.insertBefore(d,out.firstChild);window.scrollTo({top:0});return d;}
function addUser(turn,q){const d=document.createElement('div');d.className='u';d.textContent=q;turn.appendChild(d);}
function bubbleIn(turn){const d=document.createElement('div');d.className='a';turn.appendChild(d);return d;}
function loadingIn(turn,label){
  const d=bubbleIn(turn);
  d.innerHTML='<div class=load><span class=hg>⏳</span><span>'+label+'</span><span class=el>0.0s</span></div>';
  const el=d.querySelector('.el'),t0=Date.now();
  stopTimer();timer=setInterval(()=>{el.textContent=((Date.now()-t0)/1000).toFixed(1)+'s';},100);
  return d;
}
function copyText(t,b){const o=b.textContent,ok=()=>{b.textContent='copié ✓';setTimeout(()=>b.textContent=o,1200);};
  function fb(){const ta=document.createElement('textarea');ta.value=t;ta.style.position='fixed';ta.style.opacity=0;document.body.appendChild(ta);ta.select();try{document.execCommand('copy');ok();}catch(_){}document.body.removeChild(ta);}
  if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t).then(ok).catch(fb);}else fb();
}
function decorate(bub){
  if(window.hljs)bub.querySelectorAll('pre code').forEach(e=>{try{hljs.highlightElement(e);}catch(_){}});
  bub.querySelectorAll('pre').forEach(pre=>{if(pre.querySelector('.cp'))return;
    const b=document.createElement('button');b.className='cp';b.textContent='copier';
    b.onclick=()=>copyText(pre.querySelector('code').innerText,b);pre.appendChild(b);});
}
let replyTarget=null;
function replyTo(q,a){replyTarget={q,a};
  document.getElementById('replybar').style.display='flex';
  document.getElementById('replysnip').textContent=(a||'').replace(/\\s+/g,' ').slice(0,90);
  document.getElementById('q').focus();}
function cancelReply(){replyTarget=null;document.getElementById('replybar').style.display='none';}
function addReply(bub,q,a){const b=document.createElement('button');b.className='rb';b.textContent='↩ rebondir';b.onclick=()=>replyTo(q,a);bub.appendChild(b);}
function renderAns(bub,meta,body){
  const s=meta.sources&&meta.sources.length?'<div class=meta>sources: '+esc(meta.sources.join(', '))+'</div>':'';
  const n=meta.note?'<div class=meta>'+esc(meta.note)+'</div>':'';
  bub.innerHTML='<span class=badge>'+esc(meta.agent)+'</span><div style="margin-top:8px">'+renderMD(body)+'</div><div class=meta>'+esc(meta.reason||'')+'</div>'+n+s;
}
function saveThread(){try{localStorage.setItem('jarvis_thread',JSON.stringify(thread.slice(-30)));}catch(_){}}
function clearThread(){stopTimer();out.innerHTML='';thread=[];try{localStorage.removeItem('jarvis_thread');}catch(_){}}
function restoreThread(){for(const e of thread){const t=newTurn();addUser(t,e.q);const b=bubbleIn(t);renderAns(b,e.meta,e.body);decorate(b);addReply(b,e.q,e.body);}}
async function loadProjects(){
  try{const d=await(await fetch(url('/projects'))).json();
    const sel=document.getElementById('proj'); sel.innerHTML='';
    const o0=document.createElement('option'); o0.value=''; o0.textContent='— choisir un projet —'; sel.appendChild(o0);
    for(const p of (d.projects||[])){const o=document.createElement('option');
      o.value=p.name; o.textContent=p.name+' ('+(p.type||'?')+')'; if(p.name===d.active)o.selected=true; sel.appendChild(o);}
  }catch(_){}
}
async function useProj(){
  const name=document.getElementById('proj').value; if(!name)return;
  const msg=document.getElementById('projmsg'); msg.textContent='…';
  try{const d=await(await fetch(url('/use','&name='+encodeURIComponent(name)))).json();
    msg.textContent = d.active ? ('✓ '+d.active) : ('⛔ '+(d.error||'')); setTimeout(()=>msg.textContent='',2500);
  }catch(_){msg.textContent='erreur';}
}
async function newProj(){
  const el=document.getElementById('newproj'); const name=el.value.trim(); if(!name)return;
  const msg=document.getElementById('projmsg'); msg.textContent='…';
  try{const d=await(await fetch(url('/new','&name='+encodeURIComponent(name)))).json();
    if(d.error){msg.textContent='⛔ '+d.error;}
    else{el.value='';await loadProjects();msg.textContent='✓ créé : '+d.active;}
    setTimeout(()=>msg.textContent='',3000);
  }catch(_){msg.textContent='erreur';}
}
async function ask(){
  const inp=document.getElementById('q'); const q=inp.value.trim(); if(!q)return; inp.value='';
  const turn=newTurn(); addUser(turn,q); const bub=loadingIn(turn,'Jarvis réfléchit…');
  try{
    const hist=thread.slice(-4).map(t=>({q:t.q,a:(t.body||'').slice(0,400)}));
    if(replyTarget){hist.push({q:replyTarget.q||'(extrait cité)',a:(replyTarget.a||'').slice(0,600)});cancelReply();}
    const resp=await fetch(url('/ask','&q='+encodeURIComponent(q)+'&h='+encodeURIComponent(JSON.stringify(hist))));
    if(!resp.ok){stopTimer();bub.innerHTML='⛔ HTTP '+resp.status;return;}
    const reader=resp.body.getReader(), dec=new TextDecoder(); let buf='', meta=null;
    const paint=(final)=>{const body=buf.slice(buf.indexOf('\\x1e')+1);
      renderAns(bub,meta,body);
      if(final){decorate(bub);addReply(bub,q,body);thread.push({q,meta,body});saveThread();}};
    while(true){const {value,done:fin}=await reader.read(); if(fin)break;
      buf+=dec.decode(value,{stream:true});
      if(!meta){const i=buf.indexOf('\\x1e'); if(i<0)continue; meta=JSON.parse(buf.slice(0,i)); stopTimer();}
      paint(false);}
    if(meta)paint(true); else{stopTimer();bub.innerHTML='(réponse vide)';}
  }catch(e){stopTimer();bub.innerHTML='erreur: '+esc(''+e);}
}
async function recall(){
  const ri=document.getElementById('rq'); const q=ri.value.trim(); if(!q)return; ri.value='';
  const turn=newTurn(); addUser(turn,'🧠 '+q); const bub=loadingIn(turn,'Lecture du journal…');
  try{const d=await(await fetch(url('/recall','&q='+encodeURIComponent(q)))).json(); stopTimer();
    bub.innerHTML=esc(d.text);}catch(e){stopTimer();bub.innerHTML='erreur';}
}
async function history(){const turn=newTurn(); const bub=loadingIn(turn,'Chargement…');
  try{const d=await(await fetch(url('/history','&n=25'))).json(); stopTimer();
    let r='<table>';for(const e of d.events.reverse()){
      r+='<tr><td>'+esc(e.ts)+'</td><td><span class=badge>'+esc(e.agent)+'</span></td><td>'+esc(e.mode)+'</td>'
        +'<td class="'+(e.outcome==='ok'||e.outcome==='applied'?'ok':'ko')+'">'+esc(e.outcome)+'</td>'
        +'<td>'+esc(e.request)+'</td></tr>';}
    bub.innerHTML=r+'</table>';}catch(e){stopTimer();bub.innerHTML='erreur';}
}
async function infra(){const turn=newTurn(); const bub=loadingIn(turn,'Lecture du serveur…');
  try{const d=await(await fetch(url('/status'))).json(); stopTimer(); const s=d.snapshot||{};
    let dk=(s.docker||'').split('\\n').filter(Boolean).map(l=>{const p=l.split('\\t');
      const up=(p[1]||'').toLowerCase();const cl=up.includes('healthy')&&!up.includes('unhealthy')?'ok':(up.includes('unhealthy')?'ko':'');
      return '<tr><td>'+esc(p[0]||l)+'</td><td class="'+cl+'">'+esc(p[1]||'')+'</td></tr>';}).join('');
    const therm=s.thermal?('\\n\\n🌡️ '+esc(s.thermal).replace('mbpfan=','mbpfan : ')):'';
    bub.innerHTML='<b>'+esc(s.uname||'')+'</b>\\n'+esc(s.uptime||'')+'\\n\\n'+esc((s.mem||'').split('\\n').pop())+therm+'<table>'+dk+'</table>';
  }catch(e){stopTimer();bub.innerHTML='erreur';}
}
document.getElementById('q').addEventListener('keydown',e=>{if(e.key==='Enter')ask();});
document.getElementById('rq').addEventListener('keydown',e=>{if(e.key==='Enter')recall();});
restoreThread();
loadProjects();
</script>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _authorized(self, params: dict) -> bool:
        if not TOKEN:
            return True
        tok = (params.get("token", [""])[0]) or self.headers.get("X-Token", "")
        return tok == TOKEN

    def log_message(self, *args):  # silencieux
        pass

    def _stream_ask(self, q: str, history: list | None = None):
        """Stream : routage + récupération, puis génération token-par-token.
        Format : <meta JSON>\\x1e<texte qui coule…>"""
        try:
            prep = jarvis.prepare_answer(q, history=history)
        except Exception as e:
            prep = {"agent": "?", "reason": "erreur", "sources": [], "note": None,
                    "prompt": None, "text": f"Erreur : {e}", "logtarget": None}
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        meta = {"agent": prep["agent"], "reason": prep["reason"],
                "sources": prep.get("sources", []), "note": prep.get("note")}
        try:
            self.wfile.write((json.dumps(meta, ensure_ascii=False) + "\x1e").encode())
            self.wfile.flush()
            got = False
            if prep.get("prompt"):
                for ch in ollama_stream(prep["prompt"], prep["model"]):
                    self.wfile.write(ch.encode())
                    self.wfile.flush()
                    got = True
            else:
                self.wfile.write((prep.get("text") or "").encode())
                self.wfile.flush()
                got = bool(prep.get("text"))
        except (BrokenPipeError, ConnectionResetError):
            return
        jarvis.log_event(prep["agent"], "read", q, target=prep.get("logtarget"),
                         outcome="ok" if got else "error")

    def do_GET(self):
        u = urlparse(self.path)
        params = parse_qs(u.query)
        if u.path == "/":
            if not self._authorized(params):
                self._send(401, b"unauthorized", "text/plain")
                return
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            return
        if not self._authorized(params):
            self._json(401, {"error": "unauthorized"})
            return
        try:
            if u.path == "/ask":
                q = params.get("q", [""])[0].strip()
                if not q:
                    self._json(400, {"error": "paramètre q manquant"})
                    return
                try:
                    history = json.loads(params.get("h", ["[]"])[0]) or []
                except (json.JSONDecodeError, ValueError):
                    history = []
                self._stream_ask(q, history)
            elif u.path == "/recall":
                q = params.get("q", [""])[0].strip()
                self._json(200, {"text": jarvis.recall(q) if q else "paramètre q manquant"})
            elif u.path == "/history":
                n = int(params.get("n", ["20"])[0])
                self._json(200, {"events": read_events(limit=n)})
            elif u.path == "/status":
                infra = jarvis._load(
                    os.path.join(jarvis.AGENTS_DIR, "infra", "agent.py"), "infra_agent")
                self._json(200, {"snapshot": infra.snapshot()})
            elif u.path == "/projects":
                cat = _workspace().catalog(local_only=True)
                self._json(200, {
                    "projects": [{"name": e["name"], "type": e.get("type"), "local": e.get("local")}
                                 for e in cat],
                    "active": (get_active_project() or {}).get("name")})
            elif u.path == "/use":
                name = params.get("name", [""])[0].strip()
                items = {e["name"].lower(): e for e in _workspace().catalog(local_only=True)}
                e = items.get(name.lower())
                if not e:
                    self._json(404, {"error": f"projet introuvable : {name}"})
                    return
                set_active_project({"name": e["name"], "local": e.get("local"), "remote": e.get("remote")})
                self._json(200, {"active": e["name"], "local": e.get("local")})
            elif u.path == "/new":
                name = params.get("name", [""])[0].strip()
                r = _workspace().create_project(name)
                if "error" in r:
                    self._json(400, {"error": r["error"]})
                    return
                self._json(200, {"active": r["name"], "local": r["local"]})
            else:
                self._json(404, {"error": "route inconnue"})
        except Exception as e:  # robustesse : ne jamais crasher le serveur
            self._json(500, {"error": str(e)})


def main() -> int:
    # Web = usage interactif → on privilégie la réactivité (modèle unique léger,
    # gardé chaud, contexte code réduit). Surchargeable via l'environnement.
    os.environ.setdefault("JARVIS_MODEL", "qwen2.5:14b-instruct-q5_K_M")
    os.environ.setdefault("JARVIS_KEEP_ALIVE", "30m")
    os.environ.setdefault("DEV_CTX_BUDGET", "16000")
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    where = f"http://{BIND}:{PORT}"
    print(f"🤖 Jarvis HTTP (lecture seule) sur {where}"
          + ("  · token requis" if TOKEN else "  · sans token")
          + (f"\n   ⚠️ bind={BIND} (local). Pour le tailnet : JARVIS_BIND=<ip-tailscale> python3 server.py"
             if BIND in ("127.0.0.1", "localhost") else ""))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\narrêt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

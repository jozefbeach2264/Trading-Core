#!/usr/bin/env python3
"""Live dashboard for the TradingCore dry run. Standalone (stdlib only): tails the bot's own logs and
polls its /stats, so it can be restarted freely without touching the running bot.

  python3 dashboard.py                 → http://127.0.0.1:8001/   (page auto-refreshes every 2 s)
  python3 dashboard.py --host 0.0.0.0  → reachable over the tailnet too
  python3 dashboard.py --tail          → live cycle stream in the terminal instead of a web page
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path.home() / "trading_core_project" / "TradingCore"
STATS_URL = "http://127.0.0.1:8000/stats"
HEALTH_URL = "http://127.0.0.1:8081/health"
TAIL_BYTES = 400_000


def env_path(key: str, default: str) -> Path:
    try:
        for line in (REPO / ".env").read_text().splitlines():
            if line.startswith(key + "="):
                return REPO / line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return REPO / default


FAILED = env_path("FAILED_SIGNALS_PATH", "logs/failed_signals.json")
AI_LOG = env_path("AI_MODEL_LOG_PATH", "logs/ai_model.log")
SIM = env_path("SIMULATION_STATE_FILE_PATH", "logs/simulation_state.json")


def tail_json_lines(path: Path, n: int):
    if not path.exists():
        return []
    size = path.stat().st_size
    with path.open("rb") as f:
        f.seek(max(0, size - TAIL_BYTES))
        chunk = f.read().decode("utf-8", "replace")
    lines = chunk.splitlines()[1:] if size > TAIL_BYTES else chunk.splitlines()
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def http_json(url, timeout=3.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        return {"error": repr(e)}


def bucket(reason: str) -> str:
    """'Rejected - AI CONFIDENCE LOW (0.40/0.7)' → 'AI CONFIDENCE LOW'; 'Primary Gate: CTS_BLOCK' is kept whole;
    reasons whose detail carries numbers (STALE…, REVERSAL RISK) are cut at the colon."""
    r = reason.replace("Rejected - ", "").split(" (", 1)[0].strip()
    if r.startswith(("STALE", "REVERSAL RISK", "NO ENTRY PRICE", "POSITION OPEN")):
        r = r.split(":", 1)[0].split(" (", 1)[0].strip()
    return r


FLAG_SHORT = {"✅": "✓", "⚠️": "~", "❌": "✗"}


def flag_glyph(flag: str) -> str:
    for k, v in FLAG_SHORT.items():
        if flag.startswith(k):
            return v
    return "?"


def build_data():
    now = time.time()
    cycles = tail_json_lines(FAILED, 400)
    recent = []
    for c in cycles[-60:]:
        report = c.get("report") or {}
        filters = {name[:4]: f"{flag_glyph(str(r.get('flag', '')))}{r.get('score', 0):.2f}" for name, r in report.items() if isinstance(r, dict)}
        recent.append({"t": c.get("timestamp", "")[11:19], "reason": c.get("reason", ""), "bucket": bucket(c.get("reason", "")), "filters": filters})
    window = [c for c in cycles if _age(c.get("timestamp")) <= 300]
    mix = Counter(bucket(c.get("reason", "")) for c in window)
    ai = tail_json_lines(AI_LOG, 300)
    verdicts = [r for r in ai if r.get("type") in ("api_verdict", "fallback", "timeout", "api_error", "error")][-25:]
    latencies = sorted(float(r.get("latency_ms", 0)) for r in ai if r.get("type") == "latency" and _age_epoch(r) <= 900)
    verdict_rows = []
    for r in verdicts:
        v = r.get("verdict") or {}
        ctx = r.get("context") or {}
        ts = r.get("ts")
        verdict_rows.append({
            "t": datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M:%S") if ts else "", "type": r.get("type"),
            "action": v.get("action"), "confidence": v.get("confidence"), "latency_ms": r.get("latency_ms"),
            "direction": ctx.get("direction"), "reversal": ctx.get("reversal_likelihood_score"), "cts": ctx.get("cts_score"),
            "ob": ctx.get("orderbook_score"), "zone": ctx.get("orderbook_zone"), "reasoning": (v.get("reasoning") or "")[:140],
        })
    sim = {}
    if SIM.exists():
        try:
            sim = json.loads(SIM.read_text())
        except json.JSONDecodeError:
            sim = {}
    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "stats": http_json(STATS_URL), "model": http_json(HEALTH_URL),
        "cycles_last_5min": len(window), "rejection_mix_5min": mix.most_common(),
        "recent_cycles": list(reversed(recent)),
        "verdicts": list(reversed(verdict_rows)),
        "latency_15min": {"n": len(latencies), "median": latencies[len(latencies) // 2] if latencies else None,
                          "p95": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None},
        "sim_history": list(reversed((sim.get("history") or [])[-12:])), "sim_stats": sim.get("stats"),
    }


def _age(ts_iso):
    try:
        return time.time() - datetime.fromisoformat(str(ts_iso).replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001
        return 1e9


def _age_epoch(rec):
    ts = rec.get("ts")
    if ts:
        return time.time() - float(ts)
    return 0.0   # latency records carry no ts; the tail is recent enough


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>TradingCore dry run</title>
<style>
body{margin:0;background:#0f1218;color:#d7dbe2;font:13px/1.4 ui-monospace,Menlo,Consolas,monospace}
header{display:flex;flex-wrap:wrap;gap:18px;align-items:baseline;padding:10px 16px;background:#161b24;border-bottom:1px solid #2a3140;position:sticky;top:0}
header b{color:#fff;font-size:15px}.k{color:#8a93a3}.v{color:#e8ecf3}.good{color:#5fd38d}.bad{color:#ff6b6b}.warn{color:#ffc857}
main{display:grid;grid-template-columns:1.1fr 1fr;gap:14px;padding:14px 16px}
section{background:#141922;border:1px solid #242b38;border-radius:6px;padding:10px 12px;overflow:auto;max-height:46vh}
h2{margin:0 0 8px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#8a93a3}
table{border-collapse:collapse;width:100%}td,th{padding:2px 6px;text-align:left;white-space:nowrap;border-bottom:1px solid #1e2531;vertical-align:top}th{color:#8a93a3;font-weight:normal}
.wrap{white-space:normal}.tag{display:inline-block;padding:0 5px;border-radius:3px;background:#1f2736;margin-right:4px}
@media(max-width:900px){main{grid-template-columns:1fr}section{max-height:none}}
</style></head><body>
<header><b>TradingCore</b><span id="mode"></span><span><span class=k>balance</span> <span class=v id="bal"></span></span>
<span><span class=k>mark</span> <span class=v id="mark"></span></span><span><span class=k>feed age</span> <span id="age"></span></span>
<span><span class=k>position</span> <span id="pos"></span></span><span><span class=k>model</span> <span id="model"></span></span>
<span><span class=k>verdict latency</span> <span id="lat"></span></span><span><span class=k>cycles/5min</span> <span id="cyc"></span></span>
<span class=k id="now"></span></header>
<main>
<section><h2>Cycle stream (newest first) — filters: Cts Time Rete Orde Spoo LowV Comp Brea Sent</h2><table id="cycles"></table></section>
<section><h2>Model verdicts (newest first)</h2><table id="verdicts"></table></section>
<section><h2>Why cycles stop (last 5 min)</h2><table id="mix"></table></section>
<section><h2>Simulation</h2><div id="simstats" class=wrap></div><table id="sim"></table></section>
</main>
<script>
const $=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function tick(){try{const d=await (await fetch('/data',{cache:'no-store'})).json();const s=d.stats||{};
$('mode').textContent=s.mode||'?';$('mode').className=s.mode==='LIVE'?'bad':'good';
$('bal').textContent=s.balance!=null?Number(s.balance).toFixed(4)+' / '+Number(s.initial_capital).toFixed(2):'?';
$('mark').textContent=s.mark_price??'?';const age=s.market_data_age_s;$('age').textContent=age!=null?age+'s':'?';$('age').className=age>3?'bad':'good';
const p=s.open_position;$('pos').innerHTML=p?`<span class=warn>${esc(p.direction)} @ ${Number(p.entry_price).toFixed(2)} sl ${p.stop_loss??'-'} tp ${p.take_profit??'-'} (C${s.lifecycle?.candle_count})</span>`:'<span class=k>flat</span>';
const ok=d.model&&d.model.status==='ok';$('model').textContent=ok?'ok':'DOWN';$('model').className=ok?'good':'bad';
const l=d.latency_15min;$('lat').textContent=l.n?`${Math.round(l.median)} ms med / ${Math.round(l.p95)} p95 (n=${l.n})`:'—';
$('cyc').textContent=d.cycles_last_5min;$('now').textContent=d.now;
$('cycles').innerHTML='<tr><th>time</th><th>outcome</th><th>filters</th></tr>'+d.recent_cycles.map(c=>`<tr><td>${c.t}</td><td class=wrap>${esc(c.reason)}</td><td>${Object.entries(c.filters).map(([k,v])=>`<span class=tag>${k} ${esc(v)}</span>`).join('')}</td></tr>`).join('');
$('verdicts').innerHTML='<tr><th>time</th><th>dir</th><th>action</th><th>conf</th><th>ms</th><th>rev</th><th>cts</th><th>ob</th><th>zone</th><th>reasoning</th></tr>'+d.verdicts.map(v=>`<tr><td>${v.t}</td><td>${esc(v.direction)}</td><td class=${v.action==='Execute'?'good':(v.action==='Abort'?'bad':'warn')}>${esc(v.action)}${v.type!=='api_verdict'?' ('+esc(v.type)+')':''}</td><td>${v.confidence}</td><td>${v.latency_ms}</td><td>${v.reversal}</td><td>${v.cts}</td><td>${v.ob}</td><td>${esc(v.zone)}</td><td class=wrap>${esc(v.reasoning)}</td></tr>`).join('');
const tot=d.rejection_mix_5min.reduce((a,[,n])=>a+n,0)||1;$('mix').innerHTML=d.rejection_mix_5min.map(([k,n])=>`<tr><td>${n}</td><td>${(100*n/tot).toFixed(0)}%</td><td class=wrap>${esc(k)}</td></tr>`).join('');
$('simstats').textContent=d.sim_stats?JSON.stringify(d.sim_stats):'no closed trades yet';
$('sim').innerHTML='<tr><th>time</th><th>event</th><th>dir</th><th>entry</th><th>exit</th><th>pnl</th><th>fee</th><th>reason</th></tr>'+d.sim_history.map(h=>`<tr><td>${esc((h.timestamp||'').slice(11,19))}</td><td>${esc(h.event||'open')}</td><td>${esc(h.direction)}</td><td>${h.entry_price?Number(h.entry_price).toFixed(2):''}</td><td>${h.exit_price?Number(h.exit_price).toFixed(2):''}</td><td class=${(h.pnl||0)>0?'good':((h.pnl||0)<0?'bad':'')}>${h.pnl!=null?Number(h.pnl).toFixed(4):''}</td><td>${h.fee!=null?Number(h.fee).toFixed(4):''}</td><td class=wrap>${esc(h.reason||h.reasoning||'')}</td></tr>`).join('');
}catch(e){$('now').textContent='refresh failed: '+e}}
tick();setInterval(tick,2000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/data"):
            body = json.dumps(build_data()).encode()
            ctype = "application/json"
        elif self.path == "/" or self.path.startswith("/?"):
            body = PAGE.encode()
            ctype = "text/html; charset=utf-8"
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):  # quiet
        pass


def tail_mode():
    seen = 0
    while True:
        cycles = tail_json_lines(FAILED, 50)
        if seen == 0:
            cycles = cycles[-15:]
        for c in cycles[seen and -1 or 0:]:
            pass
        d = build_data()
        os.system("clear")
        s = d["stats"]
        print(f"{d['now']}  {s.get('mode')}  balance {s.get('balance')}  mark {s.get('mark_price')}  feed {s.get('market_data_age_s')}s  "
              f"model {d['model'].get('status', 'DOWN')}  latency {d['latency_15min']}")
        print(f"position: {s.get('open_position') or 'flat'}   lifecycle {s.get('lifecycle')}")
        print("\n-- last 5 min --")
        for k, n in d["rejection_mix_5min"]:
            print(f"  {n:5d}  {k}")
        print("\n-- cycles (newest first) --")
        for c in d["recent_cycles"][:20]:
            print(f"  {c['t']}  {c['reason'][:70]:70s}  {' '.join(f'{k}:{v}' for k, v in c['filters'].items())}")
        print("\n-- verdicts --")
        for v in d["verdicts"][:8]:
            print(f"  {v['t']}  {v['direction']:5s} {str(v['action']):9s} conf={v['confidence']} {v['latency_ms']}ms rev={v['reversal']} cts={v['cts']} ob={v['ob']}  {v['reasoning'][:60]}")
        time.sleep(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8001)
    ap.add_argument("--tail", action="store_true", help="terminal view instead of the web page")
    a = ap.parse_args()
    if a.tail:
        try:
            tail_mode()
        except KeyboardInterrupt:
            return 0
    server = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"dashboard on http://{a.host}:{a.port}/", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())

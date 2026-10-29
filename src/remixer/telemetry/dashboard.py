"""Static HTML dashboard rendered from telemetry Parquet (no server, no external assets)."""
from __future__ import annotations

import json
from pathlib import Path

PANELS = [
    ("GPU utilization and VRAM", [("gpu_util", "GPU util %"), ("vram_pct", "VRAM %")], 100),
    ("GPU thermals and power", [("gpu_temp_c", "GPU temp C"), ("gpu_power_w", "GPU power W"),
                                ("gpu_sm_ghz10", "SM clock (GHz x10)")], None),
    ("CPU", [("cpu_util", "CPU avg %"), ("cpu_min", "busiest-core min %"), ("cpu_temp_c", "CPU temp C")], 100),
    ("Intel iGPU / NPU", [("igpu", "iGPU busiest engine %"), ("npu", "NPU %")], 100),
    ("Memory", [("ram_util", "RAM %"), ("swap_used_gib", "swap GiB")], None),
    ("Disk", [("disk_read_mbs", "read MB/s"), ("disk_write_mbs", "write MB/s")], None),
]

HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>
:root{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--grid:#e7e5e4;--c0:#2563eb;--c1:#dc2626;--c2:#16a34a;--c3:#9333ea}
@media (prefers-color-scheme:dark){:root{--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;--grid:#292524;--c0:#60a5fa;--c1:#f87171;--c2:#4ade80;--c3:#c084fc}}
body{background:var(--bg);color:var(--fg);font:14px system-ui,sans-serif;margin:0;padding:16px;max-width:1200px;margin:auto}
h1{font-size:20px;margin:0 0 4px}.sub{color:var(--muted);margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));gap:16px}
.card{border:1px solid var(--grid);border-radius:8px;padding:12px}.card h2{font-size:14px;margin:0 0 6px}
svg{width:100%;height:180px;display:block}.legend span{margin-right:12px;font-size:12px;color:var(--muted)}
.legend i{display:inline-block;width:10px;height:3px;margin-right:4px;vertical-align:middle}
table{border-collapse:collapse;font-size:13px}td,th{padding:3px 10px;border-bottom:1px solid var(--grid);text-align:right}
th:first-child,td:first-child{text-align:left}</style></head><body>
<h1>__TITLE__</h1><div class="sub" id="sub"></div><div id="stats"></div><div class="grid" id="grid"></div>
<script>
const D=__DATA__,P=__PANELS__,C=['var(--c0)','var(--c1)','var(--c2)','var(--c3)'];
const t0=D.ts[0]||0,dur=((D.ts[D.ts.length-1]||0)-t0);
document.getElementById('sub').textContent=`${D.ts.length} samples, ${(dur/60).toFixed(1)} min, from ${new Date(t0*1000).toLocaleString()}`;
function chart(el,series,ymax){const W=600,H=180,pl=34,pb=18;let mx=ymax||0;
 series.forEach(([k])=>(D[k]||[]).forEach(v=>{if(v!=null&&v>mx)mx=v}));mx=mx||1;
 let s=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">`;
 for(let i=0;i<=4;i++){const y=pb/2+(H-pb)*(1-i/4);s+=`<line x1="${pl}" x2="${W}" y1="${y}" y2="${y}" stroke="var(--grid)"/><text x="2" y="${y+4}" font-size="10" fill="var(--muted)">${(mx*i/4).toFixed(0)}</text>`}
 (D.tags||[]).forEach(([a,b,name])=>{const x=pl+(W-pl)*(a-t0)/(dur||1);s+=`<line x1="${x}" x2="${x}" y1="0" y2="${H-pb}" stroke="var(--muted)" stroke-dasharray="2 3"/><text x="${x+2}" y="${H-4}" font-size="9" fill="var(--muted)">${name}</text>`});
 series.forEach(([k],i)=>{const v=D[k];if(!v)return;let p='';v.forEach((y,j)=>{if(y==null)return;const x=pl+(W-pl)*(D.ts[j]-t0)/(dur||1),yy=pb/2+(H-pb)*(1-y/mx);p+=(p?'L':'M')+x.toFixed(1)+','+yy.toFixed(1)});
  s+=`<path d="${p}" fill="none" stroke="${C[i]}" stroke-width="1.5" vector-effect="non-scaling-stroke"/>`});
 el.innerHTML=s+'</svg><div class="legend">'+series.filter(([k])=>D[k]).map(([k,l],i)=>`<span><i style="background:${C[i]}"></i>${l}</span>`).join('')+'</div>'}
const g=document.getElementById('grid');P.forEach(([title,series,ymax])=>{if(!series.some(([k])=>D[k]))return;const c=document.createElement('div');c.className='card';c.innerHTML=`<h2>${title}</h2><div></div>`;g.appendChild(c);chart(c.lastChild,series,ymax)});
if(D.stats){document.getElementById('stats').innerHTML='<div class="card" style="margin-bottom:16px"><table><tr><th>metric</th><th>mean</th><th>p50</th><th>p95</th><th>max</th></tr>'+Object.entries(D.stats).map(([k,v])=>`<tr><td>${k}</td><td>${v.mean}</td><td>${v.p50}</td><td>${v.p95}</td><td>${v.max}</td></tr>`).join('')+'</table></div>'}
</script></body></html>"""

STAT_COLS = ["gpu_util", "vram_used_gib", "gpu_temp_c", "gpu_power_w", "gpu_sm_mhz", "cpu_util", "cpu_mhz", "cpu_mhz_eff",
             "cpu_temp_c", "igpu", "npu", "ram_used_gib", "disk_read_mbs", "disk_write_mbs"]


def stats(table) -> dict:
    import numpy as np

    out = {}
    for c in STAT_COLS:
        if c not in table.column_names:
            continue
        v = np.array([x for x in table.column(c).to_pylist() if x is not None], dtype=float)
        if len(v):
            out[c] = {"mean": round(float(v.mean()), 1), "p50": round(float(np.percentile(v, 50)), 1),
                      "p95": round(float(np.percentile(v, 95)), 1), "max": round(float(v.max()), 1)}
    return out


def render(table, out: Path, title: str = "Telemetry", max_points: int = 3000) -> Path:
    cols = {c: table.column(c).to_pylist() for c in table.column_names}
    n = len(cols.get("ts", []))
    step = max(1, n // max_points)
    data: dict = {}
    for c, v in cols.items():
        if c.startswith("cpu_") and c[4:].isdigit():
            continue
        if c == "tag" or (c != "ts" and all(x is None for x in v)):
            continue
        if isinstance(next((x for x in v if x is not None), 0), str):
            continue
        data[c] = [None if x is None else round(float(x), 2) for x in v[::step]]
    if "vram_used_gib" in cols and "vram_total_gib" in cols:
        data["vram_pct"] = [None if u is None or t in (None, 0) else round(100 * u / t, 1)
                            for u, t in zip(cols["vram_used_gib"][::step], cols["vram_total_gib"][::step])]
    if "gpu_sm_mhz" in cols:
        data["gpu_sm_ghz10"] = [None if x is None else round(x / 100, 2) for x in cols["gpu_sm_mhz"][::step]]
    cores = sorted(c for c in cols if c.startswith("cpu_") and c[4:].isdigit())
    if cores:
        data["cpu_min"] = [round(min(cols[c][i] for c in cores), 1) for i in range(0, n, step)]
    tags, prev = [], None
    for ts, tag in zip(cols.get("ts", []), cols.get("tag", [""] * n)):
        if tag != prev:
            if tags:
                tags[-1][1] = ts
            if tag:
                tags.append([ts, ts, tag])
            prev = tag
    data["tags"] = tags
    data["stats"] = stats(table)
    html = (HTML.replace("__TITLE__", title).replace("__DATA__", json.dumps(data))
            .replace("__PANELS__", json.dumps(PANELS)))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out

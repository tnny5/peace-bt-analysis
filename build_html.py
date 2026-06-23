"""
bt_analysis/ の JSON群から index.html を生成する
新しいJSONが増えたら再実行するだけで自動更新される
"""
import json
from pathlib import Path

BASE = Path(__file__).parent
OUT  = BASE / "index.html"

# ── 1. JSONを全件ロード ──────────────────────────────────
jsons = sorted(BASE.glob("*_groups.json"))
all_data = []
for p in jsons:
    d = json.load(open(p, encoding='utf-8'))
    all_data.append(d)
    print(f"  読込: {p.name}  ({len(d['normal'])}グループ)")

if not all_data:
    print("JSONが見つかりません")
    raise SystemExit(1)

# ── 2. グラフ用月次集計データを生成 ─────────────────────
from collections import defaultdict

def weekly_nc(groups):
    from datetime import date, timedelta
    m = defaultdict(lambda: {1:0,2:0,3:0,4:0})
    for g in groups:
        if not g['close_dt']:
            continue
        dt  = date.fromisoformat(g['close_dt'][:10])
        mon = dt - timedelta(days=dt.weekday())   # その週の月曜日
        key = mon.isoformat()
        nc_key = min(g['nc'], 4)
        m[key][nc_key] += 1
    return dict(sorted(m.items()))

chart_data = {}
for d in all_data:
    pair = d['meta']['bt_name']
    chart_data[pair] = weekly_nc(d['normal'])

chart_json = json.dumps(chart_data, ensure_ascii=False, separators=(',',':'))

# ── 3. メタ情報テーブルHTML ─────────────────────────────
PARAM_LABELS = {
    'bt_name':              'BT名',
    'source':               '設定種別',
    'account':              '口座',
    'EMA_Type':             'EMA_Type',
    'EMA_reverse':          'EMA_reverse',
    'EMA_period':           'EMA_period',
    'NanpinEntryPips':      'NanpinPips',
    'Nanpin_interbal_hour': 'Nanpin_hour',
    'NanpinLotsMult':       'LotsMult',
    'NanpinCount':          'NC上限',
    'TP_pips':              'TP_pips',
    'TP_yen':               'TP_yen',
}

from collections import Counter

# 各パラメータキーの「多数派の値」を求める
majority = {}
for k in PARAM_LABELS:
    vals = [str(d['meta'].get(k, '')) for d in all_data if k in d['meta']]
    if len(set(vals)) > 1:                          # 値が割れているキーのみ
        majority[k] = Counter(vals).most_common(1)[0][0]

def meta_table(d):
    m    = d['meta']
    s    = d['stats']
    rows = ""
    for k, label in PARAM_LABELS.items():
        v    = m.get(k, '—')
        diff = k in majority and str(v) != majority[k]
        td   = ' style="background:#FFF3CD;color:#7B4D00"' if diff else ''
        rows += f"<tr><td>{label}</td><td{td}>{v}</td></tr>"
    rows += f"<tr><td>総グループ</td><td>{s['groups_normal']}</td></tr>"
    nc_dist = s.get('nc_distribution', {})
    nc_str  = '  '.join(f"NC{k}:{v}" for k,v in nc_dist.items())
    rows += f"<tr><td>NC分布</td><td style='font-size:11px'>{nc_str}</td></tr>"
    pair = m['bt_name'].split('-')[2] if '-' in m['bt_name'] else m['bt_name']
    return f"""
<div class="card">
  <div class="card-title">{pair}</div>
  <div class="card-sub">{m.get('source','')}</div>
  <table class="param-table">{rows}</table>
</div>"""

meta_html = "\n".join(meta_table(d) for d in all_data)

# ── 4. チャートキャンバスHTML ───────────────────────────
chart_labels_html = ""
chart_canvases_html = ""
for i, d in enumerate(all_data, 1):
    m    = d['meta']
    pair = m['bt_name'].split('-')[2] if '-' in m['bt_name'] else m['bt_name']
    chart_labels_html += f"""
<div class="chart-label">{pair}
  <span class="chart-sub">{m.get('source','')} — Pips={m.get('NanpinEntryPips','?')} / Mult={m.get('NanpinLotsMult','?')} / TP={m.get('TP_pips','?')}pips</span>
</div>"""
    chart_canvases_html += f"""
<div class="chart-inner">
  <canvas id="c{i}" role="img" aria-label="{pair} NC分布"></canvas>
</div>"""

canvases_html = f"""
<div class="charts-labels">
  {chart_labels_html}
</div>
<div class="charts-scroll">
  <div class="charts-inner-wrap">
    {chart_canvases_html}
  </div>
</div>"""

# ── 5. 最終HTML ─────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PEACE BT Analysis — 口座A</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f4f0;color:#1a1a18;font-size:14px;line-height:1.6}}
header{{background:#fff;border-bottom:1px solid #e0ded8;padding:16px 24px;display:flex;align-items:baseline;gap:12px}}
header h1{{font-size:17px;font-weight:500}}
header span{{font-size:12px;color:#888}}
main{{max-width:1080px;margin:0 auto;padding:24px}}
section{{margin-bottom:32px}}
h2{{font-size:13px;font-weight:500;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:12px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}}
.card{{background:#fff;border:0.5px solid #d8d6ce;border-radius:10px;padding:14px 16px}}
.card-title{{font-size:16px;font-weight:500;margin-bottom:2px}}
.card-sub{{font-size:11px;color:#888;margin-bottom:10px}}
.param-table{{width:100%;border-collapse:collapse;font-size:12px}}
.param-table td{{padding:3px 0;border-bottom:0.5px solid #eeede8}}
.param-table td:first-child{{color:#888;width:52%}}
.toolbar{{display:flex;gap:20px;margin-bottom:14px;font-size:13px;color:#555;flex-wrap:wrap;align-items:center}}
.toolbar label{{display:flex;align-items:center;gap:5px;cursor:pointer}}
.toolbar .sep{{width:1px;height:16px;background:#d8d6ce;margin:0 4px}}
.y-note{{font-size:11px;color:#aaa;margin-left:auto}}
.legend{{display:flex;gap:16px;margin-bottom:10px;font-size:12px;color:#666;flex-wrap:wrap}}
.legend span{{display:flex;align-items:center;gap:4px}}
.legend b{{display:inline-block;width:10px;height:10px;border-radius:2px}}
.chart-label{{font-size:13px;font-weight:500;color:#444;margin-bottom:4px}}
.chart-sub{{font-size:11px;font-weight:400;color:#999;margin-left:8px}}
.charts-labels{{margin-bottom:6px}}
.charts-scroll{{overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;border-top:0.5px solid #e8e6e0}}
.charts-inner-wrap{{display:flex;flex-direction:column}}
.chart-inner{{position:relative;height:150px;margin-top:4px}}
footer{{text-align:center;font-size:11px;color:#aaa;padding:24px;border-top:1px solid #e8e6e0}}
</style>
</head>
<body>
<header>
  <h1>PEACE BT Analysis</h1>
  <span>口座A — 2023〜2025 / HTM→JSON変換済み</span>
</header>
<main>

<section>
  <h2>BT パラメータ</h2>
  <div class="cards">
    {meta_html}
  </div>
</section>

<section>
  <h2>週次NC分布（クローズ週基準）</h2>
  <div class="toolbar">
    <span>表示:</span>
    <label><input type="checkbox" id="showNC1" checked> NC=1</label>
    <label><input type="checkbox" id="showNC2" checked> NC=2</label>
    <label><input type="checkbox" id="showNC3" checked> NC=3</label>
    <label><input type="checkbox" id="showNC4" checked> NC=4+</label>
    <div class="sep"></div>
    <label><input type="checkbox" id="unifyY"> Y軸を統一</label>
    <span class="y-note">Y軸 = その週にクローズしたグループ件数</span>
  </div>
  <div class="legend">
    <span><b style="background:#639922"></b>NC=1（ナンピンなし）</span>
    <span><b style="background:#BA7517"></b>NC=2</span>
    <span><b style="background:#D85A30"></b>NC=3</span>
    <span><b style="background:#A32D2D"></b>NC=4+</span>
  </div>
  {canvases_html}
</section>

</main>
<footer>生成: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')} — build_html.py</footer>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
const RAW = {chart_json};
const COLORS = {{1:'#639922',2:'#BA7517',3:'#D85A30',4:'#A32D2D'}};
const NC_LABELS = {{1:'NC=1',2:'NC=2',3:'NC=3',4:'NC=4+'}};
const PAIRS = Object.keys(RAW);
const weeks = Object.keys(RAW[PAIRS[0]]);

const PX_PER_WEEK = 16;
const CANVAS_W = weeks.length * PX_PER_WEEK;

const shortLabels = weeks.map(w => {{
  const [y, mo, d] = w.split('-');
  const day = parseInt(d);
  if (day <= 7) return mo === '01' ? y : mo;
  return '';
}});

const vertLinesPlugin = {{
  id: 'vertLines',
  afterDraw(chart) {{
    const ctx = chart.ctx;
    const xAxis = chart.scales.x;
    const {{top, bottom}} = chart.chartArea;
    weeks.forEach((w, i) => {{
      const [y, mo, d] = w.split('-');
      if (parseInt(d) > 7) return;
      const x = xAxis.getPixelForTick(i);
      ctx.save();
      if (mo === '01') {{
        ctx.strokeStyle = 'rgba(0,0,0,0.18)';
        ctx.lineWidth = 1;
      }} else {{
        ctx.strokeStyle = 'rgba(0,0,0,0.07)';
        ctx.lineWidth = 0.5;
      }}
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.restore();
    }});
  }}
}};

let charts = [];

function calcYMax(show) {{
  return Math.max(...PAIRS.map(pair =>
    Math.max(...weeks.map(w => {{
      const d = RAW[pair][w] || {{}};
      return [1,2,3,4].filter(nc => show[nc]).reduce((s,nc) => s+(d[nc]||0), 0);
    }}))
  ));
}}

function rebuild() {{
  charts.forEach(c => c.destroy());
  charts = [];
  const show = {{
    1: document.getElementById('showNC1').checked,
    2: document.getElementById('showNC2').checked,
    3: document.getElementById('showNC3').checked,
    4: document.getElementById('showNC4').checked,
  }};
  const unify = document.getElementById('unifyY').checked;
  const yMax  = unify ? calcYMax(show) : undefined;

  PAIRS.forEach((pair, idx) => {{
    const el = document.getElementById('c'+(idx+1));
    if (!el) return;
    el.width  = CANVAS_W;
    el.height = 150;
    const inner = el.parentElement;
    if (inner) inner.style.width = CANVAS_W + 'px';
    const d = RAW[pair];
    const datasets = [1,2,3,4].filter(nc => show[nc]).map(nc => ({{
      label: NC_LABELS[nc],
      data: weeks.map(w => d[w] ? (d[w][nc]||0) : 0),
      backgroundColor: COLORS[nc],
      borderWidth: 0,
      stack: 'stack',
    }}));
    charts.push(new Chart(el, {{
      type: 'bar',
      data: {{labels: shortLabels, datasets}},
      plugins: [vertLinesPlugin],
      options: {{
        responsive: false,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{display: false}},
          tooltip: {{
            callbacks: {{
              title: items => weeks[items[0].dataIndex] + ' 週',
              label: item => item.dataset.label + ': ' + item.raw + '件',
            }}
          }}
        }},
        scales: {{
          x: {{
            stacked: true,
            ticks: {{font:{{size:9}}, color:'#aaa', autoSkip:false, maxRotation:0}},
            grid: {{display:false}},
            barPercentage: 0.85,
            categoryPercentage: 1.0,
          }},
          y: {{
            stacked: true,
            max: yMax,
            ticks: {{font:{{size:10}}, color:'#999', maxTicksLimit:4}},
            grid: {{color:'rgba(0,0,0,0.06)'}},
          }},
        }},
        animation: false,
      }}
    }}));
  }});
}}

document.querySelector('.charts-inner-wrap').style.width = CANVAS_W + 'px';
rebuild();

['showNC1','showNC2','showNC3','showNC4','unifyY'].forEach(id => {{
  document.getElementById(id).addEventListener('change', rebuild);
}});
</script>
</body>
</html>"""

OUT.write_text(html, encoding='utf-8')
print(f"\n生成完了: {OUT}")
print(f"  サイズ: {OUT.stat().st_size:,} bytes")

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

# ── 2. グラフ用集計データを生成 ─────────────────────────
from collections import defaultdict
from datetime import date, timedelta

# 仮想含み損計算用：固定レート（注釈に明示）
# USDJPY=150円固定、GBPJPY≈190円、CHFJPY≈167円（=150/0.90）
PIP_SIZE = 0.0001          # 全ペア共通（JPY系でないため）
CONTRACT = 100_000         # 1ロット = 100,000通貨

PAIR_JPY_PER_LOT_PER_PIP = {
    'EURUSD': PIP_SIZE * CONTRACT * 150,        # USD建て → ×150
    'EURGBP': PIP_SIZE * CONTRACT * 190,        # GBP建て → GBPJPY≈190
    'USDCHF': PIP_SIZE * CONTRACT * 150 / 0.90, # CHF建て → CHFJPY≈167
}
RATE_NOTE = 'USDJPY=150 / GBPJPY=190 / CHFJPY=167（固定近似）'

def get_monday(date_str):
    d = date.fromisoformat(date_str[:10])
    return (d - timedelta(days=d.weekday())).isoformat()

def weekly_nc(groups):
    """各週にオープン中だったポジション数をナンピン段数別に集計（案A: リスク在中期間ベース）

    Y軸はグループ件数ではなくポジション数（オーダー数）。
    nc=N のグループは N ポジションを保有中として加算。
    表示ラベルはマニュアル準拠（NCはナンピン回数で0始まり、nc=N → マニュアルNC=N-1）。
    バケット: nc=1→bucket1(NC=0), nc=2→bucket2(NC=1), nc=3→bucket3(NC=2), nc>=4→bucket4(NC=3+)
    """
    from datetime import date, timedelta

    opens  = [date.fromisoformat(g['open_dt'][:10]) for g in groups]
    closes = [date.fromisoformat(g['close_dt'][:10]) for g in groups if g['close_dt']]
    if not opens:
        return {}

    period_start = min(opens) - timedelta(days=min(opens).weekday())
    period_end   = max(closes) if closes else max(opens)
    all_weeks = {}
    cur = period_start
    while cur <= period_end:
        all_weeks[cur.isoformat()] = {1:0, 2:0, 3:0, 4:0}
        cur += timedelta(days=7)

    for g in groups:
        open_d  = date.fromisoformat(g['open_dt'][:10])
        close_d = date.fromisoformat(g['close_dt'][:10]) if g['close_dt'] else period_end
        nc      = g['nc']
        nc_key  = min(nc, 4)
        mon = open_d - timedelta(days=open_d.weekday())
        while mon <= close_d:
            key = mon.isoformat()
            if key in all_weeks:
                all_weeks[key][nc_key] += nc  # グループ件数ではなくポジション数を加算
            mon += timedelta(days=7)

    return dict(sorted(all_weeks.items()))


def weekly_max_loss(groups, pair, meta):
    """各週の推定最大含み損（円）— NC+1想定発動価格ベース・保守的上限推計

    ステップNまで保有中、NC+1が発動するとしたら price_N ± NanpinPips の価格での
    ステップ0〜Nの合計含み損を計算し、その週の最大値を記録する。
    実際のDD（MT5実績）はこの値以下になることが多い（保守的上限）。
    """
    jpy_per_lot_per_pip = PAIR_JPY_PER_LOT_PER_PIP.get(pair, PIP_SIZE * CONTRACT * 150)
    nanpin_pips = float(meta.get('NanpinEntryPips', 120))
    weekly = {}

    for g in groups:
        entries = g['entries']
        pos_dir = g['pos_dir']

        for n in range(len(entries)):
            price_n  = entries[n]['price']
            # NC+1が発動するとしたら想定される価格（不利方向に NanpinPips 進んだ点）
            projected = price_n - nanpin_pips * PIP_SIZE if pos_dir == 'long' else price_n + nanpin_pips * PIP_SIZE
            week = get_monday(entries[n]['dt'])

            total_loss = 0.0
            for i in range(n + 1):
                price_i = entries[i]['price']
                lot_i   = entries[i]['lot']
                diff = (price_i - projected) if pos_dir == 'long' else (projected - price_i)
                total_loss += lot_i * (diff / PIP_SIZE) * jpy_per_lot_per_pip

            if total_loss > 0:
                weekly[week] = max(weekly.get(week, 0.0), total_loss)

    return dict(sorted(weekly.items()))


chart_data = {}
loss_data  = {}
all_weeks_set = set()

for d in all_data:
    key  = d['meta']['bt_name']
    pair = key.split('-')[2] if '-' in key else key
    chart_data[key] = weekly_nc(d['normal'])
    loss_data[key]  = weekly_max_loss(d['normal'], pair, d['meta'])
    all_weeks_set.update(loss_data[key].keys())

# 全ペア共通の週リスト（損失グラフ用）
all_loss_weeks = sorted(all_weeks_set)
# 各ペアのデータを共通週リストに整列（値なしは0）
loss_series = {}
for key in loss_data:
    loss_series[key] = [round(loss_data[key].get(w, 0)) for w in all_loss_weeks]

chart_json      = json.dumps(chart_data,    ensure_ascii=False, separators=(',',':'))
loss_weeks_json = json.dumps(all_loss_weeks, ensure_ascii=False, separators=(',',':'))
loss_data_json  = json.dumps(loss_series,   ensure_ascii=False, separators=(',',':'))

# ── 3. メタ情報テーブルHTML ─────────────────────────────
PARAM_LABELS = {
    'bt_name':              'BT名',
    'source':               '設定種別',
    'account':              '口座',
    'EMA_Type':             'EMA_Type',
    'EMA_reverse':          'EMA_reverse',
    'EMA_period':           'EMA_period',
    'Lots':                 '初期Lot',
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
    rows += f"<tr><td>時間足</td><td>M5</td></tr>"
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
<div class="charts-inner-wrap">
  {chart_canvases_html}
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
.charts-inner-wrap{{display:flex;flex-direction:column;border-top:0.5px solid #e8e6e0}}
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
  <h2>週次オープン中ポジション数（リスク在中ベース）</h2>
  <div class="toolbar">
    <span>表示:</span>
    <label><input type="checkbox" id="showNC1" checked> NC=0</label>
    <label><input type="checkbox" id="showNC2" checked> NC=1</label>
    <label><input type="checkbox" id="showNC3" checked> NC=2</label>
    <label><input type="checkbox" id="showNC4" checked> NC=3+</label>
    <div class="sep"></div>
    <label><input type="checkbox" id="unifyY"> Y軸を統一</label>
    <span class="y-note">Y軸 = その週に保有中だったポジション数（色はそのグループのナンピン段数、NC=ナンピン回数で0始まり）</span>
  </div>
  <div class="legend">
    <span><b style="background:#5A9E22"></b>NC=0（ナンピンなし）</span>
    <span><b style="background:#D4A017"></b>NC=1</span>
    <span><b style="background:#D85A30"></b>NC=2</span>
    <span><b style="background:#A32D2D"></b>NC=3+</span>
  </div>
  {canvases_html}
</section>

<section>
  <h2>週次 推定最大含み損（円）</h2>
  <p style="font-size:12px;color:#888;margin-bottom:12px">
    NC+1が発動するとしたら想定される価格（実約定価格±NanpinPips）での保有ポジション合計含み損。
    実際のDDより大きくなる傾向の<strong>保守的上限推計</strong>。3ペアの積み上げ表示。
    レート固定近似：{RATE_NOTE}
  </p>
  <div id="loss-inner" style="position:relative;height:240px">
    <canvas id="loss-chart" role="img" aria-label="3ペア推定含み損積み上げグラフ"></canvas>
  </div>
</section>

</main>
<footer>生成: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')} — build_html.py</footer>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
const RAW = {chart_json};
const COLORS = {{1:'#5A9E22',2:'#D4A017',3:'#D85A30',4:'#A32D2D'}};
const NC_LABELS = {{1:'NC=0',2:'NC=1',3:'NC=2',4:'NC=3+'}};
const PAIRS = Object.keys(RAW);
const weeks = Object.keys(RAW[PAIRS[0]]);


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
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{display: false}},
          tooltip: {{
            callbacks: {{
              title: items => weeks[items[0].dataIndex] + ' 週（保有中）',
              label: item => item.dataset.label + ': ' + item.raw + 'ポジション',
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

rebuild();

// ── 含み損グラフ（3ペア積み上げ棒グラフ）────────────────
const LOSS_WEEKS = {loss_weeks_json};
const LOSS_DATA  = {loss_data_json};

const LOSS_COLORS = [
  {{pair: Object.keys(LOSS_DATA)[0], color:'#185FA5'}},
  {{pair: Object.keys(LOSS_DATA)[1], color:'#D85A30'}},
  {{pair: Object.keys(LOSS_DATA)[2], color:'#3B6D11'}},
];

const lossLabels = LOSS_WEEKS.map(w => {{
  const [y,mo,d] = w.split('-');
  return parseInt(d) <= 7 ? (mo==='01' ? y : mo) : '';
}});

let lossChart = null;

function buildLossChart() {{
  if (lossChart) lossChart.destroy();
  const el = document.getElementById('loss-chart');

  const datasets = LOSS_COLORS.map(c => ({{
    label: c.pair.split('-')[2] || c.pair,
    data: LOSS_DATA[c.pair],
    backgroundColor: c.color,
    borderWidth: 0,
    stack: 'stack',
  }}));

  lossChart = new Chart(el, {{
    type: 'bar',
    data: {{labels: lossLabels, datasets}},
    plugins: [vertLinesPlugin],
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{
          display: true,
          position: 'top',
          labels: {{font:{{size:12}}, boxWidth:12, padding:16}},
        }},
        tooltip: {{
          callbacks: {{
            title: items => LOSS_WEEKS[items[0].dataIndex] + ' 週',
            label: item => item.dataset.label + ': ' + Math.round(item.raw).toLocaleString() + '円',
            footer: items => '合計: ' + Math.round(items.reduce((s,i)=>s+i.raw,0)).toLocaleString() + '円',
          }}
        }}
      }},
      scales: {{
        x: {{
          stacked: true,
          ticks: {{font:{{size:9}},color:'#aaa',autoSkip:false,maxRotation:0}},
          grid: {{display:false}},
          barPercentage: 0.85,
          categoryPercentage: 1.0,
        }},
        y: {{
          stacked: true,
          ticks: {{
            font:{{size:10}},color:'#999',maxTicksLimit:5,
            callback: v => (v>=10000 ? Math.round(v/1000)+'K' : v) + '円',
          }},
          grid: {{color:'rgba(0,0,0,0.06)'}},
        }},
      }},
      animation: false,
    }}
  }});
}}

buildLossChart();

['showNC1','showNC2','showNC3','showNC4','unifyY'].forEach(id => {{
  document.getElementById(id).addEventListener('change', rebuild);
}});
</script>
</body>
</html>"""

OUT.write_text(html, encoding='utf-8')
print(f"\n生成完了: {OUT}")
print(f"  サイズ: {OUT.stat().st_size:,} bytes")

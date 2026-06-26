#pragma once

/* Inline HTML dashboard — served at GET / */
static const char INDEX_HTML[] = R"=====(
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Power Profiler</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,sans-serif;background:#0d1117;color:#c9d1d9;padding:24px;min-height:100vh}
h1{font-size:22px;font-weight:700;margin-bottom:4px;color:#f0f6fc}
.sub{font-size:12px;color:#8b949e;margin-bottom:24px}
.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:24px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;text-align:center}
.card .val{font-size:28px;font-weight:700}
.card .lbl{font-size:11px;color:#8b949e;margin-top:4px;text-transform:uppercase;letter-spacing:0.5px}
.val.v{color:#58a6ff}
.val.c{color:#3fb950}
.val.p{color:#f78166}
.val.e{color:#d2a8ff}
.charts{display:grid;grid-template-columns:1fr;gap:16px;margin-bottom:16px}
canvas{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:8px;width:100%;height:250px}
.foot{text-align:center;font-size:11px;color:#484f58;margin-top:12px}
.foot span{color:#8b949e}
</style>
</head>
<body>
<h1>⚡ Power Profiler</h1>
<p class="sub">Live dashboard &middot; updated every second</p>

<div class="metrics">
<div class="card"><div class="val v" id="m-volt">--</div><div class="lbl">Voltage (V)</div></div>
<div class="card"><div class="val c" id="m-curr">--</div><div class="lbl">Current (mA)</div></div>
<div class="card"><div class="val p" id="m-power">--</div><div class="lbl">Power (mW)</div></div>
</div>

<div class="charts">
<div><canvas id="ch-volt"></canvas></div>
<div><canvas id="ch-curr"></canvas></div>
<div><canvas id="ch-power"></canvas></div>
</div>

<div style="text-align:center;margin-top:8px">
<span class="val e" id="m-energy" style="font-size:22px">--</span>
<span class="lbl" style="margin-left:6px;color:#8b949e">accumulated energy (mWh)</span>
</div>

<p class="foot"><span id="wifi-ip">--</span> &middot; <span id="upd">--</span></p>

<script>
const COLORS = ['#58a6ff','#3fb950','#f78166'];
function makeChart(id, label, color) {
    const ctx = document.getElementById(id).getContext('2d');
    return new Chart(ctx, {
        type: 'line',
        data: {labels:[], datasets:[{label,data:[],borderColor:color,backgroundColor:color+'20',
            borderWidth:2,pointRadius:0,tension:0.35,fill:true}]},
        options: {
            responsive:true, maintainAspectRatio:false,
            animation:{duration:200},
            scales:{
                x:{display:true,ticks:{color:'#8b949e',maxTicksLimit:8,font:{size:10}},grid:{color:'#21262d'}},
                y:{display:true,ticks:{color:'#8b949e',font:{size:10},callback:v=>v.toFixed(2)},grid:{color:'#21262d'}}
            },
            plugins:{legend:{display:false}}
        }
    });
}

const chV = makeChart('ch-volt', 'Voltage', COLORS[0]);
const chC = makeChart('ch-curr', 'Current', COLORS[1]);
const chP = makeChart('ch-power', 'Power', COLORS[2]);

async function fetchData() {
    try {
        const r = await fetch('/api/data');
        if (!r.ok) return;
        const d = await r.json();

        const labels = d.t.map(ms => (ms/1000).toFixed(0) + 's');
        chV.data.labels = labels; chV.data.datasets[0].data = d.v;
        chC.data.labels = labels; chC.data.datasets[0].data = d.c;
        chP.data.labels = labels; chP.data.datasets[0].data = d.p;
        chV.update('none'); chC.update('none'); chP.update('none');

        const n = d.v.length;
        if (n > 0) {
            document.getElementById('m-volt').textContent = d.v[n-1].toFixed(3);
            document.getElementById('m-curr').textContent = d.c[n-1].toFixed(3);
            document.getElementById('m-power').textContent = d.p[n-1].toFixed(3);
        }
        document.getElementById('m-energy').textContent = d.e.toFixed(3) + ' mWh';
        document.getElementById('upd').textContent = new Date().toLocaleTimeString();
    } catch(e) { console.error(e); }
}

let ip = '--';
fetch('/api/latest').then(r=>r.json()).then(d=>{ if(d.ip) { ip=d.ip; document.getElementById('wifi-ip').textContent='ESP32 @ '+ip; } }).catch(()=>{});

fetchData();
setInterval(fetchData, 1000);
</script>
</body>
</html>
)=====";

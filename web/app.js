const $ = (id) => document.getElementById(id);
const demoText = '【虚构教学案例】上海金午盘基准价为 620 元/克，较早盘 625 元/克下跌，较上一交易日午盘 610 元/克上涨 2%。';
const sampleURL = 'https://invest.10jqka.com.cn/20260824/c679225891.shtml';
let mode = 'demo', busy = false, active = null, liveInput = sampleURL;
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL = (u) => { try { const p = new URL(u); return ['https:','http:'].includes(p.protocol) ? p.href : ''; } catch { return ''; } };

async function request(url, options) {
  const res = await fetch(url, options); const data = await res.json();
  if (!res.ok) throw new Error(data.error || '请求失败'); return data;
}
function setMode(next) {
  if (busy) return;
  if (mode !== 'demo') liveInput = $('task').value;
  mode = next;
  $('demo-mode').classList.toggle('selected', mode === 'demo');
  $('live-mode').classList.toggle('selected', mode === 'live');
  $('multi-mode').classList.toggle('selected', mode === 'multi');
  $('task').value = mode === 'demo' ? demoText : liveInput;
  $('task').disabled = mode === 'demo'; $('strategy').disabled = mode !== 'live';
  $('start').innerHTML = (mode === 'demo' ? '运行教学演示' : mode === 'multi' ? '开始协作调查' : '开始联网调查') + ' <span>→</span>';
  $('mode-note').textContent = mode === 'demo' ? '免 Key · 虚构资料 · 固定流程，先看一遍完整效果。' : mode === 'multi' ? '三个独立研究员并行调查，由裁判 Agent 对证据和冲突进行合并。' : 'OpenAI 自主调用工具，调查员完成后交由审核员检查。';
  $('budget').textContent = mode === 'demo' ? '演示不调用模型、不消耗 API 额度。' : mode === 'multi' ? '三名研究员各自拥有独立预算，API 消耗约为单调查模式的三倍以上。' : '最多 12 次研究工具调用、5 次搜索请求。联网与模型调用会消耗 API 额度。';
  $('form-error').classList.add('hidden');
}
$('demo-mode').onclick = () => setMode('demo'); $('live-mode').onclick = () => setMode('live'); $('multi-mode').onclick = () => setMode('multi');
$('sample').onclick = () => { if (!busy) { setMode('live'); $('task').value = sampleURL; } };

async function history() {
  const runs = await request('/api/runs');
  $('history').replaceChildren();
  if (!runs.length) { $('history').textContent = '完成第一条调查后，这里会留下记录。'; return; }
  for (const run of runs.slice(0,5)) {
    const button = document.createElement('button'); button.type = 'button';
    button.innerHTML = `${esc(run.mode === 'demo' ? '教学演示 · 三个说法的核验' : run.input.slice(0,48))}<small>${esc(new Date(run.created_at).toLocaleString())} · ${esc(run.status === 'completed' ? '已完成' : '未完成')}</small>`;
    button.onclick = async () => { if (busy) return; try { active = run.id; render(await request('/api/runs/' + run.id)); } catch(e) { showError(e.message); } };
    $('history').append(button);
  }
}
function showError(text) { $('form-error').textContent = text; $('form-error').classList.remove('hidden'); }
function render(run) {
  $('welcome').classList.add('hidden'); $('run-view').classList.remove('hidden');
  $('run-mode').textContent = run.mode === 'demo' ? 'TEACHING DEMO / 虚构样例' : run.mode === 'multi' ? 'MULTI-AGENT / 协作调查' : 'LIVE INVESTIGATION / 联网调查';
  $('result-title').textContent = run.report?.title || (run.status === 'failed' ? '调查暂未完成' : '正在沿着证据调查');
  $('run-state').textContent = {running:'调查中',completed:'已完成',failed:'未完成'}[run.status];
  $('notice').textContent = run.notice || '正在收集公开资料。工具受阻会如实记录，无法确认的说法将保留为证据不足。';
  $('run-error').classList.toggle('hidden', !run.error && !run.save_error); $('run-error').textContent = run.error || run.save_error || '';
  $('metric-claims').textContent = run.report?.claims?.length ?? '—'; $('metric-evidence').textContent = run.evidence.length;
  $('metric-tools').textContent = run.usage.tool_calls; $('metric-time').textContent = run.duration_seconds ?? '…';
  $('events').innerHTML = run.events.map(e => `<li><b>${esc(e.stage)}</b><span>${esc(e.message)}</span>${e.details ? `<details><summary>查看工具参数</summary><pre>${esc(JSON.stringify(e.details,null,2))}</pre></details>`:''}</li>`).join('');
  $('events').scrollTop = $('events').scrollHeight;
  $('report-section').classList.toggle('hidden', !run.report);
  if (run.report) {
    $('summary').textContent = run.report.summary;
    $('candidates-section').classList.toggle('hidden', !run.candidates?.length);
    $('candidates').innerHTML = (run.candidates || []).map(c => `<article class="candidate"><div><b>${esc(c.strategy_name)}</b><span class="badge ${c.status === 'failed' ? 'red' : ''}">${esc(c.status === 'completed' ? '已完成' : '受阻')}</span></div><p>${esc(c.report?.summary || c.error || '没有生成候选报告')}</p><small>${esc(c.evidence_count)} 条证据 · ${esc(c.usage?.tool_calls || 0)} 次工具 · ${esc((c.usage?.input_tokens || 0) + (c.usage?.output_tokens || 0))} tokens</small></article>`).join('');
    $('claims').innerHTML = run.report.claims.map((c,i) => `<article class="claim"><div class="claim-top"><h4>${i+1}. ${esc(c.statement)}</h4><span class="badge ${c.verdict === '有证据反驳' ? 'red' : c.verdict !== '有证据支持' ? 'amber' : ''}">${esc(c.verdict)}</span></div><p>${esc(c.reason)}</p>${c.evidence_ids.map(id => `<a class="ref" href="#source-${esc(id)}">${esc(id)} ↗</a>`).join('')}</article>`).join('');
    $('unresolved').innerHTML = run.report.unresolved.map(t => `<li>${esc(t)}</li>`).join('') || '<li>未记录其他问题；这不代表结论绝对正确。</li>';
    $('review').textContent = run.report.review;
    $('validation').textContent = run.report.validation_notes?.join(' ') || '';
    $('download').href = '/api/runs/' + run.id + '/markdown';
  }
  $('evidence').innerHTML = run.evidence.map(e => {
    const url = safeURL(e.url);
    const links = (e.citations || []).filter(c => safeURL(c.url)).map(c => `<li><a href="${esc(safeURL(c.url))}" target="_blank" rel="noopener noreferrer">${esc(c.title || c.url)}</a></li>`).join('');
    return `<details class="source" id="source-${esc(e.id)}"><summary><strong>${esc(e.id)}</strong><span>${esc(e.title)}</span></summary><p class="fine">获取时间：${esc(e.retrieved_at)}${e.published_at ? ' · 资料发布时间：' + esc(e.published_at) : ''}</p>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">查看原始来源 ↗</a>` : '<p class="fine">本地计算或虚构教学材料</p>'}<pre>${esc(e.text)}</pre>${links ? '<ul>' + links + '</ul>' : ''}</details>`;
  }).join('') || '<p class="hint">尚未取得资料；失败的请求不会生成证据卡。</p>';
  $('usage').textContent = `输入 ${run.usage.input_tokens} / 输出 ${run.usage.output_tokens} tokens · ${run.usage.search_requests} 次搜索请求 · ${run.review_status || '等待审核'} · 本地保存 JSON 与 Markdown`;
}
document.addEventListener('click', e => { const a = e.target.closest('a.ref'); if(a) { const el = document.querySelector(a.getAttribute('href')); if(el) el.open = true; } });
$('investigation').onsubmit = async (event) => {
  event.preventDefault(); if (busy) return;
  $('form-error').classList.add('hidden'); busy = true; $('start').disabled = true; $('start').textContent = '调查进行中…';
  try {
    const result = await request('/api/runs', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({mode, input:$('task').value, strategy:$('strategy').value})});
    active = result.id;
    let firstRender = true;
    while (true) { const run = await request('/api/runs/' + active); render(run); if(firstRender && window.innerWidth < 740) $('run-view').scrollIntoView({behavior:'smooth',block:'start'}); firstRender = false; if(run.status !== 'running') break; await new Promise(r => setTimeout(r,1000)); }
    await history();
  } catch(e) { showError(e.message); }
  finally { busy = false; $('start').disabled = false; $('start').innerHTML = (mode === 'demo' ? '运行教学演示' : mode === 'multi' ? '开始协作调查' : '开始联网调查') + ' <span>→</span>'; }
};
async function init() {
  setMode('demo');
  try { const cfg = await request('/api/config'); $('connection').textContent = cfg.model_ready ? `已配置 · ${cfg.model}` : 'OpenAI Key 待配置'; $('connection').classList.toggle('ready',cfg.model_ready); await history(); }
  catch(e) { $('connection').textContent = '本地服务未连接'; showError(e.message); }
}
init();

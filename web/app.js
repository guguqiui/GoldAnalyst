const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const safeURL = value => { try { const url = new URL(value); return ['http:','https:'].includes(url.protocol) ? url.href : ''; } catch { return ''; } };
let activeSession = null;
let activeRun = null;
let busy = false;

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}

function setError(message = '') {
  $('chat-error').textContent = message;
  $('chat-error').classList.toggle('hidden', !message);
}

function scrollToBottom() {
  requestAnimationFrame(() => { $('chat-scroll').scrollTop = $('chat-scroll').scrollHeight; });
}

function setBusy(value) {
  busy = value;
  $('send').disabled = value;
  $('prompt').disabled = value;
  $('send').innerHTML = value ? '调查中…' : '发送 <b>↑</b>';
}

function visibleMessageContent(content) {
  return String(content || '').replace(/\n?\[run_id:\s*[0-9a-f]{16}\]\s*$/i, '').trim();
}

function verdictLabel(claim, index, run) {
  if (claim.verdict === '部分成立／表述误导') return '部分成立';
  if (claim.verdict !== '部分成立') return claim.verdict;
  const verification = run.verification_result?.fact_results?.[index];
  const explanation = [verification?.reason, ...(verification?.unresolved || [])].join(' ');
  const failedCrossCheck = verification?.verdict === 'uncorroborated'
    || ['交叉核验', 'URL 不同的新文章', '前序 Agent 已阅读的原始文章']
      .some(marker => explanation.includes(marker));
  return failedCrossCheck ? '未通过交叉验证' : '部分成立';
}

function evidenceExcerpt(item) {
  if (safeURL(item.url)) return '';
  const navigation = new Set(['主页', 'Goldhub', '市场洞察', 'Back to Insights', 'PDF']);
  let lines = String(item.text || '')
    .replace(/\[([^\]]*)\]\(https?:\/\/[^)]+\)/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .split('\n').map(line => line.trim())
    .filter(line => line && !navigation.has(line) && !/^\d+$/.test(line) && !/^\d+(\.\d+)?\s*(kb|mb)$/i.test(line));
  const seenLines = new Set();
  const unique = lines.filter(line => {
    if (seenLines.has(line)) return false;
    seenLines.add(line);
    return true;
  });
  const limit = 1800;
  const text = unique.join('\n');
  return text.length > limit ? text.slice(0, limit).trimEnd() + '…' : text;
}

function sourceLabel(url, preferred = '') {
  const hostname = new URL(url).hostname.replace(/^www\./, '');
  if (hostname === 'china.gold.org' || hostname.endsWith('.gold.org')) return '世界黄金协会';
  if (hostname === 'sge.com.cn' || hostname.endsWith('.sge.com.cn')) return '上海黄金交易所';
  return preferred && preferred !== hostname ? preferred : hostname;
}

function canonicalLink(url) {
  const parsed = new URL(url);
  parsed.hash = '';
  for (const key of [...parsed.searchParams.keys()]) {
    if (key.toLowerCase().startsWith('utm_')) parsed.searchParams.delete(key);
  }
  return parsed.href.replace(/\/$/, '');
}

function articleLabel(url, preferred, evidenceByURL) {
  const matched = evidenceByURL.get(canonicalLink(url));
  if (matched?.title) return matched.title;
  const hostname = new URL(url).hostname.replace(/^www\./, '');
  const candidate = String(preferred || '').trim();
  if (candidate && candidate !== hostname && candidate !== sourceLabel(url)) return candidate;
  const path = decodeURIComponent(new URL(url).pathname).replace(/\/$/, '');
  return `候选文章 · ${path || hostname}`;
}

function evidenceLinks(item, evidenceByURL) {
  const directURL = safeURL(item.url);
  if (directURL) {
    return {
      primary: [{
        title:articleLabel(directURL, item.title, evidenceByURL),
        source:sourceLabel(directURL, item.source_name || item.source_domain),
        url:directURL,
      }],
      extra: [],
    };
  }
  const citationByURL = new Map();
  for (const citation of item.citations || []) {
    const url = safeURL(citation.url);
    if (url) citationByURL.set(canonicalLink(url), citation);
  }
  const inlineLinks = [];
  for (const match of String(item.text || '').matchAll(/\[([^\]]*)\]\((https?:\/\/[^)]+)\)/g)) {
    const url = safeURL(match[2]);
    if (url) {
      const citation = citationByURL.get(canonicalLink(url)) || {};
      inlineLinks.push({
        title:articleLabel(url, citation.title || match[1], evidenceByURL),
        source:sourceLabel(url, citation.source_name || citation.domain),
        url,
      });
    }
  }
  const citationLinks = [];
  for (const citation of item.citations || []) {
    const url = safeURL(citation.url);
    if (url) citationLinks.push({
      title:articleLabel(url, citation.title, evidenceByURL),
      source:sourceLabel(url, citation.source_name || citation.domain),
      url,
    });
  }
  const seen = new Set();
  const unique = [...inlineLinks, ...citationLinks].filter(link => {
    const key = canonicalLink(link.url);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  const citedCount = inlineLinks.length ? new Set(inlineLinks.map(link => canonicalLink(link.url))).size : 3;
  const primaryCount = Math.min(Math.max(citedCount, 1), 3);
  return {primary:unique.slice(0, primaryCount), extra:unique.slice(primaryCount)};
}

function renderMessages(snapshot) {
  activeSession = snapshot.session.session_id;
  $('chat-title').textContent = snapshot.session.title || '黄金调查';
  $('empty').classList.add('hidden');
  $('messages').classList.remove('hidden');
  $('messages').innerHTML = snapshot.messages.map(message => {
    const role = message.role === 'user' ? 'user' : 'assistant';
    const label = role === 'user' ? '你' : 'Gold Analyst';
    const report = role === 'assistant' && message.run_id
      ? `<button class="report-link" type="button" data-run-id="${esc(message.run_id)}">查看完整调查报告 ↗</button>` : '';
    return `<article class="message ${role}"><div class="avatar">${role === 'user' ? '你' : 'Au'}</div><div class="message-body"><b>${label}</b><p>${esc(visibleMessageContent(message.content))}</p>${report}</div></article>`;
  }).join('');
  scrollToBottom();
}

async function loadSessions() {
  const sessions = await request('/api/sessions');
  $('history').replaceChildren();
  if (!sessions.length) {
    $('history').innerHTML = '<p class="muted">还没有调查记录</p>';
    return sessions;
  }
  for (const session of sessions) {
    const row = document.createElement('div');
    row.className = 'history-row' + (session.session_id === activeSession ? ' selected' : '');
    row.innerHTML = `<button class="history-open" type="button" data-session-id="${esc(session.session_id)}"><span>${esc(session.title || '未命名调查')}</span><small>${esc(new Date(session.updated_at).toLocaleString())}</small></button><button class="history-delete" type="button" data-delete-session="${esc(session.session_id)}" data-title="${esc(session.title || '未命名调查')}" aria-label="删除对话">×</button>`;
    $('history').append(row);
  }
  return sessions;
}

async function loadSession(sessionId, inspectLastRun = false) {
  const snapshot = await request('/api/sessions/' + sessionId);
  renderMessages(snapshot);
  await loadSessions();
  if (inspectLastRun) {
    const last = snapshot.messages.at(-1);
    if (last?.role === 'user' && last.run_id) {
      const run = await request('/api/runs/' + last.run_id);
      if (run.status === 'running') await pollRun(run.id);
    }
  }
}

function mergedEvents(events) {
  const rows = [];
  const positions = new Map();
  for (const event of events || []) {
    const id = event.details?.activity_id;
    if (id && positions.has(id)) rows[positions.get(id)] = event;
    else {
      if (id) positions.set(id, rows.length);
      rows.push(event);
    }
  }
  return rows.slice(-8);
}

function renderActivity(run) {
  const running = run.status === 'running';
  $('activity').classList.toggle('hidden', !running);
  if (!running) return;
  const events = mergedEvents(run.events);
  $('activity-title').textContent = events.at(-1)?.message || 'Multi-Agent 正在规划调查…';
  $('activity-meta').textContent = `${run.usage?.tool_calls || 0} 次工具调用`;
  $('events').innerHTML = events.map(event => {
    const state = event.details?.state;
    const status = state === 'completed' ? '✓' : state === 'failed' ? '×' : '…';
    return `<li><span>${status}</span><b>${esc(event.stage)}</b><p>${esc(event.message)}</p></li>`;
  }).join('');
  scrollToBottom();
}

async function pollRun(runId) {
  activeRun = runId;
  while (activeRun === runId) {
    const run = await request('/api/runs/' + runId);
    renderActivity(run);
    if (run.status !== 'running') {
      activeRun = null;
      setBusy(false);
      if (run.session_id) await loadSession(run.session_id);
      if (run.status === 'failed') setError(run.error || '调查没有完成');
      return;
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
}

function newChat() {
  if (busy) return;
  activeSession = null;
  activeRun = null;
  $('chat-title').textContent = '新调查';
  $('messages').replaceChildren();
  $('messages').classList.add('hidden');
  $('activity').classList.add('hidden');
  $('empty').classList.remove('hidden');
  setError();
  $('prompt').value = '';
  $('prompt').focus();
  loadSessions().catch(error => setError(error.message));
}

async function submitPrompt() {
  const input = $('prompt').value.trim();
  if (!input || busy) return;
  setBusy(true);
  setError();
  try {
    const url = activeSession ? `/api/sessions/${activeSession}/messages` : '/api/runs';
    const body = activeSession ? {input} : {mode:'multi', input, strategy:'source_first'};
    const result = await request(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    activeSession = result.session_id;
    $('prompt').value = '';
    await loadSession(activeSession);
    await pollRun(result.id);
  } catch (error) {
    setBusy(false);
    setError(error.message);
  }
}

async function showReport(runId) {
  const run = await request('/api/runs/' + runId);
  const report = run.report || {};
  const evidenceByURL = new Map();
  for (const item of run.evidence || []) {
    const url = safeURL(item.url);
    if (url) evidenceByURL.set(canonicalLink(url), item);
  }
  $('report-title').textContent = report.title || '调查未生成报告';
  const claims = (report.claims || []).map((claim, index) => `<article class="claim"><div><b>${index + 1}. ${esc(claim.statement)}</b><span>${esc(verdictLabel(claim, index, run))}</span></div><p>${esc(claim.reason)}</p></article>`).join('');
  const evidence = (run.evidence || []).map(item => {
    const excerpt = evidenceExcerpt(item);
    const links = evidenceLinks(item, evidenceByURL);
    const renderLink = link => `<a href="${esc(link.url)}" target="_blank" rel="noopener noreferrer"><strong>${esc(link.title)}</strong><small>${esc(link.source)} ↗</small></a>`;
    const primaryLinks = links.primary.map(renderLink).join('');
    const extraLinks = links.extra.map(renderLink).join('');
    const more = extraLinks ? `<details class="source-more"><summary>查看其他 ${links.extra.length} 个候选来源</summary><div class="source-links">${extraLinks}</div></details>` : '';
    return `<details class="source"><summary>${esc(item.id)} · ${esc(item.title)}</summary><div class="source-body">${excerpt ? `<p class="source-excerpt">${esc(excerpt)}</p>` : ''}${primaryLinks ? `<div class="source-links">${primaryLinks}</div>${more}` : '<p class="muted">这条记录没有可打开的原始网页。</p>'}</div></details>`;
  }).join('');
  $('report-body').innerHTML = `<p class="report-summary">${esc(report.summary || run.error || '暂无结论')}</p>${claims}<h3>证据资料</h3>${evidence || '<p class="muted">没有可用证据</p>'}`;
  $('report-dialog').showModal();
}

async function deleteSession(sessionId, title) {
  if (busy) return;
  if (!window.confirm(`确定删除“${title}”吗？\n消息、调查报告和运行记录都会被删除，且无法恢复。`)) return;
  try {
    await request('/api/sessions/' + sessionId, {method:'DELETE'});
    if (activeSession === sessionId) newChat();
    else await loadSessions();
  } catch (error) {
    setError(error.message);
  }
}

$('composer').addEventListener('submit', event => { event.preventDefault(); submitPrompt(); });
$('prompt').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submitPrompt(); }
});
$('new-chat').addEventListener('click', newChat);
$('sidebar-toggle').addEventListener('click', () => $('sidebar').classList.toggle('open'));
$('close-report').addEventListener('click', () => $('report-dialog').close());
$('report-dialog').addEventListener('click', event => { if (event.target === $('report-dialog')) $('report-dialog').close(); });
document.addEventListener('click', async event => {
  const suggestion = event.target.closest('.suggestion');
  if (suggestion) { $('prompt').value = suggestion.textContent; $('prompt').focus(); }
  const sessionButton = event.target.closest('[data-session-id]');
  if (sessionButton && !busy) {
    try { await loadSession(sessionButton.dataset.sessionId, true); $('sidebar').classList.remove('open'); }
    catch (error) { setError(error.message); }
  }
  const deleteButton = event.target.closest('[data-delete-session]');
  if (deleteButton) await deleteSession(deleteButton.dataset.deleteSession, deleteButton.dataset.title);
  const reportButton = event.target.closest('[data-run-id]');
  if (reportButton) {
    try { await showReport(reportButton.dataset.runId); }
    catch (error) { setError(error.message); }
  }
});

async function init() {
  try {
    const [config, sessions] = await Promise.all([request('/api/config'), loadSessions()]);
    $('connection').textContent = config.model_ready ? `${config.provider === 'codex' ? 'Codex' : 'OpenAI'} · ${config.model}` : '模型尚未配置';
    $('connection').classList.toggle('ready', config.model_ready);
    if (!config.model_ready) setError('请先配置模型，再开始调查。');
    if (sessions.length) await loadSession(sessions[0].session_id, true);
    else newChat();
  } catch (error) {
    setError(error.message);
  }
}

init();

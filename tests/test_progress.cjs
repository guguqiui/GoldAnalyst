// 只测试纯渲染函数，不需要浏览器、前端框架或网络。
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const escLine = source.split('\n').find(line => line.startsWith('const esc ='));
const renderer = source.slice(source.indexOf('function renderEvents('), source.indexOf('function render(run)'));
const render = vm.runInNewContext(escLine + '\n' + renderer + '\nrenderEvents');
const event = (id, state) => ({stage:'工具', message:'read_url', details:{activity_id:id, state}});

test('同一步更新状态，其他并行工具仍显示执行中', () => {
  const html = render([event('a', 'running'), event('b', 'running'), event('a', 'completed')], 'running');
  assert.equal((html.match(/<li>/g) || []).length, 2);
  assert.match(html, /已完成/);
  assert.match(html, /执行中/);
});

test('失败不会显示成功，结束的运行不会残留执行中', () => {
  const html = render([event('a', 'failed'), event('b', 'running')], 'failed');
  assert.match(html, /失败/);
  assert.match(html, /已中断/);
  assert.doesNotMatch(html, /已完成|执行中/);
});

test('兼容旧事件并转义不可信文本', () => {
  const html = render([{stage:'旧事件', message:'<script>test</script>', details:{query:'<img>'}}], 'completed');
  assert.match(html, /旧事件/);
  assert.doesNotMatch(html, /<script>|<img>/);
});

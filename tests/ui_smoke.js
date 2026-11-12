// 页面冒烟测试:node tests/ui_smoke.js <html 文件>   (需要 playwright;没有则跳过)
let chromium; try { ({ chromium } = require('playwright')); } catch (e) { console.log('SKIP: 没有 playwright'); process.exit(0); }
(async () => {
  const file = process.argv[2];
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1100, height: 800 } });
  const errs = []; p.on('pageerror', e => errs.push(e.message));
  await p.goto('file://' + file);
  const fail = m => { console.log('FAIL:', m); process.exitCode = 1; };
  const tabs = await p.$$eval('nav.tabs button', bs => bs.map(x => x.dataset.v));
  for (const need of ['overview', 'map', 'chapters', 'concepts', 'review', 'quiz', 'quality']) if (!tabs.includes(need)) fail('缺标签 ' + need);
  for (const v of tabs) { await p.click(`nav.tabs button[data-v="${v}"]`); const on = await p.$eval('#v-' + v, e => e.classList.contains('on')); if (!on) fail('切换失败 ' + v); }
  // 论证地图:有节点、tier3 默认隐藏、勾选后出现
  await p.click('nav.tabs button[data-v="map"]');
  const n1 = await p.$$eval('#v-map li.node[data-id]', xs => xs.filter(x => x.offsetParent !== null).length);
  await p.check('#chk3'); const n2 = await p.$$eval('#v-map li.node[data-id]', xs => xs.filter(x => x.offsetParent !== null).length);
  if (!(n1 > 0)) fail('地图没有可见节点'); if (n2 < n1) fail('显示细节后节点变少');
  // 展开全部
  await p.click('#expAll'); const col = await p.$$eval('#v-map .node.collapsed', xs => xs.length); if (col !== 0) fail('展开全部无效');
  // 搜索
  const term = await p.evaluate(() => Object.values(BOOK.cards)[0].label.slice(0, 2)); await p.fill('#q', term); await p.waitForTimeout(100);
  const vis = await p.$$eval('.item', xs => xs.filter(x => x.offsetParent !== null).length); if (!(vis > 0)) fail('搜索无结果'); 
  await p.fill('#q', ''); 
  // 自测:看答案/标记/持久化
  await p.click('nav.tabs button[data-v="quiz"]');
  await p.click('.q button.rev >> nth=0'); const open = await p.$eval('.q', q => q.classList.contains('open')); if (!open) fail('看答案无效');
  await p.click('.q button.got >> nth=0'); const t = await p.$eval('#ptxt', e => e.textContent); if (!/掌握 1/.test(t)) fail('进度没更新: ' + t);
  await p.reload(); await p.click('nav.tabs button[data-v="quiz"]'); const t2 = await p.$eval('#ptxt', e => e.textContent); if (!/掌握 1/.test(t2)) fail('刷新后进度丢失: ' + t2);
  // 检索短语可复制按钮存在
  const copies = await p.$$eval('[data-copy]', xs => xs.length); if (!(copies > 0)) fail('没有检索短语');
  if (errs.length) fail('页面报错: ' + errs.join(';'));
  console.log(process.exitCode ? 'UI 冒烟测试失败' : 'UI 冒烟测试通过', `(节点 ${n1}→${n2}, 检索短语 ${copies})`);
  await b.close();
})();

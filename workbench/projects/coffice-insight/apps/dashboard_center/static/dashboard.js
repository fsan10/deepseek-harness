(function () {
  const frame = document.getElementById('dashboardFrame');
  const loading = document.getElementById('loadingState');
  const error = document.getElementById('errorState');
  const empty = document.getElementById('emptyState');
  const fullscreen = document.getElementById('fullscreenDashboard');
  const BLANK = 'about:blank';
  let current = null;
  let loadTimer = null;
  let expectedSrc = null;
  let navigation = 0;
  const codeFromUrl = () => new URLSearchParams(location.search).get('code');
  const show = node => { [loading,error,empty].forEach(item => item.hidden = item !== node); frame.hidden = node !== null; };
  const embedUrl = config => {
    if (!config?.proxy_path) throw new Error('DataEase嵌入代理配置不可用');
    const localProxy = new URL(location.href); localProxy.port = String(config.proxy_port); localProxy.pathname = '/'; localProxy.search = ''; localProxy.hash = '';
    const origin = config.proxy_public_url || localProxy.origin;
    return new URL(config.proxy_path, origin.replace(/\/?$/, '/')).href;
  };

  async function request(path) {
    const response = await fetch(path); const result = await response.json();
    if (!response.ok) throw new Error(result.message || '请求失败'); return result.data;
  }
  // 重新加载看板时 iframe 的地址与当前地址相同，必须真正发起一次新导航，否则只会原地不动。
  // 不能先 removeAttribute('src')：它只会*异步*安排一次 about:blank 导航，紧跟其后的 src 赋值会与它竞态，
  // 赋值先于 about:blank 提交时这次导航会被丢弃，看板永久停在白屏，必须再点一次才有结果。
  // 这里改成先显式导航到 about:blank 并等它提交，再导航到看板地址，顺序不再依赖浏览器时序。
  function navigate(url) {
    if (!frame.getAttribute('src')) { expectedSrc = url; frame.src = url; return; }
    const token = ++navigation;
    expectedSrc = BLANK;
    frame.src = BLANK;
    new Promise(resolve => {
      let timer = null;
      const settle = () => { clearTimeout(timer); frame.removeEventListener('load', settle); resolve(); };
      timer = setTimeout(settle, 1000);
      frame.addEventListener('load', settle);
    }).then(() => { if (token === navigation) { expectedSrc = url; frame.src = url; } });
  }
  async function load() {
    show(loading); clearTimeout(loadTimer);
    try {
      const list = await request('/api/dashboards');
      if (!list.items.length) { current = null; expectedSrc = null; show(empty); return; }
      const requested = codeFromUrl(); const selected = list.items.find(item => item.dashboard_code === requested) || list.items[0];
      if (requested !== selected.dashboard_code) history.replaceState(null, '', `?code=${encodeURIComponent(selected.dashboard_code)}`);
      current = await request(`/api/dashboards/${encodeURIComponent(selected.dashboard_code)}`);
      document.getElementById('dashboardTitle').textContent = current.dashboard_name;
      document.getElementById('dashboardDescription').textContent = current.dashboard_description || 'DataEase 公共分享看板';
      fullscreen.hidden = !current.allow_fullscreen;
      frame.hidden = false; navigate(embedUrl(current.embed));
      loadTimer = setTimeout(() => { if (!loading.hidden) { document.getElementById('errorMessage').textContent='连接超时，请检查 DataEase 服务和公共链接'; show(error); } }, 15000);
    } catch (exception) { expectedSrc = null; document.getElementById('errorMessage').textContent = exception.message; show(error); }
  }
  frame.addEventListener('load', () => {
    if (!expectedSrc || expectedSrc === BLANK) return;   // 过渡页或空看板，不算看板加载完成
    clearTimeout(loadTimer); show(null);
  });
  frame.addEventListener('error', () => { clearTimeout(loadTimer); show(error); });
  document.getElementById('reloadDashboard').onclick = load;
  document.getElementById('retryDashboard').onclick = load;
  function exitFullscreen() { document.body.classList.remove('dashboard-fullscreen'); document.getElementById('exitFullscreen').hidden=true; if(document.fullscreenElement) document.exitFullscreen().catch(()=>{}); }
  fullscreen.onclick = async () => { if (!current?.allow_fullscreen) return; document.body.classList.add('dashboard-fullscreen'); document.getElementById('exitFullscreen').hidden=false; try{ await document.getElementById('dashboardCard').requestFullscreen(); }catch{} };
  document.getElementById('exitFullscreen').onclick = exitFullscreen;
  document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement) exitFullscreen(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') exitFullscreen(); });
  load();
})();

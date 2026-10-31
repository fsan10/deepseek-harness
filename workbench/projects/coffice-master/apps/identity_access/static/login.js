(function () {
  const form = document.getElementById('loginForm');
  const button = document.getElementById('loginButton');
  const error = document.getElementById('loginError');
  const status = document.getElementById('loginStatus');
  const usernameInput = document.getElementById('username');
  let submitting = false;
  let timer = null;

  const key = suffix => `mocc_login_${suffix}_${usernameInput.value.trim().toLowerCase() || 'invalid'}`;
  const readNumber = name => Number(sessionStorage.getItem(key(name)) || 0);
  const writeNumber = (name, value) => sessionStorage.setItem(key(name), String(value));
  const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

  function setMessage(node, message) {
    node.textContent = message;
    node.hidden = !message;
  }

  function clearCooldown() {
    clearInterval(timer);
    timer = null;
    sessionStorage.removeItem(key('cooldown'));
  }

  function renderCooldown(message) {
    clearInterval(timer);
    const tick = () => {
      const seconds = Math.max(0, Math.ceil((readNumber('cooldown') - Date.now()) / 1000));
      if (!seconds) {
        clearCooldown();
        button.disabled = false;
        button.textContent = '登录';
        return;
      }
      button.disabled = true;
      button.textContent = `${seconds}秒后重试`;
      setMessage(error, message || `操作过于频繁，请${seconds}秒后重试`);
    };
    tick();
    timer = setInterval(tick, 250);
  }

  function startCooldown(seconds, message) {
    writeNumber('cooldown', Date.now() + Math.max(1, seconds) * 1000);
    renderCooldown(message);
  }

  function restoreCooldown() {
    const until = readNumber('cooldown');
    if (until > Date.now()) renderCooldown('登录尝试过于频繁，请稍后重试');
    else if (!submitting) {
      clearCooldown();
      button.disabled = false;
      button.textContent = '登录';
    }
  }

  async function destinationAfterLogin() {
    try {
      const response = await fetch('/api/navigation', {credentials: 'same-origin'});
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || '导航加载失败');
      const items = (result.data?.groups || []).flatMap(group => group.items || []);
      const next = new URLSearchParams(location.search).get('next');
      if (next && next.startsWith('/') && !next.startsWith('//')) {
        const wanted = new URL(next, location.origin);
        const allowed = items.some(item => {
          const target = new URL(item.href, location.origin);
          return target.pathname.replace(/\/$/, '') === wanted.pathname.replace(/\/$/, '')
            && (!wanted.hash || target.hash === wanted.hash);
        });
        if (allowed) return wanted.pathname + wanted.search + wanted.hash;
      }
      return items[0]?.href || '/welcome/';
    } catch (exception) {
      return '/welcome/';
    }
  }

  usernameInput.addEventListener('input', () => {
    setMessage(error, '');
    restoreCooldown();
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (submitting || readNumber('cooldown') > Date.now()) {
      restoreCooldown();
      return;
    }
    submitting = true;
    button.disabled = true;
    button.textContent = '登录中…';
    setMessage(error, '');
    setMessage(status, '');
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username: form.username.value, password: form.password.value}),
      });
      const result = await response.json();
      if (!response.ok) {
        const failures = readNumber('failures') + 1;
        writeNumber('failures', failures);
        const serverRetry = Number(response.headers.get('Retry-After') || 0);
        const clientRetry = Math.min(30, 2 ** Math.min(failures, 5));
        startCooldown(serverRetry || clientRetry, result.message || '登录失败');
        throw new Error(result.message || '登录失败');
      }
      sessionStorage.removeItem(key('failures'));
      sessionStorage.removeItem('mocc_navigation_cache_v1');
      clearCooldown();
      setMessage(status, `登录成功，欢迎您，${result.data.user.display_name}`);
      button.disabled = true;
      button.textContent = '登录成功';
      const destination = await destinationAfterLogin();
      await wait(500);
      location.replace(destination);
      return;
    } catch (exception) {
      setMessage(error, exception.message);
    } finally {
      submitting = false;
      if (readNumber('cooldown') <= Date.now() && button.textContent !== '登录成功') {
        button.disabled = false;
        button.textContent = '登录';
      }
    }
  });

  restoreCooldown();
})();

/* Bridge-owned same-origin host. Upstream HTML, scripts and login stay unchanged. */
'use strict';
(async () => {
  const frame = document.getElementById('dashboard');
  const message = document.getElementById('message');
  const status = document.getElementById('status');
  const retry = document.getElementById('retry');
  const endpoint = location.origin + '/graphql';
  let authenticated = false;
  let generation = 0;
  let pending;
  function unavailable() {
    message.hidden = false;
    status.textContent = '暂时无法确认登录状态，请重试。已有登录信息未被清除。';
    retry.hidden = false;
  }
  function requestedRoute() {
    const route = location.hash.slice(1);
    return route.startsWith('/') && !route.startsWith('//') && route !== '/setup' ? route : '/';
  }
  function show(route) {
    const target = '/official/#' + route;
    message.hidden = true;
    frame.hidden = false;
    let current;
    try { current = frame.contentWindow.location.pathname + frame.contentWindow.location.hash; } catch (_) {}
    if (current !== target) frame.src = target;
    // The fragment is a client route; nginx never interprets it.
    history.replaceState(null, '', '/dashboard/#' + route);
  }
  async function checkSession() {
    const attempt = ++generation;
    if (pending) pending.abort();
    let token;
    try {
      token = localStorage.getItem('token');
      if (localStorage.getItem('endpointURL') !== endpoint) localStorage.setItem('endpointURL', endpoint);
    } catch (_) { unavailable(); return; }
    authenticated = false;
    frame.hidden = true;
    message.hidden = false;
    if (!token) { show('/setup'); return; }
    const controller = new AbortController();
    pending = controller;
    const timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch('/graphql', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
        body: JSON.stringify({query: '{ user { username } }'}), signal: controller.signal
      });
      const value = await response.json();
      if (attempt !== generation || localStorage.getItem('token') !== token) return;
      const denied = response.status === 401 || response.status === 403 ||
        (Array.isArray(value.errors) && value.errors.some(e =>
          typeof e.message === 'string' && e.message.toLowerCase() === 'access denied'));
      if (denied) {
        localStorage.removeItem('token');
        show('/setup');
      } else if (response.ok && !value.errors && value.data && value.data.user &&
                 typeof value.data.user.username === 'string' && value.data.user.username) {
        authenticated = true;
        show(requestedRoute());
      } else { unavailable(); }
    } catch (_) { if (attempt === generation) unavailable(); }
    finally { clearTimeout(timer); }
  }
  // Official tokenAtom writes in the child window: storage events reach this host.
  // Checking the real upstream identity bridges the upstream Setup remount after login.
  window.addEventListener('storage', event => {
    if (event.storageArea === localStorage && (event.key === 'token' || event.key === null)) checkSession();
  });
  frame.addEventListener('load', () => {
    let child;
    try { child = frame.contentWindow; if (child.location.origin !== location.origin) return; } catch (_) { return; }
    child.addEventListener('hashchange', () => {
      const route = child.location.hash.slice(1);
      if (authenticated && route === '/setup') show('/');
      else if (route.startsWith('/') && !route.startsWith('//')) history.replaceState(null, '', '/dashboard/#' + route);
    });
    if (authenticated && child.location.hash === '#/setup') show('/');
  });
  window.addEventListener('hashchange', () => show(authenticated ? requestedRoute() : '/setup'));
  retry.addEventListener('click', checkSession);
  await checkSession();
})();

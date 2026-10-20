/* Bridge-owned entry only. Official assets and authentication remain untouched. */
'use strict';
(async () => {
  const status = document.getElementById('status');
  const retry = document.getElementById('retry');
  retry.addEventListener('click', () => location.reload());
  function unavailable() {
    status.textContent = '暂时无法确认登录状态，请重试。已有登录信息未被清除。';
    retry.hidden = false;
  }
  let token;
  try { token = localStorage.getItem('token'); } catch (_) { unavailable(); return; }
  if (!token) { location.replace('/dashboard/#/setup'); return; }
  const endpoint = location.origin + '/graphql';
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5000);
  try {
    // Never send stored credentials to a saved external endpoint or URL parameter.
    const response = await fetch('/graphql', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'Authorization': token},
      body: JSON.stringify({query: '{ user { username } }'}), signal: controller.signal
    });
    const value = await response.json();
    const denied = response.status === 401 || response.status === 403 ||
      (Array.isArray(value.errors) && value.errors.some(e =>
        typeof e.message === 'string' && e.message.toLowerCase() === 'access denied'));
    if (denied) {
      localStorage.removeItem('token');
      location.replace('/dashboard/#/setup');
    } else if (response.ok && !value.errors && value.data && value.data.user && typeof value.data.user.username === 'string' && value.data.user.username) {
      localStorage.setItem('endpointURL', endpoint);
      // Ignore obsolete /#/setup bookmarks only after real upstream authentication.
      location.replace('/dashboard/#/');
    } else { unavailable(); }
  } catch (_) { unavailable(); }
  finally { clearTimeout(timer); }
})();

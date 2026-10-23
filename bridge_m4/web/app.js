/* Bridge Web Studio 2.0.0. No libraries, remote assets, stored credentials or auto-Apply. */
'use strict';
(() => {
    const $ = id => document.getElementById(id);
    const ICONS = {
        grid: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
        layers: '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/>',
        sliders: '<path d="M4 5h16M4 12h16M4 19h16"/><circle cx="8" cy="5" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="19" r="2"/>',
        shield: '<path d="m12 3 8 3v6c0 4-5 8-8 9-3-1-8-5-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
        terminal: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m7 9 3 3-3 3m6 0h4"/>',
        external: '<path d="M13 4h7v7m0-7L10 14m-1-9H6a3 3 0 0 0-3 3v10a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3v-3"/>',
        refresh: '<path d="M20 10a8 8 0 0 0-14-5L3 8m0-5v5h5M4 14a8 8 0 0 0 14 5l3-3m0 5v-5h-5"/>',
        sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
        moon: '<path d="M21 13.5A9 9 0 0 1 10.5 3 9 9 0 1 0 21 13.5Z"/>',
        server: '<rect x="3" y="3" width="18" height="8" rx="2"/><rect x="3" y="13" width="18" height="8" rx="2"/><path d="M7 7h.01M7 17h.01m4-10h6m-6 10h6"/>',
        arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
        document: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6Z"/><path d="M14 3v6h6M8 13h8m-8 4h5"/>',
        clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
        plus: '<path d="M12 5v14M5 12h14"/>',
        search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
        info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
        bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9m-9 13h6"/>',
        alert: '<path d="m10 4-8 14a2 2 0 0 0 2 3h16a2 2 0 0 0 2-3L14 4a2.3 2.3 0 0 0-4 0Z"/><path d="M12 9v4m0 4h.01"/>',
        lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 4v3"/>',
        eye: '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
        check: '<path d="m5 12 4 4L19 6"/>',
        link: '<path d="m10 13 4-4M8 15l-2 2a4 4 0 0 1-5-5l5-5a4 4 0 0 1 5 0m2 2 2-2a4 4 0 0 1 5 5l-5 5a4 4 0 0 1-5 0"/>',
    };
    function icon(name) { const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true'); s.innerHTML = ICONS[name] || ICONS.info; return s; }
    function paintIcons(root = document) { root.querySelectorAll('[data-icon]').forEach(e => e.replaceChildren(icon(e.dataset.icon))); }
    function el(tag, text, className) { const e = document.createElement(tag); if (text !== undefined && text !== null)
        e.textContent = String(text); if (className)
        e.className = className; return e; }
    function badge(text, tone = 'neutral') { return el('span', text, 'badge ' + tone); }
    function empty(target, title, description, name = 'info') { const box = el('div', null, 'empty-state'); const i = el('span'); i.dataset.icon = name; i.append(icon(name)); box.append(i, el('strong', title), el('p', description)); target.replaceChildren(box); }
    function fmtTime(n) { return Number.isInteger(n) ? new Date(n * 1000).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '暂无时间记录'; }
    function short(s) { return typeof s === 'string' && s.length > 22 ? s.slice(0, 12) + '…' + s.slice(-8) : s || '—'; }
    const HASH = /^[a-f0-9]{64}$/;
    const SERVICES = ['independent-bridge.service', 'daed-api.service', 'bridge-graphql.service', 'bridge-attestor.service', 'daed-web.service'];
    const EPHEMERAL_ACTIONS = new Set(['preview', 'validate']);
    const WRITE_MARKER = 'bridge-ui-write-v2';
    const WRITE_LOCK = 'bridge-ui-write-v2';
    const S = {
        auth: false, csrf: '', csrfVersion: 0, status: null, health: null, meta: null, ext: null,
        errors: {}, readAt: {}, readMono: {}, busy: false, readBusy: false, uncertain: false,
        conflict: false, page: 'overview', section: 'global', profile: null, drafts: new Map(),
        draftBase: new Map(), conflictFields: new Set(), suspended: null,
        preview: null, validated: false, applied: false, previewBase: null,
        mutationVersion: 0, epoch: 0, reads: {}, serverClock: null, operation: null,
        marker: null, storageUnavailable: false, saveReport: null, reviewChecked: null,
        previewInvalidReason: '', focusDeferred: false
    };
    const PAGE_TITLES = { overview: '总览', config: '配置应用', extensions: 'DAE 扩展', health: '健康与恢复', advanced: '高级维护' };
    const ACTION_NAMES = { preview: '生成配置预览', validate: '校验配置', apply: '应用配置', extensions: '保存扩展', 'bind-extensions': '同步新建配置', 'management-recovery/pause': '暂停自动恢复', 'management-recovery/resume': '恢复自动恢复', start: '启动 DAE', stop: '停止 DAE', reload: '重载 DAE', recover: '恢复事务' };
    const ERROR_TEXT = {
        UNAUTHORIZED: '登录已过期，请重新输入管理密钥。', AUTH_FAILED: '登录未通过，请核对 Bridge 管理密钥。', AUTH_RATE_LIMIT: '登录尝试过于频繁，请稍后再试。', AUTH_BUSY: '认证服务暂时忙，请稍后重试。', CSRF_REJECTED: '安全凭据已变化，本次操作被拒绝。页面会在下一次明确提交前重新核对会话。', REQUEST_REJECTED: '请求被安全检查拒绝。请确认访问的是部署时设置的 HTTPS 地址。',
        SOURCE_CHANGED: '官方配置已变化，请重新生成预览。', EXTENSION_CHANGED: '扩展记录已变化，请核对最新值并重新预览。', EXTENSION_CAS_CONFLICT: '其他操作已更新扩展记录；已停止保存，请核对草稿与服务器当前值。', PREVIEW_CONFLICT: '这份预览已失效，请重新生成。', VALIDATION_REQUIRED: '请先完成当前候选的校验。', VALIDATE_FAILED: '官方 DAE 静态校验未通过。请核对配置，不要直接应用。', OLD_SOURCE: '来源证据与候选不一致，请重新预览。', SOURCE_EXPIRED: '来源签发凭据已过期，请检查配置签发服务。', STATUS_REJECTED: '当前运行状态不允许应用配置，请查看高级维护。', UNMANAGED_SERVICE_ACTIVE: '存在未受管理的运行服务，已拒绝操作。', MANUAL_INTERVENTION_REQUIRED: '当前事务需要管理员检查，不能自动继续。', UNIT_IDENTITY_MISMATCH: '服务身份不匹配，已拒绝操作。', MANAGEMENT_HEALTH_STATE: '无法读取自动恢复记录，请查看管理服务日志。', MANAGEMENT_RECOVERY_BLOCKED: '维护、回滚或安装身份检查未通过，暂不能恢复自动管理。', MANAGEMENT_RECOVERY_REQUEST: '自动恢复控制请求无效。', MANAGEMENT_HEALTH_UNAVAILABLE: '当前后端没有提供自动恢复状态接口。',
        REQUEST_FAILED: '请求未完成。请核对后端记录，页面不会自动重试写入。', BUSY: '服务正在处理其他事务，请稍后刷新状态。', NETWORK_ERROR: '暂时无法连接 Bridge。请检查网络和 HTTPS 证书。', READ_TIMEOUT: '读取超时。相关内容暂不作为最新状态，请稍后刷新。', WRITE_UNCERTAIN: '请求结果未确认，服务器可能已执行操作。请先核对结果，不要重复提交。', INVALID_RESPONSE: '服务器返回了无法识别的响应，未把它当作成功。', INVALID_HEALTH_RESPONSE: '管理巡检返回的组件记录不完整或自相矛盾，暂不显示全部正常。', METADATA_MISSING: '编辑接口不匹配或不可用，请确认本版只读展示模块已部署。暂不允许盲目编辑。', EDITOR_INCOHERENT: '配置列表、字段或代际不一致，编辑已锁定；请刷新后核对。', EMPTY_REFERENCED_GROUP: '被路由使用的分组没有可用节点，请先到官方 daed 配置。', NO_CHANGES: '没有需要保存的修改。', UNKNOWN_RESULT: '服务器没有返回明确完成结果，需核对实际状态，不要重复操作。', CONFIRMED_STATE_CHANGED: '确认期间服务器状态已经改变，本次没有提交。请核对新状态后重新确认。', OTHER_WINDOW_BUSY: '另一个窗口正在操作或有未确认的写入。本页只读取状态，暂不重复提交。', CONTROL_ROLLED_BACK: '本次操作未成功，控制服务已恢复原状态。没有自动重试。', PROFILE_GONE: '当前对象已从官方配置中移除。草稿保留在本页，不会写入其他对象。', CLIENT_STORAGE_UNAVAILABLE: '浏览器无法保存写入防重标记。本页暂时只读，请允许此站点的本地存储后重新打开。',
        INCOMPLETE_SAVE: '只保存了部分字段；后续提交已停止。请核对保存明细与剩余草稿。'
    };
    // Only errors known to reject before a business mutation can clear a pending
    // marker. Generic 409/5xx errors may occur AFTER a write: they stay uncertain.
    const DEFINITE_REJECTIONS = new Set(['UNAUTHORIZED','AUTH_FAILED','AUTH_RATE_LIMIT','AUTH_BUSY','CSRF_REJECTED','REQUEST_REJECTED','SOURCE_CHANGED','EXTENSION_CHANGED','EXTENSION_CAS_CONFLICT','PREVIEW_CONFLICT','VALIDATION_REQUIRED','VALIDATE_FAILED','OLD_SOURCE','SOURCE_EXPIRED','STATUS_REJECTED','UNMANAGED_SERVICE_ACTIVE','UNIT_IDENTITY_MISMATCH','MANAGEMENT_RECOVERY_BLOCKED','MANAGEMENT_RECOVERY_REQUEST','MANAGEMENT_HEALTH_UNAVAILABLE','EMPTY_REFERENCED_GROUP']);
    class ApiError extends Error {
        constructor(code, uncertain = false) { super(ERROR_TEXT[code] || ERROR_TEXT.REQUEST_FAILED); this.code = code; this.uncertain = uncertain || code === 'UNKNOWN_RESULT'; }
    }
    const clone = value => value === undefined ? undefined : JSON.parse(JSON.stringify(value));
    const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
    function toast(text, error = false) {
        $('toast').textContent = text; $('toast').classList.toggle('error', error); $('toast').hidden = false;
        clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').hidden = true, error ? 12000 : 5500);
    }
    function age(key) { return S.readMono[key] === undefined ? Infinity : Math.max(0, performance.now() - S.readMono[key], Date.now() - (S.readAt[key] || 0)); }
    function stamp(key) { S.readAt[key] = Date.now(); S.readMono[key] = performance.now(); delete S.errors[key]; }
    function serverNow() { return S.serverClock ? S.serverClock.time + Math.max(0, performance.now() - S.serverClock.mono) / 1000 : Date.now() / 1000; }
    function readMarker() {
        let raw;
        try { raw=localStorage.getItem(WRITE_MARKER); }
        catch (_) { S.storageUnavailable=true; return S.marker||null; }
        if(!raw)return null;
        const invalid=()=>({v:2,id:'invalid',action:'apply',phase:'uncertain',at:0,invalid:true});
        try {
            const m=JSON.parse(raw);
            if(!object(m)||m.v!==2||typeof m.id!=='string'||!Number.isFinite(m.at)||!['pending','uncertain'].includes(m.phase)||!Object.hasOwn(ACTION_NAMES,m.action))return invalid();
            // Legacy preview/validate receipts never authorize a dataplane write.
            // Ignore only these well-formed markers; malformed/real writes stay locked.
            if (EPHEMERAL_ACTIONS.has(m.action)) return null;
            return m;
        }catch(_){return invalid();}
    }
    function writeMarker(marker) {
        if (S.storageUnavailable) throw new ApiError('CLIENT_STORAGE_UNAVAILABLE');
        try { localStorage.setItem(WRITE_MARKER, JSON.stringify(marker)); S.marker = marker; }
        catch (_) { S.storageUnavailable = true; throw new ApiError('CLIENT_STORAGE_UNAVAILABLE'); }
    }
    function clearMarker(id) {
        const m = readMarker();
        if (m && m.id !== id) return false;
        try { localStorage.removeItem(WRITE_MARKER); } catch (_) { return false; }
        S.marker = null; S.uncertain = false; S.reviewChecked = null; return true;
    }
    function markSent(action) {
        if (!S.operation || !ACTION_NAMES[action]) throw new ApiError('REQUEST_REJECTED');
        if (EPHEMERAL_ACTIONS.has(action)) return;
        const m = readMarker();
        if (m && m.id !== S.operation.id) throw new ApiError('OTHER_WINDOW_BUSY');
        const marker = { v: 2, id: S.operation.id, at: S.operation.at, action, phase: 'pending' };
        writeMarker(marker); S.operation.sent = true;
    }
    function markUncertain() {
        S.uncertain = true; S.reviewChecked = null;
        const m = readMarker() || S.marker;
        if (m && S.operation?.id === m.id) {
            try { writeMarker({ ...m, phase: 'uncertain' }); } catch (_) { /* Keep the in-memory guard. */ }
        }
    }
    function resetLogin(text = '', preserve = false) {
        if (preserve && dirty()) S.suspended = { section: S.section, profile: S.profile, drafts: new Map(S.drafts), bases: new Map(S.draftBase) };
        if (!preserve) { S.suspended = null; S.saveReport=null; }
        if ($('confirm-dialog').open) $('confirm-dialog').close('cancel');
        S.auth = false; S.csrf = ''; S.csrfVersion++; S.epoch++; S.reads = {};
        S.status = S.health = S.meta = S.ext = null; S.preview = null; S.validated = false; S.applied = false;
        S.drafts.clear(); S.draftBase.clear(); S.conflictFields.clear(); S.conflict = false;
        S.errors = {}; S.readAt = {}; S.readMono = {}; S.serverClock = null; S.readBusy=false;
        $('app').hidden = true; $('login-screen').hidden = false; $('boot').hidden = true;
        $('login-token').value = ''; $('login-token').type = 'password';
        $('toggle-secret').setAttribute('aria-pressed','false'); $('toggle-secret').setAttribute('aria-label','显示管理密钥');
        $('login-error').textContent = text + (S.suspended ? ' 未保存草稿仅保留在当前页面；重新登录后会核对服务器版本，关闭页面会丢失。' : '');
        $('login-error').hidden = !$('login-error').textContent;
        ['fields','components','recovery-history','technical-values','identity-summary','preview-result','profile-list','recent-recovery','draft-review','save-report','uncertain-readback'].forEach(id => $(id)?.replaceChildren());
        $('hero-title').textContent = '等待登录'; $('toast').hidden = true;
    }
    async function api(path, value) {
        const mutation = value !== undefined, business = mutation && path !== 'login' && path !== 'logout';
        // Session CSRF is consumed even if the protected mutation later fails.
        // Obtain the CURRENT CSRF before each deliberate POST, never retry a POST.
        if (mutation && path !== 'login') await api('session');
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), mutation ? 180000 : 25000);
        const epoch = S.epoch, version = S.mutationVersion, csrfVersion = S.csrfVersion;
        let sent = false;
        try {
            if (business) markSent(path);
            sent = mutation;
            const r = await fetch('/api/' + path, {
                method: mutation ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store',
                headers: mutation ? { 'Content-Type':'application/json', 'X-CSRF-Token':S.csrf } : {},
                body: mutation ? JSON.stringify(value) : undefined, signal: controller.signal
            });
            let data;
            try { data = await r.json(); }
            catch (_) { throw new ApiError(mutation ? 'WRITE_UNCERTAIN' : 'INVALID_RESPONSE', mutation); }
            if (!object(data)) throw new ApiError(mutation ? 'WRITE_UNCERTAIN' : 'INVALID_RESPONSE', mutation);
            if (epoch !== S.epoch) throw new ApiError(mutation ? 'WRITE_UNCERTAIN' : 'UNAUTHORIZED', mutation);
            // A late GET response must not resurrect a consumed CSRF after POST.
            if (typeof data.csrf === 'string' && version === S.mutationVersion && (mutation || csrfVersion === S.csrfVersion)) {
                S.csrf = data.csrf; S.csrfVersion++;
            }
            const date = Date.parse(r.headers.get('Date') || '');
            if (Number.isFinite(date)) S.serverClock = { time: date/1000, mono: performance.now() };
            if (!r.ok) {
                const code = typeof data.error === 'string' ? data.error : 'REQUEST_FAILED';
                if (r.status === 401 && ['UNAUTHORIZED','AUTH_FAILED'].includes(code) && S.auth)
                    resetLogin(ERROR_TEXT.UNAUTHORIZED, true);
                throw new ApiError(code, business && (r.status >= 500 || !DEFINITE_REJECTIONS.has(code)));
            }
            return data.data === undefined ? data : data.data;
        } catch (e) {
            if (e instanceof ApiError) throw e;
            throw new ApiError(sent ? 'WRITE_UNCERTAIN' : e.name === 'AbortError' ? 'READ_TIMEOUT' : 'NETWORK_ERROR', sent);
        } finally { clearTimeout(timer); }
    }
    function dirty() { return S.drafts.size > 0; }
    function invalidatePreview(reason = '') { S.preview = null; S.validated = false; S.applied = false; S.previewBase = null; S.previewInvalidReason = reason; renderWorkflow(); }
    function statusFresh() { return !!S.status && !S.status.error && !S.errors.status && age('status') <= 90000 && navigator.onLine !== false; }
    function identityOK() { return statusFresh() && S.status.state === 'running' && S.status.identityVerified === true && HASH.test(S.status.activeBundle || '') && HASH.test(S.status.configSha256 || '') && HASH.test(S.status.sourceFingerprint || ''); }
    function editorCoherent() {
        return !!S.meta && !!S.ext && !S.errors.meta && !S.errors.ext && S.meta.schemaVersion === 2
            && S.meta.generation === S.ext.generation && HASH.test(S.ext.generation || '') && S.meta.collectionStable === true
            && ['global','dns','group'].every(section => Object.values(S.ext.records[section]||{}).every(fields =>
                Object.keys(fields).length === Object.keys(S.meta.specs[section]||{}).length && Object.keys(fields).every(k=>Object.hasOwn(S.meta.specs[section],k))));
    }
    function healthShape(h) {
        if (!object(h) || !Array.isArray(h.components) || !Array.isArray(h.history) || typeof h.paused !== 'boolean' || typeof h.resumePending !== 'boolean') return false;
        const names = h.components.map(c => c?.service);
        if (names.some(n => typeof n !== 'string') || new Set(names).size !== names.length || SERVICES.some(n => !names.includes(n))) return false;
        if (!h.components.every(c => typeof c.healthy === 'boolean') || !['HEALTHY','UNKNOWN','ATTENTION_REQUIRED','PAUSED'].includes(h.overall)) return false;
        if (h.overall === 'HEALTHY' && (h.paused || !h.components.every(c => c.healthy))) return false;
        return h.history.every(e => object(e) && typeof e.event === 'string' && Number.isFinite(e.at));
    }
    function metadataShape(m) {
        if (!object(m) || m.schemaVersion !== 2 || !HASH.test(m.generation || '') || !object(m.profiles) || !object(m.specs) || !object(m.records) || typeof m.collectionStable !== 'boolean' || !Number.isFinite(m.observedAt)) return false;
        for (const section of ['global','dns','group']) {
            const rows=m.profiles[section], specs=m.specs[section], records=m.records[section];
            if (!Array.isArray(rows) || !object(specs) || !object(records)) return false;
            if (new Set(rows.map(p => p?.id)).size !== rows.length) return false;
            for (const p of rows) {
                if (!object(p) || typeof p.id!=='string' || !/^[0-9]+$/.test(p.id) || typeof p.name!=='string' || typeof p.bound!=='boolean' || typeof p.selected!=='boolean') return false;
                if (p.bound !== Object.hasOwn(records,p.id)) return false;
            }
            for (const [id, fields] of Object.entries(records)) {
                if (!rows.some(p=>p.id===id) || !object(fields)) return false;
                for (const [field,state] of Object.entries(fields)) {
                    if (!object(state) || typeof state.present!=='boolean' || (state.present ? !Object.hasOwn(state,'value') : Object.hasOwn(state,'value'))) return false;
                    // Values are validated by the existing Store. Unknown fields
                    // stay visible as read-only; this layer never coerces them.
                    if (Object.hasOwn(specs,field) && typeof specs[field]?.type!=='string') return false;
                }
            }
        }
        return true;
    }
    function showGlobal() {
        const messages=[];
        if (navigator.onLine === false) messages.push('浏览器当前离线。显示的内容仅供参考，不执行写入。');
        if (S.errors.status) messages.push('运行状态读取失败：'+S.errors.status);
        if (S.errors.health) messages.push('管理巡检读取失败：'+S.errors.health);
        if (S.storageUnavailable) messages.push(ERROR_TEXT.CLIENT_STORAGE_UNAVAILABLE);
        $('global-warning').hidden=!messages.length; $('global-warning').textContent=messages.join(' ');
        renderUncertain();
        if ($('draft-indicator')) { $('draft-indicator').hidden=!dirty(); $('draft-indicator').textContent='扩展草稿 · '+S.drafts.size+' 项'; }
    }
    function setBusy(value) {
        S.busy=value; $('app').classList.toggle('busy',value); $('app').setAttribute('aria-busy',String(value));
        $('refresh').disabled=value; $('logout').disabled=value; $('login-submit').disabled=value;
        const blocked=value || S.uncertain || S.storageUnavailable || navigator.onLine===false;
        document.querySelectorAll('[data-action]').forEach(e=>e.disabled=!actionAllowed(e.dataset.action));
        $('bind').disabled=blocked || dirty() || !editorCoherent();
        $('recovery-control').disabled=blocked || !S.health || !!S.errors.health || !healthFresh() || S.health.resumePending;
        $('save-extensions').disabled=blocked || S.conflict || !dirty() || !editorCoherent();
        $('discard').disabled=value;
        document.querySelectorAll('#fields input,#fields textarea,#fields select').forEach(e=>{e.disabled=blocked || e.dataset.disabled==='true';});
        $('resolve-conflict').disabled=value || S.uncertain;
        renderWorkflow(); updateSavebar(); renderUncertain();
    }
    async function mutate(work, action='extensions') {
        if (S.busy) return;
        const prior=readMarker();
        if (S.uncertain || prior) { S.marker=prior||S.marker; S.uncertain=true; showGlobal(); toast(ERROR_TEXT.OTHER_WINDOW_BUSY,true); return; }
        if (S.storageUnavailable || navigator.onLine===false) { toast(S.storageUnavailable?ERROR_TEXT.CLIENT_STORAGE_UNAVAILABLE:ERROR_TEXT.NETWORK_ERROR,true); return; }
        setBusy(true); S.mutationVersion++; S.operation={id:crypto.randomUUID?.()||String(Date.now())+'-'+Math.random(),at:Date.now(),action,sent:false};
        const execute=async lock=>{
            if (lock===null) { toast(ERROR_TEXT.OTHER_WINDOW_BUSY,true); return; }
            const existing=readMarker();
            if (existing) { S.marker=existing;S.uncertain=true;toast(ERROR_TEXT.OTHER_WINDOW_BUSY,true);return; }
            try { await work(); }
            catch(e) {
                if(e.uncertain && !EPHEMERAL_ACTIONS.has(action)) {
                    markUncertain(); invalidatePreview('上次写入结果未确认，请先核对。');
                } else if(e.uncertain) {
                    invalidatePreview('预览或静态校验未确认，当前运行配置未改变；请重新生成预览。');
                    e.message='预览或静态校验未确认，当前运行配置未改变；请重新生成预览。';
                }
                if(['EXTENSION_CAS_CONFLICT','EXTENSION_CHANGED'].includes(e.code)) { S.conflict=true; renderExtensions(); }
                if(['SOURCE_CHANGED','PREVIEW_CONFLICT','OLD_SOURCE'].includes(e.code)) invalidatePreview(e.message);
                toast(e.message||ERROR_TEXT.REQUEST_FAILED,true);
            } finally {
                if(!S.uncertain && S.operation?.sent) clearMarker(S.operation.id);
            }
        };
        try {
            if(navigator.locks?.request) await navigator.locks.request(WRITE_LOCK,{mode:'exclusive',ifAvailable:true},execute);
            else await execute(undefined); // Server CAS/locks remain authoritative.
        } catch(e) { if(S.operation?.sent) markUncertain(); toast(e.message||ERROR_TEXT.REQUEST_FAILED,true); }
        finally { S.operation=null; setBusy(false); showGlobal(); }
    }
    function acceptEditor(result) {
        if(!metadataShape(result)) throw new ApiError('METADATA_MISSING');
        if(dirty()) reconcileDrafts(result.records, result.specs);
        S.meta=result; S.ext={generation:result.generation,records:clone(result.records)};
        stamp('meta'); stamp('ext');
        S.serverClock={time:result.observedAt,mono:performance.now()};
        if(S.preview && (S.preview.extensionGeneration!==result.generation || S.preview.sourceFingerprint!==result.sourceFingerprint)) invalidatePreview('来源或扩展已经变化，旧预览已失效。');
    }
    async function readOne(key,path) {
        const epoch=S.epoch, version=S.mutationVersion, ticket=(S.reads[key]||0)+1; S.reads[key]=ticket;
        try {
            const result=await api(path);
            if(!S.auth||epoch!==S.epoch||version!==S.mutationVersion||ticket!==S.reads[key]) return;
            if(!object(result)) throw new ApiError('INVALID_RESPONSE');
            if(key==='status') {
                if(result.error) throw new ApiError(result.error);
                if(typeof result.state!=='string') throw new ApiError('INVALID_RESPONSE');
                if(S.preview && result.activeBundle!==S.previewBase) invalidatePreview('运行配置包已变化，请重新预览。');
                S.status=result;
            } else if(key==='health') {
                if(!healthShape(result)) throw new ApiError('INVALID_HEALTH_RESPONSE'); S.health=result;
            } else if(key==='meta') { acceptEditor(result); }
            stamp(key);
        } catch(e) {
            if(epoch!==S.epoch||!S.auth||version!==S.mutationVersion||ticket!==S.reads[key]) return;
            S.errors[key]=e.message;
            if(key==='meta') S.errors.ext=e.message;
        }
    }
    async function refresh(light=false) {
        if(!S.auth||S.readBusy||S.busy) return;
        S.readBusy=true; const refreshEpoch=S.epoch; $('refresh').classList.add('loading-spinner');
        try {
            await Promise.allSettled([readOne('status','status'),readOne('health','management-health')]);
            if(!light) await readOne('meta','editor-metadata');
            renderAll();
        } finally { if(refreshEpoch===S.epoch){S.readBusy=false; $('refresh').classList.remove('loading-spinner');} }
    }
    function verifiedModified() {
        if(!identityOK()||!editorCoherent()||S.meta.comparisonVerified!==true||age('meta')>90000) return null;
        const r=S.meta.runningIdentity;
        if(!r || ['activeBundle','configSha256','sourceFingerprint','InvocationID'].some(k=>S.status[k]!==r[k])) return null;
        return typeof S.meta.modified==='boolean'?S.meta.modified:null;
    }
    function healthFresh() {
        if(!S.health||S.errors.health||S.health.lastCheckFresh!==true||!Number.isInteger(S.health.lastCheckAt)||age('health')>90000||navigator.onLine===false) return false;
        const delta=serverNow()-S.health.lastCheckAt;
        return delta>=-2 && delta<=180;
    }
    function healthLabel() {
        if(!S.health||S.errors.health||!healthFresh()) return ['状态待核对','warning'];
        return {HEALTHY:['全部正常','good'],PAUSED:['恢复已暂停','warning'],ATTENTION_REQUIRED:['需要处理','bad'],UNKNOWN:['状态待核对','warning']}[S.health.overall]||['状态待核对','warning'];
    }
    function recoveryEventLabel(e) { return {SERVICE_HEALTH_FAILED:'检查未通过',SERVICE_HEALTH_RESTORED:'服务已恢复',RECOVERY_SUCCEEDED:'自动恢复成功',RECOVERY_FAILED:'自动恢复失败',RECOVERY_RATE_LIMITED:'已达到恢复次数上限'}[e.event] || '管理事件'; }
    function eventTone(e) { return ['RECOVERY_SUCCEEDED','SERVICE_HEALTH_RESTORED'].includes(e.event)?'good':e.event==='RECOVERY_FAILED'?'bad':'warning'; }

    function renderOverview() {
        const st = S.status;
        const up = statusFresh() && st.state === 'running';
        const id = identityOK();
        $('hero-title').textContent = up ? '转发引擎正在运行' : statusFresh() ? ({ stopped: '转发引擎已停止', 'rollback-needed': '运行事务需要处理' }[st.state] || '运行状态待核对') : '暂时无法确认运行状态';
        $('hero-description').textContent = up ? (id ? '运行配置身份已核验。管理设置与实际转发保持独立，查看页面不会改变当前网络。' : '已读取到运行进程，但配置身份尚未通过核验，请先检查，不要重复应用。') : '先核对服务与运行身份。自动恢复不会替你启动 DAE 或重新应用配置。';
        $('hero-badge').textContent = up && id ? '运行身份已核验' : up ? '身份待核验' : '待检查';
        const [hl] = healthLabel();
        $('metric-health').textContent = hl;
        $('metric-health-note').textContent = S.health && !S.errors.health && healthFresh() ? S.health.components.filter(c => c.healthy).length + ' / ' + S.health.components.length + ' 项管理组件正常' : '暂不沿用上次健康结论';
        const mod = verifiedModified();
        $('metric-config').textContent = mod === false ? '已应用' : mod === true ? '有待应用变更' : '尚未核对';
        $('metric-config-note').textContent = mod === false ? '来源、扩展与运行指纹一致' : mod === true ? '保存的变更尚未进入运行配置' : (S.meta && S.readAt.meta && Date.now() - S.readAt.meta > 90000 ? '来源对照已过期，请刷新核对' : '不把未核对显示为已生效');
        $('nav-pending').hidden = mod !== true;
        $('metric-recovery').textContent = S.health && !S.errors.health ? (S.health.paused ? (S.health.resumePending ? '恢复待确认' : '已暂停') : healthFresh() ? '正在巡检' : '记录已过期') : '尚未读取';
        $('metric-recovery-note').textContent = S.health && S.health.lastCheckAt ? '最近巡检 ' + fmtTime(S.health.lastCheckAt) : '仅恢复受支持的管理服务';
        const r = $('recent-recovery');
        const event = S.health && !S.errors.health ? S.health.lastRecovery : null;
        if (event) {
            r.className = '';
            const row = el('div', null, 'recent-result'), sym = el('span', null, 'result-icon');
            sym.append(icon(event.recovered === true ? 'check' : 'alert'));
            const copy = el('div');
            copy.append(el('strong', event.title || '管理组件'), el('p', recoveryEventLabel(event)), el('p', fmtTime(event.at)));
            row.append(sym, copy);
            r.replaceChildren(row);
        }
        else {
            r.className = 'empty-state compact';
            r.replaceChildren();
            const x = el('span');
            x.dataset.icon = 'clock';
            x.append(icon('clock'));
            r.append(x, el('strong', S.errors.health ? '恢复记录暂不可用' : '暂无保留的恢复记录'), el('p', S.errors.health ? '请刷新后再核对。' : '这里只展示后端当前保留的记录，不代表历史上从未恢复。'));
        }
    }
    function canApply() { const s = S.status; return statusFresh() && !S.uncertain && !S.storageUnavailable && !s.error && s.state !== 'rollback-needed' && (s.state === 'stopped' || s.state === 'running' && s.identityVerified === true); }
    function renderWorkflow() {
        const p = S.preview;
        const blocked = S.busy || S.uncertain || S.storageUnavailable || navigator.onLine === false;
        const mod = verifiedModified();
        const summary = $('config-summary');
        summary.className = 'notice ' + (mod === true ? 'warning' : 'neutral');
        summary.textContent = mod === true ? '检测到来源或扩展有待应用变更。请检查预览，不要直接重复应用。' : mod === false ? '当前来源、扩展与运行指纹一致。生成新预览前无需切换当前服务。' : '尚未取得可验证的来源对照。生成预览和运行身份核验是两项独立检查。';
        $('preview').disabled = blocked || dirty() || !S.auth;
        $('preview').textContent = p ? '重新生成预览' : '生成预览';
        $('validate').disabled = blocked || !p || S.applied;
        $('apply').disabled = blocked || !p || !S.validated || S.applied || !canApply();
        $('workflow-hint').textContent = S.uncertain ? '上次请求结果未确认，先使用上方结果核对入口。' : dirty() ? '请先保存或放弃扩展草稿。' : S.applied ? '本次应用已核验。新的修改需要重新预览。' : S.validated ? '静态校验已通过。应用前仍会核对来源、凭据及运行状态。' : p ? '预览已生成，尚未影响运行。下一步：校验配置。' : (S.previewInvalidReason || '请先生成预览，再进行校验。');
        for (let i = 1; i <= 3; i++)
            $('step-' + i).className = 'step ' + (S.applied ? 'done' : i === (S.validated ? 3 : p ? 2 : 1) ? 'current' : i < (S.validated ? 3 : p ? 2 : 1) ? 'done' : '');
        if (!p) {
            empty($('preview-result'), '先看看，准备改变什么。', '生成预览会保存候选文件，但不会切换当前运行配置。', 'document');
            return;
        }
        const root = $('preview-result');
        root.className = '';
        root.replaceChildren();
        const metrics = el('div', null, 'preview-summary');
        const diffAvailable = p.differences?.available !== false;
        const count = diffAvailable ? (p.differences?.daed?.changeCount || 0) + (p.differences?.daeExtensions?.changeCount || 0) : '未比较';
        for (const [val, label] of [[p.nodeCount, '节点'], [p.groupCount, '分组'], [count, '处差异']]) {
            const d = el('div');
            d.append(el('strong', val ?? '—'), el('small', label));
            metrics.append(d);
        }
        root.append(metrics);
        const baseline = { "last-applied": '上次应用的配置', "previous-preview": '上次预览（不是运行配置）', empty: '空基线（不是运行配置）' }[p.differences?.baseline] || '后端提供的基线';
        root.append(el('p', diffAvailable ? '比较基线：' + baseline :
            '旧比较记录不可用，本次不显示差异数量；新预览有效，尚未改变运行配置。', 'fine-print'));
        for (const [key, title] of [['daed', '官方配置'], ['daeExtensions', 'DAE 扩展']]) {
            const diff = p.differences?.[key];
            if (!diff)
                continue;
            const wrap = el('section', null, 'diff-group');
            wrap.append(el('h3', title + ' · ' + (diff.changeCount || 0) + ' 处变化'));
            if (!diff.changeCount)
                wrap.append(el('p', '与本次比较基线相同。', 'fine-print'));
            for (const item of (diff.changes || []).slice(0, 8)) {
                const row = el('div', null, 'diff-row');
                row.append(badge({ added: '新增', removed: '移除', changed: '修改' }[item.kind] || '变更', item.kind === 'removed' ? 'warning' : 'neutral'), el('code', item.fieldPath));
                wrap.append(row);
            }
            if ((diff.changes || []).length > 8) {
                const more = el('details', null, 'diff-more');
                more.append(el('summary', '展开其余 ' + (diff.changes.length - 8) + ' 项差异'));
                for (const item of diff.changes.slice(8)) {
                    const row = el('div', null, 'diff-row');
                    row.append(el('code', item.fieldPath));
                    more.append(row);
                }
                wrap.append(more);
            }
            root.append(wrap);
        }
        if (Array.isArray(p.compatibilityDefaults) && p.compatibilityDefaults.length) {
            const d = el('details', null, 'diff-more');
            d.append(el('summary', '兼容规则处理 ' + p.compatibilityDefaults.length + ' 项（查看说明）'));
            for (const c of p.compatibilityDefaults)
                d.append(el('p', (c.path || '字段') + ' · ' + (c.reason || '按当前来源合同处理'), 'fine-print'));
            root.append(d);
        }
        const d = el('details', null, 'technical-details');
        d.append(el('summary', '本次候选的校验信息'));
        const kv = el('dl', null, 'key-values technical');
        for (const [label, val] of [['预览ID', p.previewId], ['候选SHA-256', p.candidateSha256], ['扩展代际', p.extensionGeneration]])
            kv.append(el('dt', label), el('dd', val || '—'));
        d.append(kv);
        root.append(d);
    }
    const FIELD_INFO = {
        disable_thp: { label: '禁用透明大页（THP）', description: '控制独立 DAE 的透明大页禁用选项。这里只保存你的选择，不自动调整系统设置。', trueText: '禁用', falseText: '不禁用' },
        auto_sniff_punt: { label: '自动补充域名嗅探', description: '控制目标核心的自动嗅探选项。未设置时按当前兼容规则生成，不能简单等同于关闭。' },
        bpf_conn_state_map_size: { label: '连接状态表容量', description: '设置连接状态表的容量。更大的数值可能占用更多内存，不会因修改输入框立即调整。', unit: '条' },
        optimistic_stale_reply_ttl: { label: '乐观缓存应答 TTL', description: '设置乐观缓存应答的 TTL。此项与 DNS 缓存容量不同。', unit: '秒' },
        check_interval: { label: '健康检查间隔', description: '为此分组单独设置检查间隔，保留当前合同的时长格式。', hint: '填写带单位的时长，例如 30s、1m。' },
        check_tolerance: { label: '节点选择容差', description: '为此分组单独设置选择容差。未设置时保留原有继承规则。', hint: '填写带单位的时长，例如 100ms。' },
        tcp_check_http_method: { label: 'TCP 检查请求方法', description: '设置检查使用的 HTTP 方法；未设置时保留继承行为。' },
        tcp_check_url: { label: 'TCP 检查地址', description: '设置此分组的检查地址。请使用当前官方 DAE 支持的格式。', hint: '列表类型时每行一个值；不会自动请求这些地址。' },
        udp_check_dns: { label: 'UDP 检查 DNS', description: '设置此分组的 UDP 检查目标，格式以当前官方 DAE 配置约定为准。', hint: '列表类型时每行一个值；不会自动发起测速。' },
    };
    const SECTIONS = { global: '全局配置', dns: 'DNS', group: '分组' };
    function profiles() { return S.meta?.profiles?.[S.section] || []; }
    function selectedProfile() { return profiles().find(p => p.id === S.profile); }
    function baseFields() { return S.ext?.records?.[S.section]?.[S.profile] || {}; }
    function draftRaw(state, type) { if (!state?.present)
        return ''; if (type === '[]string')
        return Array.isArray(state.value) ? state.value.join('\n') : ''; return String(state.value ?? ''); }
    function getDraft(field, type) { if (S.drafts.has(field))
        return S.drafts.get(field); const b = baseFields()[field] || { present: false }; return { present: b.present === true, raw: draftRaw(b, type), type }; }
    function parseDraft(d) {
        if (!d.present)
            return { present: false };
        const s = d.raw;
        let value;
        if (d.type === 'bool') {
            if (s !== 'true' && s !== 'false')
                throw Error('请选择开启或关闭。');
            value = s === 'true';
        }
        else if (d.type === 'uint32' || d.type === 'int') {
            if (!/^[0-9]+$/.test(s))
                throw Error('请输入非负整数，不要留空。');
            value = Number(s);
            if (!Number.isSafeInteger(value) || (d.type === 'uint32' && value > 4294967295))
                throw Error('数值超出可安全保存的范围。');
        }
        else if (d.type === 'time.Duration') {
            if (!/^(?:0|(?:[0-9]+(?:\.[0-9]+)?(?:ns|us|µs|ms|s|m|h))+)$/.test(s))
                throw Error('请输入带单位的时长，例如 30s 或 100ms。');
            value = s;
        }
        else if (d.type === '[]string') {
            value = s === '' ? [] : s.split('\n');
            if (value.some(v => v.includes(',') || v.includes('\r') || v.includes('\0') || v === ''))
                throw Error('每行一个非空值，不要包含逗号或空行。');
        }
        else if (d.type === 'string') {
            if (/[\0\n\r]/.test(s))
                throw Error('此字段不接受换行或空字符。');
            value = s;
        }
        else
            throw Error('当前界面尚未支持此字段类型，未允许提交。');
        return { present: true, value };
    }
    function equal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
    function fieldDisplay(state,type) {
        if(!state?.present) return '未设置 · 沿用规则';
        if(state.value===null) return 'null（不能当成未设置）';
        if(type==='bool') return state.value===true?'开启 / true':state.value===false?'关闭 / false':String(state.value);
        if(Array.isArray(state.value)) return state.value.length?state.value.join('\n'):'空列表 []';
        return state.value===''?'空字符串 ""':String(state.value);
    }
    function changeDraft(field,d) {
        const b=baseFields()[field]||{present:false};
        if(!S.draftBase.has(field)) S.draftBase.set(field,clone(b));
        let v;try{v=parseDraft(d);}catch(_){v=null;}
        if(v&&equal(v,b)) {S.drafts.delete(field);S.draftBase.delete(field);S.conflictFields.delete(field);}
        else S.drafts.set(field,d);
        S.conflict=S.conflictFields.size>0;
        updateSavebar(); invalidatePreview('本地扩展草稿已修改，需要保存后重新预览。'); showGlobal();
    }
    function reconcileDrafts(records, specs = S.meta?.specs) {
        if(!dirty()) return;
        const remote=records?.[S.section]?.[S.profile];
        if(!remote) {S.conflict=true;for(const k of S.drafts.keys())S.conflictFields.add(k);return;}
        S.conflictFields.clear();
        for(const [field,d] of [...S.drafts]) {
            const live=remote[field], base=S.draftBase.get(field);
            let wanted;try{wanted=parseDraft(d);}catch(_){wanted=null;}
            if(live && wanted && equal(live,wanted)) {S.drafts.delete(field);S.draftBase.delete(field);continue;}
            if(!live || !base || !equal(live,base) || d.type !== specs?.[S.section]?.[field]?.type) S.conflictFields.add(field);
        }
        S.conflict=S.conflictFields.size>0;
    }
    function updateSavebar() {
        $('editor-savebar').hidden=!dirty();$('dirty-count').textContent=S.drafts.size+' 项未保存';
        $('save-extensions').disabled=!dirty()||S.busy||S.uncertain||S.conflict||!editorCoherent()||S.storageUnavailable||navigator.onLine===false;
        $('save-detail').textContent=S.conflict?'草稿与服务器值冲突，先核对差异再保存。':'逐项保存；失败即停，不会自动应用。';
        $('resolve-conflict').hidden=!S.conflict;
        const r=$('draft-review');r.replaceChildren();
        for(const [field,d] of S.drafts) {
            const row=el('div',null,'draft-row'),type=S.meta?.specs?.[S.section]?.[field]?.type||d.type;
            const title=FIELD_INFO[field]?.label||field;
            row.append(el('strong',title));
            const before=el('div',null,'draft-value'),after=el('div',null,'draft-value after');
            let wanted;try{wanted=fieldDisplay(parseDraft(d),type);}catch(e){wanted='尚未填写正确：'+e.message;}
            before.append(el('small','服务器当前值'),el('span',fieldDisplay(baseFields()[field],type)));
            after.append(el('small','你的草稿'),el('span',wanted));row.append(before,after);
            if(S.conflictFields.has(field)) {
                row.append(badge('服务器值已改变','warning'));
                const use=el('button','使用服务器值','text-button');use.type='button';use.disabled=S.busy||S.uncertain;
                use.onclick=()=>{S.drafts.delete(field);S.draftBase.delete(field);S.conflictFields.delete(field);S.conflict=S.conflictFields.size>0;renderExtensions();showGlobal();};
                const keep=el('button','确认保留我的值','text-button');keep.type='button';keep.disabled=S.busy||S.uncertain||!baseFields()[field]||d.type!==type;
                keep.onclick=async()=>{
                    const base=clone(baseFields()[field]);
                    if(await confirmBox('保留你的“'+title+'”修改？','这只更新当前浏览器的草稿基线，不会立即保存。下一次保存仍受服务器并发校验保护。','保留我的值')) {
                        if(!equal(base,baseFields()[field])) {toast('确认期间服务器值又有变化，请重新核对。',true);return;}
                        S.draftBase.set(field,base);S.conflictFields.delete(field);S.conflict=S.conflictFields.size>0;renderExtensions();
                    }
                };
                row.append(use,keep);
            }
            r.append(row);
        }
        $('draft-review-wrap').hidden=!dirty();
        renderSaveReport();
    }
    function renderSaveReport() {
        const r=$('save-report'),v=S.saveReport;r.hidden=!v;if(!v)return;
        r.replaceChildren();r.className='save-report '+(v.complete?'complete':'partial');
        r.append(el('strong',v.title||('已确认保存 '+v.done.length+' / '+v.total+' 项')));
        r.append(el('p',v.note||'逐字段保存，不是原子批量事务。保存不会自动应用。'));
        if(v.done.length)r.append(el('p','已确认：'+v.done.map(k=>FIELD_INFO[k]?.label||k).join('、')));
        if(v.failed)r.append(el('p','本项未确认：'+(FIELD_INFO[v.failed]?.label||v.failed)));
        if(v.pending?.length)r.append(el('p','尚未发送：'+v.pending.map(k=>FIELD_INFO[k]?.label||k).join('、')));
        r.setAttribute('role','status');
    }

    function renderExtensions() {
        $('bind').disabled=S.busy||S.uncertain||S.storageUnavailable||navigator.onLine===false||dirty()||!editorCoherent();
        document.querySelectorAll('[data-section]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.section === S.section)));
        const list = $('profile-list');
        list.replaceChildren();
        const rows = profiles();
        if (!rows.find(p => p.id === S.profile) && !dirty())
            S.profile = rows[0]?.id || null;
        $('profile-count').textContent = rows.length;
        const warning = $('extension-alert');
        const messages = [];
        if (S.conflict)
            messages.push('服务器有并发修改，草稿已保留。展开下方草稿对照，核对后选择使用服务器值或保留你的修改。');
        if (S.ext?.setupRequired)
            messages.push('官方配置授权尚未完成。请由管理员先完成已有初始化流程，此处不会重建账号。');
        if (S.errors.meta || !S.meta)
            messages.push('配置名称与字段类型暂不可用。请检查只读展示接口，页面不会猜测类型或允许盲目编辑。');
        if (S.errors.ext)
            messages.push('扩展记录读取失败，编辑已锁定。');
        if (S.meta && !editorCoherent()) messages.push('编辑快照不完整或代际不一致，已锁定编辑，请刷新核对。');
        const missing = rows.filter(p => !p.bound).length;
        if (missing)
            messages.push('发现 ' + missing + ' 个未绑定的新对象。点击“同步新建配置”后才建立扩展记录；查看页面不会自动写入。');
        warning.hidden = !messages.length;
        warning.textContent = messages.join(' ');
        const pq = $('profile-search').value.trim().toLowerCase();
        for (const p of rows.filter(p => !pq || (p.name + ' ' + p.id).toLowerCase().includes(pq))) {
            const b = el('button', null, 'profile-button' + (p.id === S.profile ? ' active' : ''));
            b.type = 'button';
            b.dataset.profile = p.id;
            b.setAttribute('aria-pressed', String(p.id === S.profile));
            b.append(el('strong', p.name || SECTIONS[S.section] + ' #' + p.id), el('small', (p.selected ? '当前选中 · ' : '') + (p.bound ? '已绑定' : '待绑定') + ' · #' + p.id));
            b.onclick = () => navigateProfile(S.section, p.id);
            list.append(b);
        }
        if (!rows.length || !list.children.length)
            empty(list, '暂无对象', S.errors.meta ? '请刷新数据后重试。' : '先在官方 daed 新建配置。');
        const p = selectedProfile();
        $('profile-kind').textContent = SECTIONS[S.section];
        $('profile-title').textContent = p?.name || '尚未选择配置';
        $('profile-status').className = 'badge ' + (p?.bound ? 'neutral' : 'warning');
        $('profile-status').textContent = p ? (p.selected ? '当前选中' : p.bound ? '可编辑' : '待绑定') : '未选择';
        const f = $('fields');
        f.replaceChildren();
        if (!p || !editorCoherent()) {
            empty(f, dirty() && !p ? '当前对象已移除，草稿仍保留' : '暂时无法编辑', dirty() && !p ? '不会把草稿写入其他对象。请核对官方配置。' : '检查读取状态后再试。');
            updateSavebar();
            return;
        }
        if (!p.bound) {
            empty(f, '先为新对象准备扩展记录', '使用页面右上角“同步新建配置”。该操作只补齐记录，不自动应用。', 'plus');
            updateSavebar();
            return;
        }
        const specs = S.meta.specs?.[S.section] || {};
        const fields = baseFields();
        if (Object.keys(specs).some(k=>!Object.hasOwn(fields,k)) || Object.keys(fields).some(k=>!Object.hasOwn(specs,k))) {empty(f,'字段合同与封存记录不一致','需要先完成正式合同适配，页面不会隐藏未知字段或自动补齐。');updateSavebar();return;}
        const q = $('field-search').value.trim().toLowerCase();
        let count = 0;
        for (const [field, spec] of Object.entries(specs)) {
            if (!Object.prototype.hasOwnProperty.call(fields, field))
                continue;
            const info = FIELD_INFO[field] || { label: field, description: '当前合同中的扩展字段。提交前请核对官方定义；界面不推断其运行效果。' };
            if (q && !(info.label + ' ' + field).toLowerCase().includes(q))
                continue;
            count++;
            const d = getDraft(field, spec.type), row = el('div', null, 'field-row'), top = el('div', null, 'field-top'), copy = el('div', null, 'field-copy');
            const id = 'field-' + field;
            const label = el('label', info.label);
            label.htmlFor = id;
            copy.append(label, el('p', info.description), el('code', field, 'field-key'));
            top.append(copy);
            if (S.drafts.has(field))
                top.append(el('span', '未保存', 'field-status'));
            if (S.drafts.has(field)) { const reset = el('button', '还原此项', 'text-button'); reset.type = 'button'; reset.disabled = S.busy || S.uncertain; reset.onclick = () => { S.drafts.delete(field); S.draftBase.delete(field); S.conflictFields.delete(field); S.conflict = S.conflictFields.size > 0; renderExtensions(); showGlobal(); }; top.append(reset); }
            row.append(top);
            const c = el('div', null, 'control');
            const supported = ['bool', 'int', 'uint32', 'string', 'time.Duration', '[]string'].includes(spec.type);
            const error = el('p', null, 'field-error');
            error.id = id + '-error';
            error.hidden = true;
            if (spec.type === 'bool') {
                const select = el('select', null, 'bool-select');
                select.id = id;
                select.setAttribute('aria-describedby', error.id);
                for (const [v, t] of [['absent', '未设置 · 沿用兼容规则'], ['true', info.trueText || '开启'], ['false', info.falseText || '关闭']]) {
                    const o = el('option', t);
                    o.value = v;
                    select.append(o);
                }
                select.value = d.present ? d.raw : 'absent';
                select.disabled = S.busy || S.uncertain || S.storageUnavailable;
                select.dataset.disabled = 'false';
                select.onchange = () => { changeDraft(field, { present: select.value !== 'absent', raw: select.value === 'absent' ? '' : select.value, type: spec.type }); renderExtensions(); requestAnimationFrame(() => $(id)?.focus()); };
                c.append(select);
            }
            else {
                const presence = el('select', null, 'presence-select');
                presence.setAttribute('aria-label', info.label + '设置方式');
                for (const [v, t] of [['absent', '未设置 · 沿用规则'], ['present', '使用自定义值']]) {
                    const o = el('option', t);
                    o.value = v;
                    presence.append(o);
                }
                presence.value = d.present ? 'present' : 'absent';
                presence.disabled = !supported || S.busy || S.uncertain || S.storageUnavailable;
                presence.dataset.disabled = String(!supported);
                const input = el(spec.type === '[]string' ? 'textarea' : 'input');
                input.id = id;
                input.value = d.raw;
                input.setAttribute('aria-describedby', id + '-error');
                if (input.tagName === 'INPUT') {
                    input.type = 'text';
                    if (['int', 'uint32'].includes(spec.type))
                        input.inputMode = 'numeric';
                }
                input.spellcheck = false;
                input.disabled = !d.present || !supported || S.busy || S.uncertain;
                input.dataset.disabled = String(!d.present || !supported);
                input.placeholder = d.present ? (spec.type === 'time.Duration' ? '例如 30s' : spec.type === '[]string' ? '每行一个值' : '输入自定义值') : '未设置，不写入此字段';
                input.oninput = () => { const draft = { present: true, raw: input.value, type: spec.type }; changeDraft(field, draft); try {
                    parseDraft(draft);
                    error.hidden = true;
                    input.removeAttribute('aria-invalid');
                }
                catch (e) {
                    error.textContent = e.message;
                    error.hidden = false;
                    input.setAttribute('aria-invalid', 'true');
                } let status = top.querySelector('.field-status'); if (S.drafts.has(field) && !status)
                    top.append(el('span', '未保存', 'field-status')); if (!S.drafts.has(field) && status)
                    status.remove(); };
                presence.onchange = () => { const on = presence.value === 'present'; changeDraft(field, { present: on, raw: input.value, type: spec.type }); renderExtensions(); requestAnimationFrame(() => on ? $(id)?.focus() : document.querySelector('#'+id)?.closest('.control')?.querySelector('select')?.focus()); };
                c.append(presence, input);
                if (info.unit)
                    c.append(el('span', info.unit, 'unit-label'));
            }
            row.append(c);
            if (info.hint)
                row.append(el('p', info.hint, 'input-hint'));
            if (!supported)
                row.append(el('p', '字段类型 ' + spec.type + ' 暂未支持编辑。', 'field-error'));
            row.append(error);
            f.append(row);
        }
        if (!count)
            empty(f, q ? '没有匹配的设置' : '此配置没有可编辑扩展', q ? '换一个名称或字段关键词试试。' : '不自动创建未知字段。', 'search');
        updateSavebar();
    }
    async function navigateProfile(section,id) {
        if(S.busy)return;
        if(section===S.section && id===S.profile)return;
        if(dirty()&&!await confirmBox('切换对象前放弃草稿？','切换配置对象会丢弃此对象尚未保存的草稿。仅切换左侧页面不会丢失草稿。','放弃并切换'))return;
        S.drafts.clear();S.draftBase.clear();S.conflictFields.clear();S.conflict=false;S.saveReport=null;
        S.section=section;S.profile=id;$('field-search').value='';$('profile-search').value='';renderExtensions();showGlobal();
    }

    function renderHealth() {
        const h = S.health;
        const [label, tone] = healthLabel();
        $('health-overall').className = 'badge ' + tone;
        $('health-overall').textContent = label;
        $('recovery-title').textContent = h && !S.errors.health ? (h.paused ? '自动恢复已暂停' : healthFresh() ? '自动恢复正在巡检' : '自动恢复状态待核对') : '自动恢复状态待核对';
        $('recovery-description').textContent = S.errors.health || h?.summary || '暂未取得服务器巡检记录。';
        $('check-time').textContent = '最近巡检 · ' + fmtTime(h?.lastCheckAt);
        const control = $('recovery-control');
        control.textContent = h?.resumePending ? '等待恢复确认' : h?.paused ? '恢复自动恢复' : '暂停自动恢复';
        control.disabled = !h || !!S.errors.health || S.busy || S.uncertain || S.storageUnavailable || !healthFresh() || h.resumePending;
        const list = $('components');
        list.replaceChildren();
        const components = h?.components || [];
        $('component-count').textContent = components.length ? (healthFresh() ? components.filter(x => x.healthy).length : 0) + ' / ' + components.length + ' 项有健康证据' : '暂无记录';
        const descriptions = { 'independent-bridge.service': '状态、配置应用与扩展管理可访问。', 'daed-api.service': '官方配置查询接口正常响应。', 'bridge-graphql.service': '官方页面与独立 DAE 的管理适配正常。', 'bridge-attestor.service': '配置签发服务正常；Apply 仍需实时核验有效凭据。', 'daed-web.service': '官方节点、订阅与分组页面可访问。' };
        const labels = { 'independent-bridge.service': 'Bridge 管理页面', 'daed-api.service': '官方配置接口', 'bridge-graphql.service': '官方页面适配', 'bridge-attestor.service': '配置签发服务', 'daed-web.service': '官方 daed 页面' };
        for (const c of components) {
            const ok = c.healthy === true && healthFresh();
            const row = el('article', null, 'component-row');
            const sym = el('span', null, 'component-icon');
            sym.append(icon('server'));
            const copy = el('div');
            copy.append(el('h3', labels[c.service] || c.title || '管理组件'), el('p', ok ? descriptions[c.service] || '本次巡检通过。' : !healthFresh() ? '巡检证据已过期，暂不确认当前状态。' : '发生故障时：' + (c.impact || '对应管理能力受影响。')));
            const detail = el('details', null, 'component-detail');
            detail.append(el('summary', '技术详情'), el('p', (c.activeState || 'unknown') + ' / ' + (c.subState || 'unknown') + ' · PID ' + (c.mainPid || '—')), el('code', c.service || ''));
            if (c.lastError)
                detail.append(el('p', '最近记录：' + c.lastError));
            copy.append(detail);
            row.append(sym, copy, badge(ok ? '正常' : !healthFresh() ? '待核对' : c.needsAttention ? '需处理' : '待复查', ok ? 'good' : c.needsAttention ? 'bad' : 'warning'));
            list.append(row);
        }
        if (!components.length)
            empty(list, '暂无巡检状态', '请刷新后核对后端的健康状态接口。');
        renderHistory();
        const note = $('notification-note');
        note.replaceChildren();
        const sym = el('span');
        sym.append(icon('bell'));
        const text = el('div');
        text.append(el('strong', h?.notification?.activeChannel ? '通知渠道已配置' : '尚未接入主动推送'), el('p', h?.notification?.description || '目前不能确认主动通知能力。'));
        note.append(sym, text);
    }
    function renderHistory() { const root = $('recovery-history'); if(S.errors.health){empty(root,'恢复历史暂不可用','上次记录不代表当前完整历史，请刷新后核对。');return;} const filter = $('history-filter').value; const svc = $('history-service').value, hours = Number($('history-range').value); const hist = (S.errors.health ? [] : S.health?.history || []).filter(e => (!svc || e.service === svc) && (!hours || serverNow() - e.at <= hours*3600)).filter(e => filter === 'all' || filter === 'recovery' && String(e.event).startsWith('RECOVERY_') || filter === 'attention' && ['SERVICE_HEALTH_FAILED', 'RECOVERY_FAILED', 'RECOVERY_RATE_LIMITED'].includes(e.event)); root.replaceChildren(); if (!hist.length) {
        empty(root, '暂无' + (filter === 'all' ? '保留的' : '符合筛选的') + '记录', '这里只展示当前后端返回的历史，不代表此前从未发生故障。', 'clock');
        return;
    } for (const e of hist) {
        const row = el('article', null, 'history-row');
        row.append(el('span', null, 'history-dot ' + eventTone(e)));
        const text = el('div');
        text.append(el('strong', recoveryEventLabel(e)), el('p', e.title || e.service || '管理系统'));
        if (e.error) {
            const d = el('details');
            d.append(el('summary', '查看技术记录'), el('p', e.error));
            text.append(d);
        }
        row.append(text, el('time', fmtTime(e.at)));
        root.append(row);
    } }
    function actionAllowed(action) { if (S.busy || S.uncertain || S.storageUnavailable || !statusFresh())
        return false; const s = S.status; if (action === 'recover')
        return HASH.test(s.recoveryBundle || ''); if (!HASH.test(s.activeBundle || '') || s.error || s.state === 'rollback-needed')
        return false; if (action === 'start')
        return s.state === 'stopped' || s.state === 'failed' && s.MainPID === 0 && s.result === 'MANUAL_INTERVENTION_REQUIRED'; return ['stop', 'reload'].includes(action) && s.state === 'running' && s.identityVerified === true; }
    function renderAdvanced() { const s = S.status || {}; const valid = identityOK(); $('identity-badge').textContent = valid ? '身份已核验' : '身份待核验'; $('identity-badge').className = 'badge ' + (valid ? 'good' : 'warning'); const main = $('identity-summary'), tech = $('technical-values'); main.replaceChildren(); tech.replaceChildren(); for (const [k, v] of [['运行状态', S.errors.status ? '读取失败' : { running: '运行中', stopped: '已停止', failed: '异常停止，需要人工介入', 'rollback-needed': '需要恢复事务' }[s.state] || '待核对'], ['配置包', short(s.activeBundle)], ['daed 合同版本', S.meta?.versions?.daed || '未读取'], ['DAE 合同版本', S.meta?.versions?.dae || '未读取']])
        main.append(el('dt', k), el('dd', v)); for (const [label, key] of [['完整配置包ID', 'activeBundle'], ['进程PID', 'MainPID'], ['进程调用标识', 'InvocationID'], ['DAE 二进制 SHA-256', 'executableSha256'], ['运行配置 SHA-256', 'configSha256'], ['来源指纹', 'sourceFingerprint'], ['可恢复事务', 'recoveryBundle'], ['最近控制结果', 'result'], ['错误记录', 'error']])
        tech.append(el('dt', label), el('dd', typeof s[key] === 'object' ? JSON.stringify(s[key]) : s[key] ?? '—')); document.querySelectorAll('[data-action]').forEach(b => b.disabled = !actionAllowed(b.dataset.action)); }
    function renderAll() {
        if(!S.auth)return;
        renderOverview();renderWorkflow();
        const focus=document.activeElement;
        if(!focus?.closest('#fields') || !dirty())renderExtensions();else updateSavebar();
        renderHealth();renderAdvanced();showGlobal();
        $('freshness').textContent=!statusFresh()?'状态待刷新':'状态更新于 '+new Date(S.readAt.status).toLocaleTimeString('zh-CN',{hour12:false});
        $('freshness').classList.toggle('stale',!statusFresh());
        $('connection-state').textContent=navigator.onLine===false?'离线':statusFresh()?'已连接':'待核对';
        $('connection-state').className='connection-state '+(statusFresh()?'good':'warning');
    }

    let dialogResolver = null;
    function confirmBox(title, description, button = '确认', danger = false, extra = '') { if (dialogResolver || !S.auth)
        return Promise.resolve(false); $('dialog-title').textContent = title; $('dialog-description').textContent = description; $('dialog-confirm').textContent = button; $('dialog-confirm').className = 'button ' + (danger ? 'danger' : 'primary'); $('confirm-check-wrap').hidden = !danger; $('confirm-check').checked = false; $('dialog-confirm').disabled = danger; $('dialog-extra').replaceChildren(); if (extra)
        $('dialog-extra').append(el('div', extra, 'dialog-detail')); $('confirm-dialog').returnValue = ''; $('confirm-dialog').showModal(); return new Promise(resolve => { dialogResolver = resolve; }); }
    // Keep keyboard navigation inside the confirmation dialog, including when
    // the primary action is disabled until the acknowledgement is checked.
    document.addEventListener('keydown', event => {
        if (event.key !== 'Tab' || !$('confirm-dialog').open)
            return;
        const dialog = $('confirm-dialog');
        const focusable = [...dialog.querySelectorAll('button,input,select,textarea,a[href],[tabindex]')].filter(e => !e.disabled && e.tabIndex >= 0 && e.getClientRects().length > 0);
        if (!focusable.length) {
            event.preventDefault();
            return;
        }
        const first = focusable[0], last = focusable[focusable.length - 1];
        if (!dialog.contains(document.activeElement)) {
            event.preventDefault();
            first.focus();
        }
        else if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        }
        else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });
    $('confirm-check').onchange = () => { $('dialog-confirm').disabled = !$('confirm-check').checked; };
    $('confirm-dialog').addEventListener('close', () => { const r = dialogResolver; dialogResolver = null; if (r)
        r($('confirm-dialog').returnValue === 'confirm'); });
    async function navigate(page) {
        if(page==='main') { $('main').focus(); return; }
        if(!PAGE_TITLES[page])page='overview';
        if(S.busy) {history.replaceState(null,'','#'+S.page);return;}
        S.page=page;document.querySelectorAll('.page').forEach(e=>e.hidden=e.id!=='page-'+page);
        document.querySelectorAll('[data-page]').forEach(a=>{a.classList.toggle('active',a.dataset.page===page);if(a.dataset.page===page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
        $('breadcrumb').textContent=PAGE_TITLES[page];history.replaceState(null,'','#'+page);
        if(S.auth&&['config','extensions'].includes(page))await refresh(false);
        renderAll();window.scrollTo({top:0,behavior:'instant'});
    }
    window.addEventListener('hashchange',()=>navigate(location.hash.slice(1)));
    document.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>navigate(b.dataset.go));
    async function entered() {
        S.auth=true;S.epoch++;S.errors={};S.readBusy=false;S.marker=readMarker();S.uncertain=!!S.marker;
        $('login-screen').hidden=true;$('boot').hidden=true;$('app').hidden=false;
        await navigate(location.hash.slice(1)||'overview');if(!S.meta)await refresh(false);
        if(S.suspended) {
            const draft=S.suspended;S.suspended=null;S.section=draft.section;S.profile=draft.profile;
            S.drafts=new Map(draft.drafts);S.draftBase=new Map(draft.bases);
            if(S.ext)reconcileDrafts(S.ext.records);else S.conflict=true;
            renderAll();toast(S.conflict?'重新登录成功；草稿已保留，请核对服务器变化。':'重新登录成功；当前页面草稿已恢复，尚未保存。');
        }
        setBusy(false);
    }

    $('login-form').onsubmit = async (e) => { e.preventDefault(); if (S.busy)
        return; const token = $('login-token').value; if (!token)
        return; setBusy(true); $('login-error').hidden = true; try {
        const c = await api('challenge');
        if (typeof c.csrf !== 'string')
            throw new ApiError('INVALID_RESPONSE');
        S.csrf = c.csrf;
        await api('login', { token });
        $('login-form').reset();
        $('login-token').type = 'password';
        $('toggle-secret').setAttribute('aria-pressed','false');
        $('toggle-secret').setAttribute('aria-label','显示管理密钥');
        S.busy = false;
        await entered();
    }
    catch (err) {
        $('login-error').textContent = err.message;
        $('login-error').hidden = false;
        $('login-token').value = '';
    }
    finally {
        setBusy(false);
    } };
    $('toggle-secret').onclick = () => { const show = $('login-token').type === 'password'; $('login-token').type = show ? 'text' : 'password'; $('toggle-secret').setAttribute('aria-pressed', String(show)); $('toggle-secret').setAttribute('aria-label', show ? '隐藏管理密钥' : '显示管理密钥'); };
    $('refresh').onclick = async () => { if (dirty()) {
        toast('本地草稿已保留，重新核对服务器状态和字段版本。');
        await refresh(false);
    }
    else
        await refresh(false); };
    $('logout').onclick=async()=>{
        if(S.busy)return;
        if(dirty()&&!await confirmBox('退出前放弃草稿？','主动退出会清除当前页面草稿；不撤销已经保存的字段。','放弃并退出'))return;
        setBusy(true);
        try{await api('logout',{});resetLogin();}
        catch(e){if(e.code==='UNAUTHORIZED')resetLogin();else toast('未能确认服务器退出。请重试退出或关闭页面；不会继续业务写入。',true);}
        finally{setBusy(false);}
    };
    function statePin(s) {return JSON.stringify(['state','activeBundle','configSha256','InvocationID','identityVerified','recoveryBundle'].map(k=>s?.[k]??null));}
    async function checkedStatus(expected) {
        const status=await api('status');
        if(!object(status)||status.error||typeof status.state!=='string')throw new ApiError('STATUS_REJECTED');
        if(expected!==undefined&&statePin(status)!==expected) {S.status=status;stamp('status');invalidatePreview('确认期间运行状态发生变化。');renderAll();throw new ApiError('CONFIRMED_STATE_CHANGED');}
        S.status=status;stamp('status');return status;
    }
    async function loadEditor() {const result=await api('editor-metadata');acceptEditor(result);return result;}
    $('preview').onclick=()=>mutate(async()=>{
        if(dirty())throw new ApiError('NO_CHANGES');
        const before=await checkedStatus();const pinned=statePin(before);invalidatePreview();
        const p=await api('preview',{});
        if(!object(p)||!HASH.test(p.previewId||'')||!HASH.test(p.candidateSha256||'')||!HASH.test(p.extensionGeneration||'')||!HASH.test(p.sourceFingerprint||''))throw new ApiError('WRITE_UNCERTAIN',true);
        const after=await checkedStatus();
        if(statePin(after)!==pinned)throw new ApiError('CONFIRMED_STATE_CHANGED');
        S.preview=p;S.previewBase=after.activeBundle??null;renderWorkflow();toast('预览已生成，当前运行配置未改变。');
    },'preview');
    $('validate').onclick=()=>mutate(async()=>{
        if(!S.preview)return;
        const p=S.preview;S.validated=false;
        const r=await api('validate',{previewId:p.previewId});
        if(!object(r)||r.validated!==true||r.candidateSha256!==p.candidateSha256)throw new ApiError('WRITE_UNCERTAIN',true);
        if(S.preview!==p)throw new ApiError('PREVIEW_CONFLICT');
        S.validated=true;renderWorkflow();toast('官方静态校验通过，尚未应用。');
    },'validate');
    $('apply').onclick=async()=>{
        if(!S.preview||!S.validated||S.busy||!canApply())return;
        const p=S.preview,pin=statePin(S.status);
        if(!await confirmBox('应用这份候选配置？','将改变独立 DAE 的运行配置，可能影响代理连接和 DNS。服务器仍会检查来源、签发凭据和事务状态。','确认应用',true,'候选 '+short(p.candidateSha256)))return;
        if(S.preview!==p||!S.validated){toast('预览在确认期间已失效，请重新生成。',true);return;}
        await mutate(async()=>{
            await checkedStatus(pin);
            if(!canApply())throw new ApiError('STATUS_REJECTED');
            const meta=await loadEditor();
            if(meta.generation!==p.extensionGeneration||meta.sourceFingerprint!==p.sourceFingerprint)throw new ApiError('SOURCE_CHANGED');
            S.validated=false;
            const result=await api('apply',{previewId:p.previewId});
            if(result?.result?.result==='ROLLED_BACK'){const back=await checkedStatus();if(!['running','stopped'].includes(back.state)||back.state==='running'&&!back.identityVerified)throw new ApiError('UNKNOWN_RESULT');invalidatePreview('应用失败后已恢复原状态。');renderAll();throw new ApiError('CONTROL_ROLLED_BACK');}
            if(result?.result?.error||!['APPLIED','ALREADY_APPLIED'].includes(result?.result?.result)||!HASH.test(result?.bundleId||''))throw new ApiError('UNKNOWN_RESULT');
            let status;try{status=await checkedStatus();}catch(_){throw new ApiError('WRITE_UNCERTAIN',true);}
            const verified=status.identityVerified===true&&status.state==='running'&&status.activeBundle===result.bundleId&&status.configSha256===p.candidateSha256;
            if(!verified)throw new ApiError('UNKNOWN_RESULT');
            S.applied=true;S.preview=p;S.previewBase=status.activeBundle;S.meta=null;renderAll();toast('应用完成，运行配置身份已核验。');
        },'apply');
    };
    $('bind').onclick=async()=>{
        if(S.busy)return;
        if(dirty()){toast('请先保存或放弃草稿，再同步新对象。',true);return;}
        if(!await confirmBox('同步官方新建的配置？','只为官方实际存在的新对象补齐扩展记录。不覆盖原记录、不猜测复制继承、不自动应用。','确认同步'))return;
        await mutate(async()=>{
            const r=await api('bind-extensions',{});
            if(!object(r)||typeof r.changed!=='boolean'||!HASH.test(r.generation||''))throw new ApiError('UNKNOWN_RESULT');
            invalidatePreview('对象绑定可能改变扩展代际，请重新预览。');
            try{await loadEditor();}catch(e){S.errors.meta=e.message;S.errors.ext=e.message;toast('同步请求已确认，但列表回读失败。请刷新列表，不要重复同步。',true);renderExtensions();return;}
            renderExtensions();toast(r.changed?'新对象已同步，可以编辑扩展。尚未应用。':'没有需要补齐的新对象，现有记录保持不变。');
        },'bind-extensions');
    };
    $('discard').onclick=async()=>{
        if(S.busy)return;
        if(await confirmBox('放弃这些草稿？','仅清除当前页面未保存的修改；已保存到服务器的字段不会被撤销。','放弃草稿')) {
            S.drafts.clear();S.draftBase.clear();S.conflictFields.clear();S.conflict=false;
            await refresh(false);renderExtensions();showGlobal();
        }
    };
    $('resolve-conflict').onclick=async()=>{
        await refresh(false);renderExtensions();$('draft-review-wrap').open=true;
        toast(S.conflict?'冲突值已列出，请逐项选择保留草稿或使用服务器值。':'最新值已核对，未冲突的草稿仍保留。');
    };
    $('save-extensions').onclick=async()=>{
        if(!dirty()||S.busy||S.conflict||!editorCoherent())return;
        const section=S.section,profile=S.profile,generation=S.ext.generation;
        const tasks=[];
        try{for(const [field,d]of S.drafts)tasks.push({field,state:parseDraft(d)});}catch(e){toast(e.message,true);return;}
        const epoch=S.epoch;
        if(!await confirmBox('保存 '+tasks.length+' 项扩展设置？','只保存当前对象，不自动应用。按字段逐项提交；中途失败会停止，并显示已确认、未确认和未发送的字段。','保存扩展',false,selectedProfile()?.name||'当前配置'))return;
        if(!S.auth||epoch!==S.epoch||S.section!==section||S.profile!==profile)return;
        await mutate(async()=>{
            const meta=await loadEditor();
            if(!editorCoherent())throw new ApiError('EDITOR_INCOHERENT');
            if(tasks.some(t=>S.drafts.get(t.field)?.type!==meta.specs[section]?.[t.field]?.type))throw new ApiError('EDITOR_INCOHERENT');
            const objectProfile=meta.profiles[section]?.find(p=>p.id===profile);
            if(!objectProfile?.bound)throw new ApiError('PROFILE_GONE');
            if(meta.generation!==generation){renderExtensions();throw new ApiError('EXTENSION_CAS_CONFLICT');}
            // Compare again after the confirmation, before the first write.
            if(tasks.some(t=>!S.drafts.has(t.field)||!equal(parseDraft(S.drafts.get(t.field)),t.state)))throw new ApiError('CONFIRMED_STATE_CHANGED');
            let gen=meta.generation;const done=[];let failure=null,failed=null,index=0;
            S.saveReport={total:tasks.length,done:[],pending:tasks.map(t=>t.field),title:'正在保存扩展',complete:false};renderSaveReport();
            for(index=0;index<tasks.length;index++){
                const task=tasks[index];
                S.saveReport.title='正在保存 '+(index+1)+' / '+tasks.length+' 项';renderSaveReport();
                try{
                    const r=await api('extensions',{expected:gen,section,profile,field:task.field,state:task.state});
                    if(!object(r)||!HASH.test(r.generation||''))throw new ApiError('WRITE_UNCERTAIN',true);
                    gen=r.generation;done.push(task.field);S.drafts.delete(task.field);S.draftBase.delete(task.field);S.conflictFields.delete(task.field);
                    S.ext.records[section][profile][task.field]=clone(task.state);S.ext.generation=gen;
                    S.saveReport.done=[...done];S.saveReport.pending=tasks.slice(index+1).map(t=>t.field);renderSaveReport();
                }catch(e){failure=e;failed=task.field;break;}
            }
            invalidatePreview('扩展已保存或部分保存，旧预览已失效。');
            let readback=true;
            try{await loadEditor();}catch(e){S.errors.meta=e.message;S.errors.ext=e.message;readback=false;}
            // Returned generation alone is not enough for final success: confirm
            // the saved values are still visible in a coherent server readback.
            const matches=readback&&done.every(k=>equal(S.ext.records[section]?.[profile]?.[k],tasks.find(t=>t.field===k).state));
            if(!failure&&!matches){failure=new ApiError('UNKNOWN_RESULT');failed=null;}
            S.saveReport={total:tasks.length,done:[...done],failed,pending:failure?tasks.slice(index+1).map(t=>t.field):[],complete:!failure,
                title:failure?'保存需要核对 · '+done.length+' / '+tasks.length+' 项已有回执':'扩展已保存并回读确认',
                note:failure?(failure.message+' 剩余草稿仅保留在本页，不自动重发。'):'所有修改已在服务器回读确认；尚未应用到 DAE。'};
            if(failure?.uncertain)markUncertain();
            if(failure?.code==='EXTENSION_CAS_CONFLICT'&&!S.conflictFields.size)S.conflict=true;
            if(!failure){S.drafts.clear();S.draftBase.clear();S.conflictFields.clear();S.conflict=false;}
            renderExtensions();renderSaveReport();
            toast(failure?'保存未全部确认，请查看明细；没有自动重发。':'扩展已保存，尚未应用。请到「配置应用」重新预览。',!!failure);
        },'extensions');
    };
    document.querySelectorAll('[data-section]').forEach(b=>b.onclick=()=>navigateProfile(b.dataset.section,null));
    $('field-search').oninput=renderExtensions;
    $('profile-search').oninput=renderExtensions;
    $('history-filter').onchange=renderHistory;
    $('history-service').onchange=renderHistory;
    $('history-range').onchange=renderHistory;
    $('recovery-control').onclick=async()=>{
        if(!S.health||!healthFresh()||S.health.resumePending||S.busy)return;
        const paused=S.health.paused,pause=!paused;
        if(!await confirmBox(pause?'暂停管理系统自动恢复？':'请求恢复自动恢复？',pause?'不会停止 DAE，也不会改变 DNS。暂停没有自动到期，维护结束后请主动恢复。':'只提交恢复请求。需等待底层巡检通过维护、事务与安装身份检查，不能把请求受理当成恢复完成。',pause?'确认暂停':'提交恢复请求'))return;
        await mutate(async()=>{
            const before=await api('management-health');
            if(!healthShape(before)||before.paused!==paused||before.resumePending)throw new ApiError('CONFIRMED_STATE_CHANGED');
            const h=await api('management-recovery/'+(pause?'pause':'resume'),{});
            if(!healthShape(h)||(pause?h.paused!==true:h.paused!==false&&h.resumePending!==true))throw new ApiError('UNKNOWN_RESULT');
            S.health=h;stamp('health');renderHealth();renderOverview();
            toast(pause?'自动恢复已暂停，请在维护结束后恢复。':h.resumePending?'恢复请求已提交，等待底层巡检确认。':'后端已确认自动恢复启用。');
        },pause?'management-recovery/pause':'management-recovery/resume');
    };
    document.querySelectorAll('[data-action]').forEach(b=>b.onclick=async()=>{
        const action=b.dataset.action;if(!actionAllowed(action))return;
        const names={start:'启动独立 DAE',stop:'停止独立 DAE',reload:'重载当前配置',recover:'恢复未完成事务'};
        const target=action==='recover'?S.status.recoveryBundle:S.status.activeBundle,pin=statePin(S.status);
        if(!await confirmBox(names[action]+'？','可能影响代理与由 DAE 提供的 DNS。确认后只提交一次，服务器仍执行权限与事务检查。','确认'+names[action],true,'目标配置包 '+short(target)))return;
        await mutate(async()=>{
            await checkedStatus(pin);
            const r=await api(action,{bundleId:target});
            if(!object(r)||r.error||!['running','stopped'].includes(r.state)||(r.result&&!['ALREADY_RUNNING','ALREADY_STOPPED','ROLLED_BACK'].includes(r.result)))throw new ApiError('UNKNOWN_RESULT');
            let st;try{st=await checkedStatus();}catch(_){throw new ApiError('WRITE_UNCERTAIN',true);}
            if(r.result==='ROLLED_BACK'&&action!=='recover'){S.meta=null;invalidatePreview('操作失败后已恢复原状态，需要重新核对。');renderAll();throw new ApiError('CONTROL_ROLLED_BACK');}
            const verified=action==='stop'?st.state==='stopped':action==='recover'?r.result==='ROLLED_BACK'&&['running','stopped'].includes(st.state)&&!st.error&&(st.state==='stopped'||st.identityVerified===true)&&st.activeBundle===r.activeBundle:st.state==='running'&&st.identityVerified===true&&st.activeBundle===target;
            if(!verified)throw new ApiError('UNKNOWN_RESULT');
            S.meta=null;invalidatePreview('运行控制已执行，需要重新核对来源。');renderAll();toast('控制请求完成，已回读核对运行状态；不代表全部业务逐项验证。');
        },action);
    });
    function renderUncertain() {
        const box=$('uncertain-panel');if(!box)return;
        const m=S.marker||readMarker();
        box.hidden=!S.auth||!S.uncertain;
        if(box.hidden)return;
        $('uncertain-title').textContent=(m?.invalid?'写入防重记录需要检查':(ACTION_NAMES[m?.action]||'上次写入')+'的结果需要核对');
        $('uncertain-description').textContent='页面不会自动重发。刷新、重新登录或打开另一个窗口，也不会悄悄解除这项保护。该标记只保留操作类别与时间，不保存密钥或配置值。';
        $('uncertain-time').textContent=m?.at?'开始时间 · '+new Date(m.at).toLocaleString('zh-CN',{hour12:false}):'记录格式异常，不推测上次结果';
        $('review-uncertain').disabled=S.busy||S.readBusy;
        $('ack-uncertain').disabled=S.busy||!S.reviewChecked||age('status')>15000;
    }
    async function reviewUncertain() {
        if(S.busy||!S.auth||!S.uncertain)return;
        S.reviewChecked=null;
        const marker=readMarker();
        if(navigator.locks?.query){const locks=await navigator.locks.query();if(locks.held.some(x=>x.name===WRITE_LOCK)){toast('另一窗口仍在执行，请等待完成，不要解除保护。',true);return;}}
        try{
            const a=await api('status');
            await new Promise(resolve=>setTimeout(resolve,500));
            const b=await api('status');
            S.status=b;stamp('status');
            if(!object(b)||b.error||b.state==='rollback-needed'||!['running','stopped'].includes(b.state)||statePin(a)!==statePin(b)||b.state==='running'&&b.identityVerified!==true)throw new ApiError('STATUS_REJECTED');
            await loadEditor();
            if(readMarker()?.id!==marker?.id)throw new ApiError('CONFIRMED_STATE_CHANGED');
            S.reviewChecked={id:marker?.id,pin:statePin(b),at:performance.now()};
            $('uncertain-readback').replaceChildren(el('strong','当前状态已重新读取'),el('p',(b.state==='running'?'DAE 正在运行，运行身份已核验。':'DAE 当前已停止。')+' 连续两次运行身份一致，扩展与来源也已重新读取。'),el('p','这不是对上次请求的完成证明。请结合保存明细或后台事务记录确认操作已经结束，再手动解除保护；不会自动撤销或重新执行。','fine-print'));
            renderAll();
        }catch(e){$('uncertain-readback').replaceChildren(el('p',e.message,'field-error'));toast('状态仍不能可靠确认，保留写入保护。',true);renderUncertain();}
    }
    $('review-uncertain').onclick=reviewUncertain;
    $('ack-uncertain').onclick=async()=>{
        if(!S.reviewChecked||S.busy)return;
        const review={...S.reviewChecked};
        if(!await confirmBox('确认解除本浏览器的写入保护？','只有在你已确认后台操作结束后才继续。解除保护不是撤销、不是重试，也不证明上次操作失败；后续写入仍需重新确认并由后端校验。','我已核对，解除保护',true))return;
        const resolve=async lock=>{
            if(lock===null){toast(ERROR_TEXT.OTHER_WINDOW_BUSY,true);return;}
            try{
                const current=await checkedStatus(review.pin);
                if(readMarker()?.id!==review.id||current.error||current.state==='rollback-needed')throw new ApiError('CONFIRMED_STATE_CHANGED');
                if(!clearMarker(review.id))throw new ApiError('CONFIRMED_STATE_CHANGED');
                S.uncertain=false;invalidatePreview('已人工解除待核对状态；需要重新预览。');renderAll();setBusy(false);toast('写入保护已由你解除。没有重发任何业务请求。');
            }catch(e){toast(e.message,true);}
        };
        if(navigator.locks?.request)await navigator.locks.request(WRITE_LOCK,{mode:'exclusive',ifAvailable:true},resolve);else await resolve(undefined);
    };
    window.addEventListener('storage',event=>{
        if(event.key!==WRITE_MARKER)return;
        const marker=readMarker();
        if(S.operation?.id&&marker?.id===S.operation.id)return;
        S.marker=marker;S.uncertain=!!marker;S.reviewChecked=null;
        if(marker)invalidatePreview('另一个窗口正在操作或有未确认的请求。');
        if(S.auth){setBusy(S.busy);showGlobal();}
    });
    $('download-diagnostic').onclick=()=>{
        if(!S.auth)return;
        const data={format:'bridge-ui-diagnostic-v2',createdAt:new Date().toISOString(),uiVersion:'2.0.0',
            observation:'browser readback only; not a connectivity test',
            runtime:{state:['running','stopped','starting','reloading','rollback-needed','failed'].includes(S.status?.state)?S.status.state:'unknown',fresh:statusFresh(),identityVerified:identityOK()},
            configuration:{modified:verifiedModified(),editorCoherent:editorCoherent()},
            management:{overall:healthLabel()[0],fresh:healthFresh(),paused:S.health?.paused??null,lastCheckAt:Number.isInteger(S.health?.lastCheckAt)?S.health.lastCheckAt:null,
                components:(S.health?.components||[]).map(c=>({service:SERVICES.includes(c.service)?c.service:'additional-component',healthy:c.healthy===true&&healthFresh(),needsAttention:c.needsAttention===true}))},
            browser:{online:navigator.onLine,writeNeedsReview:S.uncertain,storageAvailable:!S.storageUnavailable},
            privacy:'No host, profile/node names, tokens, configuration values, raw errors, hashes or full history.'};
        const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=el('a');
        a.href=url;a.download='bridge-ui-diagnostic.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);
        toast('已生成脱敏摘要；不含密钥、节点、配置值或原始错误。');
    };

    const THEMES = ['system', 'light', 'dark'];
    let theme = 'system';
    try {
        const saved = localStorage.getItem('bridge-ui-theme');
        if (THEMES.includes(saved))
            theme = saved;
    }
    catch (_) { }
    const media = matchMedia('(prefers-color-scheme: dark)');
    function setTheme() { document.documentElement.dataset.theme = theme === 'system' ? (media.matches ? 'dark' : 'light') : theme; $('theme').title = '配色：' + ({ system: '跟随系统', light: '浅色', dark: '深色' }[theme]); $('theme').setAttribute('aria-label', '当前配色' + ({ system: '跟随系统', light: '浅色', dark: '深色' }[theme]) + '，点击切换'); $('theme').replaceChildren(icon(document.documentElement.dataset.theme === 'dark' ? 'moon' : 'sun')); }
    $('theme').onclick = () => { theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length]; try {
        localStorage.setItem('bridge-ui-theme', theme);
    }
    catch (_) { } setTheme(); };
    media.addEventListener?.('change', setTheme);
    window.addEventListener('beforeunload', e => { if (dirty() || S.busy || S.uncertain) {
        e.preventDefault();
        e.returnValue = '';
    } });
    window.addEventListener('online', () => { if (S.auth && !S.busy) refresh(false); });
    window.addEventListener('offline', () => { if(S.auth) { renderAll();setBusy(S.busy); } });
    document.addEventListener('visibilitychange', () => { if (!document.hidden && S.auth) { S.readMono.status=undefined;S.readMono.health=undefined;renderAll();refresh(false); } });
    try { const k='bridge-ui-storage-test';localStorage.setItem(k,'1');localStorage.removeItem(k); } catch(_) { S.storageUnavailable=true; }
    paintIcons();
    setTheme();
    $('login-origin').textContent = location.protocol === 'https:' ? 'HTTPS · ' + location.host : '仅供本地预览';
    $('host-label').textContent = location.hostname || '本地预览';
    const official = new URL(location.href);
    official.protocol = 'http:';
    official.port = '2023';
    official.pathname = '/';
    official.search = '';
    official.hash = '';
    document.querySelectorAll('.official-dynamic,#official-link').forEach(a => a.href = official.href);
    if (window.BRIDGE_DEMO === true) {
        // The downloadable file:// preview has no origin storage in some browsers.
        // Its writes are browser-local synthetic data only.
        if(location.protocol==='about:' || location.protocol==='file:') S.storageUnavailable=false;
        document.body.classList.add('demo-mode');
        $('demo-banner').hidden = false;
        document.querySelectorAll('.official-dynamic,#official-link').forEach(a => { a.href = '#'; a.onclick = e => { e.preventDefault(); toast('演示页面不连接官方 daed。'); }; });
    }
    (async () => { try {
        await api('session');
        await entered();
    }
    catch (e) {
        resetLogin(e.code === 'UNAUTHORIZED' ? '' : e.message);
    } })();
    setInterval(() => { if (S.auth && !document.hidden && !S.busy) {renderOverview();renderWorkflow();renderAdvanced();showGlobal();} },5000);
    setInterval(() => { if (S.auth && !document.hidden && !S.busy)
        refresh(age('meta') < 60000); }, 30000);
})();

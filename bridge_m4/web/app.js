/* Bridge Web Studio 1.0.0. No libraries, remote assets, stored credentials or auto-Apply. */
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
    const S = { auth: false, csrf: '', status: null, health: null, meta: null, ext: null, errors: {}, readAt: {}, busy: false, readBusy: false, uncertain: false, conflict: false, page: 'overview', section: 'global', profile: null, drafts: new Map(), preview: null, validated: false, applied: false, previewBase: null, mutationVersion: 0, epoch: 0 };
    const PAGE_TITLES = { overview: '总览', config: '配置应用', extensions: 'DAE 扩展', health: '健康与恢复', advanced: '高级维护' };
    const ERROR_TEXT = {
        UNAUTHORIZED: '登录已过期，请重新输入管理密钥。', AUTH_FAILED: '登录未通过，请核对 Bridge 管理密钥。', AUTH_RATE_LIMIT: '登录尝试过于频繁，请稍后再试。', AUTH_BUSY: '认证服务暂时忙，请稍后重试。', CSRF_REJECTED: '安全验证未通过，请刷新页面后重试。', REQUEST_REJECTED: '请求被安全检查拒绝。请确认访问的是部署时设置的 HTTPS 地址。',
        SOURCE_CHANGED: '官方配置已变化，请重新生成预览。', EXTENSION_CHANGED: '扩展记录已变化，请刷新并重新预览。', EXTENSION_CAS_CONFLICT: '其他操作已更新扩展记录；已停止保存，请核对最新值后再提交。', PREVIEW_CONFLICT: '这份预览已失效，请重新生成。', VALIDATION_REQUIRED: '请先完成当前候选的校验。', VALIDATE_FAILED: '官方 DAE 静态校验未通过。请核对配置，不要直接应用。', OLD_SOURCE: '来源证据与候选不一致，请重新预览。', SOURCE_EXPIRED: '来源签发凭据已过期，请检查配置签发服务。', STATUS_REJECTED: '当前运行状态不允许应用配置，请查看高级维护。', UNMANAGED_SERVICE_ACTIVE: '存在未受管理的运行服务，已拒绝操作。', MANUAL_INTERVENTION_REQUIRED: '当前事务需要管理员检查，不能自动继续。', UNIT_IDENTITY_MISMATCH: '服务身份不匹配，已拒绝操作。', MANAGEMENT_HEALTH_STATE: '无法读取自动恢复记录，请查看管理服务日志。', MANAGEMENT_RECOVERY_BLOCKED: '维护、回滚或安装身份检查未通过，暂不能恢复自动管理。', MANAGEMENT_RECOVERY_REQUEST: '自动恢复控制请求无效。', MANAGEMENT_HEALTH_UNAVAILABLE: '当前后端没有提供自动恢复状态接口。', REQUEST_FAILED: '请求未完成。请核对后端日志，页面不会自动重试写入。', BUSY: '服务正在处理其他事务，请稍后刷新状态。', NETWORK_ERROR: '暂时无法连接 Bridge。请检查网络和 HTTPS 证书，页面不会自动重试写入。', READ_TIMEOUT: '读取超时。当前内容可能已经过期，请稍后刷新。', WRITE_UNCERTAIN: '请求超时或连接中断，服务器可能已执行操作。结果未确认，禁止重复提交；请先核对服务器状态。', INVALID_RESPONSE: '服务器返回了无法识别的响应，未把它当作成功。', METADATA_MISSING: '扩展名称与类型信息不可用。请确认只读展示接口已部署，编辑暂时锁定。', EMPTY_REFERENCED_GROUP: '被路由使用的分组没有可用节点，请先到官方 daed 配置。', NO_CHANGES: '没有需要保存的修改。', INCOMPLETE_SAVE: '只保存了部分字段，已停止后续提交。请核对提示和服务器当前值。', UNKNOWN_RESULT: '服务器没有返回明确成功结果，请核对实际状态，不要重复操作。'
    };
    class ApiError extends Error {
        constructor(code, uncertain = false) { super(ERROR_TEXT[code] || ERROR_TEXT.REQUEST_FAILED); this.code = code; this.uncertain = uncertain || code === 'UNKNOWN_RESULT'; }
    }
    function toast(text, error = false) { $('toast').textContent = text; $('toast').classList.toggle('error', error); $('toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').hidden = true, error ? 10000 : 5500); }
    function resetLogin(text = '') { S.auth = false; S.csrf = ''; S.epoch++; S.status = S.health = S.meta = S.ext = null; S.preview = null; S.validated = false; S.applied = false; S.drafts.clear(); S.conflict = false; S.errors = {}; S.readAt = {}; $('app').hidden = true; $('login-screen').hidden = false; $('boot').hidden = true; $('login-token').value = ''; $('login-token').type = 'password'; $('login-error').textContent = text; $('login-error').hidden = !text; ['fields', 'components', 'recovery-history', 'technical-values', 'identity-summary', 'preview-result', 'profile-list'].forEach(id => $(id).replaceChildren()); $('hero-title').textContent = '等待登录'; }
    async function api(path, value) {
        const mutation = value !== undefined;
        const controller = new AbortController();
        const ms = mutation ? 180000 : 25000;
        const timer = setTimeout(() => controller.abort(), ms);
        const epoch = S.epoch;
        try {
            const r = await fetch('/api/' + path, { method: mutation ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store', headers: mutation ? { 'Content-Type': 'application/json', 'X-CSRF-Token': S.csrf } : {}, body: mutation ? JSON.stringify(value) : undefined, signal: controller.signal });
            let data;
            try {
                data = await r.json();
            }
            catch (_) {
                throw new ApiError(mutation ? 'WRITE_UNCERTAIN' : 'INVALID_RESPONSE', mutation);
            }
            if (epoch !== S.epoch)
                throw new ApiError('UNAUTHORIZED');
            if (typeof data.csrf === 'string')
                S.csrf = data.csrf;
            if (!r.ok) {
                const code = typeof data.error === 'string' ? data.error : 'REQUEST_FAILED';
                if (r.status === 401 && ['UNAUTHORIZED', 'AUTH_FAILED'].includes(code) && S.auth)
                    resetLogin(ERROR_TEXT.UNAUTHORIZED);
                throw new ApiError(code);
            }
            return data.data === undefined ? data : data.data;
        }
        catch (e) {
            if (e instanceof ApiError)
                throw e;
            throw new ApiError(mutation ? 'WRITE_UNCERTAIN' : e.name === 'AbortError' ? 'READ_TIMEOUT' : 'NETWORK_ERROR', mutation);
        }
        finally {
            clearTimeout(timer);
        }
    }
    function dirty() { return S.drafts.size > 0; }
    function invalidatePreview() { S.preview = null; S.validated = false; S.applied = false; S.previewBase = null; renderWorkflow(); }
    function showGlobal() { const messages = []; if (S.uncertain)
        messages.push(ERROR_TEXT.WRITE_UNCERTAIN + ' 重新登录前请先由管理员确认操作已结束。'); if (S.errors.status)
        messages.push('运行状态读取失败：' + S.errors.status); if (S.errors.health)
        messages.push('管理巡检读取失败：' + S.errors.health); $('global-warning').hidden = !messages.length; $('global-warning').textContent = messages.join(' '); }
    function setBusy(value) { S.busy = value; $('app').classList.toggle('busy', value); $('refresh').disabled = value; $('logout').disabled = value; $('login-submit').disabled = value; document.querySelectorAll('[data-action]').forEach(e => e.disabled = value || !actionAllowed(e.dataset.action)); $('bind').disabled = value || S.uncertain; $('recovery-control').disabled = value || S.uncertain || !S.health || !!S.errors.health || S.health.resumePending; $('save-extensions').disabled = value || S.uncertain || S.conflict || !dirty(); $('discard').disabled = value; document.querySelectorAll('#fields input,#fields textarea,#fields select').forEach(e => { if (value)
        e.disabled = true;
    else if (e.dataset.disabled !== 'true')
        e.disabled = false; }); renderWorkflow(); }
    async function mutate(work) { if (S.busy)
        return; if (S.uncertain) {
        toast(ERROR_TEXT.WRITE_UNCERTAIN, true);
        return;
    } setBusy(true); S.mutationVersion++; try {
        await work();
    }
    catch (e) {
        if (e.uncertain) {
            S.uncertain = true;
            invalidatePreview();
        }
        if (e.code === 'EXTENSION_CAS_CONFLICT') {
            S.conflict = true;
            renderExtensions();
        }
        toast(e.message || ERROR_TEXT.REQUEST_FAILED, true);
    }
    finally {
        setBusy(false);
        showGlobal();
    } }
    async function readOne(key, path) {
        const epoch = S.epoch, version = S.mutationVersion;
        try {
            const result = await api(path);
            if (!S.auth || epoch !== S.epoch || version !== S.mutationVersion)
                return;
            if (!result || typeof result !== 'object')
                throw new ApiError('INVALID_RESPONSE');
            if (key === 'status') {
                if (S.preview && result.activeBundle !== S.previewBase)
                    invalidatePreview();
                S.status = result;
            }
            else if (key === 'health') {
                if (!Array.isArray(result.components) || !Array.isArray(result.history))
                    throw new ApiError('INVALID_RESPONSE');
                S.health = result;
            }
            else if (key === 'meta') {
                if (result.schemaVersion !== 1 || !result.profiles || !result.specs)
                    throw new ApiError('METADATA_MISSING');
                S.meta = result;
            }
            else if (key === 'ext') {
                if (!result.records)
                    throw new ApiError('INVALID_RESPONSE');
                S.ext = result;
            }
            S.readAt[key] = Date.now();
            delete S.errors[key];
        }
        catch (e) {
            if (epoch !== S.epoch || !S.auth || version !== S.mutationVersion)
                return;
            S.errors[key] = e.message;
        }
    }
    async function refresh(light = false) { if (!S.auth || S.readBusy || S.busy)
        return; S.readBusy = true; $('refresh').classList.add('loading-spinner'); try {
        await Promise.allSettled([readOne('status', 'status'), readOne('health', 'management-health')]);
        if (!light && !dirty())
            await Promise.allSettled([readOne('ext', 'extensions'), readOne('meta', 'editor-metadata')]);
        renderAll();
    }
    finally {
        S.readBusy = false;
        $('refresh').classList.remove('loading-spinner');
    } }
    function identityOK() { return !!S.status && !S.errors.status && S.status.identityVerified === true; }
    function verifiedModified() { if (!identityOK() || !S.meta || S.errors.meta || S.meta.comparisonVerified !== true || !S.readAt.meta || Date.now() - S.readAt.meta > 90000 || S.meta.generation !== S.ext?.generation)
        return null; if (S.status.sourceFingerprint !== S.meta.runningSourceFingerprint)
        return null; return typeof S.meta.modified === 'boolean' ? S.meta.modified : null; }
    function healthFresh() { return !!S.health && !S.errors.health && S.health.lastCheckFresh === true && Number.isInteger(S.health.lastCheckAt) && Date.now() / 1000 - S.health.lastCheckAt <= 180 && Date.now() / 1000 >= S.health.lastCheckAt; }
    function healthLabel() { if (!S.health || S.errors.health || !healthFresh())
        return ['状态待核对', 'warning']; return { HEALTHY: ['全部正常', 'good'], PAUSED: ['恢复已暂停', 'warning'], ATTENTION_REQUIRED: ['需要处理', 'bad'], UNKNOWN: ['状态待核对', 'warning'] }[S.health.overall] || ['状态待核对', 'warning']; }
    function recoveryEventLabel(e) { const labels = { SERVICE_HEALTH_FAILED: '检查未通过', SERVICE_HEALTH_RESTORED: '服务已恢复', RECOVERY_SUCCEEDED: '自动恢复成功', RECOVERY_FAILED: '自动恢复失败', RECOVERY_RATE_LIMITED: '已达到恢复次数上限' }; return labels[e.event] || '管理事件'; }
    function eventTone(e) { return e.event === 'RECOVERY_SUCCEEDED' || e.event === 'SERVICE_HEALTH_RESTORED' ? 'good' : e.event === 'RECOVERY_FAILED' ? 'bad' : 'warning'; }
    function renderOverview() {
        const st = S.status;
        const up = !!st && !S.errors.status && st.state === 'running';
        const id = identityOK();
        $('hero-title').textContent = up ? '转发引擎正在运行' : st && !S.errors.status ? ({ stopped: '转发引擎已停止', 'rollback-needed': '运行事务需要处理' }[st.state] || '运行状态待核对') : '暂时无法确认运行状态';
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
    function canApply() { const s = S.status; return !!s && !S.errors.status && !s.error && s.state !== 'rollback-needed' && (s.state === 'stopped' || s.state === 'running' && s.identityVerified === true); }
    function renderWorkflow() {
        const p = S.preview;
        const blocked = S.busy || S.uncertain;
        const mod = verifiedModified();
        const summary = $('config-summary');
        summary.className = 'notice ' + (mod === true ? 'warning' : 'neutral');
        summary.textContent = mod === true ? '检测到来源或扩展有待应用变更。请检查预览，不要直接重复应用。' : mod === false ? '当前来源、扩展与运行指纹一致。生成新预览前无需切换当前服务。' : '尚未取得可验证的来源对照。生成预览和运行身份核验是两项独立检查。';
        $('preview').disabled = blocked || dirty() || !S.auth;
        $('preview').textContent = p ? '重新生成预览' : '生成预览';
        $('validate').disabled = blocked || !p || S.applied;
        $('apply').disabled = blocked || !p || !S.validated || S.applied || !canApply();
        $('workflow-hint').textContent = S.uncertain ? '上次请求结果未确认，已暂停写入操作。' : dirty() ? '请先保存或放弃扩展草稿。' : S.applied ? '本次应用已核验。新的修改需要重新预览。' : S.validated ? '静态校验已通过。应用前仍会核对来源、凭据及运行状态。' : p ? '预览已生成，尚未影响运行。下一步：校验配置。' : '请先生成预览，再进行校验。';
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
        const count = (p.differences?.daed?.changeCount || 0) + (p.differences?.daeExtensions?.changeCount || 0);
        for (const [val, label] of [[p.nodeCount, '节点'], [p.groupCount, '分组'], [count, '处差异']]) {
            const d = el('div');
            d.append(el('strong', val ?? '—'), el('small', label));
            metrics.append(d);
        }
        root.append(metrics);
        const baseline = { "last-applied": '上次应用的配置', "previous-preview": '上次预览（不是运行配置）', empty: '空基线（不是运行配置）' }[p.differences?.baseline] || '后端提供的基线';
        root.append(el('p', '比较基线：' + baseline, 'fine-print'));
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
    function changeDraft(field, d) { const b = baseFields()[field] || { present: false }; let v; try {
        v = parseDraft(d);
    }
    catch (_) {
        v = null;
    } if (v && equal(v, b))
        S.drafts.delete(field);
    else
        S.drafts.set(field, d); updateSavebar(); invalidatePreview(); }
    function updateSavebar() { $('editor-savebar').hidden = !dirty(); $('dirty-count').textContent = S.drafts.size + ' 项未保存'; $('save-extensions').disabled = !dirty() || S.busy || S.uncertain || S.conflict; $('save-detail').textContent = S.conflict ? '存在并发冲突，请放弃草稿并刷新后重新编辑。' : '逐项保存；失败即停，不会自动应用。'; }
    function renderExtensions() {
        document.querySelectorAll('[data-section]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.section === S.section)));
        const list = $('profile-list');
        list.replaceChildren();
        const rows = profiles();
        if (!rows.find(p => p.id === S.profile))
            S.profile = rows[0]?.id || null;
        $('profile-count').textContent = rows.length;
        const warning = $('extension-alert');
        const messages = [];
        if (S.conflict)
            messages.push('扩展记录发生并发冲突，已锁定保存。请放弃本地草稿并刷新，核对服务器当前值后重新编辑。');
        if (S.ext?.setupRequired)
            messages.push('官方配置授权尚未完成。请由管理员先完成已有初始化流程，此处不会重建账号。');
        if (S.errors.meta || !S.meta)
            messages.push('配置名称与字段类型暂不可用。请检查只读展示接口，页面不会猜测类型或允许盲目编辑。');
        if (S.errors.ext)
            messages.push('扩展记录读取失败，编辑已锁定。');
        const missing = rows.filter(p => !p.bound).length;
        if (missing)
            messages.push('发现 ' + missing + ' 个未绑定的新对象。点击“同步新建配置”后才建立扩展记录；查看页面不会自动写入。');
        warning.hidden = !messages.length;
        warning.textContent = messages.join(' ');
        for (const p of rows) {
            const b = el('button', null, 'profile-button' + (p.id === S.profile ? ' active' : ''));
            b.type = 'button';
            b.dataset.profile = p.id;
            b.setAttribute('aria-pressed', String(p.id === S.profile));
            b.append(el('strong', p.name || SECTIONS[S.section] + ' #' + p.id), el('small', (p.selected ? '当前选中 · ' : '') + (p.bound ? '已绑定' : '待绑定') + ' · #' + p.id));
            b.onclick = () => navigateProfile(S.section, p.id);
            list.append(b);
        }
        if (!rows.length)
            empty(list, '暂无对象', S.errors.meta ? '请刷新数据后重试。' : '先在官方 daed 新建配置。');
        const p = selectedProfile();
        $('profile-kind').textContent = SECTIONS[S.section];
        $('profile-title').textContent = p?.name || '尚未选择配置';
        $('profile-status').className = 'badge ' + (p?.bound ? 'neutral' : 'warning');
        $('profile-status').textContent = p ? (p.selected ? '当前选中' : p.bound ? '可编辑' : '待绑定') : '未选择';
        const f = $('fields');
        f.replaceChildren();
        if (!p || !S.meta || S.errors.ext || S.errors.meta) {
            empty(f, '暂时无法编辑', '检查读取状态后再试。');
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
                select.disabled = S.busy || S.uncertain;
                select.onchange = () => { changeDraft(field, { present: select.value !== 'absent', raw: select.value === 'absent' ? '' : select.value, type: spec.type }); renderExtensions(); };
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
                presence.disabled = !supported || S.busy || S.uncertain;
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
                input.dataset.disabled = String(!d.present || !supported || S.uncertain);
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
                presence.onchange = () => { changeDraft(field, { present: presence.value === 'present', raw: input.value, type: spec.type }); renderExtensions(); };
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
    async function navigateProfile(section, id) { if (S.busy)
        return; if (dirty() && !await confirmBox('放弃未保存的修改？', '切换配置会清除当前浏览器中的草稿，已经保存到服务器的值不受影响。', '放弃并切换'))
        return; S.drafts.clear(); S.conflict = false; S.section = section; S.profile = id; $('field-search').value = ''; renderExtensions(); }
    function renderHealth() {
        const h = S.health;
        const [label, tone] = healthLabel();
        $('health-overall').className = 'badge ' + tone;
        $('health-overall').textContent = label;
        $('recovery-title').textContent = h ? (h.paused ? '自动恢复已暂停' : healthFresh() ? '自动恢复正在巡检' : '自动恢复状态待核对') : '自动恢复状态待核对';
        $('recovery-description').textContent = S.errors.health || h?.summary || '暂未取得服务器巡检记录。';
        $('check-time').textContent = '最近巡检 · ' + fmtTime(h?.lastCheckAt);
        const control = $('recovery-control');
        control.textContent = h?.resumePending ? '等待恢复确认' : h?.paused ? '恢复自动恢复' : '暂停自动恢复';
        control.disabled = !h || !!S.errors.health || S.busy || S.uncertain || h.resumePending;
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
    function renderHistory() { const root = $('recovery-history'); const filter = $('history-filter').value; const hist = (S.health?.history || []).filter(e => filter === 'all' || filter === 'recovery' && String(e.event).startsWith('RECOVERY_') || filter === 'attention' && ['SERVICE_HEALTH_FAILED', 'RECOVERY_FAILED', 'RECOVERY_RATE_LIMITED'].includes(e.event)); root.replaceChildren(); if (!hist.length) {
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
    function actionAllowed(action) { if (S.busy || S.uncertain || S.errors.status || !S.status)
        return false; const s = S.status; if (action === 'recover')
        return HASH.test(s.recoveryBundle || ''); if (!HASH.test(s.activeBundle || '') || s.error || s.state === 'rollback-needed')
        return false; if (action === 'start')
        return s.state === 'stopped'; return ['stop', 'reload'].includes(action) && s.state === 'running' && s.identityVerified === true; }
    function renderAdvanced() { const s = S.status || {}; const valid = identityOK(); $('identity-badge').textContent = valid ? '身份已核验' : '身份待核验'; $('identity-badge').className = 'badge ' + (valid ? 'good' : 'warning'); const main = $('identity-summary'), tech = $('technical-values'); main.replaceChildren(); tech.replaceChildren(); for (const [k, v] of [['运行状态', S.errors.status ? '读取失败' : { running: '运行中', stopped: '已停止', 'rollback-needed': '需要恢复事务' }[s.state] || '待核对'], ['配置包', short(s.activeBundle)], ['daed 合同版本', S.meta?.versions?.daed || '未读取'], ['DAE 合同版本', S.meta?.versions?.dae || '未读取']])
        main.append(el('dt', k), el('dd', v)); for (const [label, key] of [['完整配置包ID', 'activeBundle'], ['进程PID', 'MainPID'], ['进程调用标识', 'InvocationID'], ['DAE 二进制 SHA-256', 'executableSha256'], ['运行配置 SHA-256', 'configSha256'], ['来源指纹', 'sourceFingerprint'], ['可恢复事务', 'recoveryBundle'], ['最近控制结果', 'result'], ['错误记录', 'error']])
        tech.append(el('dt', label), el('dd', typeof s[key] === 'object' ? JSON.stringify(s[key]) : s[key] ?? '—')); document.querySelectorAll('[data-action]').forEach(b => b.disabled = !actionAllowed(b.dataset.action)); }
    function renderAll() { if (!S.auth)
        return; renderOverview(); renderWorkflow(); if (!dirty())
        renderExtensions(); renderHealth(); renderAdvanced(); showGlobal(); const age = S.readAt.status ? Math.floor((Date.now() - S.readAt.status) / 1000) : null; $('freshness').textContent = S.errors.status ? '状态读取失败' : age === null ? '尚未更新' : '状态更新于 ' + new Date(S.readAt.status).toLocaleTimeString('zh-CN', { hour12: false }); $('freshness').classList.toggle('stale', !!S.errors.status || age > 90); }
    let dialogResolver = null;
    function confirmBox(title, description, button = '确认', danger = false, extra = '') { if (dialogResolver)
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
    async function navigate(page) { if (!PAGE_TITLES[page])
        page = 'overview'; if (S.busy) {
        location.hash = S.page;
        return;
    } if (page !== S.page && dirty()) {
        if (!await confirmBox('先处理未保存的修改', '离开扩展编辑将清除本地草稿，不影响已保存的服务器配置。', '放弃并离开')) {
            history.replaceState(null, '', '#' + S.page);
            return;
        }
        S.drafts.clear();
    } S.page = page; document.querySelectorAll('.page').forEach(e => e.hidden = e.id !== 'page-' + page); document.querySelectorAll('[data-page]').forEach(a => { a.classList.toggle('active', a.dataset.page === page); if (a.dataset.page === page)
        a.setAttribute('aria-current', 'page');
    else
        a.removeAttribute('aria-current'); }); $('breadcrumb').textContent = PAGE_TITLES[page]; history.replaceState(null, '', '#' + page); if (S.auth && ['config', 'extensions'].includes(page) && !dirty())
        await refresh(false); renderAll(); window.scrollTo({ top: 0, behavior: 'instant' }); }
    window.addEventListener('hashchange', () => navigate(location.hash.slice(1)));
    document.querySelectorAll('[data-go]').forEach(b => b.onclick = () => navigate(b.dataset.go));
    async function entered() { S.auth = true; S.uncertain = false; S.errors = {}; $('login-screen').hidden = true; $('boot').hidden = true; $('app').hidden = false; await navigate(location.hash.slice(1) || 'overview'); await refresh(false); }
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
        toast('本地草稿已保留，仅刷新运行与健康状态。');
        await refresh(true);
    }
    else
        await refresh(false); };
    $('logout').onclick = async () => { if (dirty() && !await confirmBox('退出前放弃草稿？', '退出会清除浏览器中的未保存修改。', '放弃并退出'))
        return; await mutate(async () => { await api('logout', {}); resetLogin(); }); };
    $('preview').onclick = () => mutate(async () => { if (dirty())
        throw new ApiError('NO_CHANGES'); invalidatePreview(); const p = await api('preview', {}); if (!HASH.test(p.previewId || '') || !HASH.test(p.candidateSha256 || ''))
        throw new ApiError('INVALID_RESPONSE'); S.preview = p; S.previewBase = S.status?.activeBundle ?? null; renderWorkflow(); toast('预览已生成，当前运行配置未改变。'); });
    $('validate').onclick = () => mutate(async () => { if (!S.preview)
        return; S.validated = false; const r = await api('validate', { previewId: S.preview.previewId }); if (r.validated !== true || r.candidateSha256 !== S.preview.candidateSha256)
        throw new ApiError('VALIDATE_FAILED'); S.validated = true; renderWorkflow(); toast('官方静态校验通过，尚未应用。'); });
    $('apply').onclick = async () => { if (!S.preview || !S.validated || S.busy)
        return; const p = S.preview; if (!await confirmBox('应用这份候选配置？', '此操作会改变独立 DAE 的运行配置，可能影响代理连接和 DNS。\n服务器仍会检查来源是否变化、签发凭据及事务状态。', '确认应用', true, '候选 ' + short(p.candidateSha256)))
        return; await mutate(async () => { S.validated = false; const result = await api('apply', { previewId: p.previewId }); if (result.result?.error || !['APPLIED', 'ALREADY_APPLIED'].includes(result.result?.result))
        throw new ApiError('UNKNOWN_RESULT'); let status; try {
        status = await api('status');
    }
    catch (_) {
        throw new ApiError('WRITE_UNCERTAIN', true);
    } S.status = status; S.readAt.status = Date.now(); delete S.errors.status; const verified = status.identityVerified === true && status.activeBundle === result.bundleId && status.configSha256 === p.candidateSha256; S.applied = verified; S.preview = verified ? p : null; S.meta = null; toast(verified ? '应用完成，运行配置身份已核验。' : '请求已处理，但运行身份尚未核验，请先查看状态。', !verified); renderAll(); }); };
    $('bind').onclick = async () => { if (S.busy)
        return; if (dirty()) {
        toast('请先保存或放弃本地草稿。', true);
        return;
    } if (!await confirmBox('同步官方新建的配置？', '将读取官方 daed，并只为真实存在的新对象补齐扩展记录。\n此操作会持久保存缺失的绑定；不覆盖原记录、不猜测复制继承、不自动应用。', '确认同步'))
        return; await mutate(async () => { const r = await api('bind-extensions', {}); if (typeof r.changed !== 'boolean' || !HASH.test(r.generation || ''))
        throw new ApiError('UNKNOWN_RESULT'); invalidatePreview(); S.ext = await api('extensions'); S.meta = await api('editor-metadata'); S.readAt.meta = Date.now(); delete S.errors.ext; delete S.errors.meta; renderExtensions(); toast(r.changed ? '新对象已同步，可以编辑扩展。尚未应用。' : '没有需要补齐的新对象，现有记录保持不变。'); }); };
    $('discard').onclick = async () => { if (await confirmBox('放弃这些修改？', '仅清除浏览器中的未保存草稿，服务器配置不变。', '放弃修改')) {
        S.drafts.clear();
        S.conflict = false;
        await refresh(false);
        renderExtensions();
    } };
    $('save-extensions').onclick = async () => {
        if (!dirty() || !S.ext || S.busy || S.conflict)
            return;
        const tasks = [];
        try {
            for (const [field, d] of S.drafts)
                tasks.push({ field, state: parseDraft(d) });
        }
        catch (e) {
            toast(e.message, true);
            return;
        }
        if (!await confirmBox('保存 ' + tasks.length + ' 项扩展设置？', '仅保存当前对象的扩展，不自动应用。\n后端按字段逐项提交；若中途失败，将停止后续保存，并明确列出已保存项。', '保存扩展', false, selectedProfile()?.name || '当前配置'))
            return;
        await mutate(async () => {
            const current = await api('extensions');
            if (current.generation !== S.ext.generation) {
                S.ext = current;
                throw new ApiError('EXTENSION_CAS_CONFLICT');
            }
            let gen = current.generation;
            const done = [];
            let failure = null;
            for (const task of tasks) {
                try {
                    const r = await api('extensions', { expected: gen, section: S.section, profile: S.profile, field: task.field, state: task.state });
                    if (!HASH.test(r.generation || ''))
                        throw new ApiError('WRITE_UNCERTAIN', true);
                    gen = r.generation;
                    done.push(task.field);
                    S.drafts.delete(task.field);
                    if (S.ext.records?.[S.section]?.[S.profile])
                        S.ext.records[S.section][S.profile][task.field] = task.state;
                    S.ext.generation = gen;
                }
                catch (e) {
                    failure = e;
                    break;
                }
            }
            invalidatePreview();
            S.meta = null;
            try {
                S.ext = await api('extensions');
                delete S.errors.ext;
            }
            catch (e) {
                S.errors.ext = e.message;
            }
            try {
                S.meta = await api('editor-metadata');
                S.readAt.meta = Date.now();
                delete S.errors.meta;
            }
            catch (e) {
                S.errors.meta = e.message;
            }
            renderExtensions();
            if (failure) {
                if (failure.uncertain)
                    S.uncertain = true;
                if (failure.code === 'EXTENSION_CAS_CONFLICT')
                    S.conflict = true;
                const names = done.map(k => FIELD_INFO[k]?.label || k).join('、');
                $('extension-alert').hidden = false;
                $('extension-alert').className = 'notice warning';
                $('extension-alert').textContent = '已确认保存 ' + done.length + ' / ' + tasks.length + ' 项' + (names ? '（' + names + '）' : '') + '；其余未确认完成。' + failure.message + ' 剩余草稿已保留。';
                toast('保存未全部完成，已停止后续提交。', true);
            }
            else {
                S.drafts.clear();
                renderExtensions();
                toast('扩展已保存，尚未应用。请到「配置应用」重新预览。');
            }
        });
    };
    document.querySelectorAll('[data-section]').forEach(b => b.onclick = () => navigateProfile(b.dataset.section, null));
    $('field-search').oninput = renderExtensions;
    $('history-filter').onchange = renderHistory;
    $('recovery-control').onclick = async () => { if (!S.health || S.health.resumePending || S.busy)
        return; const pause = !S.health.paused; const yes = await confirmBox(pause ? '暂停管理系统自动恢复？' : '请求恢复自动恢复？', pause ? '巡检将尊重维护暂停，不会自动恢复管理服务。不会停止 DAE，也不会改变 DNS。\n维护完成后请主动恢复；本页不擅自设置自动到期。' : '恢复请求会交由底层巡检核对维护锁、事务和安装身份。提交成功不代表已经恢复运行。', pause ? '确认暂停' : '提交恢复请求'); if (!yes)
        return; await mutate(async () => { const h = await api('management-recovery/' + (pause ? 'pause' : 'resume'), {}); if (!h || !Array.isArray(h.components))
        throw new ApiError('UNKNOWN_RESULT'); S.health = h; delete S.errors.health; S.readAt.health = Date.now(); renderHealth(); renderOverview(); toast(pause ? '自动恢复已暂停，请在维护结束后恢复。' : '恢复请求已提交，等待下一轮巡检确认。'); }); };
    document.querySelectorAll('[data-action]').forEach(b => b.onclick = async () => { const action = b.dataset.action; if (!actionAllowed(action))
        return; const names = { start: '启动独立 DAE', stop: '停止独立 DAE', reload: '重载当前配置', recover: '恢复未完成事务' }; const target = action === 'recover' ? S.status.recoveryBundle : S.status.activeBundle; if (!await confirmBox(names[action] + '？', '该操作会提交给现有控制服务。可能影响当前代理和由 DAE 提供的 DNS。\n不会由页面自动重试；确认前请核对配置包。', names[action], true, '目标配置包 ' + short(target)))
        return; await mutate(async () => { const r = await api(action, { bundleId: target }); if (r.error)
        throw new ApiError('UNKNOWN_RESULT'); let st; try {
        st = await api('status');
    }
    catch (_) {
        throw new ApiError('WRITE_UNCERTAIN', true);
    } S.status = st; S.readAt.status = Date.now(); S.meta = null; invalidatePreview(); renderAll(); toast('控制请求已返回。请以最新运行状态为准，不代表全部业务已验证。'); }); });
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
    window.addEventListener('online', () => { if (S.auth && !S.busy)
        refresh(true); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden && S.auth)
        refresh(true); });
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
    setInterval(() => { if (S.auth && !document.hidden && !S.busy)
        refresh(dirty() || Date.now() - (S.readAt.meta || 0) < 60000); }, 30000);
})();

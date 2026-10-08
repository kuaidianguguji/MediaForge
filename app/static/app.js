'use strict';

const state = { user: null, csrf: '', initialized: true, view: 'dashboard', models: [], projects: [], project: null, health: null, settingsTab: 'models', storage: {}, workspace: {share_projects:false}, wordRecreate: {enabled:false,installed:false,ready:false,version:'',reason:''}, users: [], libraryFilter: 'all', libraryScope: 'all', busy: false, poll: null, polling: false, search: '' };
const $ = (selector, scope = document) => scope.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const icons = {
  grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  video:'<rect x="3" y="5" width="13" height="14" rx="2"/><path d="m16 10 5-3v10l-5-3z"/>',
  folder:'<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
  image:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m3 16 5-5 4 4 3-3 6 6"/>',
  settings:'<path d="m10 3-.5 2-2 .9-1.8-.6-2 3.4 1.5 1.5v2.4l-1.5 1.5 2 3.4 1.8-.6 2 .9.5 2h4l.5-2 2-.9 1.8.6 2-3.4-1.5-1.5v-2.4l1.5-1.5-2-3.4-1.8.6-2-.9L14 3Z"/><circle cx="12" cy="11.4" r="3"/>',
  users:'<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6M21 21v-3a6 6 0 0 0-4-5"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
  chevron:'<path d="m9 5 7 7-7 7"/>',
  logout:'<path d="M9 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4M14 8l5 4-5 4M8 12h11"/>',
  upload:'<path d="M12 16V3m-5 5 5-5 5 5M3 16v4a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-4"/>',
  spark:'<path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4ZM20 2v4m-2-2h4"/>',
  play:'<path d="m8 4 12 8-12 8z"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  check:'<path d="m5 12 4 4 10-10"/>',
  checkCircle:'<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  download:'<path d="M12 3v13m-5-5 5 5 5-5M3 17v4h18v-4"/>',
  close:'<path d="m6 6 12 12M6 18 18 6"/>',
  menu:'<path d="M4 6h16M4 12h16M4 18h16"/>',
  cloud:'<path d="M7 18a5 5 0 1 1 1-9 6 6 0 1 1 10 9M12 21v-8m-3 3 3-3 3 3"/>',
  edit:'<path d="m15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 14z"/>',
  shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
  refresh:'<path d="M20 7V2l-4 4a8 8 0 1 0 4 10M20 7h-5"/>',
  file:'<path d="M14 3H5v18h14V8ZM14 3v6h5M8 14h8M8 17h5"/>',
  home:'<path d="m3 10 9-7 9 7v11h-7v-7h-4v7H3Z"/>'
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.file}</svg>`;
const brand = () => '<div class="brand"><div class="brand-symbol">V<span>↗</span></div><div class="brand-name">VideoImageOperation<small>AI CREATIVE WORKSPACE</small></div></div>';
const statusNames = {draft:'待分析',analyzing:'分析中',ready:'待生成',generating:'生成中',reviewing:'检查中',needs_review:'待人工审核',completed:'已完成',failed:'失败',needs_attention:'需要处理',cancelled:'已取消',canceled:'已取消',pending:'待处理',prepared:'待提交',received:'结果已保存',no_speech:'未识别到口播',rejected:'请求被拒绝',query_error:'查询失败',submitted:'已提交',submitting:'提交中',queued:'排队中',running:'进行中',succeeded:'已完成'};
const levels = {inspired:'创意借鉴',balanced:'平衡复刻',faithful:'高相似度',strict:'严格复刻'};
const kinds = {vision:'视频 / 视觉分析',image:'图片优化',video:'视频生成',transcription:'音频转写'};
const protocols = {openai:'OpenAI 兼容',anthropic:'Anthropic',volcengine:'火山引擎',dashscope:'阿里云百炼（万相视频）',dashscope_asr:'阿里云百炼（音频转写）'};
const activeStatuses = ['analyzing','generating','reviewing'];
const arr = value => Array.isArray(value) ? value : [];
const formatDate = value => { if (!value) return '—'; const date = new Date(typeof value === 'number' ? value * 1000 : value); return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}); };
const fileSize = n => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.ceil((n || 0) / 1024)} KB`;
const badge = status => `<span class="badge ${esc(status)}"><i class="dot" style="background:currentColor;width:4px;height:4px"></i>${esc(statusNames[status] || status || '待处理')}</span>`;
const admin = () => state.user?.role === 'admin';
const canEditProject = project => {
  if(!project)return false;
  if(Object.prototype.hasOwnProperty.call(project,'can_edit'))return project.can_edit===true;
  // Until the service restarts, the legacy private detail endpoint only returns owned/admin projects.
  return state.workspace.share_projects===false;
};
const isWordProject = project => project?.engine==='hypit'||project?.options?.engine==='hypit';
const projectEngineName = project => isWordProject(project)?'词-复刻视频':'视频复刻';
const wordAvailable = () => state.wordRecreate.enabled===true&&state.wordRecreate.ready===true;
const canUseProject = project => canEditProject(project)&&(!isWordProject(project)||wordAvailable());
const projectActionPath = (project, action) => `/api/${isWordProject(project)?'word-recreate/':''}projects/${encodeURIComponent(project.id)}/${action}`;
function requireProjectUse() { if(!requireProjectEdit())return false;if(canUseProject(state.project))return true;toast('词-复刻视频已停用或引擎未就绪，现有项目仍可查看和下载。',true);return false; }
function resetWorkspace() { state.projects=[];state.project=null;state.models=[];state.workspace={share_projects:false};state.wordRecreate={enabled:false,installed:false,ready:false,version:'',reason:''};state.libraryScope='all';state.libraryFilter='all';state.search=''; }
function requireProjectEdit() { if(canEditProject(state.project))return true;toast('共享项目只可查看和下载，请联系制作人或管理员修改。',true);return false; }
const assetUrl = id => `/api/assets/${encodeURIComponent(id)}`;
function toast(message, error = false) { const item = document.createElement('div'); item.className = `toast-item${error ? ' error' : ''}`; item.textContent = message; $('#toast').append(item); setTimeout(() => item.remove(), 6500); }
function errorText(error) { return error?.message || '请求失败，请稍后重试。'; }
async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && !(options.body instanceof FormData)) { headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(options.body); }
  if (options.method && options.method !== 'GET') headers['X-CSRF-Token'] = state.csrf;
  let response;
  try { response = await fetch(path, { ...options, headers, credentials: 'same-origin' }); } catch { throw new Error('无法连接服务，请确认运行本项目的电脑和网络连接正常。'); }
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && state.user) { state.user = null; state.csrf = '';resetWorkspace(); stopPolling(); renderAuth(); }
    const detail = data?.detail ?? data?.error;
    const error=new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => item.msg || '参数不正确').join('；') : detail?.message || `请求失败（${response.status}）`);error.status=response.status;throw error;
  }
  return data;
}
function normalizeList(data, key) { return Array.isArray(data) ? data : arr(data?.[key] ?? data?.items); }
async function loadBase() {
  const results = await Promise.allSettled([api('/api/models'),api('/api/settings/workspace'),api('/api/health'),api('/api/settings/word-recreate')]);
  if (results[0].status === 'fulfilled') state.models = normalizeList(results[0].value,'models');
  if (results[1].status === 'fulfilled') state.workspace = results[1].value;
  else state.workspace={share_projects:false};
  if(!state.workspace.share_projects)state.libraryScope='all';
  if (results[2].status === 'fulfilled') state.health = results[2].value;
  state.wordRecreate=results[3].status==='fulfilled'?results[3].value:{enabled:false,installed:false,ready:false,version:'',reason:'服务尚未更新或引擎未就绪'};
  state.projects=await loadProjects(state.view==='library'&&state.libraryScope==='mine');
  const failure = results.slice(0,3).find(r => r.status === 'rejected');
  if (failure) toast(errorText(failure.reason),true);
}
async function loadProjects(mine=false) {
  const projects=[],seen=new Set(),limit=200;
  for(let offset=0;;offset+=limit){
    const page=normalizeList(await api(`/api/projects?limit=${limit}&offset=${offset}${mine?'&mine=true':''}`),'projects');
    const previousCount=seen.size;
    for(const project of page)if(!seen.has(project.id)){seen.add(project.id);projects.push(project);}
    if(page.length<limit||seen.size===previousCount)break;
  }
  return projects;
}
function filteredProjects() {
  return state.projects.filter(p=>(state.libraryScope!=='mine'||String(p.owner_id)===String(state.user?.id))&&(state.libraryFilter==='all'||(state.libraryFilter==='active'?activeStatuses.includes(p.status):p.status===state.libraryFilter))&&(!state.search||String(p.name).toLowerCase().includes(state.search.toLowerCase())));
}
function renderAuth() {
  closeModal();
  const setup = !state.initialized;
  $('#app').innerHTML = `<main class="auth-page"><section class="auth-story">${brand()}<div class="auth-story-content"><div class="eyebrow">MADE FOR YOUR NEXT BESTSELLER</div><h1>让好产品，<br>拥有<span>好内容。</span></h1><p>从一段灵感到一条成片，让 AI 帮助你的产品走进巴西消费者的日常。</p><div class="auth-feature">${icon('checkCircle')} 参考视频理解与产品替换</div><div class="auth-feature">${icon('checkCircle')} 巴西葡萄牙语内容本地化</div><div class="auth-feature">${icon('checkCircle')} 从分镜到成片，一站完成</div></div><div class="auth-foot">VIDEOIMAGEOPERATION · YOUR CREATIVE SPACE</div></section><section class="auth-form-wrap"><form id="auth-form" class="auth-form"><div class="eyebrow">WELCOME TO YOUR WORKSPACE</div><h2>${setup?'初始化你的工作台':'欢迎回来'}</h2><p>${setup?'创建首位管理员，开始配置模型和团队账号。':'登录你的团队账号，继续下一次创作。'}</p><div class="field"><label for="auth-username">${setup?'管理员用户名':'用户名'}</label><input id="auth-username" name="username" autocomplete="username" required placeholder="请输入用户名"></div><div class="field"><label for="auth-password">密码</label><input id="auth-password" name="password" type="password" autocomplete="${setup?'new-password':'current-password'}" required placeholder="请输入密码（不能为空）"></div>${setup?'<div class="field"><label for="setup-token">初始化令牌</label><input id="setup-token" name="setup_token" type="password" autocomplete="off" required placeholder="运行服务时终端显示的令牌"><small>令牌用于确认你是本机服务的所有者。</small></div>':''}<div class="form-error" id="auth-error" role="alert"></div><button class="button primary" type="submit">${setup?'创建管理员并进入':'登录工作台'} ${icon('arrow')}</button><div class="note">${setup?'模型和存储服务可在进入后配置。初始化只需完成一次。':'账号由管理员统一创建。如需开通账号或重置密码，请联系你的管理员。'}</div><div class="auth-copyright">属于你的团队，专注每一次创作。</div></form></section></main>`;
}
const viewLabels = {dashboard:'工作台',create:'视频复刻','word-create':'词-复刻视频',library:'作品库',images:'图片制作',settings:'设置中心',users:'用户管理',project:'视频项目'};
function renderShell(body) {
  if (!state.user) return;
  const navButton = (view, name, glyph, tag = '') => `<button data-nav="${view}" class="${state.view === view || (state.view === 'project' && view === (isWordProject(state.project)?'word-create':'create')) ? 'active':''}">${icon(glyph)}<span>${name}</span>${tag?`<span class="nav-tag">${tag}</span>`:''}</button>`;
  $('#app').innerHTML = `<div class="shell"><aside class="sidebar">${brand()}<div class="nav-label">创作空间 · WORKSPACE</div><nav class="nav">${navButton('dashboard','工作台','grid')}${navButton('create','视频复刻','video')}${state.wordRecreate.enabled?navButton('word-create','词-复刻视频','spark'):''}${navButton('library','作品库','folder')}${navButton('images','图片制作','image','即将上线')}</nav>${admin()?`<div class="nav-label">管理 · ADMINISTRATION</div><nav class="nav">${navButton('settings','设置中心','settings')}${navButton('users','用户管理','users')}</nav>`:''}<div class="sidebar-bottom"><div class="connection"><div class="connection-title"><span class="dot"></span>团队创作空间</div><p>局域网协作 · 私有素材管理<br>为跨境电商内容创作而生</p></div><div class="profile"><div class="avatar">${esc(state.user.username?.slice(0,1).toUpperCase())}</div><div class="profile-info">${esc(state.user.username)}<small>${admin()?'工作台管理员':'创作成员'}</small></div><button class="icon-button" data-action="logout" title="退出登录" aria-label="退出登录">${icon('logout')}</button></div></div></aside><div class="main"><header class="topbar"><div class="breadcrumb"><button class="icon-button mobile-menu" data-action="menu" aria-label="打开导航">${icon('menu')}</button><span>创作空间</span>${icon('chevron')}<span>${viewLabels[state.view] || '工作台'}</span></div><div class="top-right"><span class="date-stamp">${new Date().toLocaleDateString('zh-CN',{year:'numeric',month:'long',day:'numeric'})}</span><span class="site-pill"><span class="flag">🇧🇷</span> 巴西站点</span></div></header><main class="content" id="main-content">${body}</main></div></div>`;
}
function heading(title, text, actions = '', eyebrow = '') { return `<div class="page-heading"><div>${eyebrow?`<div class="eyebrow">${eyebrow}</div>`:''}<h1>${title}</h1><p>${text}</p></div>${actions}</div>`; }
function empty(title, text, action = '', glyph = 'video') { return `<div class="empty"><div class="empty-icon">${icon(glyph)}</div><h3>${title}</h3><p>${text}</p>${action}</div>`; }
const newButton = () => `<div class="button-row"><button class="button primary" data-nav="create">${icon('plus')} 新建视频复刻</button>${wordAvailable()?'<button class="button" data-nav="word-create">词-复刻视频</button>':''}</div>`;
function projectTable(projects) {
  if (!projects.length) return empty('你的第一条好内容，从这里开始','上传参考视频与产品图片，将灵感变成属于你产品的故事。',`<button class="button small" data-nav="create">创建第一个项目 ${icon('arrow')}</button>`);
  return `<div class="table-wrap"><table class="table"><thead><tr><th>项目名称</th><th>制作人</th><th>状态</th><th>创建时间</th><th></th></tr></thead><tbody>${projects.map(p=>`<tr><td><button class="table-name" data-project="${esc(p.id)}">${esc(p.name)}</button><span class="subline">${projectEngineName(p)} · 🇧🇷 巴西站点 · ${esc(p.options?.ratio || '9:16')} · ${esc(p.options?.resolution || '720p')}</span></td><td class="project-owner">${esc(p.owner_username)}</td><td>${badge(p.status)}</td><td style="font-size:10px">${formatDate(p.created_at)}</td><td><button class="button ghost small" data-project="${esc(p.id)}">查看 ${icon('arrow')}</button></td></tr>`).join('')}</tbody></table></div>`;
}
function dashboard() {
  const done = state.projects.filter(p=>p.status === 'completed').length;
  const running = state.projects.filter(p=>activeStatuses.includes(p.status)).length;
  const enabled = state.models.filter(m=>m.enabled).length;
  const stats = [['全部视频项目',state.projects.length,'每一次创作，都在这里','video',''],['已完成作品',done,'从创意走向成片','checkCircle','blue'],['正在处理中',running,'AI 正在为你创作','clock','gold'],['可用 AI 模型',enabled,'管理员配置 · 团队共享','spark','purple']];
  return heading(`你好，${esc(state.user.username)} <span style="font-size:23px">☀</span>`,'新的灵感，值得被看见。今天想为哪款产品创作？',newButton(),'YOUR CREATIVE WORKSPACE')+`<section class="hero"><div class="hero-copy"><span class="hero-badge">${icon('spark')} AI 视频复刻</span><h2>复刻好创意，<span>让你的产品成为主角。</span></h2><p>参考爆款视频的镜头与节奏，替换为你的产品，自动规划分镜，创作面向巴西市场的本地化内容。</p><button class="button dark" data-nav="create">开始创作 ${icon('arrow')}</button></div><div class="hero-art" aria-hidden="true"><div class="reel one"><div class="reel-top"><i></i><i></i><i></i></div></div><div class="reel two"><div class="reel-top"><i></i><i></i><i></i></div></div><div class="reel-play">${icon('play')}</div><span class="spark">✧</span></div></section><div class="stats">${stats.map(s=>`<div class="stat"><div><div class="stat-label">${s[0]}</div><div class="stat-number">${s[1]}</div><div class="stat-note">${s[2]}</div></div><div class="stat-icon ${s[4]}">${icon(s[3])}</div></div>`).join('')}</div><div class="dashboard-bottom"><section><div class="section-heading"><div><h2>最近的创作 <span class="count">${state.projects.length} 个项目</span></h2><p>每一个值得被看见的产品，都有自己的故事</p></div><button class="button ghost small" data-nav="library">查看全部 ${icon('arrow')}</button></div><div class="panel">${projectTable(state.projects.slice(0,5))}</div></section><aside class="guide"><h3>三步，开启你的创作</h3><div class="guide-step"><span class="step-number">01</span><div><b>上传视频与产品图片</b><p>好的参考与清晰的素材<br>是好内容的开始</p></div></div><div class="guide-step"><span class="step-number">02</span><div><b>确认 AI 分镜方案</b><p>检查产品、文案与镜头<br>让每个细节符合你的想法</p></div></div><div class="guide-step"><span class="step-number">03</span><div><b>生成并下载你的作品</b><p>AI 生成片段，自动拼接<br>用新内容连接巴西消费者</p></div></div><div class="guide-tip">✧ 小提示：多角度、高清的产品图片，有助于保持外观与细节的一致性。</div></aside></div>`;
}
function modelSelect(kind, optional = false, protocol = null) { const accepted = protocol ? arr(Array.isArray(protocol)?protocol:[protocol]) : null; const list = state.models.filter(m=>m.enabled && m.kind === kind && (!accepted||accepted.includes(m.protocol))); return `${optional?'<option value="">不使用</option>':`<option value="">${list.length?'请选择模型':'尚无可用模型，请联系管理员'}</option>`}${list.map(m=>`<option value="${esc(m.id)}">${esc(m.name)} · ${esc(protocols[m.protocol] || m.protocol)}</option>`).join('')}`; }
function createPage(word=false) {
  if(word&&!wordAvailable())return heading('词-复刻视频','通过可独立停用的 Hypit 引擎制作并保存视频。','','WORD RECREATION')+`<div class="panel">${empty('功能暂未开放',state.wordRecreate.enabled?'引擎尚未就绪，请联系管理员检查。':'请联系管理员在设置中心启用此功能。',admin()?'<button class="button" data-word-settings>前往设置中心</button>':'','spark')}</div>`;
  const modelWarning = !state.models.some(m=>m.enabled&&m.kind==='vision') || !state.models.some(m=>m.enabled&&m.kind==='video');
  return heading(word?'词-复刻视频':'从灵感，开始一条好视频',word?'分析参考视频，替换产品和巴西葡语文案，以实际口播时间生成字幕。':'上传参考视频与产品素材，AI 将为你规划并生成新的产品视频。','',word?'WORD RECREATION':'VIDEO RECREATION')+`<form id="create-form" data-engine="${word?'hypit':'native'}">${word?'<div class="note word-intro">此功能使用独立的 Hypit 引擎完成合成，视频生成沿用管理员配置的模型。开启口播和字幕时，须选择支持逐词时间戳的音频转写模型；会转写生成后的实际口播并产生额外费用。关闭口播时，字幕按分镜时间显示。</div>':''}<div class="new-grid"><div class="stack">${modelWarning?`<div class="note warning">创作需要至少一个视觉分析模型和一个视频生成模型。${admin()?'<button class="button ghost small" type="button" data-nav="settings">前往设置中心 →</button>':'请联系管理员配置后再创建项目。'}</div>`:''}<section class="panel"><div class="panel-head"><div><h2><span class="section-number">01</span>创作素材</h2><p>让 AI 认识你的产品，理解你喜欢的创作风格。</p></div></div><div class="panel-body"><div class="form-grid"><div class="field full"><label for="project-name">项目名称 <span class="required">*</span></label><input id="project-name" name="name" required maxlength="120" placeholder="例如：便携咖啡杯 · 巴西站种草视频"></div><div class="field"><label>参考视频 <span class="required">*</span></label><label class="upload-area">${icon('video')}<b>点击上传参考视频</b><span>MP4 / MOV / WebM<br>清晰的视频更利于分镜理解</span><input type="file" name="reference" accept="video/mp4,video/quicktime,video/webm,.mkv" required aria-label="上传参考视频"><div class="upload-files" data-files="reference"></div></label></div><div class="field"><label>你的产品图片 <span class="required">*</span></label><label class="upload-area">${icon('image')}<b>点击上传产品图片</b><span>JPG / PNG / WebP · 至少 1 张<br>建议包含整体外观与细节特写</span><input type="file" name="products" accept="image/jpeg,image/png,image/webp" multiple required aria-label="上传产品图片"><div class="upload-files" data-files="products"></div></label></div><div class="field full"><label for="product-description">产品信息</label><textarea id="product-description" name="product_description" rows="3" maxlength="6000" placeholder="描述产品名称、材质、颜色、真实卖点，以及希望保留的关键外观。请勿填写未经证实的功效。"></textarea><small>这些信息将作为产品替换与葡语文案的依据。</small></div></div></div></section><section class="panel"><div class="panel-head"><div><h2><span class="section-number">02</span>复刻策略</h2><p>相似度越高，对产品形态与复杂动作的要求也越高。</p></div></div><div class="panel-body"><div class="level-options">${[['inspired','创意借鉴','保留卖点和叙事，镜头自由发挥'],['balanced','平衡复刻','兼顾原片节奏与生成稳定性'],['faithful','高相似度','尽量还原构图、动作与运镜'],['strict','严格复刻','逐镜头对齐，风险处交由你确认']].map(l=>`<label class="level-option"><input type="radio" name="level" value="${l[0]}" ${l[0]==='balanced'?'checked':''}><span class="level-content"><b>${l[1]}${l[0]==='balanced'?' · 推荐':''}</b><small>${l[2]}</small></span></label>`).join('')}</div><div class="note" style="margin-top:15px">复刻等级控制镜头、节奏与动作还原程度；产品一致性在所有等级均为基本要求。分析会检查局部、遮挡与背景中的产品，缺少素材时可补图或调整镜头。</div><div class="divider"></div>${toggle('replicate_music','复刻背景音乐','借鉴音乐情绪和节奏，由模型重新生成')}${toggle('replicate_voice','复刻口播','保留表达逻辑，使用巴西葡语重新创作')}${toggle('replicate_subtitles','复刻字幕','参考原片表达，检查巴西葡语字幕后叠加')}</div></section><section class="panel"><div class="panel-head"><div><h2><span class="section-number">03</span>生成设置</h2><p>所有模型由管理员配置，按需要选择本次创作的模型。</p></div></div><div class="panel-body"><div class="form-grid"><div class="field"><label for="site">目标站点</label><select id="site" name="site"><option value="BR">🇧🇷 巴西站点 · 巴西葡萄牙语</option></select></div><div class="field"><label for="duration">视频时长</label><input id="duration" name="duration" type="number" min="4" max="300" step="1" placeholder="默认：与参考视频相同"><small>超过 15 秒的内容将分段生成并自动拼接。</small></div><div class="field"><label for="ratio">视频比例</label><select id="ratio" name="ratio"><option value="9:16">9:16 · 竖屏短视频</option><option value="16:9">16:9 · 横屏视频</option><option value="1:1">1:1 · 方形视频</option><option value="4:3">4:3</option><option value="3:4">3:4</option></select></div><div class="field"><label for="resolution">分辨率</label><select id="resolution" name="resolution"><option value="720p">720P · 推荐</option><option value="480p">480P</option><option value="1080p">1080P</option></select><small>可用参数取决于所选视频模型。</small></div><div class="field"><label for="vision-model">视觉分析模型 <span class="required">*</span></label><select id="vision-model" name="vision_model_id" required>${modelSelect('vision')}</select></div><div class="field"><label for="video-model">视频生成模型 <span class="required">*</span></label><select id="video-model" name="video_model_id" required>${modelSelect('video')}</select></div><div class="field"><label for="image-model">图片优化模型</label><select id="image-model" name="image_model_id">${modelSelect('image',true)}</select><small>可选。用于产品图优化和难镜头的关键画面引导；图片编辑与核对会产生额外费用。</small></div><div class="field"><label for="transcription-model">音频转写模型</label><select id="transcription-model" name="transcription_model_id" ${word?'required':''}>${modelSelect('transcription',true,word?['openai','dashscope_asr']:null)}</select><small>${word?'口播与字幕同时开启时必选。OpenAI 接口须支持 verbose_json 和逐词时间戳；阿里云选择文件转写 filetrans 协议，需已配置 TOS。仅普通文字转写不足以对齐。':'有口播时建议配置，可提高原文识别准确度。'}</small></div>${word?'<div class="field full"><label for="caption-style">字幕样式</label><select id="caption-style" name="caption_style"><option value="highlight">逐词高亮</option><option value="plain">普通字幕</option></select><small>口播与字幕同时开启时按生成后的实际声音对齐；关闭口播时两种样式均按分镜时间显示。</small></div>':''}</div></div></section></div><aside class="panel summary-panel"><div class="panel-head"><h2>本次创作</h2>${icon('spark')}</div><div class="panel-body"><div class="summary-preview">${icon('play')}9:16 · 竖屏视频</div><div class="summary-line"><span>目标市场</span><strong>🇧🇷 巴西</strong></div><div class="summary-line"><span>内容语言</span><strong>Português do Brasil</strong></div><div class="summary-line"><span>默认输出</span><strong>720P · 9:16</strong></div><div class="summary-line"><span>创作流程</span><strong>分析 → 确认 → 生成</strong></div><div class="divider"></div><div class="note">先创建项目并上传素材，再分析参考视频。分镜方案确认后才会调用视频模型。</div><button class="button primary" type="submit" ${modelWarning?'disabled':''}>${icon('plus')} 创建并上传素材</button><div id="upload-progress" class="upload-progress" role="status"></div><p class="form-help" style="margin-top:14px;text-align:center">素材与生成结果由工作台统一管理</p></div></aside></div></form>`;
}
function toggle(name,title,description,checked=true) { return `<div class="toggle-row"><div><b>${title}</b><p>${description}</p></div><label class="switch"><input type="checkbox" name="${name}" aria-label="${title}" ${checked?'checked':''}><span></span></label></div>`; }
function libraryPage() {
  const list = filteredProjects();
  return heading('每一次创作，都值得收藏','查看视频项目、生成进度与完成的作品。项目按创建时间从新到旧排列。',newButton(),'YOUR CREATIVE LIBRARY')+`<div class="toolbar"><div class="library-filters">${state.workspace.share_projects?`<div class="filter-tabs scope-tabs" aria-label="项目范围">${[['all','全部项目'],['mine','我的项目']].map(f=>`<button data-scope="${f[0]}" class="${state.libraryScope===f[0]?'active':''}" aria-pressed="${state.libraryScope===f[0]}">${f[1]}</button>`).join('')}</div>`:''}<div class="filter-tabs" aria-label="项目状态">${[['all',state.workspace.share_projects?'全部状态':'全部项目'],['active','进行中'],['completed','已完成'],['needs_review','待审核'],['failed','失败']].map(f=>`<button data-filter="${f[0]}" class="${state.libraryFilter===f[0]?'active':''}">${f[1]}</button>`).join('')}</div></div><input class="search-input" id="library-search" aria-label="搜索项目" placeholder="搜索项目名称…" value="${esc(state.search)}"></div><div id="library-results">${libraryResults(list)}</div>`;
}
function libraryResults(list) {
  if(!list.length) return `<div class="panel">${empty(state.projects.length?'还没有符合条件的项目':'作品库还在等待你的第一条视频','从一段参考视频开始，为你的产品创作新的故事。',newButton(),'folder')}</div>`;
  return `<div class="library-grid">${list.map(p=>{const thumb=arr(p.assets).find(a=>a.role==='product'&&a.mime?.startsWith('image/'));return `<article class="project-card"><div class="project-cover">${thumb?`<img src="${assetUrl(thumb.id)}" alt="${esc(p.name)}的产品素材" loading="lazy">`:icon('video')}${badge(p.status)}</div><div class="project-card-body"><h3><button class="table-name" data-project="${esc(p.id)}">${esc(p.name)}</button></h3><p>${projectEngineName(p)} · 🇧🇷 巴西站点 · ${esc(levels[p.options?.level] || '平衡复刻')}</p><p class="project-owner">制作人：${esc(p.owner_username)}</p><div class="project-card-footer"><span>${formatDate(p.created_at)}</span><button class="button ghost small" data-project="${esc(p.id)}">打开项目 ${icon('arrow')}</button></div></div></article>`;}).join('')}</div>`;
}
function settingsPage() {
  const tabs = `<div class="settings-tabs">${[['models','AI 模型'],['storage','对象存储'],['workspace','团队共享'],['word-recreate','词-复刻视频'],['system','运行状态']].map(t=>`<button data-settings="${t[0]}" class="${state.settingsTab===t[0]?'active':''}">${t[1]}</button>`).join('')}</div>`;
  let body;
  if(state.settingsTab==='models') body=`<div class="section-heading"><div><h2>团队模型配置 <span class="count">${state.models.length} 个模型</span></h2><p>连接官方 API 或兼容协议的中转服务，启用后团队成员即可选择。</p></div><button class="button primary" data-action="add-model">${icon('plus')} 添加模型</button></div>${state.models.length?`<div class="model-grid">${state.models.map(m=>`<article class="model-card"><div class="model-top"><div class="model-icon">${icon(m.kind==='video'?'video':m.kind==='image'?'image':'spark')}</div><div class="model-title"><h3>${esc(m.name)}</h3><small>${esc(kinds[m.kind]||m.kind)} · ${esc(protocols[m.protocol]||m.protocol)}</small></div><span class="badge ${m.enabled?'ready':'disabled'}">${m.enabled?'已启用':'已停用'}</span></div><div class="model-detail">${esc(m.model_id)}<br>${esc(m.base_url||'服务地址由管理员配置')}</div><div class="model-footer"><span>${m.api_key_set?'● API 密钥已配置':'○ 尚未配置密钥'}</span><button class="button small" data-edit-model="${esc(m.id)}">${icon('edit')} 编辑配置</button></div></article>`).join('')}</div>`:`<div class="panel">${empty('连接你的第一个 AI 模型','先添加视觉分析模型，再添加 Seedance 或万相视频模型。模型标识请以服务提供方实际开通的标识为准。','<button class="button small" data-action="add-model">添加模型 →</button>','spark')}</div>`}<div class="note" style="margin-top:20px">OpenAI / Anthropic 为协议适配，模型能力以服务商为准。Seedance 选择火山引擎协议，万相 3.0 选择阿里云百炼（万相视频），阿里云文件转写选择阿里云百炼（音频转写）；OpenAI Chat 兼容不代表视频或文件转写接口兼容。密钥仅保存在服务端。</div>`;
  else if(state.settingsTab==='storage') body=storageForm();
  else if(state.settingsTab==='workspace')body=workspaceForm();
  else if(state.settingsTab==='word-recreate')body=wordRecreateForm();
  else body=`<div class="panel"><div class="panel-head"><h2>服务运行状态</h2><button class="button small" data-action="refresh-health">${icon('refresh')} 刷新</button></div><div class="panel-body"><div class="system-grid"><div class="system-item"><b>数据库</b><p>${esc(typeof state.health?.database==='string'?state.health.database:state.health?.database?'已连接':'状态未知')}</p></div><div class="system-item"><b>FFmpeg</b><p>${state.health?.ffmpeg?'已就绪 · 支持视频处理与自动拼接':'未检测到 · 请在服务主机安装 FFmpeg'}</p></div></div><div class="note" style="margin-top:18px">其他电脑请通过“运行此服务的电脑局域网 IP + 端口”访问。127.0.0.1 仅供运行服务的本机使用。</div></div></div>`;
  return heading('为团队，配置创作能力','模型连接、素材存储和服务状态，由管理员统一管理。','','WORKSPACE SETTINGS')+tabs+body;
}
function updateWordInputs(form) {
  if(form?.dataset?.engine!=='hypit'||!form.elements.transcription_model_id)return;
  form.elements.transcription_model_id.required=form.elements.replicate_voice.checked&&form.elements.replicate_subtitles.checked;
}
function wordRecreateForm() {
  const w=state.wordRecreate;
  return `<form id="word-recreate-form" class="panel settings-storage"><div class="panel-head"><div><h2>词-复刻视频</h2><p>独立的 Hypit 视频工作流，可随时停用并保留历史作品。</p></div><button class="button small" type="button" data-action="refresh-word-runtime">${icon('refresh')} 检查引擎</button></div><div class="panel-body">${toggle('enabled','启用词-复刻视频','默认关闭；启用后，团队成员可从侧边栏创建项目。',!!w.enabled)}<div class="system-grid word-runtime"><div class="system-item"><b>引擎状态</b><p>${w.ready?'已就绪':w.installed?'已安装，尚未就绪':'尚未安装'}</p></div><div class="system-item"><b>固定版本</b><p>${esc(w.version||'未检测到')}</p></div></div>${w.reason?`<div class="note ${w.ready?'':'warning'}">${esc(w.reason)}</div>`:''}<div class="note" style="margin-top:18px">此功能复用已有视觉、图片和视频模型配置。口播与字幕同时开启时，还需要支持逐词时间戳的音频转写模型。生成、分析、转写及视觉检查均可能产生费用；检查引擎不调用收费模型。商品替换效果需用实际素材验证。</div><p class="form-help">停用后不再接受新的分析、生成或重试，正在运行的任务可停止；历史素材、工作流和成片仍可按现有权限查看、下载。安装与卸载由服务主机命令完成，网页不会自动安装依赖。</p><div class="button-row" style="margin-top:22px"><button class="button primary" type="submit">保存功能设置</button></div></div></form>`;
}
function workspaceForm() {
  return `<form id="workspace-form" class="panel settings-storage"><div class="panel-head"><div><h2>团队项目共享</h2><p>由管理员统一决定成员能否查看彼此的项目。</p></div>${icon('users')}</div><div class="panel-body">${toggle('share_projects','允许成员查看其他人的项目','默认关闭；开启后，成员可以查看、预览和下载所有人的项目及素材。',!!state.workspace.share_projects)}<div class="note" style="margin-top:20px">共享为只读：修改方案、上传素材、分析、生成、重试、停止任务仍由制作人或管理员操作。开关适用于已有和新建项目；关闭后成员恢复为只看自己的项目。模型密钥继续仅管理员管理。</div><div class="button-row" style="margin-top:22px"><button class="button primary" type="submit">保存共享设置</button></div></div></form>`;
}
function storageForm() { const s=state.storage;return `<form id="storage-form" class="panel settings-storage"><div class="panel-head"><div><h2>火山引擎 TOS 存储桶</h2><p>为需要公网素材链接的模型提供临时访问地址。</p></div>${icon('cloud')}</div><div class="panel-body">${toggle('enabled','启用 TOS 素材中转','原始素材与生成结果仍由工作台数据库保存。',!!s.enabled)}<div class="form-grid" style="margin-top:20px"><div class="field full"><label for="tos-endpoint">Endpoint</label><input id="tos-endpoint" name="endpoint" value="${esc(s.endpoint)}" placeholder="tos-cn-beijing.volces.com"><small>填写存储桶所在区域的 TOS Endpoint。</small></div><div class="field"><label for="tos-region">Region</label><input id="tos-region" name="region" value="${esc(s.region)}" placeholder="cn-beijing"></div><div class="field"><label for="tos-bucket">Bucket 名称</label><input id="tos-bucket" name="bucket" value="${esc(s.bucket)}" placeholder="你的存储桶名称"></div><div class="field full"><label for="tos-access-key">Access Key ID</label><input id="tos-access-key" name="access_key_id" value="${esc(s.access_key_id)}" autocomplete="off"></div><div class="field full"><label for="tos-secret">Secret Access Key</label><input id="tos-secret" name="secret_access_key" type="password" autocomplete="new-password" placeholder="${s.secret_set?'已配置，留空保留当前密钥':'请输入密钥'}"></div><div class="field"><label for="tos-ttl">临时链接有效期（秒）</label><input id="tos-ttl" name="url_ttl" type="number" min="3600" max="604800" value="${esc(s.url_ttl||86400)}"><small>应覆盖排队、生成与结果下载所需时间。</small></div></div><div class="note" style="margin-top:20px">建议使用私有存储桶，并为素材中转目录设置自动过期规则。跨云迁移时可更换数据库连接与存储适配配置。</div><div class="button-row" style="margin-top:22px"><button class="button primary" type="submit">保存存储配置</button></div></div></form>`; }
function usersPage() {return heading('一起，把内容做好','只有管理员可以创建账号。每位成员通过自己的账号使用工作台。','<button class="button primary" data-action="add-user">'+icon('plus')+' 创建用户</button>','TEAM MEMBERS')+`<div class="panel"><div class="table-wrap"><table class="table"><thead><tr><th>用户</th><th>角色</th><th>状态</th><th>账号管理</th></tr></thead><tbody>${state.users.map(u=>`<tr><td><span class="table-name">${esc(u.username)}</span>${u.id===state.user.id?'<span class="subline">当前账号</span>':''}</td><td>${u.role==='admin'?'管理员':'创作成员'}</td><td><span class="badge ${u.active?'ready':'disabled'}">${u.active?'正常':'已禁用'}</span></td><td><div class="button-row"><button class="button small" data-edit-user="${esc(u.id)}">管理账号</button></div></td></tr>`).join('')}</tbody></table></div></div>`; }
function identityText(value) { return typeof value==='string'?value:value?JSON.stringify(value,null,2):'识别结果将在视频分析后展示。'; }
const strategyNames = {direct:'直接生成',keyframe:'关键画面引导',adapt:'调整动作与构图',needs_reference:'需补素材'};
const visibilityNames = {full:'完整出现',partial:'局部特写',background:'背景出现',occluded:'遮挡中',absent:'未出现',uncertain:'待确认'};
const qualityNames = {pass:'抽样检查通过',issues:'发现问题',uncertain:'需要人工确认'};
const qualityCategories = {original_product:'原产品残留',mixed_identity:'产品特征混合',geometry:'结构或外观变化',action:'操作不匹配',text:'文字残留或错误',uncertain:'无法确认'};
const seconds = value => `${(Number(value)||0).toFixed(1)} 秒`;
const textList = (values, fallback='暂未提供') => arr(values).length ? arr(values).map(v=>esc(typeof v==='string'?v:JSON.stringify(v))).join('；') : fallback;
const projectBusy = p => activeStatuses.includes(p.status)||arr(p.jobs).some(j=>['queued','running'].includes(j.status));
function strategyOptions(selected='direct', allowMissing=true) {
  return Object.entries(strategyNames).filter(([key])=>allowMissing||key!=='needs_reference').map(([key,label])=>`<option value="${key}" ${key===selected?'selected':''} ${key==='keyframe'&&!state.project?.image_model_id?'disabled':''}>${label}${key==='keyframe'&&!state.project?.image_model_id?'（未配置图片模型）':''}</option>`).join('');
}
function productAnalysis(analysis) {
  const profile=analysis.product_profile||{}, shots=arr(analysis.shots);
  const missing=[...new Set(shots.flatMap(s=>arr(s.missing_views)))];
  return `<div class="identity-box"><strong>目标产品识别</strong><p>${esc(identityText(analysis.product_identity))}</p><p>产品一致性独立于复刻等级：整体、局部、背景和遮挡中的产品都应与目标素材一致。</p></div>
    ${analysis.product_profile?`<div class="profile-grid">${[['features','外观特征'],['parts','部件与附件'],['known_views','已知角度与状态'],['unknowns','尚不确定的细节'],['forbidden_traits','不得沿用的原产品特征']].map(([key,label])=>`<div class="profile-item"><strong>${label}</strong><p>${textList(profile[key])}</p></div>`).join('')}</div>`:'<p class="form-help">旧版分析暂无产品档案；尚未开始生成的项目可重新分析。</p>'}
    ${missing.length?`<div class="note warning" style="margin-top:16px"><strong>建议补充的真实素材</strong><p>${textList(missing)}</p><p>在下方「项目素材」补图后重新分析；也可以明确调整相应片段的动作或构图。AI 推测的结构不能代替真实产品资料。</p></div>`:''}
    ${analysis.sampling?`<p class="form-help">分析采用镜头变化与时间覆盖抽样${analysis.sampling.limited?'，本次抽样达到数量限制':''}，可能遗漏快速动作、短暂露出或遮挡中的细节。</p>`:''}
    ${shots.length?`<details class="shot-analysis" open><summary>镜头与产品出现情况 · ${shots.length} 个镜头</summary><div class="shots">${shots.map((shot,i)=>`<article class="shot"><div class="shot-title"><b>镜头 ${i+1} · ${esc(visibilityNames[shot.product_visibility]||'待确认')}</b><span>${seconds(shot.start)} — ${seconds(shot.end)}</span></div><p>${esc(shot.description)}</p><p><strong>可见部件：</strong>${textList(shot.visible_parts,'未记录')}</p><p><strong>操作与状态：</strong>${esc(shot.interaction||'未记录')}</p><p><strong>替换要求：</strong>${textList(shot.constraints,'遵循目标产品外观')}</p>${arr(shot.missing_views).length?`<p class="missing-reference"><strong>缺少素材：</strong>${textList(shot.missing_views)}</p>`:''}<p><strong>建议：</strong>${esc(strategyNames[shot.strategy]||'直接生成')}${shot.adaptation?' · '+esc(shot.adaptation):''}</p>${arr(shot.reference_image_indices).length?`<p><strong>关联产品图：</strong>${shot.reference_image_indices.map(n=>`第 ${Number(n)+1} 张`).join('、')}</p>`:''}</article>`).join('')}</div></details>`:''}`;
}
function planPanel(p, output) {
  const analysis=p.analysis;
  if(!analysis)return '';
  const segments=arr(analysis.segments), editable=canUseProject(p)&&!projectBusy(p)&&!output&&!arr(p.segments).length;
  return `<section class="panel"><${editable?'form id="plan-form"':'div'} class="panel-body"><div class="section-heading"><h2>视频理解与创作方案</h2>${badge(p.status)}</div><p class="analysis-summary">${esc(analysis.summary||'分镜方案已生成，请检查后开始制作。')}</p>${productAnalysis(analysis)}
    ${arr(analysis.risks).length?`<ul class="risk-list">${analysis.risks.map(r=>`<li>${esc(typeof r==='string'?r:JSON.stringify(r))}</li>`).join('')}</ul>`:''}
    <div class="divider"></div><h3 class="subsection-title">生成片段与替换策略</h3><p class="form-help">生成片段可能包含多个镜头。需补素材时先补图或明确改编；关键画面引导需要图片模型，先修正每段的一张代表画面再生成。关键画面与改编策略均不输入原视频，动作相似度可能降低。</p>
    <div class="shots">${segments.map((s,i)=>`<article class="shot"><div class="shot-title"><b>片段 ${i+1}</b><span>${seconds(s.start)} — ${seconds((Number(s.start)||0)+(Number(s.duration)||0))}</span></div>${arr(s.shot_indices).length?`<p>覆盖镜头：${s.shot_indices.map(n=>Number(n)+1).join('、')}</p>`:''}<div class="form-grid"><div class="field"><label for="strategy-${i}">替换策略</label><select id="strategy-${i}" name="strategy-${i}" ${editable?'':'disabled'}>${strategyOptions(s.strategy||'direct')}</select></div><div class="field"><label for="repair-${i}">补充替换要求（可选）</label><textarea id="repair-${i}" name="repair-${i}" rows="2" ${editable?'':'readonly'} placeholder="说明哪些局部、背景或操作需要特别处理">${esc(s.repair_prompt||'')}</textarea></div></div><div class="field"><label for="prompt-${i}">视频生成提示词</label><textarea id="prompt-${i}" name="prompt-${i}" rows="3" ${editable?'':'readonly'}>${esc(s.prompt)}</textarea></div><div class="form-grid" style="margin-top:12px"><div class="field"><label for="voice-${i}">葡语口播</label><textarea id="voice-${i}" name="voice-${i}" rows="2" ${editable?'':'readonly'}>${esc(s.voiceover||'')}</textarea></div><div class="field"><label for="subtitle-${i}">葡语字幕</label><textarea id="subtitle-${i}" name="subtitle-${i}" rows="2" ${editable?'':'readonly'}>${esc(s.subtitle||'')}</textarea></div></div>${s.risk?`<p><strong>风险提示：</strong>${esc(typeof s.risk==='string'?s.risk:JSON.stringify(s.risk))}</p>`:''}</article>`).join('')}</div>
    ${!segments.length?'<div class="note warning">当前方案未包含视频片段，请重新分析。</div>':''}
    <details class="advanced-editor"><summary>${editable?'高级编辑 · ':''}完整分析 JSON</summary><p class="form-help">${editable?'编辑 JSON 后保存将使用完整 JSON 内容；普通表单保存会保留产品档案与镜头结构。重新打开项目可放弃未保存修改。':'此处为已保存的完整分析内容，仅供查看。'}</p><textarea id="plan-json" aria-label="完整分析 JSON" ${editable?'':'readonly'}>${esc(JSON.stringify(analysis,null,2))}</textarea></details>${editable?'<div class="button-row" style="margin-top:20px"><button class="button" type="submit">保存分镜修改</button><button class="button ghost" type="button" data-action="analyze-project">重新分析素材</button></div><p class="form-help">保存方案不调用模型；重新分析素材会重新调用模型，产生分析费用。</p>':''}</${editable?'form':'div'}></section>`;
}
function qualityReport(quality, start=0) {
  if(!quality)return '<p class="form-help">尚无检查报告，可在所有片段生成后发起复查。</p>';
  const issues=arr(quality.issues);
  return `<div class="quality-report ${esc(quality.status)}"><strong>${esc(qualityNames[quality.status]||'待检查')}</strong><p>${esc(quality.summary||quality.keyframe_reason||'请结合视频人工核对。')}</p>${issues.length?`<ul class="quality-issues">${issues.map(issue=>`<li><span class="quality-severity ${esc(issue.severity)}">${issue.severity==='error'?'问题':'提示'}</span> <strong>${seconds(start+(Number(issue.time)||0))} · ${esc(qualityCategories[issue.category]||'待核对')}</strong><p>${esc(issue.description)}</p>${issue.suggestion?`<p>建议：${esc(issue.suggestion)}</p>`:''}</li>`).join('')}</ul>`:''}${arr(quality.sampled_times).length?`<p class="form-help">已检查全片时间：${quality.sampled_times.map(t=>seconds(start+(Number(t)||0))).join('、')}</p>`:''}</div>`;
}
function qualityPanel(p) {
  const records=arr(p.segments);if(!records.length)return '';
  const active=projectBusy(p), allReady=!!p.analysis&&records.length===arr(p.analysis.segments).length&&records.every(s=>s.asset_id);
  return `<section class="panel"><div class="panel-head"><div><h2>片段预览与产品一致性检查</h2><p>检查旧产品残留、混合外观、结构、操作与文字；时间点已换算为全片时间。</p></div>${canUseProject(p)&&allReady&&!active?'<button class="button small" data-action="review-project">'+icon('refresh')+' 重新检查</button>':''}</div><div class="panel-body"><div class="note">检查采用有限抽帧，不能保证所有画面无误，也不代替音轨与字幕人工验收。重新检查会调用视觉模型，不会重新生成视频。</div><div class="shots">${records.map(s=>{
    const index=Number(s.index)||0, plan=arr(p.analysis?.segments)[index]||{}, start=Number(plan.start)||0, attempts=Number(s.attempts)||0;
    const canRepair=!isWordProject(p)&&canUseProject(p)&&allReady&&!active&&attempts<3;
    const canChange=!isWordProject(p)&&canUseProject(p)&&!active&&attempts<3&&!s.asset_id&&(!s.remote_id||s.status==='failed')&&!['submitting','submitted'].includes(s.status);
    return `<article class="shot segment-result"><div class="shot-title"><b>片段 ${index+1} · ${esc(statusNames[s.status]||s.status)}</b><span>已提交 ${attempts} / 3 次</span></div>${s.asset_id?`<video controls preload="none" src="${assetUrl(s.asset_id)}" aria-label="片段 ${index+1} 预览"></video>`:''}${s.error?`<p class="note error">${esc(s.error)}</p>`:''}${qualityReport(s.quality,start)}${s.quality?.keyframe_asset_id?`<details class="version-history"><summary>查看关键画面参考</summary><a href="${assetUrl(s.quality.keyframe_asset_id)}" target="_blank" rel="noopener"><img class="keyframe-preview" src="${assetUrl(s.quality.keyframe_asset_id)}" alt="片段 ${index+1} 的关键画面参考" loading="lazy"></a></details>`:''}
      ${canRepair?`<button class="button small" data-regenerate-segment="${esc(s.id)}">${icon('refresh')} 仅重做此片段</button>`:s.asset_id&&attempts>=3?'<p class="form-help">此片段已达到 3 次视频生成提交上限，仍可复查和下载现有版本。</p>':''}
      ${canChange?`<button class="button small" data-strategy-segment="${esc(s.id)}">修改此片段策略</button>`:''}
      ${arr(s.history).length?`<details class="version-history"><summary>历史版本与任务 · ${s.history.length} 条</summary>${s.history.map((old,i)=>`<div class="version-item"><strong>${old.asset_id?'历史版本':'失败任务'} ${i+1}${old.attempts?' · 第 '+Number(old.attempts)+' 次生成':''}</strong>${old.asset_id?`<video controls preload="none" src="${assetUrl(old.asset_id)}" aria-label="片段 ${index+1} 历史版本 ${i+1}"></video><a href="${assetUrl(old.asset_id)}?download=1">下载此版本</a>${qualityReport(old.quality,start)}`:`${old.remote_id?`<p>任务 ID：${esc(old.remote_id)}</p>`:''}${old.error?`<p>${esc(old.error)}</p>`:''}`}</div>`).join('')}</details>`:''}</article>`;
  }).join('')}</div></div></section>`;
}
function projectAssets(p) {
  const assets=arr(p.assets).filter(a=>a.role!=='word_render_state'), canUpload=canUseProject(p)&&!projectBusy(p)&&!arr(p.segments).length&&['draft','ready','failed','needs_attention'].includes(p.status);
  return `<section class="panel" id="project-assets"><div class="panel-head"><div><h2>项目素材</h2><p>原图、参考片段、关键画面与历史结果均保存在本项目中。</p></div></div><div class="panel-body"><div class="asset-list">${assets.length?assets.map(a=>`<div class="asset-item">${icon(a.mime?.startsWith('image/')?'image':a.mime?.startsWith('video/')?'video':'file')}<a href="${assetUrl(a.id)}" target="_blank" rel="noopener">${esc(a.name||a.filename||'素材文件')}</a><small>${esc(({reference:'参考视频',product:'产品图片',output:'最终成片',segment:'视频片段',optimized_product:'优化图片',normalized_product:'规范化产品图',model_reference:'模型参考图',rejected_product:'未采纳的优化图',transcript:'语音转写',keyframe:'关键画面参考',rejected_keyframe:'未采纳的关键画面',analysis_raw:'分析原始结果',analysis_repair:'分析格式修复结果',asr_audio:'转写音频',asr_raw:'音频转写原始回复',word_asr_audio:'词复刻转写音频',word_asr_raw:'音频转写原始回复',word_workflow:'词复刻工作流归档',word_alignment:'字幕对齐记录',word_evidence:'词复刻合成记录'})[a.role]||a.role)} · ${fileSize(a.size)}</small></div>`).join(''):'<p class="form-help">尚未上传素材。</p>'}</div>${canUpload?`<form id="asset-form" class="form-grid" style="margin-top:20px"><div class="field"><label for="asset-role">补充素材</label><select name="role" id="asset-role"><option value="product">产品图片</option>${p.status==='draft'?'<option value="reference">参考视频</option>':''}</select></div><div class="field"><label for="asset-file">选择文件</label><input id="asset-file" name="file" type="file" required accept="${p.status==='draft'?'image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm':'image/jpeg,image/png,image/webp'}"></div><div class="field full"><p class="form-help">补图将清除旧分析方案，保留原始素材。上传后请重新分析；不会自动调用模型。</p><button class="button small" type="submit">${icon('upload')} 上传素材</button></div></form>`:''}</div></section>`;
}
function projectPage() {
  const p=state.project;if(!p)return '<div class="loading"><span class="spinner"></span>正在读取项目…</div>';
  const analysis=p.analysis, segments=arr(analysis?.segments), active=projectBusy(p), canGenerate=canUseProject(p)&&!!analysis&&p.status==='ready'&&!active;
  const output=p.output_asset_id||arr(p.assets).find(a=>['output','final'].includes(a.role))?.id;
  const hasReference=arr(p.assets).some(a=>a.role==='reference'), hasProduct=arr(p.assets).some(a=>a.role==='product');
  const model=state.models.find(m=>String(m.id)===String(p.video_model_id)), totalDuration=segments.reduce((sum,s)=>sum+(Number(s.duration)||0),0);
  const price=model?.price_per_second?segments.reduce((sum,s)=>sum+(Number(s.generation_duration)||Math.max(4,Math.ceil(s.duration))),0)*Number(model.price_per_second):null;
  const needsReferences=segments.some(s=>s.strategy==='needs_reference');
  const analysisFailed=!analysis&&!arr(p.segments).length&&['failed','needs_attention'].includes(p.status);
  let controls='<button class="button" data-nav="library">返回作品库</button>';
  if(!isWordProject(p)&&canUseProject(p)&&['draft','ready','failed','needs_attention'].includes(p.status)&&!active&&!arr(p.segments).some(s=>s.asset_id||!['pending','failed'].includes(s.status)))controls+='<button class="button" data-action="audio-options">调整音频设置</button>';
  if(canEditProject(p)&&active)controls+='<button class="button danger" data-action="cancel-project">停止任务</button>';
  else if(canUseProject(p)&&(p.status==='failed'||p.status==='needs_attention'))controls+=`<button class="button" data-action="retry-project">${icon('refresh')} 重试任务</button>`;
  if(canUseProject(p)&&analysisFailed&&!active)controls+='<button class="button small ghost" data-action="analyze-project">重新分析素材</button>';
  const current=p.status==='completed'?4:p.status==='reviewing'||p.status==='needs_review'||output?3:p.status==='generating'?2:analysis?1:0;
  return heading(esc(p.name),`${projectEngineName(p)} · 制作人：${esc(p.owner_username)} · 创建于 ${formatDate(p.created_at)} · 🇧🇷 巴西站点 · ${esc(levels[p.options?.level]||'平衡复刻')}`,`<div class="button-row">${controls}</div>`,'VIDEO PROJECT')+`${canEditProject(p)?'':'<div class="note readonly-notice">这是团队共享项目，仅可查看和下载。修改和制作由项目制作人或管理员操作。</div>'}${isWordProject(p)?`<div class="note word-intro">${wordAvailable()?`此项目由 Hypit 引擎合成。${p.options?.replicate_subtitles===false?'已关闭字幕，不执行字幕对齐。':p.options?.replicate_voice===false?'已关闭口播，字幕按分镜时间显示，不属于逐词口播对齐。':'字幕根据生成视频的实际口播对齐，识别内容与语言仍需人工验收。'}首版暂不支持生成后的单片段重做，请完整预览商品、声音和字幕。`:'词-复刻视频已停用或引擎未就绪。历史素材和成片仍可查看、下载，新的分析和制作暂不可用。'}</div>`:''}<div class="project-layout"><div class="stack">
    ${active?`<div class="work-status"><span class="spinner"></span>${p.status==='analyzing'?'正在识别产品、镜头与素材缺口。':p.status==='reviewing'?'正在抽帧检查产品一致性。':'正在生成片段、检查产品并合成视频。'}你可以离开此页面，任务会继续运行。</div>`:''}${p.error?`<div class="note error">${esc(p.error)}</div>`:''}
    <section class="panel"><div class="timeline">${['素材准备','确认方案','视频生成','一致性检查','成片预览'].map((v,i)=>`<div class="timeline-step ${i===current?'current':i<current?'done':''}"><span>${i<current?'✓':i+1}</span>${v}</div>`).join('')}</div>
    ${output?`<div class="panel-body">${p.status==='needs_review'?'<div class="note warning">成片已合成，但检查发现问题或有无法确认的部分。请查看下方报告，人工核对后决定是否局部重做。</div>':active?'<div class="note">下方保留上次合成的视频。新片段完成并重新合成后才会更新成片。</div>':'<p class="form-help">请完整预览产品细节、葡语文案和声音。抽样检查通过不代表所有画面都准确。</p>'}<div class="media-preview"><video controls preload="metadata" src="${assetUrl(output)}"></video></div><div class="button-row" style="margin-top:18px"><a class="button primary" href="${assetUrl(output)}?download=1">${icon('download')} ${p.status==='needs_review'?'下载待审核成片':'下载当前成片'}</a></div></div>`:!analysis?`<div class="panel-body">${empty(analysisFailed?'分析结果需要处理':'素材就绪后，开始拆解好创意',analysisFailed?'查看上方原因后，可继续处理已保存结果，或重新分析素材。':'AI 会建立产品档案，检查每个镜头中的局部、背景、操作与缺失素材。',canUseProject(p)?`<button class="button primary" data-action="${analysisFailed?'retry-project':'analyze-project'}" ${active||!hasReference||!hasProduct?'disabled':''}>${icon(analysisFailed?'refresh':'spark')} ${active?'处理中':analysisFailed?'重试任务':'分析参考视频'}</button>`:'','spark')}${analysisFailed?'<p class="form-help">重试任务优先使用已保存的模型返回结果，本地格式修复不调用模型；必要时最多调用一次文本格式修复，可能产生费用。重新分析素材会重新调用模型，产生分析费用。</p>':''}${!hasReference||!hasProduct?'<div class="note warning">还需上传参考视频与至少一张产品图。</div>':''}</div>`:'<div class="panel-body"><p class="form-help">先确认下方产品档案、镜头分析和每段替换策略，再开始生成。</p></div>'}</section>
    ${qualityPanel(p)}${planPanel(p,output)}${projectAssets(p)}
    </div><aside class="stack"><section class="panel"><div class="panel-head"><h2>创作状态</h2>${badge(p.status)}</div><div class="panel-body"><div class="metric-list"><div class="metric-row"><span>目标语言</span><strong>巴西葡萄牙语</strong></div><div class="metric-row"><span>画面规格</span><strong>${esc(p.options?.ratio||'9:16')} · ${esc(p.options?.resolution||'720p')}</strong></div><div class="metric-row"><span>复刻等级</span><strong>${esc(levels[p.options?.level]||'平衡复刻')}</strong></div><div class="metric-row"><span>生成片段</span><strong>${segments.length?`${segments.length} 段 · ${seconds(totalDuration)}`:'等待分析'}</strong></div>${['music','voice','subtitles'].map((k,i)=>`<div class="metric-row"><span>${['背景音乐','口播','字幕'][i]}</span><strong>${p.options?.['replicate_'+k]===false?'不复刻':'复刻'}</strong></div>`).join('')}</div>
    ${canGenerate?`<div class="divider"></div><div class="metric-row"><span>视频生成费用估算</span><strong>${price!==null?'约 '+price.toFixed(2)+'（配置币种）':'未配置单价'}</strong></div><p class="form-help">${isWordProject(p)?'另有视觉检查、可能的图片编辑及实际口播转写费用':'另有视觉检查与可能的图片编辑费用'}，实际以服务商账单为准。开始前请保存方案。</p>${needsReferences?'<div class="note warning">部分片段需要补图。请补充素材后重新分析，或在方案中调整策略并保存。</div>':''}<button class="button primary" style="width:100%;margin-top:10px" data-action="generate-project" ${!segments.length?'disabled':''}>${icon('play')} 开始生成视频</button>`:''}
    ${totalDuration>15?`<div class="note" style="margin-top:16px">${isWordProject(p)?'按片段生成，完成后由 Hypit 合成字幕并输出长视频。':'按片段生成，完成后由 FFmpeg 统一规格并拼接。只重做有问题的片段可保留其余结果。'}</div>`:''}</div></section>${remoteTasksPanel(p)}${arr(p.jobs).length?`<section class="panel"><div class="panel-head"><h2>任务记录</h2></div><div class="panel-body job-list">${p.jobs.slice(-8).reverse().map(j=>`<div class="job-row"><strong>${esc(({analyze:'分析分镜',generate:'生成视频',review:'一致性复查',regenerate:'局部重做',word_analyze:'词复刻分析分镜',word_generate:'词复刻生成与合成',word_review:'词复刻一致性复查'})[j.action]||'处理任务')} · ${esc(statusNames[j.status]||j.status)}</strong>${esc(j.message||j.error||formatDate(j.created_at))}</div>`).join('')}</div></section>`:''}</aside></div>`;
}
function repairModal(id, saveOnly=false) {
  if(!requireProjectUse()||isWordProject(state.project))return;
  const p=state.project,s=arr(p.segments).find(item=>item.id===id);if(!s)return;
  const plan=arr(p.analysis?.segments)[Number(s.index)]||{}, attempts=Number(s.attempts)||0;
  const guidance=arr(s.quality?.issues).map(issue=>[issue.description,issue.suggestion].filter(Boolean).join('；')).join('\n');
  showModal(saveOnly?'修改片段替换策略':`仅重做片段 ${Number(s.index)+1}`,`<form id="segment-repair-form" data-id="${esc(id)}" data-save-only="${saveOnly}"><div class="note ${saveOnly?'':'warning'}">${saveOnly?'只保存策略，不调用模型。保存后点击「重试任务」继续；重试可能产生费用。':'将重新调用视频模型，并可能调用图片编辑与视觉检查模型，产生额外费用。其他片段会保留，上次成片保留至重新合成完成。'}</div><p class="form-help">已提交视频生成 ${attempts} 次，每个片段最多提交 3 次（包含首次生成）。检查不通过时不会自动重做。</p><div class="field"><label for="repair-strategy">本次替换方式</label><select id="repair-strategy" name="strategy">${strategyOptions(plan.strategy==='needs_reference'?'adapt':plan.strategy||'direct',false)}</select></div><div class="field" style="margin-top:16px"><label for="repair-prompt">具体修复要求</label><textarea id="repair-prompt" name="repair_prompt" required maxlength="6000" rows="5" placeholder="指出需要修正的部位、时间点或操作，避免仅填写‘重新生成’">${esc(plan.repair_prompt||guidance)}</textarea><small>关键画面引导先修正一张代表画面，需图片模型；此策略与改编策略均不输入原视频，不能保证完整动作还原。请说明希望怎样调整。</small></div><div class="form-error" id="modal-error" role="alert"></div><div class="modal-actions"><button class="button" type="button" data-action="close-modal">取消</button><button class="button primary" type="submit">${saveOnly?'仅保存策略':'确认付费重做此片段'}</button></div></form>`);
}
function reviewModal() {
  if(!requireProjectUse())return;
  showModal('重新检查产品一致性','<form id="review-form"><p class="form-help">检查所有现有片段，会产生视觉模型调用费用，不会重新生成视频。报告采用有限抽帧，仍需人工完整预览。</p><div class="form-error" id="modal-error" role="alert"></div><div class="modal-actions"><button class="button" type="button" data-action="close-modal">取消</button><button class="button primary" type="submit">开始复查</button></div></form>');
}

function render() {
  if(!state.user)return renderAuth();
  const pages={dashboard,create:createPage,'word-create':()=>createPage(true),library:libraryPage,settings:settingsPage,users:usersPage,project:projectPage,images:()=>heading('让好产品，拥有好画面','图片制作模块即将加入你的创作空间。','','IMAGE STUDIO')+`<div class="panel disabled-panel">${empty('图片制作，正在准备中','这里将支持产品主图、场景图与巴西葡语营销图片。现在可以先从视频复刻开始。',newButton(),'image')}</div>`};
  renderShell((pages[state.view]||dashboard)());
}
async function navigate(view,id) {
  stopPolling();state.view=view;
  if(!state.user)return renderAuth();
  if(['settings','users'].includes(view)&&!admin()){state.view='dashboard';return render();}
  renderShell('<div class="loading"><span class="spinner"></span>正在加载…</div>');
  try {
    if(view==='project'){const [project,word]=await Promise.all([api(`/api/projects/${encodeURIComponent(id)}`),api('/api/settings/word-recreate').catch(()=>({enabled:false,ready:false}))]);state.project=project;state.wordRecreate=word;}
    else if(view==='users')state.users=normalizeList(await api('/api/users'),'users');
    else if(view==='settings'){state.models=normalizeList(await api('/api/models'),'models');if(state.settingsTab==='storage')state.storage=await api('/api/settings/storage');if(state.settingsTab==='workspace')state.workspace=await api('/api/settings/workspace');if(state.settingsTab==='system')state.health=await api('/api/health');if(state.settingsTab==='word-recreate')state.wordRecreate=await api('/api/settings/word-recreate/runtime');}
    else if(view==='dashboard'||view==='library')await loadBase();
    else if(view==='create'||view==='word-create'){state.models=normalizeList(await api('/api/models'),'models');state.wordRecreate=await api('/api/settings/word-recreate').catch(()=>({enabled:false,ready:false}));}
    render();window.scrollTo({top:0});startPolling();
  }catch(error){if(view==='project'&&error.status===404&&state.user){await projectUnavailable();return;}toast(errorText(error),true);if(state.user){renderShell(`<div class="panel">${empty('页面加载失败',esc(errorText(error)),`<button class="button" data-nav="dashboard">返回工作台</button>`,'refresh')}</div>`);}}
}
async function projectUnavailable(){closeModal();state.project=null;state.projects=[];toast('项目已不可访问，可能已删除或管理员已关闭团队共享。',true);await navigate('library');}
function stopPolling(){if(state.poll)clearTimeout(state.poll);state.poll=null;}
function startPolling(){stopPolling();if(!state.user)return;const hasActive=state.view==='project'?activeStatuses.includes(state.project?.status):['dashboard','library'].includes(state.view)&&state.projects.some(p=>activeStatuses.includes(p.status));const shared=state.view==='project'?state.project&&!canEditProject(state.project):['dashboard','library'].includes(state.view)&&state.workspace.share_projects;if(hasActive||shared)state.poll=setTimeout(poll,hasActive?5000:15000);}
async function poll(){
  if(state.polling)return;state.polling=true;const view=state.view;
  try{
    if(view==='project'){
      const id=state.project?.id,updated=await api(`/api/projects/${encodeURIComponent(id)}`);
      if(state.view===view&&state.project?.id===id){const oldStatus=state.project.status;state.project=updated;render();if(oldStatus!==updated.status&&!activeStatuses.includes(updated.status))toast(updated.status==='completed'?'视频已生成，快来预览你的作品。':'任务状态已更新，请查看项目。');}
    }else if(['dashboard','library'].includes(view)){
      const workspace=await api('/api/settings/workspace');
      if(state.view!==view)return;
      state.workspace=workspace;
      if(!workspace.share_projects){state.libraryScope='all';state.projects=state.projects.filter(p=>String(p.owner_id)===String(state.user?.id));render();}
      const scope=state.libraryScope,projects=await loadProjects(view==='library'&&scope==='mine');
      if(state.view===view&&state.libraryScope===scope){state.projects=projects;render();}
    }
  }catch(error){if(view==='project'&&error.status===404&&state.user)await projectUnavailable();else toast(errorText(error),true);}
  finally{state.polling=false;startPolling();}
}
function closeModal(){$('#modal-root').innerHTML='';}
function remoteTasksPanel(p) {
  const records=arr(p.segments),transcriptions=arr(p.assets).filter(a=>['asr_raw','word_asr_raw'].includes(a.role)&&a.meta?.protocol==='dashscope_asr');
  if(!records.length&&!transcriptions.length)return '';
  const asrRows=transcriptions.map(a=>{
    const meta=a.meta,generated=meta.purpose==='generated',unconfirmed=['submitting','uncertain'].includes(meta.state)&&!meta.remote_id;
    const code=meta.error_code==='SUCCESS_WITH_NO_VALID_FRAGMENT'?meta.error_code:'';
    const speechHelp=meta.state==='no_speech'?(generated?'成片需要有效的实际口播和词级时间戳才能合成字幕；已生成片段会保留，不会编造字幕时间。':'可继续根据产品事实和参考画面重写新口播，无法还原原口播。'):'';
    return `<div class="job-row"><strong>${generated?'成片口播转写':'参考视频转写'} · ${esc(meta.state==='uncertain'?'提交结果未确认':statusNames[meta.state]||meta.state||'待处理')}</strong>${meta.remote_id?`<small>任务 ID：${esc(meta.remote_id)}</small>`:''}${meta.error?`<p class="form-help">${esc(meta.error)}</p>`:''}${code?`<small>错误码：${esc(code)}</small>`:''}${speechHelp?`<p class="form-help">${speechHelp}</p>`:''}${unconfirmed?(admin()&&canEditProject(p)?`<button class="button small" data-resolve-transcription="${esc(a.id)}">关联转写任务 ID</button>`:'<p>请管理员核对转写任务，避免重复计费。</p>'):''}</div>`;
  }).join('');
  return `<section class="panel"><div class="panel-head"><h2>${transcriptions.length?'模型任务':'分段任务'}</h2></div><div class="panel-body job-list">${records.map(s=>`<div class="job-row"><strong>片段 ${Number(s.index)+1} · ${esc(statusNames[s.status]||s.status)}</strong>${s.remote_id?`<small>任务 ID：${esc(s.remote_id)}</small>`:''}${s.asset_id?`<a href="${assetUrl(s.asset_id)}" target="_blank" rel="noopener">预览片段</a>`:''}${s.status==='submitting'&&!s.remote_id?(admin()&&canEditProject(p)?`<button class="button small" data-resolve-segment="${esc(s.id)}">关联供应商任务 ID</button>`:'<p>请管理员核对供应商任务，避免重复计费。</p>'):''}</div>`).join('')}${asrRows}</div></section>`;
}
function audioOptionsModal(){
  if(!requireProjectUse()||isWordProject(state.project))return;
  const o=state.project.options||{};
  showModal('调整本项目音频',`<form id="audio-options-form"><p class="form-help">只保存设置，不会提交生成。适用于尚无成功片段的项目。保存后再点击重试。</p><div class="button-row"><button type="button" class="button small" data-action="audio-original-voice">仅原创口播</button><button type="button" class="button small" data-action="audio-silent">先生成无声版</button></div><div class="divider"></div>${toggle('replicate_music','生成背景音乐','创作新的配乐，不复用原曲旋律或歌词。',o.replicate_music!==false)}${toggle('replicate_voice','生成巴西葡语口播','使用分镜台词与新旁白音色；请先确认台词内容。',o.replicate_voice!==false)}${toggle('reference_audio','将原片音轨作为参考输入','关闭后，上传的参考视频会移除音轨，仍保留画面。',o.reference_audio!==false)}<div class="note">如果收到音频版权错误，可先测试仅原创口播（关闭背景音乐和原片音轨），或无声版。调整不保证供应商接受，保存不会产生新的生成费用。</div><div class="form-error" id="modal-error" role="alert"></div><div class="modal-actions"><button type="button" class="button" data-action="close-modal">取消</button><button type="submit" class="button primary">保存音频设置</button></div></form>`);
}
function showModal(title,body){$('#modal-root').innerHTML=`<div class="modal-backdrop"><section class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}"><div class="modal-head"><h2>${esc(title)}</h2><button class="icon-button" data-action="close-modal" aria-label="关闭">${icon('close')}</button></div><div class="modal-body">${body}</div></section></div>`;setTimeout(()=>$('#modal-root input')?.focus(),20);}
function modelProtocolHelp(protocol) {
  if(protocol==='dashscope')return {base:'示例：https://你的业务空间ID.cn-beijing.maas.aliyuncs.com/api/v1；替换真实空间ID，密钥和模型须同地域，不包含具体操作路径。',model:'填写 wan3.0-video 或 wan3.0-video-prime；用途选择视频生成。'};
  if(protocol==='dashscope_asr')return {base:'填写阿里云控制台提供的 /api/v1 基础地址，例如 https://dashscope.aliyuncs.com/api/v1；密钥与模型须同地域，不使用 compatible-mode/v1。',model:'填写 qwen3-asr-flash-filetrans 或其已开通的日期版本；用途选择音频转写。支持葡萄牙语与逐词时间戳，需要已启用的 TOS 提供临时音频链接。'};
  if(protocol==='volcengine')return {base:'示例：https://ark.cn-beijing.volces.com/api/v3；不包含最终操作路径。',model:'Seedance 模型标识以火山引擎控制台实际开通的标识为准。'};
  return {base:'填写服务商提供的 API 基础地址及版本路径，不包含最终操作路径。',model:'填写服务商实际开通的模型标识；视频模型需要对应的专用协议。'};
}
function protocolSupportsKind(protocol,kind) {
  return ({vision:['openai','anthropic','volcengine'],image:['openai','volcengine'],video:['volcengine','dashscope'],transcription:['openai','dashscope_asr']})[kind]?.includes(protocol)===true;
}
function updateProtocolOptions(form) {
  for(const option of Array.from(form.elements.protocol.options||[]))option.disabled=!protocolSupportsKind(option.value,form.elements.kind.value);
}
function suggestModelId(form,protocol) {
  if(form.dataset?.id)return;
  const value=form.elements.model_id.value;
  if(value&&!/^wan3\.0-video(?:-prime)?$|^qwen3-asr-flash-filetrans(?:-\d{4}-\d{2}-\d{2})?$|seedance/i.test(value))return;
  if(protocol==='dashscope_asr')form.elements.model_id.value='qwen3-asr-flash-filetrans';
  else if(protocol==='dashscope')form.elements.model_id.value='wan3.0-video';
}
function updateModelKind(form) {
  if(!form)return;
  const kind=form.elements.kind.value,protocol=form.elements.protocol.value;
  if(!protocolSupportsKind(protocol,kind)){
    form.elements.protocol.value=kind==='transcription'&&protocol==='dashscope'?'dashscope_asr':kind==='video'&&protocol==='dashscope_asr'?'dashscope':kind==='video'?'volcengine':'openai';
    suggestModelId(form,form.elements.protocol.value);
  }
  updateModelProtocol(form);
}
function updateModelProtocol(form, changed=false) {
  if(!form)return;
  const protocol=form.elements.protocol.value,help=modelProtocolHelp(protocol);
  if($('#model-base-help'))$('#model-base-help').textContent=help.base;
  if($('#model-id-help'))$('#model-id-help').textContent=help.model;
  if(changed){
    if(protocol==='dashscope')form.elements.kind.value='video';
    if(protocol==='dashscope_asr')form.elements.kind.value='transcription';
    suggestModelId(form,protocol);
  }
  updateProtocolOptions(form);
}
function modelModal(id){const m=state.models.find(x=>String(x.id)===String(id))||{};showModal(m.id?'编辑模型配置':'添加 AI 模型',`<form id="model-form" data-id="${esc(m.id||'')}"><div class="form-grid"><div class="field full"><label for="model-name">显示名称</label><input id="model-name" name="name" required maxlength="100" value="${esc(m.name)}" placeholder="例如：万相 3.0 视频生成"></div><div class="field"><label for="model-kind">模型用途</label><select id="model-kind" name="kind">${Object.entries(kinds).map(([k,v])=>`<option value="${k}" ${m.kind===k?'selected':''}>${v}</option>`).join('')}</select></div><div class="field"><label for="model-protocol">接口协议</label><select id="model-protocol" name="protocol">${Object.entries(protocols).map(([k,v])=>`<option value="${k}" ${m.protocol===k?'selected':''} ${protocolSupportsKind(k,m.kind||'vision')?'':'disabled'}>${v}</option>`).join('')}</select></div><div class="field full"><label for="model-base">API Base URL</label><input id="model-base" name="base_url" type="url" required value="${esc(m.base_url)}" placeholder="https://你的服务地址/v1"><small id="model-base-help">${esc(modelProtocolHelp(m.protocol).base)}</small></div><div class="field full"><label for="model-id">模型 ID / 推理接入点</label><input id="model-id" name="model_id" required value="${esc(m.model_id)}" placeholder="填写服务商实际开通的模型标识"><small id="model-id-help">${esc(modelProtocolHelp(m.protocol).model)}</small></div><div class="field full"><label for="model-key">API Key</label><input id="model-key" name="api_key" type="password" autocomplete="new-password" ${m.api_key_set?'':'required'} placeholder="${m.api_key_set?'已配置，留空保留当前密钥':'请输入 API 密钥'}"></div><div class="field"><label for="model-duration">单片段最长时长（秒）</label><input id="model-duration" name="max_duration" type="number" min="4" max="15" value="${esc(m.max_duration||15)}"><small>本项目每段 4–15 秒，长视频自动分段拼接。</small></div><div class="field"><label for="model-price">每秒参考单价</label><input id="model-price" name="price_per_second" type="number" min="0" step="0.0001" value="${esc(m.price_per_second||0)}"><small>0 表示暂不估算。</small></div><div class="field full">${toggle('enabled','启用模型','启用后，成员可在创作页面选择。',m.enabled!==false)}</div></div>${m.id&&admin()?'<p class="form-help">已被项目引用的模型不能删除，可通过启用开关停用。</p>':''}<div class="form-error" id="modal-error" role="alert"></div><div class="modal-actions">${m.id&&admin()?`<button class="button danger" type="button" data-delete-model="${esc(m.id)}">删除模型</button>`:''}<button class="button" type="button" data-action="close-modal">取消</button><button class="button primary" type="submit">保存模型</button></div></form>`);}
function userModal(id){const u=state.users.find(x=>String(x.id)===String(id))||{};showModal(u.id?'管理用户':'创建团队用户',`<form id="user-form" data-id="${esc(u.id||'')}"><div class="form-grid"><div class="field full"><label for="user-name">用户名</label><input id="user-name" name="username" required value="${esc(u.username)}" ${u.id?'readonly':''} autocomplete="off"></div><div class="field full"><label for="user-password">${u.id?'重置密码':'初始密码'}</label><input id="user-password" name="password" type="password" ${u.id?'':'required'} autocomplete="new-password" placeholder="${u.id?'留空则不修改密码':'请输入密码（不能为空）'}"></div><div class="field full"><label for="user-role">用户角色</label><select id="user-role" name="role"><option value="user" ${u.role!=='admin'?'selected':''}>创作成员</option><option value="admin" ${u.role==='admin'?'selected':''}>管理员</option></select></div>${u.id?`<div class="field full">${toggle('active','账号启用','停用后该用户无法继续访问工作台。',!!u.active)}</div>`:''}</div><div class="form-error" id="modal-error" role="alert"></div><div class="modal-actions"><button class="button" type="button" data-action="close-modal">取消</button><button class="button primary" type="submit">${u.id?'保存修改':'创建用户'}</button></div></form>`);}
async function withBusy(element,fn){if(state.busy)return;state.busy=true;const text=element?.innerHTML;if(element){element.disabled=true;element.setAttribute('aria-busy','true');}try{await fn();}catch(error){const errorEl=$('#modal-error')||$('#auth-error');if(errorEl)errorEl.textContent=errorText(error);else toast(errorText(error),true);}finally{state.busy=false;if(element?.isConnected){element.disabled=false;element.removeAttribute('aria-busy');if(text)element.innerHTML=text;}}}
function formDataObject(form){return Object.fromEntries(new FormData(form));}
async function projectAction(action){const p=state.project;if(!p||!(action==='cancel'?requireProjectEdit():requireProjectUse()))return;await api(projectActionPath(p,action),{method:'POST'});state.project=await api(`/api/projects/${encodeURIComponent(p.id)}`);render();startPolling();toast(action==='cancel'?'已请求停止任务。':action==='generate'?'生成任务已提交。':action==='analyze'?'分析任务已提交。':action==='review'?'一致性复查已提交，不会重新生成视频。':'重试任务已提交。');}
document.addEventListener('click',event=>{
  const button=event.target.closest('button,[data-project]');if(!button)return;
  if(button.hasAttribute?.('data-word-settings')){state.settingsTab='word-recreate';navigate('settings');return;}
  if(button.dataset.nav){navigate(button.dataset.nav);return;}
  if(button.dataset.project){navigate('project',button.dataset.project);return;}
  if(button.dataset.scope){withBusy(button,async()=>{state.libraryScope=button.dataset.scope==='mine'?'mine':'all';state.projects=[];await navigate('library');});return;}
  if(button.dataset.filter){state.libraryFilter=button.dataset.filter;render();return;}
  if(button.dataset.settings){state.settingsTab=button.dataset.settings;navigate('settings');return;}
  if(button.dataset.editModel){modelModal(button.dataset.editModel);return;}
  if(button.dataset.editUser){userModal(button.dataset.editUser);return;}
  if(button.dataset.regenerateSegment){repairModal(button.dataset.regenerateSegment);return;}
  if(button.dataset.strategySegment){repairModal(button.dataset.strategySegment,true);return;}
  if(button.dataset.resolveSegment){if(!requireProjectEdit())return;showModal('关联供应商任务',`<form id="resolve-form" data-id="${esc(button.dataset.resolveSegment)}"><p class="form-help">先在供应商控制台按提交时间和素材核对任务，再填写其任务 ID。保存后点击重试将继续查询已有任务。</p><div class="field"><label for="remote-task-id">任务 ID</label><input id="remote-task-id" name="remote_id" required maxlength="200" pattern="[A-Za-z0-9_-]+"></div><div class="form-error" id="modal-error"></div><div class="modal-actions"><button class="button primary" type="submit">保存关联</button></div></form>`);return;}
  if(button.dataset.resolveTranscription){if(!admin()||!requireProjectEdit())return;showModal('关联阿里云转写任务',`<form id="asr-resolve-form" data-id="${esc(button.dataset.resolveTranscription)}"><p class="form-help">请先按提交时间和音频在百炼控制台核对任务，再填写已确认的任务 ID。保存只关联记录，不调用模型；随后点击项目重试，继续查询该任务。</p><div class="field"><label for="asr-task-id">转写任务 ID</label><input id="asr-task-id" name="remote_id" required maxlength="200" pattern="[A-Za-z0-9_-]+"></div><div class="form-error" id="modal-error"></div><div class="modal-actions"><button class="button primary" type="submit">保存关联</button></div></form>`);return;}
  if(button.dataset.deleteModel){if(!admin())return;withBusy(button,async()=>{if((await api('/api/health'))?.model_deletion!==true)throw new Error('服务尚未更新，请管理员重启服务后刷新页面，再删除模型。');await api(`/api/models/${encodeURIComponent(button.dataset.deleteModel)}`,{method:'DELETE'});closeModal();toast('模型已删除。');await navigate('settings');});return;}
  const action=button.dataset.action;if(!action)return;
  if(['analyze-project','generate-project','retry-project','cancel-project','review-project','audio-options','audio-original-voice','audio-silent'].includes(action)&&!requireProjectEdit())return;
  if(action==='menu'){$('.shell').classList.toggle('nav-open');return;}
  if(action==='close-modal'){closeModal();return;}
  if(action==='add-model'){modelModal();return;}
  if(action==='add-user'){userModal();return;}
  if(action==='audio-options'){audioOptionsModal();return;}
  if(action==='review-project'){reviewModal();return;}
  if(action==='audio-original-voice'||action==='audio-silent'){const form=$('#audio-options-form');form.elements.replicate_music.checked=false;form.elements.reference_audio.checked=false;form.elements.replicate_voice.checked=action==='audio-original-voice';return;}
  withBusy(button,async()=>{
    if(action==='logout'){await api('/api/auth/logout',{method:'POST'});state.user=null;state.csrf='';resetWorkspace();stopPolling();renderAuth();}
    if(action==='refresh-word-runtime'){state.wordRecreate=await api('/api/settings/word-recreate/runtime');render();toast('引擎状态已更新，未调用收费模型。');}
    if(action==='refresh-health'){state.health=await api('/api/health');render();toast('运行状态已刷新。');}
    if(action==='analyze-project')await projectAction('analyze');
    if(action==='generate-project'){if($('#plan-json')?.dataset.dirty==='true'||$('#plan-form')?.dataset.dirty==='true'){toast('请先保存分镜修改，再开始生成。',true);return;}if(arr(state.project.analysis?.segments).some(s=>s.strategy==='needs_reference')){toast('有片段需要补充素材。请在项目素材中补图并重新分析，或调整替换策略后保存。',true);$('#project-assets')?.scrollIntoView({behavior:'smooth'});return;}if(arr(state.project.analysis?.segments).some(s=>s.strategy==='keyframe')&&!state.project.image_model_id)throw new Error('关键画面引导需要图片模型，请先改用直接生成或调整动作与构图。');await projectAction('generate');}
    if(action==='retry-project')await projectAction('retry');
    if(action==='cancel-project')await projectAction('cancel');
  });
});
document.addEventListener('change',event=>{const input=event.target;if(input.form?.dataset?.engine==='hypit')updateWordInputs(input.form);if(input.id==='model-protocol')updateModelProtocol(input.form,true);if(input.id==='model-kind')updateModelKind(input.form);if(input.closest('#plan-form'))$('#plan-form').dataset.dirty='true';if(input.type==='file'&&input.closest('#create-form')){const box=$(`[data-files="${input.name}"]`);if(box)box.textContent=[...input.files].map(f=>`${f.name} · ${fileSize(f.size)}`).join(' / ');}});
document.addEventListener('input',event=>{if(event.target.id==='plan-json')event.target.dataset.dirty='true';if(event.target.closest('#plan-form'))$('#plan-form').dataset.dirty='true';if(event.target.id==='library-search'){state.search=event.target.value;$('#library-results').innerHTML=libraryResults(filteredProjects());}});
document.addEventListener('keydown',event=>{if(event.key==='Escape')closeModal();if(event.key==='Tab'&&$('#modal-root .modal')){const items=[...$('#modal-root .modal').querySelectorAll('button:not(:disabled),input:not(:disabled),select,textarea,[tabindex="0"]')];const first=items[0],last=items[items.length-1];if(event.shiftKey&&document.activeElement===first){last?.focus();event.preventDefault();}else if(!event.shiftKey&&document.activeElement===last){first?.focus();event.preventDefault();}}});
document.addEventListener('submit',event=>{
  const form=event.target;if(!form.id)return;event.preventDefault();const submit=form.querySelector('[type="submit"]');
  if(['review-form','segment-repair-form','audio-options-form','asset-form','plan-form'].includes(form.id)&&!requireProjectUse())return;
  if(form.id==='resolve-form'&&!requireProjectEdit())return;
  if(form.id==='asr-resolve-form'&&(!admin()||!requireProjectEdit()))return;
  withBusy(submit,async()=>{
    const data=formDataObject(form);
    if(form.id==='review-form'){closeModal();await projectAction('review');}
    if(form.id==='segment-repair-form'){
      if(!data.repair_prompt?.trim())throw new Error('请填写具体修复要求。');
      if(data.strategy==='keyframe'&&!state.project.image_model_id)throw new Error('此项目没有配置图片模型，请选择其他策略。');
      const saveOnly=form.dataset.saveOnly==='true';
      await api(`/api/segments/${encodeURIComponent(form.dataset.id)}/${saveOnly?'strategy':'regenerate'}`,{method:'POST',body:{strategy:data.strategy,repair_prompt:data.repair_prompt}});
      closeModal();await navigate('project',state.project.id);toast(saveOnly?'策略已保存，尚未调用模型。可点击重试继续。':'此片段的重做任务已提交，其他片段保留。');
    }
    if(form.id==='audio-options-form'){state.project=await api(`/api/projects/${encodeURIComponent(state.project.id)}/audio-options`,{method:'PATCH',body:{replicate_music:form.elements.replicate_music.checked,replicate_voice:form.elements.replicate_voice.checked,reference_audio:form.elements.reference_audio.checked}});closeModal();render();toast('音频设置已保存，尚未提交生成。');}
    if(form.id==='resolve-form'){await api(`/api/segments/${encodeURIComponent(form.dataset.id)}/resolve`,{method:'POST',body:{remote_id:data.remote_id}});closeModal();toast('任务已关联，可点击重试继续处理。');await navigate('project',state.project.id);}
    if(form.id==='asr-resolve-form'){await api(`/api/transcriptions/${encodeURIComponent(form.dataset.id)}/resolve`,{method:'POST',body:{remote_id:data.remote_id}});closeModal();toast('转写任务已关联，可点击重试继续查询。');await navigate('project',state.project.id);}
    if(form.id==='auth-form'){
      $('#auth-error').textContent='';if(!state.initialized){await api('/api/bootstrap',{method:'POST',body:data});state.initialized=true;}
      const result=await api('/api/auth/login',{method:'POST',body:{username:data.username,password:data.password}});resetWorkspace();state.user=result.user;state.csrf=result.csrf_token;state.view='dashboard';await loadBase();render();startPolling();
    }
    if(form.id==='create-form'){
      const word=form.dataset?.engine==='hypit';if(word&&!wordAvailable())throw new Error('词-复刻视频尚未启用或引擎未就绪。');
      if(word&&form.elements.replicate_voice.checked&&form.elements.replicate_subtitles.checked&&!data.transcription_model_id)throw new Error('口播与字幕同时开启时，请选择支持逐词时间戳的音频转写模型。');
      const reference=form.elements.reference.files[0];const products=[...form.elements.products.files];if(!reference||!products.length)throw new Error('请上传参考视频与至少一张产品图片。');
      const progress=$('#upload-progress');progress.textContent='正在创建项目…';
      const modelId=name=>data[name]||null;
      const p=await api(word?'/api/word-recreate/projects':'/api/projects',{method:'POST',body:{name:data.name,product_description:data.product_description,vision_model_id:modelId('vision_model_id'),video_model_id:modelId('video_model_id'),image_model_id:modelId('image_model_id'),transcription_model_id:modelId('transcription_model_id'),options:{...(word?{caption_style:data.caption_style||'highlight'}:{}),site:'BR',level:data.level,replicate_music:form.elements.replicate_music.checked,replicate_voice:form.elements.replicate_voice.checked,replicate_subtitles:form.elements.replicate_subtitles.checked,duration:data.duration?Number(data.duration):null,ratio:data.ratio,resolution:data.resolution}}});
      try {const files=[{file:reference,role:'reference'},...products.map(file=>({file,role:'product'}))];for(let i=0;i<files.length;i++){progress.textContent=`正在上传素材 ${i+1}/${files.length}：${files[i].file.name}`;const fd=new FormData();fd.append('file',files[i].file);fd.append('role',files[i].role);await api(`/api/projects/${encodeURIComponent(p.id)}/assets`,{method:'POST',body:fd});}toast('项目已创建，素材上传完成。');}
      catch(error){toast(`项目已保存，但部分素材未上传：${errorText(error)}。请在项目中补充上传。`,true);}
      await navigate('project',p.id);
    }
    if(form.id==='asset-form'){const fd=new FormData(form);await api(`/api/projects/${encodeURIComponent(state.project.id)}/assets`,{method:'POST',body:fd});toast('素材已上传，请重新分析。尚未调用模型。');await navigate('project',state.project.id);}
    if(form.id==='plan-form'){
      let analysis=structuredClone(state.project.analysis);const json=$('#plan-json');
      if(json?.dataset.dirty==='true'){try{analysis=JSON.parse(json.value);}catch{throw new Error('完整分析 JSON 格式不正确，请检查逗号与括号。');}if(!analysis||Array.isArray(analysis)||typeof analysis!=='object')throw new Error('分析内容必须是 JSON 对象。');}
      else analysis.segments=arr(analysis.segments).map((segment,i)=>({...segment,prompt:data[`prompt-${i}`]??segment.prompt,voiceover:data[`voice-${i}`]??segment.voiceover,subtitle:data[`subtitle-${i}`]??segment.subtitle,strategy:data[`strategy-${i}`]??segment.strategy??'direct',repair_prompt:data[`repair-${i}`]??segment.repair_prompt??''}));
      if(arr(analysis.segments).some(s=>s.strategy==='keyframe')&&!state.project.image_model_id)throw new Error('关键画面引导需要图片模型，请选择直接生成或调整动作与构图。');
      await api(projectActionPath(state.project,'plan'),{method:'PUT',body:{analysis}});toast('分镜方案已保存。');await navigate('project',state.project.id);
    }
    if(form.id==='model-form'){
      const payload={...data,enabled:form.elements.enabled.checked,max_duration:Number(data.max_duration),price_per_second:Number(data.price_per_second)};if(!payload.api_key)delete payload.api_key;
      await api(`/api/models${form.dataset.id?'/'+encodeURIComponent(form.dataset.id):''}`,{method:form.dataset.id?'PUT':'POST',body:payload});closeModal();toast('模型配置已保存。');await navigate('settings');
    }
    if(form.id==='storage-form'){
      const payload={...data,enabled:form.elements.enabled.checked,url_ttl:Number(data.url_ttl)};if(!payload.secret_access_key)delete payload.secret_access_key;
      state.storage=await api('/api/settings/storage',{method:'PUT',body:payload});toast('存储配置已保存。');await navigate('settings');
    }
    if(form.id==='word-recreate-form'){state.wordRecreate=await api('/api/settings/word-recreate',{method:'PUT',body:{enabled:form.elements.enabled.checked}});toast('词-复刻视频设置已保存。');render();}
    if(form.id==='workspace-form'){
      state.workspace=await api('/api/settings/workspace',{method:'PUT',body:{share_projects:form.elements.share_projects.checked}});
      if(!state.workspace.share_projects){state.libraryScope='all';state.projects=state.projects.filter(p=>String(p.owner_id)===String(state.user?.id));}
      toast('团队共享设置已保存。');await navigate('settings');
    }
    if(form.id==='user-form'){
      const payload=form.dataset.id?{role:data.role,active:form.elements.active.checked,...(data.password?{password:data.password}:{})}:{username:data.username,password:data.password,role:data.role};
      await api(`/api/users${form.dataset.id?'/'+encodeURIComponent(form.dataset.id):''}`,{method:form.dataset.id?'PATCH':'POST',body:payload});closeModal();toast(form.dataset.id?'用户信息已保存。':'用户已创建。');const me=await api('/api/auth/me');state.user=me.user;state.csrf=me.csrf_token;await navigate(admin()?'users':'dashboard');
    }
  });
});
async function init(){try{const bootstrap=await api('/api/bootstrap');state.initialized=bootstrap.initialized;if(!state.initialized)return renderAuth();try{const me=await api('/api/auth/me');state.user=me.user;state.csrf=me.csrf_token;}catch{return renderAuth();}await loadBase();render();startPolling();}catch(error){$('#app').innerHTML=`<div class="boot"><div class="brand-symbol">V<span>↗</span></div><p>${esc(errorText(error))}</p><button class="button" id="reload-app">重新连接</button></div>`;$('#reload-app').addEventListener('click',init);}}
init();

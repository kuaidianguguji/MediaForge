'use strict';
// Offline browser-state checks; no database, server, or paid model calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const listeners = {};
const nodes = {};
const context = vm.createContext({
  document: { querySelector: selector => nodes[selector] || null, addEventListener: (name, handler) => { listeners[name] = handler; } },
  structuredClone, URL, setTimeout: () => 0, clearTimeout: () => {},
  FormData: class { constructor(form) { this.values = Object.entries(form?.values || {}); } append(name,value) { this.values.push([name,value]); } [Symbol.iterator]() { return this.values[Symbol.iterator](); } },
});
const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8').replace(/\ninit\(\);\s*$/, '');
vm.runInContext(source, context);
const run = code => vm.runInContext(code, context);
// Wan is a native video protocol; selecting it guides the admin away from image editing.
nodes['#modal-root']={innerHTML:''};
run('modelModal()');
assert.ok(nodes['#modal-root'].innerHTML.includes('value="dashscope"'));
assert.ok(nodes['#modal-root'].innerHTML.includes('阿里云百炼（万相视频）'));
assert.ok(nodes['#modal-root'].innerHTML.includes('value="dashscope_asr"')&&nodes['#modal-root'].innerHTML.includes('阿里云百炼（音频转写）'));
assert.match(nodes['#modal-root'].innerHTML,/value="dashscope_asr"[^>]*disabled/, 'The audio protocol cannot be selected for visual analysis.');
nodes['#model-base-help']={textContent:''};nodes['#model-id-help']={textContent:''};
context.wanForm={elements:{protocol:{value:'dashscope'},kind:{value:'image'},model_id:{value:'wan3.0-video'},base_url:{value:'https://workspace.cn-beijing.maas.aliyuncs.com/api/v1'},api_key:{value:'test-key'}}};
run('updateModelProtocol(wanForm,true)');
assert.equal(context.wanForm.elements.kind.value,'video');
assert.equal(context.wanForm.elements.model_id.value,'wan3.0-video');
assert.ok(nodes['#model-base-help'].textContent.includes('maas.aliyuncs.com/api/v1'));
assert.ok(nodes['#model-id-help'].textContent.includes('wan3.0-video-prime'));
assert.equal(context.wanForm.elements.base_url.value,'https://workspace.cn-beijing.maas.aliyuncs.com/api/v1');
assert.equal(context.wanForm.elements.api_key.value,'test-key');

// Aliyun audio and video use different native protocols; changing purpose updates availability.
context.aliyunAsrForm={dataset:{id:''},elements:{protocol:{value:'dashscope_asr',options:[{value:'openai'},{value:'anthropic'},{value:'volcengine'},{value:'dashscope'},{value:'dashscope_asr'}]},kind:{value:'image'},model_id:{value:''},base_url:{value:'https://dashscope.aliyuncs.com/api/v1'},api_key:{value:'audio-test-key'}}};
run('updateModelProtocol(aliyunAsrForm,true)');
assert.equal(context.aliyunAsrForm.elements.kind.value,'transcription');
assert.equal(context.aliyunAsrForm.elements.model_id.value,'qwen3-asr-flash-filetrans');
assert.equal(context.aliyunAsrForm.elements.base_url.value,'https://dashscope.aliyuncs.com/api/v1');
assert.equal(context.aliyunAsrForm.elements.api_key.value,'audio-test-key');
assert.ok(nodes['#model-id-help'].textContent.includes('逐词时间戳')&&nodes['#model-id-help'].textContent.includes('TOS'));
assert.ok(nodes['#model-base-help'].textContent.includes('/api/v1')&&nodes['#model-base-help'].textContent.includes('同地域'));
assert.deepEqual(context.aliyunAsrForm.elements.protocol.options.filter(x=>!x.disabled).map(x=>x.value),['openai','dashscope_asr']);
context.aliyunAsrForm.elements.kind.value='video';run('updateModelKind(aliyunAsrForm)');
assert.equal(context.aliyunAsrForm.elements.protocol.value,'dashscope');
assert.equal(context.aliyunAsrForm.elements.model_id.value,'wan3.0-video');
context.aliyunAsrForm.elements.kind.value='transcription';run('updateModelKind(aliyunAsrForm)');
assert.equal(context.aliyunAsrForm.elements.protocol.value,'dashscope_asr');
assert.equal(context.aliyunAsrForm.elements.model_id.value,'qwen3-asr-flash-filetrans');
context.aliyunAsrForm.elements.kind.value='image';run('updateModelKind(aliyunAsrForm)');
assert.equal(context.aliyunAsrForm.elements.protocol.value,'openai');
assert.ok(context.aliyunAsrForm.elements.protocol.options.find(x=>x.value==='dashscope_asr').disabled);
context.aliyunAsrForm.dataset.id='existing-audio';context.aliyunAsrForm.elements.protocol.value='dashscope_asr';context.aliyunAsrForm.elements.model_id.value='qwen3-asr-flash-filetrans-2025-11-17';
run('updateModelProtocol(aliyunAsrForm,true)');
assert.equal(context.aliyunAsrForm.elements.model_id.value,'qwen3-asr-flash-filetrans-2025-11-17', 'Editing preserves an administrator-selected model snapshot.');
context.aliyunAsrForm.dataset.id='';context.aliyunAsrForm.elements.model_id.value='custom-model';run('updateModelProtocol(aliyunAsrForm,true)');
assert.equal(context.aliyunAsrForm.elements.model_id.value,'custom-model', 'Changing protocol does not overwrite a custom model ID.');
for(const kind of ['vision','image','video'])assert.equal(run(`protocolSupportsKind('dashscope_asr','${kind}')`),false);
for(const [status,label] of [['prepared','待提交'],['received','结果已保存'],['no_speech','未识别到口播'],['rejected','请求被拒绝'],['query_error','查询失败']])assert.ok(run(`badge('${status}')`).includes(label), 'ASR receipt states are shown in Chinese.');
run(`state.project={id:'p',can_edit:true,owner_id:'owner',owner_username:'Maker',name:'Product',status:'ready',options:{},assets:[{id:'r',role:'reference'},{id:'p',role:'product'}],segments:[],jobs:[],analysis:{summary:'Plan',product_identity:'Target',product_profile:{features:['<img src=x onerror=alert(1)>'],parts:['control'],known_views:['front'],unknowns:['rear'],forbidden_traits:['old display']},sampling:{limited:true},shots:[{start:0,end:5,description:'Close-up',product_visibility:'partial',visible_parts:['control'],interaction:'press',missing_views:['back view'],constraints:['no display'],strategy:'needs_reference',reference_image_indices:[0]}],segments:[{start:0,duration:5,prompt:'P',strategy:'needs_reference',shot_indices:[0],reference_image_indices:[0],repair_prompt:''}]}};`);
let html = run('projectPage()');
assert.ok(html.includes('back view'), 'Missing references must be visible.');
assert.ok(html.includes('局部特写'), 'Partial product visibility must be visible.');
assert.ok(html.includes('部分片段需要补图'), 'Generation must explain missing references.');
assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'), 'Model text must be HTML escaped.');
assert.ok(!html.includes('<img src=x onerror=alert(1)>'));
assert.ok(html.includes('重新分析素材'));
assert.ok(html.includes('id="asset-form"'), 'Ready projects without segments can add references.');
assert.match(run('strategyOptions()'), /value="keyframe"[^>]*disabled/, 'Missing image model disables keyframe selection.');

// Analysis retries keep a separate explicit action for a new, billable analysis.
run(`globalThis.originalProject=structuredClone(state.project);state.project={id:'p',can_edit:true,owner_id:'owner',owner_username:'Maker',name:'Product',status:'failed',options:{},assets:[{id:'r',role:'reference'},{id:'p',role:'product'},{id:'raw',role:'analysis_raw',name:'reply.json',mime:'application/json',size:100},{id:'repair',role:'analysis_repair',name:'repair.json',mime:'application/json',size:100}],segments:[],jobs:[],analysis:null,error:'第 1 个镜头的约束格式有误'};`);
html = run('projectPage()');
assert.ok(html.includes('data-action="retry-project"'), 'Failed analysis must allow continuing the saved result.');
assert.ok(html.includes('class="button small ghost" data-action="analyze-project">重新分析素材'), 'Starting fresh must have a distinct small action.');
assert.ok(html.includes('本地格式修复不调用模型')&&html.includes('最多调用一次文本格式修复'), 'Analysis recovery must explain its limited model calls.');
assert.ok(html.includes('重新分析素材会重新调用模型，产生分析费用'), 'Starting fresh must explain the analysis fee.');
assert.ok(html.includes('分析原始结果')&&html.includes('分析格式修复结果'), 'Saved response roles need understandable labels.');
assert.ok(html.includes('/api/assets/raw')&&html.includes('/api/assets/repair'), 'Saved model replies remain available through the asset list.');
run(`state.project.status='analyzing';state.project.jobs=[{status:'running'}]`);
html = run('projectPage()');
assert.ok(!html.includes('>重新分析素材</button>'), 'A running analysis must not offer a fresh conflicting analysis.');
run(`state.project=originalProject;delete globalThis.originalProject`);

run(`state.project.status='needs_review';state.project.output_asset_id='output';state.project.analysis.segments[0].start=10;state.project.segments=[{id:'s',index:0,asset_id:'current',status:'succeeded',attempts:1,quality:{status:'issues',summary:'Mismatch',sampled_times:[2],issues:[{time:2,category:'mixed_identity',severity:'error',description:'Wrong parts',suggestion:'Replace'}]},history:[{asset_id:'old',attempts:1,quality:{status:'uncertain',summary:'Old'}}]}];`);
html = run('projectPage()');
assert.ok(html.includes('下载待审核成片'), 'Flagged outputs remain downloadable and explicitly unapproved.');
assert.ok(html.includes('12.0 秒 · 产品特征混合'), 'Issue times must map to full-project time.');
assert.ok(html.includes('/api/assets/old'), 'History video must remain available.');
assert.ok(html.includes('data-regenerate-segment="s"'));
assert.ok(html.includes('data-action="review-project"'));
assert.ok(!html.includes('id="asset-form"'), 'References cannot change after generation.');
run('state.project.segments[0].attempts=3');
html = run('qualityPanel(state.project)');
assert.ok(!html.includes('data-regenerate-segment'), 'Generation limit must hide paid retry action.');
assert.ok(html.includes('data-action="review-project"'), 'Review remains possible at the generation limit.');
run(`state.project.status='reviewing';state.project.jobs=[{status:'running'}]`);
html = run('qualityPanel(state.project)');
assert.ok(!html.includes('data-regenerate-segment')&&!html.includes('data-action="review-project"'), 'Active work blocks conflicting actions.');
run(`state.project.status='needs_attention';state.project.jobs=[];state.project.segments=[{id:'s',index:0,status:'failed',quality:{keyframe_status:'rejected',keyframe_asset_id:'kf',keyframe_reason:'Incorrect geometry'},attempts:0}]`);
html = run('qualityPanel(state.project)');
assert.ok(html.includes('data-strategy-segment="s"'), 'Failed keyframes offer a non-generating strategy edit.');
assert.ok(html.includes('/api/assets/kf')&&html.includes('Incorrect geometry'));
assert.ok(!html.includes('data-action="review-project"'), 'Incomplete outputs cannot be reviewed.');

// Ordinary plan editing must preserve the model-provided product and shot contract.
nodes['#plan-json'] = { dataset: {} };
run(`state.project.segments=[];state.project.status='ready';state.project.output_asset_id=null;globalThis.originalNavigate=navigate;globalThis.originalApi=api;globalThis.saved=[];api=async(path,options)=>{saved.push({path,options});return {}};navigate=async()=>{};toast=()=>{};`);
const form = { id:'plan-form', values:{'prompt-0':'Updated','strategy-0':'adapt','repair-0':'Use real control','voice-0':'V','subtitle-0':'S'}, querySelector:()=>null };
listeners.submit({target:form,preventDefault(){}});
setImmediate(async()=>{
  const saved = JSON.parse(run('JSON.stringify(saved[0].options.body.analysis)'));
  assert.equal(saved.segments[0].strategy,'adapt');
  assert.equal(saved.segments[0].repair_prompt,'Use real control');
  assert.deepEqual(saved.segments[0].shot_indices,[0]);
  assert.deepEqual(saved.segments[0].reference_image_indices,[0]);
  assert.deepEqual(saved.product_profile.parts,['control']);
  assert.equal(saved.shots[0].product_visibility,'partial');
  await sharingChecks();
  await wordRecreateChecks();
  await modelDeletionChecks();
  console.log('Frontend offline checks passed.');
});

async function sharingChecks() {
  run(`state.user={id:'owner',username:'Maker',role:'user'};state.workspace={share_projects:true};state.libraryScope='all';state.libraryFilter='all';state.search='';globalThis.notices=[];toast=(message)=>notices.push(message);globalThis.editableProject=structuredClone(state.project);`);
  assert.equal(run(`canEditProject({id:'legacy'})`),false, 'Missing permission flags must fail closed while sharing is enabled.');
  assert.equal(run(`canEditProject({id:'owned',can_edit:true})`),true);
  run('state.workspace.share_projects=false');
  assert.equal(run(`canEditProject({id:'legacy'})`),true, 'The legacy private detail endpoint remains editable before a service restart.');
  assert.equal(run(`canEditProject({id:'shared',can_edit:false})`),false, 'An explicit read-only flag always overrides legacy compatibility.');
  assert.equal(run(`canEditProject({id:'invalid',can_edit:null})`),false, 'Invalid explicit flags do not gain compatibility access.');
  assert.equal(run('canEditProject(null)'),false);
  run('state.workspace.share_projects=true');
  const evil='<img src=x onerror=alert(1)>';
  context.sharingRows=[{id:'new',owner_id:'owner',owner_username:evil,name:'New product',status:'completed',created_at:200}, {id:'other',owner_id:'another',owner_username:'其他成员',name:'New product shared',status:'completed',created_at:100}, {id:'own-failed',owner_id:'owner',owner_username:'Maker',name:'Old product',status:'failed',created_at:50}];
  run('state.projects=sharingRows');
  let rendered=run('libraryPage()');
  assert.ok(rendered.includes('data-scope="mine"')&&rendered.includes('我的项目'));
  assert.ok(rendered.includes('aria-label="项目状态"')&&rendered.includes('全部状态'));
  assert.ok(rendered.indexOf('data-project="new"')<rendered.indexOf('data-project="other"'), 'The ordered server list must remain in time order.');
  assert.ok(rendered.includes(`制作人：&lt;img src=x onerror=alert(1)&gt;`)&&!rendered.includes(evil), 'Creator names must be escaped in cards.');
  rendered=run('projectTable(state.projects)');
  assert.ok(rendered.includes('<th>制作人</th>')&&rendered.includes('&lt;img src=x onerror=alert(1)&gt;')&&!rendered.includes(evil));
  run(`state.libraryScope='mine';state.libraryFilter='completed';state.search='New';`);
  assert.deepEqual(JSON.parse(run('JSON.stringify(filteredProjects().map(p=>p.id))')),['new'], 'Mine, status, and search filters must intersect.');
  nodes['#library-results']={innerHTML:''};
  listeners.input({target:{id:'library-search',value:'shared',closest:()=>null}});
  assert.ok(!nodes['#library-results'].innerHTML.includes('data-project="other"'), 'Typing search must retain mine scope.');
  run(`state.workspace.share_projects=false;state.libraryScope='all';state.libraryFilter='all';state.search='';`);
  assert.ok(!run('libraryPage()').includes('data-scope='), 'Private mode hides sharing scope.');
  run(`state.settingsTab='workspace';`);
  rendered=run('settingsPage()');
  assert.ok(rendered.includes('团队共享')&&rendered.includes('id="workspace-form"'));
  assert.match(rendered, /name="share_projects"[^>]*>/);
  assert.ok(!/name="share_projects"[^>]*checked/.test(rendered), 'Sharing defaults off.');

  run(`state.project={...editableProject,owner_id:'another',owner_username:'<img src=x onerror=alert(1)>',can_edit:false,status:'ready',segments:[],jobs:[],output_asset_id:null};`);
  rendered=run('projectPage()');
  assert.ok(rendered.includes('制作人：&lt;img src=x onerror=alert(1)&gt;')&&!rendered.includes(evil), 'Creator name must be escaped in detail.');
  assert.ok(rendered.includes('团队共享项目，仅可查看和下载'));
  assert.ok(rendered.includes('id="plan-json" aria-label="完整分析 JSON" readonly'));
  assert.ok(rendered.includes('name="strategy-0" disabled')&&rendered.includes('name="prompt-0" rows="3" readonly'));
  assert.ok(!rendered.includes('id="plan-form"')&&!rendered.includes('id="asset-form"')&&!rendered.includes('保存分镜修改')&&!rendered.includes('data-action="generate-project"')&&!rendered.includes('data-action="audio-options"'));
  run(`state.project.status='failed';state.project.analysis=null`);
  rendered=run('projectPage()');
  assert.ok(!rendered.includes('data-action="analyze-project"')&&!rendered.includes('data-action="retry-project"'));
  run(`state.project.status='analyzing';state.project.jobs=[{status:'running'}]`);
  assert.ok(!run('projectPage()').includes('data-action="cancel-project"'));
  run(`state.project.analysis=editableProject.analysis;state.project.jobs=[];state.project.status='needs_review';state.project.output_asset_id='output';state.project.segments=[{id:'s',index:0,status:'succeeded',asset_id:'current',attempts:1,history:[{asset_id:'old'}]}]`);
  rendered=run('projectPage()');
  assert.ok(rendered.includes('/api/assets/output?download=1')&&rendered.includes('/api/assets/old'), 'Read-only users can download and preview outputs and history.');
  assert.ok(!rendered.includes('data-regenerate-segment')&&!rendered.includes('data-action="review-project"'));
  run(`state.project.status='needs_attention';state.project.segments=[{id:'s',index:0,status:'failed',attempts:0}]`);
  assert.ok(!run('qualityPanel(state.project)').includes('data-strategy-segment'));
  run(`state.project.segments=[{id:'s',index:0,status:'submitting',attempts:1}];state.user.role='admin'`);
  assert.ok(!run('remoteTasksPanel(state.project)').includes('data-resolve-segment'), 'Even stale admin UI follows the explicit project permission.');
  nodes['#modal-root'].innerHTML='untouched';
  run(`repairModal('s');reviewModal();audioOptionsModal()`);
  assert.equal(nodes['#modal-root'].innerHTML,'untouched', 'Direct modal calls cannot expose shared project mutations.');
  run(`globalThis.saved=[];api=async(path,options)=>{saved.push({path,options});return {}};`);
  for(const action of ['analyze-project','generate-project','retry-project','cancel-project','review-project','audio-options','audio-original-voice','audio-silent'])listeners.click({target:{closest:()=>({dataset:{action}})}});
  listeners.click({target:{closest:()=>({dataset:{resolveSegment:'s'}})}});
  for(const id of ['plan-form','asset-form','audio-options-form','segment-repair-form','review-form','resolve-form','asr-resolve-form'])listeners.submit({target:{id,querySelector:()=>null},preventDefault(){}});
  await run(`projectAction('generate')`);
  assert.equal(run('saved.length'),0, 'Forged events and direct actions must never submit mutations for shared projects.');

  // The application requests each page from the server, including server-side mine scope.
  context.pagedRows=Array.from({length:502},(_,i)=>({id:`p${i}`,owner_id:i%2?'owner':'another',name:`Project ${i}`,created_at:502-i,status:'completed'}));
  run(`state.user.role='user';globalThis.requests=[];api=async(path)=>{requests.push(path);const u=new URL(path,'http://test');const rows=u.searchParams.get('mine')==='true'?pagedRows.filter(p=>p.owner_id==='owner'):pagedRows;return rows.slice(Number(u.searchParams.get('offset')),Number(u.searchParams.get('offset'))+Number(u.searchParams.get('limit')))};`);
  const every=await run('loadProjects()');
  assert.equal(every.length,502);
  assert.deepEqual(Array.from(every,p=>p.id),context.pagedRows.map(p=>p.id));
  assert.deepEqual(JSON.parse(run('JSON.stringify(requests)')),['/api/projects?limit=200&offset=0','/api/projects?limit=200&offset=200','/api/projects?limit=200&offset=400']);
  run('requests=[]');
  const mine=await run('loadProjects(true)');
  assert.equal(mine.length,251, 'Mine must include owned projects beyond the first 200 rows.');
  assert.ok(mine.every(p=>p.owner_id==='owner'));
  assert.ok(JSON.parse(run('JSON.stringify(requests)')).every(url=>url.includes('&mine=true')));

  context.repeatingRows=context.pagedRows.slice(0,200);
  run(`requests=[];api=async(path)=>{requests.push(path);return repeatingRows}`);
  const legacy=await run('loadProjects()');
  assert.equal(legacy.length,200);
  assert.equal(run('requests.length'),2, 'A legacy endpoint that ignores offset must stop after the repeated page without an infinite loop.');

  run(`globalThis.saved=[];api=async(path,options)=>{saved.push({path,options});return options.body};state.user.role='admin';state.workspace={share_projects:false};state.busy=false`);
  listeners.submit({target:{id:'workspace-form',values:{},elements:{share_projects:{checked:true}},querySelector:()=>null},preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(run('saved[0].path'),'/api/settings/workspace');
  assert.equal(run('saved[0].options.method'),'PUT');
  assert.deepEqual(JSON.parse(run('JSON.stringify(saved[0].options.body)')),{share_projects:true}, 'Only explicit form save enables sharing.');
  run(`state.libraryScope='mine';state.projects=sharingRows;state.busy=false;`);
  listeners.submit({target:{id:'workspace-form',values:{},elements:{share_projects:{checked:false}},querySelector:()=>null},preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(run('state.libraryScope'),'all');
  assert.deepEqual(JSON.parse(run('JSON.stringify(state.projects.map(p=>p.id))')),['new','own-failed'], 'Disabling sharing immediately clears other creators from cached rows, including for admins.');

  // A project already open when sharing is revoked must lose its cached content.
  context.window={scrollTo:()=>{}};nodes['#app']={innerHTML:''};
  run(`state.user.role='user';state.project={id:'revoked',can_edit:false,status:'completed'};state.projects=sharingRows;state.workspace={share_projects:true};navigate=originalNavigate;api=async(path)=>{if(path==='/api/projects/revoked'){const error=new Error('Project not found');error.status=404;throw error;}if(path==='/api/settings/workspace')return {share_projects:false};if(path.startsWith('/api/projects?'))return sharingRows.filter(p=>p.owner_id==='owner');if(path==='/api/models')return [];return {}};`);
  await run(`navigate('project','revoked')`);
  assert.equal(run('state.view'),'library');
  assert.equal(run('state.project'),null);
  assert.ok(!nodes['#app'].innerHTML.includes('data-project="other"'));
  assert.equal(nodes['#modal-root'].innerHTML,'');

  run(`state.project=editableProject;state.libraryScope='mine';state.libraryFilter='failed';state.search='text';state.workspace.share_projects=true;resetWorkspace()`);
  assert.deepEqual(JSON.parse(run('JSON.stringify({scope:state.libraryScope,filter:state.libraryFilter,search:state.search,shared:state.workspace.share_projects,projects:state.projects,project:state.project})')),{scope:'all',filter:'all',search:'',shared:false,projects:[],project:null}, 'Logout reset clears previous user project state.');
}

async function modelDeletionChecks() {
  run(`state.user={id:'admin',role:'admin'};state.models=[{id:'model / id',name:'Unused model',kind:'vision',protocol:'openai',model_id:'model',base_url:'https://example.com/v1',enabled:false,api_key_set:true}];state.busy=false;globalThis.modelRequests=[];globalThis.modelNavigations=[];globalThis.modelNotices=[];navigate=async(view)=>modelNavigations.push(view);toast=(message)=>modelNotices.push(message);api=async(path,options)=>{modelRequests.push({path,options});return path==='/api/health'?{model_deletion:true}:{ok:true}};`);
  run('modelModal()');
  assert.ok(!nodes['#modal-root'].innerHTML.includes('data-delete-model'), 'New configurations do not expose a deletion action.');
  run(`modelModal('model / id')`);
  let rendered=nodes['#modal-root'].innerHTML;
  assert.ok(rendered.includes('data-delete-model="model / id"')&&rendered.includes('>删除模型</button>'));
  assert.ok(!rendered.includes('data-disable-model')&&!rendered.includes('>停用模型</button>'));
  assert.ok(rendered.includes('已被项目引用的模型不能删除，可通过启用开关停用。'));
  assert.match(rendered,/name="enabled"[^>]*>/, 'The independent enable switch remains available.');
  assert.ok(!/name="enabled"[^>]*checked/.test(rendered), 'A previously disabled configuration stays disabled.');
  const button={dataset:{deleteModel:'model / id'},innerHTML:'删除模型',isConnected:true,setAttribute(){},removeAttribute(){}};
  listeners.click({target:{closest:()=>button}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(run('modelRequests.length'),2);
  assert.equal(run('modelRequests[0].path'),'/api/health', 'Deletion verifies the running backend supports physical deletion.');
  assert.equal(run('modelRequests[0].options'),undefined, 'The capability check is a read-only GET.');
  assert.equal(run('modelRequests[1].path'),'/api/models/model%20%2F%20id');
  assert.equal(run('modelRequests[1].options.method'),'DELETE');
  assert.equal(nodes['#modal-root'].innerHTML,'', 'Successful deletion closes the editor.');
  assert.deepEqual(JSON.parse(run('JSON.stringify(modelNotices)')),['模型已删除。']);
  assert.deepEqual(JSON.parse(run('JSON.stringify(modelNavigations)')),['settings'], 'Successful deletion refreshes the settings list.');

  run(`modelModal('model / id');modelRequests=[];modelNavigations=[];modelNotices=[];api=async(path,options)=>{modelRequests.push({path,options});if(path==='/api/health')return {model_deletion:true};throw new Error('模型已被项目引用，请通过启用开关停用。')}`);
  nodes['#modal-error']={textContent:''};
  rendered=nodes['#modal-root'].innerHTML;
  listeners.click({target:{closest:()=>button}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(run('modelRequests.length'),2);
  assert.equal(run('modelRequests[0].path'),'/api/health');
  assert.equal(run('modelRequests[1].options.method'),'DELETE');
  assert.equal(nodes['#modal-root'].innerHTML,rendered, 'Rejected deletion keeps the editor open and its configuration intact.');
  assert.equal(nodes['#modal-error'].textContent,'模型已被项目引用，请通过启用开关停用。');
  assert.equal(run('modelNavigations.length'),0);
  assert.equal(run('modelNotices.length'),0, 'Rejected deletion cannot announce success.');
  assert.equal(button.disabled,false, 'A failed deletion leaves the action usable after the response.');
  assert.equal(run('state.busy'),false);

  // Updated static files must not call an older service whose DELETE still disables a model.
  const originalModels=run('JSON.stringify(state.models)');
  for(const capability of [undefined,false,'true']){
    context.oldDeletionCapability=capability;
    run(`modelModal('model / id');modelRequests=[];modelNavigations=[];modelNotices=[];api=async(path,options)=>{modelRequests.push({path,options});return {model_deletion:oldDeletionCapability}}`);
    nodes['#modal-error'].textContent='';
    rendered=nodes['#modal-root'].innerHTML;
    listeners.click({target:{closest:()=>button}});
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(run('modelRequests.length'),1);
    assert.equal(run('modelRequests[0].path'),'/api/health');
    assert.equal(run('modelRequests[0].options'),undefined, 'Unsupported services receive only the GET capability request.');
    assert.equal(nodes['#modal-root'].innerHTML,rendered);
    assert.equal(nodes['#modal-error'].textContent,'服务尚未更新，请管理员重启服务后刷新页面，再删除模型。');
    assert.equal(run('JSON.stringify(state.models)'),originalModels, 'The older service cannot disable or alter the model through the new deletion button.');
    assert.equal(run('modelNavigations.length'),0);
    assert.equal(run('modelNotices.length'),0);
    assert.equal(button.disabled,false);
  }

  run(`state.user.role='user';modelRequests=[];modelModal('model / id')`);
  assert.ok(!nodes['#modal-root'].innerHTML.includes('data-delete-model'), 'Non-administrators do not see model deletion controls.');
  listeners.click({target:{closest:()=>button}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(run('modelRequests.length'),0, 'Forged non-administrator deletion clicks never reach the API.');
  delete nodes['#modal-error'];
}


async function wordRecreateChecks() {
  run(`state.user={id:'owner',username:'Maker',role:'admin'};state.models=[{id:'vision',enabled:true,kind:'vision',protocol:'openai',name:'Vision'},{id:'video',enabled:true,kind:'video',protocol:'volcengine',name:'Video'},{id:'asr',enabled:true,kind:'transcription',protocol:'openai',name:'Word ASR'},{id:'aliyun-asr',enabled:true,kind:'transcription',protocol:'dashscope_asr',name:'Aliyun ASR'},{id:'disabled-aliyun-asr',enabled:false,kind:'transcription',protocol:'dashscope_asr',name:'Disabled Aliyun ASR'},{id:'wrong-asr',enabled:true,kind:'transcription',protocol:'anthropic',name:'Not compatible ASR'}];state.wordRecreate={enabled:false,installed:false,ready:false,version:'0.2.17',reason:'<img src=x onerror=alert(1)>'};state.settingsTab='word-recreate';state.view='dashboard'`);
  let rendered=run('settingsPage()');
  assert.ok(rendered.includes('id="word-recreate-form"')&&rendered.includes('检查引擎'));
  assert.ok(!/name="enabled"[^>]*checked/.test(rendered), 'The word module defaults off.');
  assert.ok(rendered.includes('&lt;img src=x onerror=alert(1)&gt;')&&!rendered.includes('<img src=x onerror=alert(1)>'), 'Runtime messages are escaped.');
  assert.ok(run('createPage(true)').includes('功能暂未开放'), 'A direct navigation cannot create projects while the module is off.');
  run('renderShell("")');
  assert.ok(!nodes['#app'].innerHTML.includes('data-nav="word-create"'), 'Disabled word module is absent from the sidebar.');
  run(`state.wordRecreate={enabled:true,installed:true,ready:true,version:'0.2.17',reason:''};renderShell('')`);
  assert.ok(nodes['#app'].innerHTML.includes('data-nav="word-create"'));
  rendered=run('createPage(true)');
  assert.ok(rendered.includes('data-engine="hypit"')&&rendered.includes('name="caption_style"'));
  assert.ok(rendered.includes('value="highlight"')&&rendered.includes('value="plain"'));
  assert.ok(rendered.includes('verbose_json')&&rendered.includes('逐词时间戳'), 'Word alignment clearly requires a timestamp-capable ASR model.');
  assert.ok(rendered.includes('value="asr"')&&rendered.includes('value="aliyun-asr"')&&!rendered.includes('value="wrong-asr"')&&!rendered.includes('value="disabled-aliyun-asr"'), 'Word creation offers enabled OpenAI and Aliyun audio protocols.');
  assert.ok(rendered.includes('阿里云选择文件转写 filetrans 协议')&&rendered.includes('需已配置 TOS'));
  context.wordForm={dataset:{engine:'hypit'},elements:{transcription_model_id:{required:true},replicate_voice:{checked:false},replicate_subtitles:{checked:true}}};
  run('updateWordInputs(wordForm)');
  assert.equal(context.wordForm.elements.transcription_model_id.required,false, 'Scene captions need no word ASR when speech is disabled.');
  context.wordForm.elements.replicate_voice.checked=true;run('updateWordInputs(wordForm)');
  assert.equal(context.wordForm.elements.transcription_model_id.required,true);
  assert.ok(run('createPage()').includes('value="wrong-asr"')&&run('createPage()').includes('data-engine="native"'), 'The existing model selection is unchanged for native projects.');
  assert.equal(run(`projectActionPath({id:'a / b',engine:'hypit'},'generate')`),'/api/word-recreate/projects/a%20%2F%20b/generate');
  assert.equal(run(`projectActionPath({id:'native'},'analyze')`),'/api/projects/native/analyze');
  assert.equal(run(`projectActionPath({id:'legacy',options:{engine:'hypit'}},'retry')`),'/api/word-recreate/projects/legacy/retry');

  run(`state.project={...editableProject,engine:'hypit',can_edit:true,owner_id:'owner',options:{engine:'hypit',caption_style:'highlight'},status:'needs_review',output_asset_id:'output',jobs:[],segments:[{id:'s',index:0,status:'succeeded',asset_id:'current',attempts:1}],assets:[{id:'r',role:'reference'},{id:'p',role:'product'},{id:'workflow',role:'word_workflow',name:'workflow.svml',size:12},{id:'alignment',role:'word_alignment',name:'alignment.json',size:12},{id:'receipt',role:'word_render_state',name:'internal-receipt.json',size:12},{id:'asr-raw',role:'word_asr_raw',name:'reply.json',size:12},{id:'evidence',role:'word_evidence',name:'evidence.json',size:12}]};state.wordRecreate.enabled=false`);
  rendered=run('projectPage()');
  assert.ok(rendered.includes('词-复刻视频已停用')&&rendered.includes('/api/assets/output?download=1'));
  assert.ok(rendered.includes('词复刻工作流归档')&&rendered.includes('字幕对齐记录')&&rendered.includes('音频转写原始回复')&&rendered.includes('词复刻合成记录'), 'Archived workflow and alignment assets stay discoverable.');
  assert.ok(!rendered.includes('internal-receipt.json')&&!rendered.includes('/api/assets/receipt'), 'Internal renderer receipts are not user media.');
  assert.ok(!rendered.includes('data-action="review-project"')&&!rendered.includes('data-regenerate-segment')&&!rendered.includes('data-action="audio-options"'), 'Disabled word projects have no paid or unsupported repair controls.');
  run(`state.project.status='ready';state.project.output_asset_id=null;state.project.segments=[]`);
  rendered=run('projectPage()');
  assert.ok(!rendered.includes('id="plan-form"')&&!rendered.includes('id="asset-form"')&&!rendered.includes('data-action="generate-project"'));
  run('state.wordRecreate.enabled=true');
  rendered=run('projectPage()');
  assert.ok(rendered.includes('id="plan-form"')&&rendered.includes('data-action="generate-project"'));
  run(`state.project.status='needs_review';state.project.output_asset_id='output';state.project.segments=[{id:'s',index:0,status:'succeeded',asset_id:'current',attempts:1}]`);
  assert.ok(!run('qualityPanel(state.project)').includes('data-regenerate-segment'), 'First-version word projects do not expose native segment regeneration.');
  run(`state.project.can_edit=false`);
  assert.ok(!run('projectPage()').includes('data-action="review-project"'), 'Shared word projects remain read-only when the module is enabled.');

  run(`state.project.can_edit=true;state.project.status='ready';state.project.output_asset_id=null;state.project.segments=[];state.wordRecreate.enabled=false;globalThis.saved=[];globalThis.notices=[];toast=(message)=>notices.push(message);navigate=async()=>{};render=()=>{};startPolling=()=>{};api=async(path,options)=>{saved.push({path,options});return options?.body||state.project};state.busy=false;`);
  await run(`projectAction('generate')`);
  assert.equal(run('saved.length'),0, 'Direct paid actions fail closed while the word module is off.');
  listeners.submit({target:{id:'plan-form',values:{},querySelector:()=>null},preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(run('saved.length'),0, 'Forged plan submit cannot mutate a disabled word project.');
  run(`state.project.status='generating'`);
  await run(`projectAction('cancel')`);
  assert.equal(run('saved[0].path'),'/api/word-recreate/projects/p/cancel', 'Running word jobs may be stopped even after disabling the module.');
  run(`saved=[];state.wordRecreate.enabled=true;state.project.status='ready'`);
  await run(`projectAction('generate')`);
  assert.equal(run('saved[0].path'),'/api/word-recreate/projects/p/generate');
  run(`saved=[];delete state.project.engine;state.project.options={};state.wordRecreate.enabled=false`);
  await run(`projectAction('generate')`);
  assert.equal(run('saved[0].path'),'/api/projects/p/generate', 'Native generation does not depend on the optional module.');

  run(`saved=[];state.busy=false;state.wordRecreate.enabled=true;`);
  const form={id:'create-form',dataset:{engine:'hypit'},values:{name:'Word project',product_description:'Product',vision_model_id:'vision',video_model_id:'video',transcription_model_id:'',caption_style:'plain',level:'balanced',ratio:'9:16',resolution:'720p'},elements:{reference:{files:[{name:'ref.mp4',size:1}]},products:{files:[{name:'product.png',size:1}]},replicate_voice:{checked:true},replicate_subtitles:{checked:true},replicate_music:{checked:true}},querySelector:()=>null};
  nodes['#upload-progress']={textContent:''};
  listeners.submit({target:form,preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(run('saved.length'),0, 'Missing word ASR is caught before creating or submitting a paid project.');
  form.values.transcription_model_id='asr';
  run(`state.busy=false;api=async(path,options)=>{saved.push({path,options});return {id:'new-word',...options?.body}}`);
  listeners.submit({target:form,preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(run('saved[0].path'),'/api/word-recreate/projects');
  assert.equal(run('saved[0].options.body.options.caption_style'),'plain');
  assert.equal(run('saved[0].options.body.options.site'),'BR');
  assert.equal(run('saved[0].options.body.options.ratio'),'9:16');
  assert.ok(JSON.parse(run('JSON.stringify(saved.slice(1).map(r=>r.path))')).every(p=>p==='/api/projects/new-word/assets'), 'Product uploads retain the shared authenticated asset API.');

  run(`saved=[];state.busy=false;api=async(path,options)=>{saved.push({path,options});return {enabled:options.body.enabled,ready:true,installed:true,version:'0.2.17'}}`);
  listeners.submit({target:{id:'word-recreate-form',values:{},elements:{enabled:{checked:false}},querySelector:()=>null},preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(run('saved[0].path'),'/api/settings/word-recreate');
  assert.deepEqual(JSON.parse(run('JSON.stringify(saved[0].options.body)')),{enabled:false});
  assert.equal(run('state.wordRecreate.enabled'),false);

  // Resolving an unknown paid ASR receipt remains a free admin operation while Hypit is disabled.
  run(`state.user.role='admin';state.project={id:'asr-project',engine:'hypit',can_edit:true,status:'needs_attention',segments:[],assets:[{id:'asr / pending',role:'word_asr_raw',meta:{protocol:'dashscope_asr',purpose:'generated',state:'uncertain',file_url:'https://private.example/?secret=hidden',api_key:'hidden-key'}},{id:'known',role:'asr_raw',meta:{protocol:'dashscope_asr',state:'failed',remote_id:'<img src=x onerror=alert(1)>'}},{id:'openai',role:'word_asr_raw',meta:{protocol:'openai',state:'uncertain'}}]};saved=[];state.busy=false;api=async(path,options)=>{saved.push({path,options});return {}};`);
  rendered=run('remoteTasksPanel(state.project)');
  assert.ok(rendered.includes('关联转写任务 ID')&&rendered.includes('成片口播转写'), 'A transcription receipt is visible even before native segments exist.');
  assert.ok(rendered.includes('&lt;img src=x onerror=alert(1)&gt;')&&!rendered.includes('<img src=x onerror=alert(1)>'), 'Preserved remote task IDs are escaped.');
  assert.ok(!rendered.includes('hidden-key')&&!rendered.includes('private.example'), 'Receipt UI only exposes whitelisted task state and ID.');
  assert.equal((rendered.match(/data-resolve-transcription=/g)||[]).length,1, 'Only unknown Aliyun requests offer task association.');
  listeners.click({target:{closest:()=>({dataset:{resolveTranscription:'asr / pending'}})}});
  assert.ok(nodes['#modal-root'].innerHTML.includes('id="asr-resolve-form"'));
  assert.ok(nodes['#modal-root'].innerHTML.includes('pattern="[A-Za-z0-9_-]+"'), 'Browser validation matches the server task ID format.');
  assert.ok(run(`remoteTasksPanel({assets:[{id:'reference-word',role:'word_asr_raw',meta:{protocol:'dashscope_asr',purpose:'reference',state:'submitted',remote_id:'reference-task'}}]})`).includes('参考视频转写'), 'Word project source analysis is labeled by receipt purpose.');
  rendered=run(`remoteTasksPanel({assets:[{id:'silent-reference',role:'asr_raw',meta:{protocol:'dashscope_asr',purpose:'reference',state:'no_speech',remote_id:'reference-task',error_code:'SUCCESS_WITH_NO_VALID_FRAGMENT',error:'未识别到有效口播 <img src=x onerror=alert(1)>',file_url:'https://private.example/?secret=hidden',api_key:'hidden-key',provider_status:'sensitive-status'}}]})`);
  assert.ok(rendered.includes('参考视频转写 · 未识别到口播')&&rendered.includes('错误码：SUCCESS_WITH_NO_VALID_FRAGMENT'), 'A known no-speech receipt shows its meaningful status and exact safe error code.');
  assert.ok(rendered.includes('根据产品事实和参考画面重写新口播')&&rendered.includes('无法还原原口播'), 'Source no-speech explains that visual analysis can continue without inventing the original transcript.');
  assert.ok(rendered.includes('&lt;img src=x onerror=alert(1)&gt;')&&!rendered.includes('<img src=x onerror=alert(1)>'), 'The saved safe ASR error is HTML escaped.');
  assert.ok(!rendered.includes('hidden-key')&&!rendered.includes('private.example')&&!rendered.includes('sensitive-status'), 'Only approved receipt diagnostics are rendered.');
  assert.ok(!rendered.includes('data-resolve-transcription'), 'A known no-speech task never offers association or a duplicate submission action.');
  rendered=run(`remoteTasksPanel({assets:[{id:'silent-output',role:'word_asr_raw',meta:{protocol:'dashscope_asr',purpose:'generated',state:'no_speech',remote_id:'generated-task',error_code:'SUCCESS_WITH_NO_VALID_FRAGMENT',error:'未识别到有效口播'}}]})`);
  assert.ok(rendered.includes('成片口播转写 · 未识别到口播')&&rendered.includes('有效的实际口播和词级时间戳')&&rendered.includes('已生成片段会保留')&&rendered.includes('不会编造字幕时间'), 'Generated no-speech remains a blocking alignment issue with paid clips preserved.');
  assert.ok(!rendered.includes('继续根据产品事实'), 'Generated no-speech must not promise the reference-only fallback.');
  rendered=run(`remoteTasksPanel({assets:[{id:'unknown-error',role:'asr_raw',meta:{protocol:'dashscope_asr',state:'failed',error:'安全的错误提示',error_code:'<script>unknown-provider-diagnostic</script>'}}]})`);
  assert.ok(rendered.includes('安全的错误提示')&&!rendered.includes('unknown-provider-diagnostic')&&!rendered.includes('错误码：'), 'Unknown provider error codes are not exposed.');
  const asrForm={id:'asr-resolve-form',dataset:{id:'asr / pending'},values:{remote_id:'verified-task-id'},querySelector:()=>null};
  listeners.submit({target:asrForm,preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(run('saved[0].path'),'/api/transcriptions/asr%20%2F%20pending/resolve');
  assert.deepEqual(JSON.parse(run('JSON.stringify(saved[0].options.body)')),{remote_id:'verified-task-id'});
  run(`saved=[];state.busy=false;state.user.role='user'`);
  assert.ok(!run('remoteTasksPanel(state.project)').includes('data-resolve-transcription'));
  nodes['#modal-root'].innerHTML='untouched';
  listeners.click({target:{closest:()=>({dataset:{resolveTranscription:'asr / pending'}})}});
  listeners.submit({target:asrForm,preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(nodes['#modal-root'].innerHTML,'untouched');
  assert.equal(run('saved.length'),0, 'An owned non-admin project cannot forge ASR association.');
  run(`state.user.role='admin';state.project.can_edit=false`);
  assert.ok(!run('remoteTasksPanel(state.project)').includes('data-resolve-transcription'));
  listeners.click({target:{closest:()=>({dataset:{resolveTranscription:'asr / pending'}})}});
  listeners.submit({target:asrForm,preventDefault(){}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(nodes['#modal-root'].innerHTML,'untouched');
  assert.equal(run('saved.length'),0, 'ASR association obeys explicit read-only project permission.');
}

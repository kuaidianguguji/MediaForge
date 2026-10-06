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
  structuredClone, setTimeout: () => 0, clearTimeout: () => {},
  FormData: class { constructor(form) { this.values = Object.entries(form.values); } [Symbol.iterator]() { return this.values[Symbol.iterator](); } },
});
const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8').replace(/\ninit\(\);\s*$/, '');
vm.runInContext(source, context);
const run = code => vm.runInContext(code, context);
run(`state.project={id:'p',name:'Product',status:'ready',options:{},assets:[{id:'r',role:'reference'},{id:'p',role:'product'}],segments:[],jobs:[],analysis:{summary:'Plan',product_identity:'Target',product_profile:{features:['<img src=x onerror=alert(1)>'],parts:['control'],known_views:['front'],unknowns:['rear'],forbidden_traits:['old display']},sampling:{limited:true},shots:[{start:0,end:5,description:'Close-up',product_visibility:'partial',visible_parts:['control'],interaction:'press',missing_views:['back view'],constraints:['no display'],strategy:'needs_reference',reference_image_indices:[0]}],segments:[{start:0,duration:5,prompt:'P',strategy:'needs_reference',shot_indices:[0],reference_image_indices:[0],repair_prompt:''}]}};`);
let html = run('projectPage()');
assert.ok(html.includes('back view'), 'Missing references must be visible.');
assert.ok(html.includes('局部特写'), 'Partial product visibility must be visible.');
assert.ok(html.includes('部分片段需要补图'), 'Generation must explain missing references.');
assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'), 'Model text must be HTML escaped.');
assert.ok(!html.includes('<img src=x onerror=alert(1)>'));
assert.ok(html.includes('重新分析素材'));
assert.ok(html.includes('id="asset-form"'), 'Ready projects without segments can add references.');
assert.match(run('strategyOptions()'), /value="keyframe"[^>]*disabled/, 'Missing image model disables keyframe selection.');

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
run(`state.project.segments=[];state.project.status='ready';state.project.output_asset_id=null;globalThis.saved=[];api=async(path,options)=>{saved.push({path,options});return {}};navigate=async()=>{};toast=()=>{};`);
const form = { id:'plan-form', values:{'prompt-0':'Updated','strategy-0':'adapt','repair-0':'Use real control','voice-0':'V','subtitle-0':'S'}, querySelector:()=>null };
listeners.submit({target:form,preventDefault(){}});
setImmediate(()=>{
  const saved = JSON.parse(run('JSON.stringify(saved[0].options.body.analysis)'));
  assert.equal(saved.segments[0].strategy,'adapt');
  assert.equal(saved.segments[0].repair_prompt,'Use real control');
  assert.deepEqual(saved.segments[0].shot_indices,[0]);
  assert.deepEqual(saved.segments[0].reference_image_indices,[0]);
  assert.deepEqual(saved.product_profile.parts,['control']);
  assert.equal(saved.shots[0].product_visibility,'partial');
  console.log('Frontend offline checks passed.');
});

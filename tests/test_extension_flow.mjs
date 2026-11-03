// El reloj, las API y las páginas son simulados. No es una prueba de Cloudflare real.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {CollectorEngine,ALARM} from '../extension_navegador/engine.mjs';
import {BASE,buildArchive} from '../extension_navegador/core.mjs';
import {exportBlob} from '../extension_navegador/export.mjs';

function snapshot(page,image=null){
 const first=(page-1)*5+1;
 const result={kind:'questions',page,per_page:5,total:349,total_pages:70,topics:[],series:[],case_studies:[],items:Array.from({length:Math.min(5,350-first)},(_,i)=>({id:first+i,order:first+i,question_text:'Pregunta sintética '+(first+i),solution_text:'Explicación sintética',choices:[{letter:'A',text:'Opción sintética',is_correct:true}],type_data:{}}))};
 if(image&&page===1)result.items[0].question_text+='<img src="'+image+'">';
 return {url:BASE+page,html:'<!doctype html><title>Prueba sintética</title>',scripts:['let x={data:'+JSON.stringify({result})+'}'],dom:result,currentImages:[],captured_at:'2026-11-02T12:00:00Z'};
}
function harness(options={}){
 const saved=structuredClone(options.saved||{}),events=[],reads=new Map(),tabs=new Map([[1,{id:1,url:BASE+'1',status:'complete',active:true,autoDiscardable:true,windowId:2}]]),alarms=new Map(),downloads=new Map();
 let clock=100000,locks=options.locks||0,downloadId=0;
 const state={};
 const api={
  storage:{local:{async get(k){return structuredClone(k==null?saved:{[k]:saved[k]});},async set(v){if(options.failSave&&Object.keys(v).some(k=>k.startsWith('page:')))throw Error('No se pudo guardar la página');Object.assign(saved,structuredClone(v));events.push({kind:'save',keys:Object.keys(v)});},async remove(k){delete saved[k];}}},
  power:{requestKeepAwake(level){events.push({kind:'power',level});},releaseKeepAwake(){events.push({kind:'power-release'});}},
  alarms:{async create(name,value){alarms.set(name,value);events.push({kind:'alarm',name,value});},async clear(name){alarms.delete(name);}},
  tabs:{async get(id){if(!tabs.has(id))throw Error('No tab with id: '+id);return {...tabs.get(id)};},async query(){return [...tabs.values()].map(t=>({...t}));},async create(v){const id=tabs.size?Math.max(...tabs.keys())+1:2;const tab={id,windowId:2,status:'complete',autoDiscardable:true,...v};tabs.set(id,tab);events.push({kind:'create',id});return {...tab};},async update(id,v){const tab=tabs.get(id);if(!tab)throw Error('No tab with id: '+id);const target=Number((v.url||tab.url).match(/\d+$/)[0]);if(target===(options.busyPage||27)&&locks>0){locks--;events.push({kind:'tab-lock'});throw Error('Tabs cannot be edited right now (user may be dragging a tab).');}if(options.permanentTabError)throw Error('Permission denied');Object.assign(tab,v);events.push({kind:'tab-update',id,change:{...v}});return {...tab};}},
  windows:{async update(){}},permissions:{async contains(){return true;}},
  scripting:{async executeScript({target,func,args}){const tab=tabs.get(target.tabId),page=Number(tab.url.match(/\d+$/)[0]);assert.equal(func.name,'captureExamPage');assert.equal(args[0],page);reads.set(page,(reads.get(page)||0)+1);events.push({kind:'capture',page,expand:args[1]});if(options.failedPage===page)return [{result:{verification:{label:'Verification Failed',failed:true,code:'600010'}}}];if(options.waitForever===page||(options.everyThree&&page%3===0&&reads.get(page)<=3))return [{result:{url:tab.url,verification:{label:"Checking That You're Human",failed:false,code:null}}}];return [{result:options.fixture ? options.fixture(page,tab.url) : snapshot(page,options.image)}];}},
  downloads:{async search({id}){return downloads.has(id)?[{...downloads.get(id)}]:[];}}
 };
 const make=()=>new CollectorEngine(api,{now:()=>clock,sleep:async ms=>{clock+=ms;},setTimer:()=>1,clearTimer:()=>{},exportZip:async()=>{const id=++downloadId;downloads.set(id,{id,state:'complete'});events.push({kind:'export',id});return id;},closeExport:async()=>events.push({kind:'close-export'})});
 let engine=make();
 async function drive(limit=1200,restart=false){for(let i=0;i<limit&&saved.collectorJob?.running;i++){if(restart)engine=make();clock=Math.max(clock,saved.collectorJob.due||clock);await engine.wake();}return saved.collectorJob;}
 return {saved,events,tabs,reads,alarms,downloads,api,state,drive,make,get engine(){return engine;},advance(ms){clock+=ms;}};
}

test('70 páginas y 349 preguntas con comprobaciones cada tres páginas, sin panel',async()=>{
 const h=harness({everyThree:true});await h.engine.start({delay:60});await h.drive();
 assert.equal(h.saved.collectorJob.phase,'finished');assert.equal(h.saved.collectorJob.running,false);
 assert.equal(Object.keys(h.saved).filter(k=>k.startsWith('page:')).length,70);
 assert.equal(h.events.filter(e=>e.kind==='export').length,1);
 assert(h.saved.runLog.some(t=>t.includes('se continúa automáticamente')));
 assert(h.saved.runLog.some(t=>t.includes('Descarga del ZIP completada')));
 assert.equal(h.tabs.get(1).autoDiscardable,true);assert(!h.alarms.has(ALARM));
});
test('pestaña bloqueada dos veces: reintenta y termina sin Reanudar',async()=>{
 const h=harness({locks:2,busyPage:27});await h.engine.start();await h.drive();
 assert.equal(h.events.filter(e=>e.kind==='tab-lock').length,2);assert.equal(h.saved.collectorJob.phase,'finished');assert(h.saved['page:27']);
});
test('bloqueo prolongado: checkpoint y alarma reanudan el mismo paso',async()=>{
 const h=harness({locks:8,busyPage:1});await h.engine.start();await h.engine.wake();
 assert.equal(h.saved.collectorJob.running,true);assert(h.saved.collectorJob.message.includes('automáticamente'));assert(h.alarms.has(ALARM));assert(!h.saved['page:1']);
 await h.drive(1200,true);assert.equal(h.saved.collectorJob.phase,'finished');assert(h.saved['page:1']);
});
test('reiniciar el worker en cada alarma conserva avance y no duplica páginas',async()=>{
 const h=harness();await h.engine.start({delay:90});await h.drive(1200,true);
 assert.equal(h.saved.collectorJob.phase,'finished');assert.equal(h.events.filter(e=>e.kind==='capture'&&e.page===1&&e.expand).length,1);
 assert.equal(h.events.filter(e=>e.kind==='export').length,1);
});
test('pausa explícita se mantiene tras reiniciar; libera energía y no navega',async()=>{
 const h=harness();await h.engine.start();await h.engine.wake();await h.engine.pause();const count=h.events.length;await h.make().wake();
 assert.equal(h.saved.collectorJob.phase,'paused');assert.equal(h.events.length,count);assert(!h.alarms.has(ALARM));assert(h.events.some(e=>e.kind==='power-release'));
});
test('error real de verificación detiene y no navega a páginas posteriores',async()=>{
 const h=harness({failedPage:2});await h.engine.start();await h.drive();
 assert(h.saved['page:1']);assert(!h.saved['page:2']);assert(!h.saved['page:3']);assert.equal(h.saved.collectorJob.phase,'blocked');assert(h.saved.collectorJob.error.includes('600010'));
});
test('espera persistente sólo observa la página; no recarga ni repite la navegación',async()=>{
 const h=harness({waitForever:1});await h.engine.start();await h.drive();
 assert.equal(h.saved.collectorJob.phase,'blocked');assert(h.saved.collectorJob.error.includes('tres minutos'));
 assert.equal(h.events.filter(e=>e.kind==='tab-update'&&e.change.url).length,0);
});
test('fallo al guardar no avanza ni declara página guardada',async()=>{
 const h=harness({failSave:true});await h.engine.start();await h.drive();
 assert(!h.saved['page:1']);assert(!h.saved['page:2']);assert.equal(h.saved.collectorJob.phase,'blocked');assert(h.saved.collectorJob.error.includes('guardar'));
});
test('al cerrar la pestaña de contenido recupera otra y conserva las páginas',async()=>{
 const h=harness();await h.engine.start();await h.engine.wake();assert(h.saved['page:1']);h.tabs.clear();await h.drive();
 assert.equal(h.saved.collectorJob.phase,'finished');assert(h.events.some(e=>e.kind==='create'));
});
test('gran salto de reloj reanuda desde el checkpoint sin repetir el guardado',async()=>{
 const h=harness();await h.engine.start();await h.engine.wake();h.advance(42*60000);await h.drive();
 assert.equal(h.saved.collectorJob.phase,'finished');assert(h.saved.runLog.some(t=>t.includes('espera prolongada')));
 assert.equal(h.events.filter(e=>e.kind==='capture'&&e.page===1&&e.expand).length,1);
});
test('mantener despierto es configurable y se libera al terminar',async()=>{
 const h=harness();await h.engine.start({keepAwake:false});await h.drive();assert(!h.events.some(e=>e.kind==='power'));
 const g=harness();await g.engine.start({keepAwake:true});await g.drive();assert(g.events.some(e=>e.kind==='power'&&e.level==='display'));assert(g.events.some(e=>e.kind==='power-release'));
});
test('349 ya guardadas: exporta y verifica descarga sin volver a recorrer la web',async()=>{
 const saved={};for(let page=1;page<=70;page++){const s=snapshot(page);saved['page:'+page]={number:page,html:s.html,extracted:{url:s.url,parser:'structured',payload:{result:s.dom},warnings:[]}};}
 const h=harness({saved});await h.engine.start();await h.drive();assert.equal(h.events.filter(e=>e.kind==='capture').length,0);assert.equal(h.events.filter(e=>e.kind==='export').length,1);assert.equal(h.saved.collectorJob.phase,'finished');
});
test('sin descarga automática libera recursos y conserva el resultado',async()=>{
 const h=harness();await h.engine.start({automatic:false});await h.drive();assert.equal(h.events.filter(e=>e.kind==='export').length,0);assert.equal(h.saved.collectorJob.phase,'finished');assert(!h.alarms.has(ALARM));
});
test('contextos iguales con claves en distinto orden no generan conflictos',()=>{
 const captures=[];for(let page=1;page<=70;page++){const s=snapshot(page);s.dom.topics=page%2?[{id:105,name:'Topic 1',order:1}]:[{order:1,name:'Topic 1',id:105}];captures.push({number:page,html:s.html,extracted:{url:s.url,parser:'structured',payload:{result:s.dom},warnings:[]}});}
 const data=buildArchive(captures);assert.equal(data.report.conflicts.length,0);assert.equal(data.report.coverage_complete,true);
 captures[3].extracted.payload.result.topics[0].name='Otro contenido';assert(buildArchive(captures).report.conflicts.length>0);
});
test('exportación incluye imágenes y diagnóstico con integridad verificable',async()=>{
 const h=harness({image:'data:image/png;base64,iVBORw0KGgo='});await h.engine.start();await h.drive();
 const blob=exportBlob(h.saved);writeFileSync(new URL('./extension_recorrido_verificacion.zip',import.meta.url),new Uint8Array(await blob.arrayBuffer()));
 assert.equal(Object.keys(h.saved).filter(k=>k.startsWith('image:')).length,1);
});
test('manifiesto contiene las API del proceso de fondo sin debugger/proxy/cookies',()=>{
 const m=JSON.parse(readFileSync(new URL('../extension_navegador/manifest.json',import.meta.url),'utf8'));
 for(const p of ['alarms','power','offscreen','downloads'])assert(m.permissions.includes(p));
 assert(!m.permissions.some(p=>['debugger','cookies','proxy'].includes(p)));assert.equal(m.version,'5.0.0');
});

test('integración del worker y documento de exportación: descarga sin panel y confirma finalización',async t=>{
 const saved={};for(let page=1;page<=70;page++){const s=snapshot(page);saved['page:'+page]={number:page,html:s.html,extracted:{url:s.url,parser:'structured',payload:{result:s.dom},warnings:[]}};}
 const h=harness({saved}),api=h.api;
 const event=()=>({listeners:[],addListener(fn){this.listeners.push(fn);},emit(...args){for(const fn of this.listeners)fn(...args);}});
 let offscreen=false,blob=null;
 api.runtime={id:'test-extension',onMessage:event(),onStartup:event(),onInstalled:event(),getURL:path=>'chrome-extension://test-extension/'+path,
  async getContexts(){return offscreen?[{}]:[];},
  sendMessage(message){return new Promise((resolve,reject)=>{let pending=false,answered=false;const reply=value=>{answered=true;resolve(value);};for(const fn of api.runtime.onMessage.listeners){try{if(fn(message,{id:api.runtime.id,url:api.runtime.getURL('panel.html')},reply)===true)pending=true;}catch(e){reject(e);}}if(!pending&&!answered)reject(Error('Receiving end does not exist'));});}
 };
 api.action={onClicked:event()};api.tabs.onUpdated=event();api.alarms.onAlarm=event();api.downloads.onChanged=event();
 api.offscreen={async createDocument(value){assert.deepEqual(value.reasons,['BLOBS']);offscreen=true;await import('../extension_navegador/offscreen.mjs?bridge');},async closeDocument(){offscreen=false;}};
 const {resolveObjectURL}=await import('node:buffer');
 api.downloads.download=async options=>{assert.equal(options.saveAs,false);blob=resolveObjectURL(options.url);h.downloads.set(73,{id:73,state:'complete'});queueMicrotask(()=>api.downloads.onChanged.emit({id:73,state:{current:'complete'}}));return 73;};
 const previous=globalThis.chrome;globalThis.chrome=api;t.after(()=>{globalThis.chrome=previous;});
 await import('../extension_navegador/background.js?bridge');
 const reply=await api.runtime.sendMessage({target:'worker',action:'start',settings:{automatic:true}});assert(reply.job.running);
 for(let n=0;n<100&&h.saved.collectorJob.phase!=='finished';n++)await new Promise(r=>setTimeout(r,10));
 assert.equal(h.saved.collectorJob.phase,'finished');assert.equal(h.saved.collectorJob.running,false);assert.equal(h.saved.collectorJob.downloadId,73);assert(blob instanceof Blob);assert.equal(offscreen,false);
 writeFileSync(new URL('./extension_worker_exportacion.zip',import.meta.url),new Uint8Array(await blob.arrayBuffer()));
});

test('otro examen detecta 12 preguntas, usa su propio banco y conserva el PDE antiguo',async()=>{
 const old=snapshot(1),oldCapture={number:1,html:old.html,extracted:{url:old.url,parser:'structured',payload:{result:old.dom},warnings:[]}};
 const h=harness({saved:{'page:1':oldCapture},fixture:(page,url)=>{
  if(!url.includes('/cisco/demo/'))return snapshot(page);
  const s=snapshot(page),first=(page-1)*5+1;
  Object.assign(s.dom,{total:12,total_pages:3,items:s.dom.items.slice(0,Math.min(5,13-first))});s.url=url;s.title='Cisco Demo Practice Questions | ExamBase';s.scripts=['let x={result:'+JSON.stringify(s.dom)+'}'];return s;
 }});
 await h.engine.selectExam('https://www.exambase.com/exams/cisco/demo');await h.engine.start();await h.drive();
 assert.equal(h.saved.selectedExam.total,12);assert.equal(h.saved.selectedExam.pages,3);assert.equal(h.saved.collectorJob.phase,'finished');
 assert.equal(Object.keys(h.saved).filter(k=>k.startsWith('exam:cisco/demo:page:')).length,3);
 assert.deepEqual(h.saved['page:1'],oldCapture);assert(!h.saved['page:2']);
 await h.engine.selectExam(BASE+'1');assert.equal(h.saved.selectedExam.total,349);assert.deepEqual(h.saved['page:1'],oldCapture);
});
test('seleccionar otro examen mientras hay un recorrido activo exige pausarlo',async()=>{
 const h=harness();await h.engine.start();await assert.rejects(()=>h.engine.selectExam('https://www.exambase.com/exams/cisco/demo'),/Pausa/);
 assert.equal(h.saved.selectedExam.key,'google/professional-data-engineer');
});

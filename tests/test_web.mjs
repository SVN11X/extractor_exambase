import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {downloadInputs,filterExams,summary,runStatus,bankStatus} from '../web/model.mjs';
import {GitHub} from '../web/github-api.mjs';
import {inspectBytes,readZip} from '../web/zip.mjs';
import {zipBytes,textFromHtml} from '../extension_navegador/core.mjs';
import {aiOutputs} from '../extension_navegador/ai.mjs';
const exam={id:'cisco/demo',url:'https://www.exambase.com/exams/cisco/demo',name:'Demo ágil',vendor:'Cisco',vendor_slug:'cisco',code:'DEMO'};
test('busca nombre, código y acentos sin confundir proveedores',()=>{
  assert.equal(filterExams([exam],'agil DEMO','cisco').length,1);assert.equal(filterExams([exam],'','microsoft').length,0);
});
test('inputs dinámicos usan la URL elegida y separan guardado de reanudación',()=>{
  const d=downloadInputs(exam,{mode:'selenium',delay:90,resume:'1234',save:true},'request');
  assert.equal(d.exam_url,exam.url+'/practice-questions/1');assert.equal(d.save_to_repo,'true');assert.equal(d.resume_run_id,'1234');
  for(const delay of [NaN,Infinity,0,121])assert.throws(()=>downloadInputs(exam,{mode:'browser',delay,resume:'',save:false},'x'));
  assert.throws(()=>downloadInputs(exam,{mode:'http',delay:10,resume:'$(cmd)',save:false},'x'));
});
test('una ejecución exitosa no se presenta como validación de contenido',()=>{
  assert.equal(runStatus({status:'completed',conclusion:'success'}).text,'Ejecución terminada');
  assert.match(runStatus({status:'completed',conclusion:'failure'}).text,/parcial/);
});
test('runner propio se envía explícitamente y se rechazan entornos desconocidos',()=>{
  const d=downloadInputs(exam,{mode:'selenium',delay:10,resume:'41558984612',save:true,runner:'self-hosted'},'request');
  assert.equal(d.runner,'self-hosted');assert.equal(d.resume_run_id,'41558984612');
  assert.throws(()=>downloadInputs(exam,{mode:'selenium',delay:10,resume:'',runner:'external'},'request'),/entorno/i);
});
test('el historial distingue un rechazo de acceso de cobertura parcial',()=>{
  assert.equal(bankStatus({status:'blocked',failure:{code:'600010'},coverage_complete:false}).text,'Acceso bloqueado · 600010');
  assert.equal(bankStatus({coverage_complete:false}).text,'Cobertura parcial');
  assert.equal(bankStatus({coverage_complete:true}).text,'Cobertura completa');
});
test('API mantiene el token fuera de propiedades públicas, rutas y errores',async()=>{
  const calls=[]; const api=new GitHub('usuario','repo','TEST_SECRET',async(url,options)=>{calls.push({url,options});return {ok:true,status:204};});
  api.branch='main';await api.dispatch('descargar-examen.yml',{exam_url:exam.url});
  assert.equal(calls[0].options.headers.Authorization,'Bearer TEST_SECRET');assert.equal(calls[0].options.redirect,'error');
  assert(!JSON.stringify(api).includes('TEST_SECRET'));assert(!calls[0].url.includes('TEST_SECRET'));
  await assert.rejects(()=>api.request('/user'),/Ruta/);assert.throws(()=>api.bankUrl('bancos/../secreto.zip'));
  api.disconnect();await api.dispatch('descargar-examen.yml',{});assert.equal(calls[1].options.headers.Authorization,'Bearer ');
});
test('inspector distingue cobertura, explicación ausente y archivo de imagen faltante',()=>{
  const data={questions:[{number:1,correct_choices:['B'],explanation_text:''}],report:{expected_questions:1,missing_pages:[]},assets:{x:{local_path:'imagenes/x.png'}}};
  const r=summary(data,new Set());assert(r.coverage);assert.deepEqual(r.missingExplanations,[1]);assert.deepEqual(r.missingFiles,['imagenes/x.png']);
  assert(!summary({...data,questions:[data.questions[0],data.questions[0]]}).coverage);
});
test('inspector abre ZIP de extensión y el contenedor adicional de Actions',async()=>{
  const data={questions:[],report:{}};
  const inner=new Uint8Array(await zipBytes([{name:'resultado/preguntas.json',data:JSON.stringify(data)}]).arrayBuffer());
  const outer=new Uint8Array(await zipBytes([{name:'resultado.zip',data:inner}]).arrayBuffer());
  assert.deepEqual((await inspectBytes(inner)).data,data);assert.deepEqual((await inspectBytes(outer)).data,data);
});
test('ZIP rechaza rutas fuera del paquete y CRC dañado',async()=>{
  const bad=new Uint8Array(await zipBytes([{name:'../escape.json',data:'{}'}]).arrayBuffer());await assert.rejects(()=>readZip(bad),/rutas/);
  const corrupt=new Uint8Array(await zipBytes([{name:'preguntas.json',data:'{}'}]).arrayBuffer());corrupt[44]^=1;await assert.rejects(()=>inspectBytes(corrupt),/integridad/);
});
test('JSONL conserva imágenes por opción, id ausente y explicación pendiente',()=>{
  assert.equal(textFromHtml('<p>actor=<actorname> o <timestamp>#<sensorid></sensorid></timestamp></actorname></p>'),'actor=<actorname> o <timestamp>#<sensorid>');
  const data={exam:{key:'cisco/demo'},questions:[{number:1,id:null,question_text:'Pregunta',choices:[],correct_choices:['A'],answer_status:'explicit_choices',image_refs:[{asset_id:'a',field:'choices[0].text'}],context_refs:[],type_data:{},sources:[],raw:{}}],assets:{a:{local_path:'imagenes/a.png'}}};
  const q=JSON.parse(aiOutputs(data).jsonl);assert.equal(q.stable_id,'cisco/demo:q:00001');assert.equal(q.source_id,null);assert.equal(q.explanation.status,'missing');assert.equal(q.images[0].field,'choices[0].text');assert.equal(q.images[0].review_required,true);
});
test('frontend usa rutas relativas y nunca persiste el token',()=>{
  const html=readFileSync(new URL('../web/index.html',import.meta.url),'utf8'),js=readFileSync(new URL('../web/app.mjs',import.meta.url),'utf8');
  assert(!/src="\//.test(html));assert(!/remember\(['"]token/.test(js));assert(!html.includes('cdn.'));assert(html.includes('https://api.github.com'));
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const script=readFileSync(new URL('../capture_page.js',import.meta.url),'utf8');

async function run({answerDelay=150,hydrateDelay=0}={}) {
  let clock=0,epoch=0;const answered=new Set(),pending=[],clicked=[];
  function card(id) {
    const birth=epoch,c={querySelector:sel=>sel==='.exambase-question__rich-text'?{textContent:'Question content'}:null};
    const title={textContent:'Question '+id,closest:()=>c};
    c.querySelectorAll=sel=>{
      if(sel==='h3,h4,h5')return [{textContent:'A topic'},title];
      if(sel.startsWith('.list-group-item'))return answered.has(id)?[{textContent:'Correct'}]:[];
      if(sel==='button')return answered.has(id)?[]:[{textContent:'Reveal Answer',disabled:false,getClientRects:()=>[{}],click(){
        assert.equal(birth,epoch,'El botón pertenece a un DOM sustituido');clicked.push(id);
        if(Number.isFinite(answerDelay))pending.push({at:clock+answerDelay,run(){answered.add(id);epoch++;}});
      }}];
      return [];
    };
    return {card:c,title};
  }
  const document={body:{textContent:'Showing 1–2 of 2'},documentElement:{outerHTML:'<main>fixture</main>'},
    querySelectorAll:()=>[1,...(clock>=hydrateDelay?[2]:[])].map(i=>card(i).title),querySelector:()=>({textContent:'Exam'})};
  const context={document,location:{href:'https://www.exambase.com/exams/cisco/demo/practice-questions/1'},Date:{now:()=>clock},
    setTimeout(callback,ms){clock+=ms;for(const task of [...pending])if(task.at<=clock){pending.splice(pending.indexOf(task),1);task.run();}queueMicrotask(callback);}};
  const options={page:1,expectedCount:2,waitMs:1000,revealMs:2000,imageMs:0,images:false};
  const value=await vm.runInNewContext(script.replace('__EXAMBASE_CAPTURE_OPTIONS__',JSON.stringify(options)),context);
  return {value:JSON.parse(value),clicked,clock};
}
test('cada respuesta espera datos y vuelve a localizar tarjetas reemplazadas por la SPA',async()=>{
  const {value,clicked}=await run();assert.deepEqual(clicked,[1,2]);assert.deepEqual(value.capture.unanswered,[]);
  assert.deepEqual(value.capture.attempts.map(a=>a.answerVisible),[true,true]);
});
test('la captura espera que se hidrate la segunda tarjeta',async()=>{
  const {value,clicked,clock}=await run({hydrateDelay:500});assert.deepEqual(clicked,[1,2]);assert(clock>=500);assert.deepEqual(value.capture.questions,[1,2]);
});
test('una respuesta que no llega tiene espera acotada y queda pendiente',async()=>{
  const {value,clicked,clock}=await run({answerDelay:Infinity});assert.deepEqual(clicked,[1]);assert(clock<4000);assert.deepEqual(value.capture.unanswered,[1,2]);
  assert.equal(value.capture.attempts[0].answerVisible,false);
});

import {filterExams,parseExamUrl,downloadInputs,runStatus,bankStatus,summary} from './model.mjs';
import {GitHub} from './github-api.mjs';
import {inspectBytes} from './zip.mjs';
const $=id=>document.getElementById(id), state={catalog:null,selected:null,api:null,tab:'runs',runs:[],banks:[],timer:null,busy:false,generation:0,pending:null,artifacts:new Map(),catalogRequest:null};
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n;};
const append=(parent,...children)=>{parent.append(...children);return parent;};
function saved(key,fallback) {try {return JSON.parse(localStorage.getItem('archivo:'+key)) || fallback;}catch{return fallback;}}
function remember(key,value) {try{localStorage.setItem('archivo:'+key,JSON.stringify(value));}catch{}}
function notice(message,error=false) {$('notice').textContent=message;$('notice').hidden=!message;$('notice').classList.toggle('error',error);}
function route() {
  const view=['catalogo','descargas','revisar','ayuda'].includes(location.hash.slice(1))?location.hash.slice(1):'catalogo';
  document.querySelectorAll('.view').forEach(n=>n.hidden=n.id!=='view-'+view);
  document.querySelectorAll('[data-view]').forEach(n=>{n.classList.toggle('active',n.dataset.view===view);if(n.dataset.view===view)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');});
}
function choose(exam) {state.selected=exam;remember('selected',exam.id);remember('selected-config',exam);$('selected-title').textContent=exam.name;$('selected-vendor').textContent=exam.vendor;$('selected-count').textContent=exam.questions?`${exam.questions} preguntas en el índice · se confirma al iniciar`:'El total se detecta al iniciar';renderCatalog();}
function renderCatalog() {
  if(!state.catalog)return;
  const focusLabel=document.activeElement?.getAttribute('aria-label');
  const exams=filterExams(state.catalog.exams,$('search').value,$('vendor').value),grid=$('exam-grid');grid.replaceChildren();
  for(const exam of exams.slice(0,120)) {
    const card=el('article','exam-card'+(state.selected?.id===exam.id?' selected':'')),top=el('div','exam-top'),bottom=el('div','exam-bottom'),button=el('button','select-exam',state.selected?.id===exam.id?'✓':'→');
    button.type='button';button.setAttribute('aria-label','Elegir '+exam.name);button.setAttribute('aria-pressed',String(state.selected?.id===exam.id));button.addEventListener('click',()=>choose(exam));
    append(top,el('span','vendor-icon',exam.vendor.slice(0,1)),el('span','exam-vendor',exam.vendor));
    append(bottom,el('span','question-meta',exam.questions?`${exam.questions.toLocaleString('es')} preguntas`:'Total por detectar'),button);
    append(card,top,el('h3','',exam.name),el('p','exam-code',exam.code || ''),bottom);grid.append(card);
  }
  $('catalog-empty').hidden=!!exams.length;$('catalog-caption').textContent=`${exams.length} ${exams.length===1?'examen disponible':'exámenes disponibles'}${exams.length>120?' · se muestran los primeros 120; afina tu búsqueda':''}`;
  document.querySelectorAll('[data-vendor]').forEach(n=>{n.classList.toggle('active',n.dataset.vendor===$('vendor').value);n.setAttribute('aria-pressed',String(n.dataset.vendor===$('vendor').value));});
  if(focusLabel)[...grid.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')===focusLabel)?.focus({preventScroll:true});
}
function loadCatalog(data) {
  if(!Array.isArray(data.exams)||!Array.isArray(data.vendors))throw Error('El catálogo no tiene el formato esperado.');
  const valid=data.exams.filter(e=>{try{return parseExamUrl(e.url).key===e.id && typeof e.name==='string' && typeof e.vendor==='string';}catch{return false;}});
  state.catalog={...data,exams:valid};const old=$('vendor').value;$('vendor').replaceChildren(new Option('Todos los proveedores','all'));
  for(const vendor of data.vendors) $('vendor').append(new Option(vendor.vendor,vendor.slug));
  if([...$('vendor').options].some(o=>o.value===old))$('vendor').value=old;
  $('vendor-count').textContent=data.vendors.length;$('exam-count').textContent=valid.length;
  $('catalog-info').textContent=`Lista actualizada: ${String(data.updated_at || 'sin fecha').slice(0,10)}. ${data.complete?'Catálogo cargado.':'La lista aún es parcial.'} Puedes pegar el enlace de cualquier examen admitido.`;
  let prior=valid.find(e=>e.id===saved('selected',''));
  if(!prior){const custom=saved('selected-config',null);try{if(custom && parseExamUrl(custom.url).key===custom.id && typeof custom.name==='string' && typeof custom.vendor==='string')prior=custom;}catch{}}
  if(!state.selected && prior)choose(prior);else renderCatalog();
}
function openConnect() {$('connect-error').textContent='';$('connect-dialog').showModal();}
function disconnected() {
  state.api?.disconnect();state.api=null;state.generation++;clearTimeout(state.timer);state.runs=[];state.banks=[];state.pending=null;state.artifacts.clear();state.catalogRequest=null;
  $('token').value='';$('connect').textContent='Conectar GitHub ↗';$('repo-label').textContent='Tu repositorio, tu material';$('side-status').textContent='Sin conectar';$('side-status').classList.remove('connected');$('save-repo').checked=false;$('save-hint').textContent='Conecta tu repositorio para conservar cada ejecución.';renderResults();
}
async function connect(event) {
  event.preventDefault();const submit=event.submitter;submit.disabled=true;
  try {
    const api=new GitHub($('owner').value.trim(),$('repo').value.trim(),$('token').value.trim()), info=await api.connect();
    disconnected();state.api=api;remember('repo',{owner:api.owner,repo:api.repo});$('token').value='';
    $('repo-label').textContent=info.full_name;$('connect').textContent='Conectado · Ajustes';$('side-status').textContent='GitHub conectado';$('side-status').classList.add('connected');
    $('save-repo').checked=!!info.private;$('save-hint').textContent=info.private?'Cada ejecución quedará versionada en bancos/ de tu repositorio privado.':'Este repositorio es público: los bancos guardados serán visibles en GitHub. Puedes conservar sólo el artefacto temporal.';
    $('connect-dialog').close();notice('Repositorio conectado. Ya puedes preparar un examen.');await refresh();
  } catch(error) {$('connect-error').textContent=error.message;}finally{submit.disabled=false;}
}
function link(text,url,cls='btn secondary') {const n=el('a',cls,text);n.href=url;n.target='_blank';n.rel='noopener noreferrer';return n;}
function renderResults() {
  const list=$('run-list');list.replaceChildren();const api=state.api;
  $('show-runs').classList.toggle('active',state.tab==='runs');$('show-banks').classList.toggle('active',state.tab==='banks');
  $('nav-run-count').textContent=state.runs.filter(r=>r.status!=='completed').length;
  $('saved-count').textContent=state.banks.length;
  if(!api){$('runs-empty').hidden=false;$('sync-info').textContent='Conecta GitHub para consultar tus resultados.';return;}
  const items=state.tab==='runs'?state.runs:state.banks;
  $('runs-empty').hidden=items.length>0 || !!state.pending;
  if(state.pending) {const card=el('article','run-card');append(card,el('div','',`Solicitud aceptada: ${state.pending.name}. Esperando a que GitHub publique la ejecución…`));list.append(card);}
  for(const item of items) {
    const run=state.tab==='runs',status=run?runStatus(item):bankStatus(item),card=el('article','run-card'),body=el('div'),links=el('div','run-links');
    const title=run ? (saved('requests',{})[item.display_title?.match(/\[([\w-]+)\]/)?.[1]]?.name || item.display_title?.split(' [')[0] || 'Descarga de examen') : item.exam?.name || item.exam_key;
    append(body,el('span','badge '+status.style,status.text),el('h3','',title),el('p','run-meta',run?`Ejecución #${item.run_number} · ${new Date(item.created_at).toLocaleString('es')}`:`${item.questions} preguntas · ${new Date(item.generated_at).toLocaleString('es')}`));
    if(run) {
      links.append(link('Ver ejecución ↗',api.url(`actions/runs/${item.id}`),'text-btn'));
      for(const artifact of item.artifacts || []) if(artifact.name==='exambase-resultado' && !artifact.expired && new Date(artifact.expires_at)>new Date())links.append(link('Descargar ZIP ↓',api.artifactUrl(item.id,artifact.id),'btn primary'));
      if(item.status==='completed' && !item.artifacts?.some(a=>!a.expired && a.name==='exambase-resultado' && new Date(a.expires_at)>new Date()))body.append(el('p','run-meta','El artefacto no está disponible o ya caducó. Consulta la ejecución o los bancos guardados.'));
      if(item.status==='completed'){const b=el('button','text-btn','Reanudar desde aquí');b.addEventListener('click',()=>{$('resume-id').value=item.id;location.hash='catalogo';notice('ID de respaldo seleccionado. Elige el mismo examen antes de iniciar.');});links.append(b);}
      if(status.active)body.append(el('div','run-status-bar'));
    } else {try {links.append(link('Descargar ZIP ↓',api.bankUrl(item.zip_path),'btn primary'));}catch(error){body.append(el('p','error-text',error.message));} if(item.review_pending)body.append(el('p','run-meta','Hay contenido que requiere revisión. Consulta el informe incluido.')); const again=el('button','text-btn','Volver a preparar');again.addEventListener('click',()=>{try{const exam=parseExamUrl(item.exam.base+'1');choose({id:exam.key,url:exam.base+'1',name:item.exam.name || exam.name,vendor:item.exam.vendor || exam.vendor,vendor_slug:exam.vendor,questions:item.exam.total});$('resume-id').value='';location.hash='catalogo';}catch(error){notice(error.message,true);}});links.append(again);}
    if(!run && item.failure){body.append(el('p','run-meta',`Acceso rechazado en página ${item.failure.page ?? '?'}. Próxima página pendiente: ${item.next_page ?? 'revisar informe'}.`));const resume=el('button','text-btn','Reanudar este banco');resume.addEventListener('click',()=>{try{const exam=parseExamUrl(item.exam.base+'1');choose({id:exam.key,url:exam.base+'1',name:item.exam.name || exam.name,vendor:item.exam.vendor || exam.vendor,vendor_slug:exam.vendor,questions:item.exam.total});if(!/^\d+$/.test(item.run_id))throw Error('El banco no conserva un ID de ejecución válido.');$('resume-id').value=item.run_id;location.hash='catalogo';notice('Se seleccionó el examen y su respaldo. Elige el entorno de ejecución antes de continuar.');}catch(error){notice(error.message,true);}});links.append(resume);}
    append(card,body,links);list.append(card);
  }
}
async function refresh() {
  const api=state.api,generation=state.generation;if(!api||state.busy)return;state.busy=true;clearTimeout(state.timer);
  try {
    const result=await api.runs();const runs=result.workflow_runs || [];
    await Promise.all(runs.filter(r=>r.status==='completed').map(async r=>{const cache=state.artifacts.get(r.id);if(cache && Date.now()-cache.time<60000){r.artifacts=cache.values;return;}try{r.artifacts=(await api.artifacts(r.id)).artifacts;state.artifacts.set(r.id,{time:Date.now(),values:r.artifacts});}catch{r.artifacts=[];}}));
    let banks=[];try{banks=(await api.content('bancos/index.json')).runs || [];}catch(error){if(!error.message.startsWith('No se encontró'))throw error;}
    if(generation!==state.generation)return;state.runs=runs;state.banks=banks;
    if(state.pending && runs.some(r=>r.display_title?.includes(state.pending.id)))state.pending=null;
    if(state.pending && Date.now()-state.pending.time>180000){notice('GitHub aceptó la solicitud, pero aún no aparece. Abre Actions en tu repositorio para comprobar la cola.');state.pending=null;}
    $('sync-info').textContent=`Última consulta: ${new Date().toLocaleTimeString('es')} · Los enlaces de descarga pueden requerir que inicies sesión en GitHub.`;
    renderResults();
  }catch(error){if(generation===state.generation)notice(error.message,true);}finally{state.busy=false;if(state.api)state.timer=setTimeout(refresh,document.hidden?60000:15000);}
}
async function start() {
  if(!state.selected){notice('Elige un examen del catálogo o pega su enlace.',true);return;}
  if(!state.api){openConnect();return;}
  $('start').disabled=true;
  try {
    const id=crypto.randomUUID(),inputs=downloadInputs(state.selected,{mode:$('engine').value,delay:$('delay').value,resume:$('resume-id').value,save:$('save-repo').checked,runner:$('runner').value},id);
    await state.api.dispatch('descargar-examen.yml',inputs);state.pending={id,name:state.selected.name,time:Date.now()};
    const requests=saved('requests',{});requests[id]={name:state.selected.name,exam:state.selected.id};remember('requests',Object.fromEntries(Object.entries(requests).slice(-100)));
    location.hash='descargas';notice('Solicitud enviada a GitHub. Puedes cerrar la página; la ejecución continuará en Actions.');renderResults();await refresh();
  }catch(error){notice(error.message,true);}finally{$('start').disabled=false;}
}
async function updateCatalog() {
  if(!state.api){openConnect();return;}$('update-catalog').disabled=true;
  try {
    // Primero recupera el catálogo persistido; después solicita su actualización.
    try {const remote=await state.api.content('web/data/catalog.json'),changed=remote.updated_at!==state.catalog?.updated_at;loadCatalog(remote);if(changed){state.catalogRequest=null;notice('Catálogo guardado cargado desde tu repositorio.');return;}}catch{}
    if(state.catalogRequest && Date.now()-state.catalogRequest<600000){notice('La actualización ya se solicitó. Espera a que termine en Actions y vuelve a cargar el catálogo.');return;}
    await state.api.dispatch('actualizar-catalogo.yml',{vendor:$('vendor').value,delay:'5'});
    state.catalogRequest=Date.now();
    notice('Actualización del catálogo solicitada. Cuando termine en Actions, vuelve a pulsar este botón para cargar la lista guardada.');
  }catch(error){notice(error.message,true);}finally{$('update-catalog').disabled=false;}
}
async function inspect(event) {
  const file=event.target.files[0];if(!file)return;const target=$('inspection');target.hidden=false;target.replaceChildren(el('p','muted','Comprobando el archivo…'));
  try {
    if(file.size>100*1024**2)throw Error('El archivo supera 100 MB. Extrae el ZIP y elige preguntas.json.');
    const parsed=file.name.toLowerCase().endsWith('.json')?{data:JSON.parse(await file.text()),files:null}:await inspectBytes(new Uint8Array(await file.arrayBuffer()));
    const result=summary(parsed.data,parsed.files),grid=el('div','review-grid');
    for(const [n,label] of [[`${result.questions}/${result.expected??'?'}`,'preguntas conservadas'],[`${result.answersPresent}/${result.questions}`,'respuestas conservadas'],[result.images,'imágenes detectadas']])append(grid,append(el('div','review-stat'),el('strong','',n),el('span','',label)));
    const details=el('div','review-details'),list=el('ul');append(details,el('h2','',result.coverage?'Cobertura de preguntas completa':'Cobertura incompleta o sin confirmar'));
    const lines=[`Preguntas sin respuesta conservada: ${result.answersMissing.join(', ') || 'ninguna'}.`,`Respuestas conservadas como imagen: ${result.answerImages.length}; requieren revisión.`,`Explicaciones ausentes en el contenido conservado: ${result.missingExplanations.length}.`,`Contextos de preguntas que requieren revisión: ${result.contextReview.length}.`,`Conflictos: ${result.conflicts.length}. Errores registrados: ${result.errors.length}.`,parsed.files?`Archivos de imagen presentes en el ZIP: ${result.imagesPresent}/${result.images}. Pendientes: ${result.missingFiles.length}. Integridad CRC comprobada.`:'Carga el ZIP para comprobar los archivos de imagen asociados a este JSON.',`Las ${result.images} imágenes requieren revisión visual, incluso si contienen OCR. La integridad no valida la corrección de las respuestas.`];
    for(const line of lines)list.append(el('li','',line));if(result.formattingReview.length)list.append(el('li','',`Marcadores del HTML cuyo formato requiere revisión: preguntas ${result.formattingReview.map(q=>q.question).join(', ')}.`));if(result.missingExplanations.length)list.append(el('li','',`Sin explicación conservada: ${result.missingExplanations.join(', ')}.`));
    details.append(list);target.replaceChildren(grid,details);
  }catch(error){target.replaceChildren(el('p','notice error',error.message));}
}
$('connect').addEventListener('click',openConnect);$('connect-close').addEventListener('click',()=>$('connect-dialog').close());$('connect-form').addEventListener('submit',connect);
$('disconnect').addEventListener('click',()=>{disconnected();$('connect-dialog').close();notice('Conexión cerrada y token borrado de la memoria.');});
for(const id of ['custom-open','empty-custom'])$(id).addEventListener('click',()=>{$('custom-error').textContent='';$('custom-dialog').showModal();});
$('custom-close').addEventListener('click',()=>$('custom-dialog').close());$('custom-form').addEventListener('submit',event=>{event.preventDefault();try {const exam=parseExamUrl($('custom-url').value);choose({id:exam.key,url:exam.base+'1',name:exam.name,vendor:exam.vendor,vendor_slug:exam.vendor,questions:null});$('custom-dialog').close();notice('Examen seleccionado. El total de preguntas se detectará durante la ejecución.');}catch(error){$('custom-error').textContent=error.message;}});
$('start').addEventListener('click',start);$('search').addEventListener('input',renderCatalog);$('vendor').addEventListener('change',renderCatalog);
$('runner').addEventListener('change',()=>{$('runner-hint').textContent=$('runner').value==='self-hosted'?'Requiere un runner con etiqueta exambase y equipo encendido. Los motores de navegador usan pantalla gráfica; los solvers usan su servicio local.':'GitHub puede ejecutar la descarga sin tu ordenador. Una verificación de acceso puede dejar un resultado parcial.';});
$('engine').addEventListener('change',()=>{const hints={'scrapling':'Scrapling mantiene una sesión y captura respuestas de API y objetos referenciados. En GitHub se prepara su navegador automáticamente.','flaresolverr-next':'Next utiliza una sesión para preguntas, respuestas e imágenes. Requiere Docker; en GitHub se inicia automáticamente.','rebrowser':'Usa los parches de Rebrowser con Chrome. En GitHub se ejecuta con pantalla virtual.','flaresolverr':'El motor clásico entrega HTML. Las imágenes conservan el User-Agent y las cookies del solver; las respuestas dinámicas pueden quedar pendientes.','cloudproxy':'Compatibilidad con una instancia local existente de CloudProxy. Requiere runner propio; no se instala automáticamente.','browser':'Playwright estándar; conserva una sesión durante la ejecución.','selenium':'Selenium estándar, con navegación mediante los enlaces del examen.','http':'Lectura de HTML, sin ejecución de JavaScript.'};$('engine-hint').textContent=hints[$('engine').value];});
$('diagnose-browser').addEventListener('click',()=>{if(!state.api){openConnect();return;}window.open(state.api.url('actions/workflows/diagnosticar-navegador.yml'),'_blank','noopener,noreferrer');});
document.querySelectorAll('[data-vendor]').forEach(n=>n.addEventListener('click',()=>{$('vendor').value=n.dataset.vendor;renderCatalog();}));
$('show-runs').addEventListener('click',()=>{state.tab='runs';renderResults();});$('show-banks').addEventListener('click',()=>{state.tab='banks';renderResults();});$('refresh-runs').addEventListener('click',refresh);$('update-catalog').addEventListener('click',updateCatalog);$('inspect-file').addEventListener('change',inspect);
window.addEventListener('hashchange',route);document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
window.addEventListener('pagehide',disconnected);
const known=saved('repo',{});$('owner').value=known.owner || '';$('repo').value=known.repo || '';route();
try {const response=await fetch('./data/catalog.json',{cache:'no-cache'});if(!response.ok)throw Error('No se pudo cargar el catálogo.');loadCatalog(await response.json());}catch(error){notice(error.message,true);$('catalog-caption').textContent='Usa «Tengo el enlace» para seleccionar un examen.';}

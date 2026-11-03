import {parseExamUrl} from './lib/exam.mjs';
export {parseExamUrl};
export function repository(owner, repo) {
  if (!/^[a-zA-Z0-9][a-zA-Z0-9-]{0,38}$/.test(owner) || !/^[\w.-]{1,100}$/.test(repo) || ['.', '..'].includes(repo)) throw Error('Revisa el usuario y el nombre del repositorio.');
  return {owner, repo};
}
export function filterExams(exams, query='', vendor='all') {
  const normalize = s => String(s || '').normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase();
  const terms = normalize(query).split(/\s+/).filter(Boolean);
  return exams.filter(e => (vendor === 'all' || e.vendor_slug === vendor) && terms.every(t => normalize([e.name,e.code,e.vendor].join(' ')).includes(t)));
}
export function downloadInputs(exam, options, requestId) {
  const parsed = parseExamUrl(exam.url), delay = Number(options.delay), resume = options.resume.trim();
  if (!Number.isFinite(delay) || delay < 5 || delay > 120) throw Error('La pausa debe estar entre 5 y 120 segundos.');
  if (resume && !/^\d+$/.test(resume)) throw Error('El ID para reanudar debe contener sólo números.');
  if (!['browser','selenium','http'].includes(options.mode)) throw Error('Motor desconocido.');
  const runner=options.runner || 'github';if(!['github','self-hosted'].includes(runner))throw Error('Entorno de ejecución desconocido.');
  return {exam:'personalizado', exam_url:parsed.base+'1', exam_label:exam.name.slice(0,100), mode:options.mode, delay:String(delay), page_limit:'0', resume_run_id:resume, request_id:requestId, save_to_repo:String(!!options.save),runner};
}
export function runStatus(run) {
  if (run.status !== 'completed') return {text:run.status === 'in_progress' ? 'Preparando paquete' : 'En cola', style:'wait', active:true};
  return ({success:{text:'Ejecución terminada',style:''},failure:{text:'Revisar resultado parcial',style:'error'},cancelled:{text:'Cancelada',style:'neutral'},timed_out:{text:'Tiempo agotado',style:'error'}})[run.conclusion] || {text:run.conclusion || 'Terminada',style:'neutral'};
}
export function bankStatus(bank) {
  if(bank.status==='blocked')return {text:'Acceso bloqueado'+(bank.failure?.code?' · '+bank.failure.code:''),style:'error'};
  return {text:bank.coverage_complete?'Cobertura completa':'Cobertura parcial',style:bank.coverage_complete?'':'error'};
}
export function summary(data, files=null) {
  if (!data || !Array.isArray(data.questions) || !data.report) throw Error('Este JSON no tiene la estructura de un resultado de ExamBase.');
  const r=data.report, numbers=data.questions.map(q=>q.number), unique=new Set(numbers);
  const expected=r.expected_questions, missingExplanations=data.questions.filter(q=>!q.explanation_text && !q.raw?.solution_text).map(q=>q.number);
  const assets=Object.values(data.assets || {}), missingFiles=files ? assets.filter(a=>a.local_path && !files.has(a.local_path)).map(a=>a.local_path) : null;
  const coverage=Number.isSafeInteger(expected) && expected>0 && numbers.length===expected && unique.size===expected && numbers.every(n=>Number.isInteger(n)&&n>=1&&n<=expected) && !r.missing_pages?.length;
  return {questions:numbers.length,expected,coverage,images:assets.length,missingExplanations,missingFiles,answersMissing:data.questions.filter(q=>!q.correct_choices?.length).map(q=>q.number),contextReview:r.dom_questions_requiring_context_review || [],formattingReview:r.html_markers_requiring_review || [],conflicts:r.conflicts || [],errors:r.errors || []};
}

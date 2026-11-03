import {repository} from './model.mjs';
export class GitHub {
  #token;
  constructor(owner,repo,token,fetcher=fetch) { Object.assign(this,repository(owner,repo)); this.#token=token; this.fetcher=fetcher; }
  disconnect() { this.#token=''; }
  get base() { return `/repos/${encodeURIComponent(this.owner)}/${encodeURIComponent(this.repo)}`; }
  async request(path,options={}) {
    if (!path.startsWith(this.base+'/') && path!==this.base) throw Error('Ruta de API no permitida.');
    const response=await this.fetcher('https://api.github.com'+path,{...options,redirect:'error',headers:{Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28',Authorization:'Bearer '+this.#token,...(options.body?{'Content-Type':'application/json'}:{})},signal:AbortSignal.timeout(25000)});
    if (!response.ok) {
      const status=response.status;
      throw Error(status===404?'No se encontró el repositorio, el workflow o el permiso para verlo.':status===401?'El token no es válido o ha caducado.':status===403?'GitHub rechazó el permiso o alcanzaste el límite de consultas.':status===422?'GitHub rechazó los parámetros. Comprueba que el workflow del repositorio esté actualizado.':`GitHub respondió con el estado ${status}.`);
    }
    return response.status===204 ? null : response.json();
  }
  async connect() { const info=await this.request(this.base); this.branch=info.default_branch; this.private=info.private; await this.request(this.base+'/actions/workflows/descargar-examen.yml'); return info; }
  dispatch(workflow,inputs) {
    if (!['descargar-examen.yml','actualizar-catalogo.yml'].includes(workflow)) throw Error('Workflow no permitido.');
    return this.request(this.base+'/actions/workflows/'+workflow+'/dispatches',{method:'POST',body:JSON.stringify({ref:this.branch,inputs})});
  }
  runs() { return this.request(this.base+'/actions/workflows/descargar-examen.yml/runs?per_page=30'); }
  artifacts(id) { if (!/^\d+$/.test(String(id))) throw Error('ID inválido.'); return this.request(this.base+`/actions/runs/${id}/artifacts`); }
  async content(path) {
    if (!['web/data/catalog.json','bancos/index.json'].includes(path)) throw Error('Archivo no permitido.');
    const data=await this.request(this.base+'/contents/'+path+'?ref='+encodeURIComponent(this.branch));
    if (data.encoding!=='base64') throw Error('El índice supera el tamaño admitido por la interfaz.');
    return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(data.content.replace(/\s/g,'')),c=>c.charCodeAt(0))));
  }
  url(path='') { return `https://github.com/${this.owner}/${this.repo}/${path}`; }
  artifactUrl(run,id) { if (![run,id].every(v=>/^\d+$/.test(String(v)))) throw Error('ID inválido.'); return this.url(`actions/runs/${run}/artifacts/${id}`); }
  bankUrl(path) {
    if (!/^bancos\/[a-zA-Z0-9_./-]+\.zip$/.test(path) || path.split('/').includes('..')) throw Error('Ruta de banco inválida.');
    return this.url('blob/'+encodeURIComponent(this.branch)+'/'+path+'?raw=true');
  }
}

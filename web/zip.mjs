// ZIP acotado y sin extracción al disco. Admite el ZIP externo de Actions.
export function crc32(bytes) { let n=0xffffffff; for(const b of bytes) { n^=b; for(let j=0;j<8;j++) n=(n>>>1)^((n&1)?0xedb88320:0); } return (n^0xffffffff)>>>0; }
export async function readZip(bytes) {
  const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength), decoder=new TextDecoder();
  let end=-1; for(let p=bytes.length-22;p>=Math.max(0,bytes.length-65557);p--) if(view.getUint32(p,true)===0x06054b50) {end=p;break;}
  if(end<0 || view.getUint16(end+4,true) || view.getUint16(end+6,true)) throw Error('ZIP no reconocido o dividido en varios discos.');
  const count=view.getUint16(end+10,true), files=new Map(); let p=view.getUint32(end+16,true), total=0;
  if(count>15000) throw Error('El ZIP contiene demasiados archivos.');
  for(let i=0;i<count;i++) {
    if(p+46>bytes.length || view.getUint32(p,true)!==0x02014b50) throw Error('Índice ZIP dañado.');
    const flags=view.getUint16(p+8,true),method=view.getUint16(p+10,true),crc=view.getUint32(p+16,true),packed=view.getUint32(p+20,true),size=view.getUint32(p+24,true),len=view.getUint16(p+28,true),extra=view.getUint16(p+30,true),comment=view.getUint16(p+32,true),offset=view.getUint32(p+42,true),name=decoder.decode(bytes.subarray(p+46,p+46+len));
    p+=46+len+extra+comment; total+=size;
    if(flags&1 || ![0,8].includes(method) || size>100*1024**2 || total>300*1024**2 || name.includes('\\') || name.split('/').includes('..') || name.startsWith('/') || files.has(name)) throw Error('ZIP cifrado, demasiado grande o con rutas no admitidas.');
    if(offset+30>bytes.length || view.getUint32(offset,true)!==0x04034b50) throw Error('Cabecera ZIP dañada.');
    const start=offset+30+view.getUint16(offset+26,true)+view.getUint16(offset+28,true);
    if(start+packed>bytes.length) throw Error('Archivo ZIP truncado.');
    files.set(name,{size,read:async()=>{
      let body=bytes.subarray(start,start+packed);
      if(method===8) {
        let stream; try {stream=new DecompressionStream('deflate-raw');} catch {throw Error('Este navegador no puede descomprimir ZIP. Extrae el archivo y elige preguntas.json.');}
        const reader=new Blob([body]).stream().pipeThrough(stream).getReader(), chunks=[]; let length=0;
        for(;;) { const {value,done}=await reader.read(); if(done) break; length+=value.length; if(length>size) {await reader.cancel();throw Error('Tamaño ZIP inválido.');} chunks.push(value); }
        body=new Uint8Array(length); let position=0; for(const chunk of chunks) {body.set(chunk,position);position+=chunk.length;}
      }
      if(body.length!==size || crc32(body)!==crc) throw Error('El ZIP tiene un archivo con tamaño o integridad incorrectos.'); return body;
    }});
  }
  return files;
}
export async function inspectBytes(bytes,depth=0) {
  const files=await readZip(bytes), names=[...files.keys()], question=names.filter(n=>/(^|\/)preguntas\.json$/.test(n));
  if(question.length===1) { const root=question[0].slice(0,-'preguntas.json'.length); const data=JSON.parse(new TextDecoder().decode(await files.get(question[0]).read())); for(const item of files.values()) await item.read(); return {data,files:new Set(names.filter(n=>n.startsWith(root)).map(n=>n.slice(root.length)))}; }
  const nested=names.filter(n=>n.endsWith('.zip')); if(!question.length && nested.length===1 && depth===0) return inspectBytes(await files.get(nested[0]).read(),1);
  throw Error('Se necesita un ZIP con un único preguntas.json o un único resultado dentro del paquete de Actions.');
}

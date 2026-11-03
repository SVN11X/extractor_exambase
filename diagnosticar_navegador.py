"""Diagnóstico manual con rebrowser-bot-detector; no prueba acceso a ExamBase."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from descargar import BrowserSource
from solver_support import SolverSource

DETECTOR='https://bot-detector.rebrowser.net/'
PROBE=r'''(async () => {
  await new Promise(resolve => setTimeout(resolve, 5000));
  if (typeof window.dummyFn === 'function') window.dummyFn();
  document.getElementsByClassName('div');
  const field=document.getElementById('detections-json');
  return JSON.stringify({url:location.href, detections:field ? JSON.parse(field.value || '{}') : null});
})()'''


def diagnose(mode, output, headed=False):
    exam={'base':DETECTOR,'key':'diagnostic'}
    if mode=='flaresolverr-next':
        with SolverSource(exam,output,5,engine=mode) as source:
            solution=source.request(DETECTOR,executeJs='return '+PROBE+';')
            value=json.loads(solution.get('executeJsResult','{}'))
    else:
        with BrowserSource(exam,output,5,headed=headed,patched=mode=='rebrowser') as source:
            source.tab.goto(DETECTOR,wait_until='load',timeout=60000)
            value=json.loads(source.tab.evaluate(PROBE))
    if not isinstance(value,dict):raise ValueError('El detector no devolvió un objeto JSON válido.')
    value.update(engine=mode,scope='Señales observadas en Rebrowser Bot Detector; no valida acceso a ExamBase ni garantiza ausencia de detección.',probes='Se prueban APIs de lectura del extractor; no se activan artificialmente todos los tests del detector.')
    target=Path(output)/'diagnostico_rebrowser.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    if not isinstance(value.get('detections'),list) or not value['detections']:raise ValueError('El detector no entregó resultados; no se considera una prueba superada.')
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['browser','rebrowser','flaresolverr-next'],default='rebrowser')
    parser.add_argument('--headed',action='store_true')
    parser.add_argument('--output',type=Path,default=Path('salida/diagnostico'))
    args=parser.parse_args()
    print(diagnose(args.mode,args.output,args.headed))

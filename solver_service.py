"""Arranca y cierra únicamente el contenedor local creado por esta ejecución."""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from solver_support import NoRedirect, solver_endpoint

IMAGES = {'flaresolverr-next':'ghcr.io/rix1337/flaresolverr-next:latest',
          'flaresolverr':'ghcr.io/flaresolverr/flaresolverr:latest'}


def docker(*arguments):
    result = subprocess.run(['docker', *arguments], text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError('Docker no pudo completar la operación. Comprueba el daemon y la descarga de la imagen del motor elegido.')
    return result.stdout.strip()


def ready(endpoint, seconds=90):
    root=endpoint.rsplit('/v1',1)[0]+'/'
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        try:
            with opener.open(root,timeout=3) as response:
                value=json.loads(response.read(65536))
            if isinstance(value,dict) and ('version' in value or 'msg' in value):return
        except (urllib.error.URLError,OSError,ValueError):pass
        time.sleep(1)
    raise RuntimeError('El servicio no está listo. No se inició ninguna descarga del examen.')


def start(engine, state_file, *, external=False, endpoint='http://127.0.0.1:8191/v1'):
    solver_endpoint(endpoint)
    state_file=Path(state_file)
    if state_file.exists():raise ValueError('El archivo de servicio ya existe; utiliza una carpeta de salida nueva.')
    if external or engine=='cloudproxy':
        ready(endpoint)
        data={'engine':engine,'managed':False,'endpoint':endpoint}
    else:
        if engine not in IMAGES:raise ValueError('Motor de servicio desconocido.')
        if not shutil.which('docker'):raise RuntimeError('Instala Docker o utiliza el motor rebrowser, que no necesita Docker.')
        from urllib.parse import urlsplit
        port=urlsplit(endpoint).port or 80
        image=IMAGES[engine]
        docker('pull',image)
        owner=uuid.uuid4().hex
        name='exambase-solver-'+owner[:12]
        try:
            container=docker('run','-d','--name',name,'--label','exambase.owner='+owner,
                '-p',f'127.0.0.1:{port}:8191','--shm-size=1g',
                '-e','LOG_LEVEL=error','-e','LOG_HTML=false','-e','HEADLESS=true',
                '-e','EXECUTE_JS_TIMEOUT=75',image)
        except RuntimeError:
            # Docker puede crear el contenedor antes de fallar al publicar el puerto.
            try:
                if docker('inspect','--format','{{index .Config.Labels "exambase.owner"}}',name)==owner:
                    docker('rm','-f',name)
            except RuntimeError:
                pass
            raise
        data={'engine':engine,'managed':True,'container':container,'owner':owner,'image':image,'endpoint':endpoint}
        state_file.parent.mkdir(parents=True,exist_ok=True)
        state_file.write_text(json.dumps(data),encoding='utf-8')
        try:
            data['image_digest']=docker('image','inspect','--format','{{json .RepoDigests}}',image)
            ready(endpoint)
        except Exception:
            stop(state_file)
            raise
    state_file.parent.mkdir(parents=True,exist_ok=True)
    state_file.write_text(json.dumps(data,indent=2),encoding='utf-8')
    return data


def stop(state_file):
    state_file=Path(state_file)
    if not state_file.exists():return
    data=json.loads(state_file.read_text(encoding='utf-8'))
    if data.get('managed') and not data.get('stopped'):
        container=data['container']
        actual=docker('inspect','--format','{{index .Config.Labels "exambase.owner"}}',container)
        if actual!=data.get('owner'):raise RuntimeError('El contenedor no pertenece a esta ejecución; no se modificó.')
        docker('rm','-f',container)
        data['stopped']=True
        state_file.write_text(json.dumps(data,indent=2),encoding='utf-8')
    # No elimina un servicio externo ni sus sesiones ajenas.


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['start','stop'])
    parser.add_argument('--engine',choices=[*IMAGES,'cloudproxy'],default='flaresolverr-next')
    parser.add_argument('--state-file',type=Path,default=Path('salida/solver_runtime.json'))
    parser.add_argument('--endpoint',default='http://127.0.0.1:8191/v1')
    parser.add_argument('--external',action='store_true')
    args=parser.parse_args()
    try:
        if args.action=='start':
            value=start(args.engine,args.state_file,external=args.external,endpoint=args.endpoint)
            print('Servicio local listo: '+value['engine'])
        else:stop(args.state_file)
    except (RuntimeError,ValueError,OSError) as exc:parser.exit(1,str(exc)+'\n')

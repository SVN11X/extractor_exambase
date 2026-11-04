"""Un banco vigente por proveedor y examen, con publicación recuperable."""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import extractor as core
from capture_quality import answers_report
from reference_support import reference_graph
from descargar import exam_from_url


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write((json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode())
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def bank_path(root, exam):
    normalized = exam_from_url(exam['base']+'1')
    if normalized['key'] != exam['key']:
        raise ValueError('La identidad del examen no coincide con su URL.')
    target = Path(root)/'bancos'/normalized['vendor']/normalized['slug']
    if any(part in {'.','..'} for part in (normalized['vendor'],normalized['slug'])) or not target.resolve().is_relative_to((Path(root)/'bancos').resolve()):
        raise ValueError('Ruta de banco inválida.')
    return target


def inspect_zip(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 95*1024**2:
        raise ValueError('El resultado debe ser un ZIP local de hasta 95 MiB.')
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist())>50000 or sum(i.file_size for i in archive.infolist())>1024**3:
            raise ValueError('El contenido del ZIP supera los límites admitidos.')
        names = [n for n in archive.namelist() if n.endswith('/preguntas.json')]
        if len(names) != 1 or archive.testzip():
            raise ValueError('El ZIP debe contener un resultado único con CRC válido.')
        data = json.loads(archive.read(names[0]))
        prefix = names[0][:-len('preguntas.json')]
        assets_complete = True
        for asset in data.get('assets',{}).values():
            local = asset.get('local_path')
            if not local or prefix+local not in archive.namelist():
                assets_complete = False
            elif asset.get('sha256') and hashlib.sha256(archive.read(prefix+local)).hexdigest()!=asset['sha256']:
                raise ValueError('Una imagen no coincide con su hash.')
    exam_from_url(data['exam']['base']+'1')
    report = data['report']
    answers = answers_report(data)
    numbers = [q['number'] for q in data['questions']]
    total = report.get('expected_questions')
    coverage = type(total) is int and total > 0 and sorted(numbers) == list(range(1,total+1)) and not report.get('missing_pages')
    complete = bool(coverage and assets_complete and answers['answers_complete'] and reference_graph(data)['complete']
                    and not any(report.get(k) for k in ('images_failed','errors','conflicts','empty_questions','empty_choices')))
    return data, complete


@contextlib.contextmanager
def writer_lock(root):
    with (Path(root)/'.exambase-bank.lock').open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            stream.seek(0)
            stream.write(b'0')
            stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def recover_publications(root):
    for previous in (Path(root)/'bancos').glob('*/.*.anterior'):
        target = previous.with_name(previous.name[1:-len('.anterior')])
        if not target.exists():
            os.replace(previous, target)
        else:
            try:
                inspect_zip(target/'resultado.zip')
            except (ValueError, OSError, zipfile.BadZipFile):
                shutil.rmtree(target)
                os.replace(previous, target)
            else:
                shutil.rmtree(previous)


def current_entries(root):
    entries = []
    for path in sorted((Path(root)/'bancos').glob('*/*/manifest_guardado.json')):
        if not any(part.startswith('.') for part in path.relative_to(Path(root)/'bancos').parts):
            entries.append(json.loads(path.read_text(encoding='utf-8')))
    return {'schema_version':'2.0', 'exams':entries}


def persist(output, repository_root, run_id):
    output, root = Path(output), Path(repository_root)
    root.mkdir(parents=True, exist_ok=True)
    if not re.fullmatch(r'\d+', str(run_id)):
        raise ValueError('ID de ejecución inválido.')
    state = json.loads((output/'estado_ejecucion.json').read_text(encoding='utf-8'))
    if Path(state['zip']).name != state['zip'] or not state['zip'].endswith('.zip'):
        raise ValueError('Nombre de resultado inválido.')
    archive = output/state['zip']
    data, complete = inspect_zip(archive)
    if state['exam']['key'] != data['exam']['key']:
        raise ValueError('El estado y el ZIP pertenecen a exámenes distintos.')
    target = bank_path(root, data['exam'])
    target.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    state = {**state, 'zip':'resultado.zip', 'execution_complete':complete,
             'status':'complete' if complete else 'blocked' if state.get('failure') else 'partial' if data['questions'] else 'failed'}
    state.update(answers_report(data), questions=len(data['questions']))
    report = data['report']
    state.update({key:report.get(key, []) for key in ('images_failed','images_requiring_review','missing_explanations')})
    state.update(images_found=report.get('images_found', len(data.get('assets', {}))),
                 images_downloaded=report.get('images_downloaded', len(data.get('assets', {}))-len(report.get('images_failed', []))))
    relative = target.relative_to(root)
    entry = {**state, 'run_id':str(run_id), 'exam_key':data['exam']['key'], 'exam':data['exam'],
             'updated_at':now, 'zip_path':(relative/'resultado.zip').as_posix(),
             'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(), 'bytes':archive.stat().st_size}
    attempt = {key:entry.get(key) for key in ('run_id','updated_at','status','failure','stopped_reason','questions','next_page')}
    with writer_lock(root):
        recover_publications(root)
        old = json.loads((target/'manifest_guardado.json').read_text()) if (target/'manifest_guardado.json').exists() else None
        stage = Path(tempfile.mkdtemp(prefix='.'+target.name+'.nuevo-', dir=target.parent))
        previous = target.with_name('.'+target.name+'.anterior')
        try:
            old_quality = (old.get('questions',0), old.get('answers_present',0)) if old else (0,0)
            retain = bool(old and not complete and (old.get('execution_complete') or old_quality>(entry['questions'],entry['answers_present'])))
            if retain:
                shutil.copytree(target, stage, dirs_exist_ok=True)
                entry = {**old, 'last_attempt':attempt}
                shutil.copy2(archive, stage/'progreso.zip')
                core.write_json(stage/'progreso_estado.json', {**state,'zip':'progreso.zip'})
                entry['checkpoint_path'] = (relative/'progreso.zip').as_posix()
                entry['checkpoint_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
            else:
                shutil.copy2(archive, stage/'resultado.zip')
                core.write_json(stage/'estado_ejecucion.json', state)
                core.write_json(stage/'informe_validacion.json', data['report'])
                entry['last_attempt'] = attempt
            core.write_json(stage/'manifest_guardado.json', entry)
            if target.exists():
                os.replace(target, previous)
            try:
                os.replace(stage, target)
                atomic_json(root/'bancos/index.json', current_entries(root))
            except BaseException:
                if target.exists():
                    shutil.rmtree(target)
                if previous.exists():
                    os.replace(previous, target)
                raise
            if previous.exists():
                shutil.rmtree(previous)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    return entry


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('salida'))
    parser.add_argument('--repo', type=Path, default=Path('.'))
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    print(json.dumps(persist(args.output,args.repo,args.run_id),ensure_ascii=False))

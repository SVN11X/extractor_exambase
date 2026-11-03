"""Conserva resultados versionados en bancos/, sin perfiles ni credenciales."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
import extractor as core


def persist(output, repository_root, run_id):
    output, repository_root = Path(output), Path(repository_root)
    if not re.fullmatch(r'\d+', str(run_id)):
        raise ValueError('ID de ejecución inválido.')
    state = json.loads((output / 'estado_ejecucion.json').read_text(encoding='utf-8'))
    name = state['zip']
    if Path(name).name != name or not name.endswith('.zip'):
        raise ValueError('Nombre de resultado inválido.')
    archive = output / name
    if not archive.is_file() or archive.stat().st_size > 95 * 1024**2:
        raise ValueError('El ZIP no existe o supera 95 MiB. Usa el artefacto de Actions para este resultado.')
    key = state['exam']['key']
    slug = re.sub(r'[^a-zA-Z0-9_-]', '_', key)[:100] + '-' + hashlib.sha256(key.encode()).hexdigest()[:8]
    source = output / name[:-4]
    if not source.is_dir():
        raise ValueError('No se encontró la carpeta del resultado.')
    # Persiste únicamente el paquete producido, jamás el directorio de trabajo.
    for path in source.rglob('*'):
        if path.is_symlink() or (path.is_file() and path.stat().st_size > 95 * 1024**2):
            raise ValueError('Archivo no apto para conservar en Git.')
    index_path = repository_root / 'bancos' / 'index.json'
    index = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {'schema_version': '1.0', 'runs': []}
    relative = Path('bancos') / slug / str(run_id)
    target = repository_root / relative
    if target.exists():
        raise ValueError('Esta ejecución ya está guardada; no se sobrescribirá.')
    target.mkdir(parents=True)
    shutil.copytree(source, target / 'material')
    shutil.copy2(archive, target / name)
    shutil.copy2(output / 'estado_ejecucion.json', target / 'estado_ejecucion.json')
    data = json.loads((source / 'preguntas.json').read_text(encoding='utf-8'))
    entry = {'run_id': str(run_id), 'exam_key': key, 'exam': data['exam'], 'generated_at': data['report'].get('integrity_checked_at') or data.get('generated_at'), 'questions': state['questions'], 'coverage_complete': state['coverage_complete'], 'review_pending': state['review_pending'], 'zip_path': (relative / name).as_posix(), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'bytes': archive.stat().st_size}
    entry.update(status=state.get('status', 'complete' if state['coverage_complete'] else 'partial'), failure=state.get('failure'), pages_saved=state.get('pages_saved', []), next_page=state.get('next_page'))
    index['runs'] = [entry] + index['runs']
    core.write_json(index_path, index)
    core.write_json(target / 'manifest_guardado.json', entry)
    return entry


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('salida'))
    parser.add_argument('--repo', type=Path, default=Path('.'))
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    print(json.dumps(persist(args.output, args.repo, args.run_id), ensure_ascii=False))

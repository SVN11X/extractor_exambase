"""Consolida los bancos anteriores, conservando la mejor copia de cada examen."""
import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from persistir_banco import atomic_json, current_entries, inspect_zip, persist
import extractor as core
from paquetes import import_zip, enrich


def remove_legacy(root, folders):
    for relative in folders:
        folder = (root/relative).resolve()
        if not folder.is_relative_to((root/'bancos').resolve()) or len(folder.relative_to(root/'bancos').parts) != 1:
            raise ValueError('Contenedor de migración inválido.')
        if folder.name.rsplit('-',1)[-1].isalnum() and len(folder.name.rsplit('-',1)[-1])==8 and folder.exists():
            shutil.rmtree(folder)


def migrate(root):
    root = Path(root).resolve()
    index_path = root/'bancos/index.json'
    journal = root/'bancos/.migracion-v1.json'
    index = json.loads((journal if journal.exists() else index_path).read_text()) if index_path.exists() else {}
    if index.get('phase') == 'cleanup':
        remove_legacy(root, index['folders'])
        atomic_json(index_path,current_entries(root))
        journal.unlink(missing_ok=True)
        return {'migrated':index['migrated'], 'exams':len(current_entries(root)['exams'])}
    rows = index.get('runs',[])
    if not rows:
        return {'migrated':0, 'exams':len(current_entries(root)['exams'])}
    selected = {}
    old_folders = set()
    for row in rows:
        path = (root/row['zip_path']).resolve()
        if not path.is_relative_to((root/'bancos').resolve()) or not path.is_file():
            raise ValueError('Falta un respaldo de la migración.')
        if row.get('sha256') and hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Un respaldo anterior tiene un hash distinto.')
        data, complete = inspect_zip(path)
        key = data['exam']['key']
        quality = (complete,len(data['questions']),len(data['questions'])-len(data['report'].get('answers_missing',[])),row.get('generated_at') or '')
        if key not in selected or quality>selected[key][0]:
            selected[key] = (quality,path,row)
        old_folders.add(path.parent.parent)
    atomic_json(journal,index)
    for _, path, row in selected.values():
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            material = output/'resultado'
            material.mkdir()
            import_zip(path, material)
            before, _ = inspect_zip(path)
            after = enrich(material)
            # Verifica que regenerar el lector no elimine contenido ni objetos.
            for field in ('questions', 'contexts', 'assets'):
                if field == 'assets':
                    invariant = {k:v.get('sha256') for k,v in before[field].items()} == {k:v.get('sha256') for k,v in after[field].items()}
                else:
                    invariant = before[field] == after[field]
                if not invariant:
                    raise ValueError(f'La migración cambió el contenido de {field}.')
            archive = core.create_zip(material)
            state = json.loads((path.parent/'estado_ejecucion.json').read_text())
            state.update(zip=archive.name, migrated_from_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            core.write_json(output/'estado_ejecucion.json',state)
            persist(output,root,row['run_id'])
    cleanup = {'phase':'cleanup', 'folders':[f.relative_to(root.resolve()).as_posix() for f in old_folders], 'migrated':len(rows)}
    atomic_json(journal, cleanup)
    remove_legacy(root, cleanup['folders'])
    atomic_json(index_path,current_entries(root))
    journal.unlink(missing_ok=True)
    return {'migrated':len(rows),'exams':len(selected)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path('.'))
    args=parser.parse_args()
    print(json.dumps(migrate(args.repo)))

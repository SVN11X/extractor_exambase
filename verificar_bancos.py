"""Audita el índice, los ZIP y sus hashes sin ejecutar contenido del examen."""
import hashlib
import json
import re
import zipfile
from pathlib import Path
from persistir_banco import current_entries, inspect_zip


def audit(root):
    root = Path(root).resolve()
    index = json.loads((root/'bancos/index.json').read_text(encoding='utf-8'))
    if index != current_entries(root):
        raise ValueError('El índice no coincide con los manifiestos vigentes.')
    keys, results = set(), []
    for entry in index['exams']:
        if entry['exam_key'] in keys:
            raise ValueError('Un examen figura más de una vez en el banco.')
        keys.add(entry['exam_key'])
        path = (root/entry['zip_path']).resolve()
        if not path.is_relative_to(root/'bancos') or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('El ZIP no coincide con la ruta o el hash del manifiesto.')
        data, complete = inspect_zip(path)
        if complete != entry['execution_complete']:
            raise ValueError('El estado de recopilación no coincide con el contenido.')
        with zipfile.ZipFile(path) as archive:
            integrity_name = next(n for n in archive.namelist() if n.endswith('/integridad_sha256.json'))
            prefix = integrity_name[:-len('integridad_sha256.json')]
            hashes = json.loads(archive.read(integrity_name))['files']
            actual = {n[len(prefix):] for n in archive.namelist() if not n.endswith('/') and n != integrity_name}
            if actual != set(hashes):
                raise ValueError('El inventario de integridad no cubre exactamente los archivos del ZIP.')
            for name, digest in hashes.items():
                if hashlib.sha256(archive.read(prefix+name)).hexdigest() != digest:
                    raise ValueError('Un archivo no coincide con su hash de integridad.')
                suffix = Path(name).suffix.lower()
                if suffix in {'.js','.mjs','.exe','.cmd','.bat','.ps1','.vbs','.dll','.scr','.com'}:
                    raise ValueError('El ZIP de estudio incluye un archivo ejecutable inesperado.')
                if suffix in {'.html','.htm'}:
                    if name != 'preguntas.html' or re.search(rb'<script\b', archive.read(prefix+name), re.I):
                        raise ValueError('El ZIP contiene un HTML de origen activo o un script en el lector.')
        report = data['report']
        results.append({'exam':entry['exam_key'], 'questions':len(data['questions']),
                        'answers':entry['answers_present'], 'images':report['images_downloaded'],
                        'metadata_pending':len(entry.get('metadata_unverified_questions', [])),
                        'complete':complete,'files_checked':len(hashes),'sha256':entry['sha256']})
    return results


if __name__ == '__main__':
    print(json.dumps({'banks':audit(Path('.')), 'antivirus_scan':'not_performed'},ensure_ascii=False,indent=2))

"""Recupera el parcial de Actions sin depender de GitHub CLI."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

LIMIT = 200 * 1024**2


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_limited(response, limit=LIMIT):
    body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError('El respaldo supera el tamaño admitido.')
    return body


def github_request(path, token):
    # No propaga Authorization al almacenamiento que firma la descarga.
    request = urllib.request.Request('https://api.github.com' + path,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'ExamBaseArchive/5.0.1'})
    return urllib.request.build_opener(NoRedirect()).open(request, timeout=60)


def artifact_bytes(path, token):
    try:
        with github_request(path, token) as response:
            return read_limited(response)
    except urllib.error.HTTPError as response:
        if response.code != 302:
            raise
        target = response.headers.get('Location', '')
        response.close()
    url = urllib.parse.urlsplit(target)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.port:
        raise ValueError('GitHub devolvió una ruta de descarga no admitida.')
    # La URL temporal de descarga no recibe el token de GitHub.
    with urllib.request.urlopen(urllib.request.Request(target, headers={'User-Agent': 'ExamBaseArchive/5.0.1'}), timeout=90) as response:
        return read_limited(response)


def extract_result(body, destination):
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        files = [i for i in archive.infolist() if not i.is_dir() and i.filename.endswith('.zip')]
        if len(files) != 1:
            raise ValueError('El artefacto debe contener un único ZIP de resultado.')
        info = files[0]
        if info.file_size > LIMIT or info.filename != Path(info.filename).name or '\\' in info.filename:
            raise ValueError('Ruta o tamaño no admitidos en el artefacto.')
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / info.filename
        if target.exists():
            raise ValueError('La carpeta de respaldo ya contiene un resultado.')
        target.write_bytes(archive.read(info))
        return target


def saved_backup(root, run_id, destination):
    root = Path(root).resolve()
    index = root / 'bancos/index.json'
    entries = json.loads(index.read_text(encoding='utf-8')).get('runs', []) if index.exists() else []
    entry = next((row for row in entries if row.get('run_id') == str(run_id)), None)
    if not entry:
        raise ValueError('El artefacto no está disponible y no hay copia guardada de esa ejecución en el repositorio.')
    path = (root / entry['zip_path']).resolve()
    if not path.is_relative_to(root / 'bancos') or not path.is_file() or path.stat().st_size > LIMIT:
        raise ValueError('Ruta o tamaño de respaldo inválidos.')
    if entry.get('sha256') and hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
        raise ValueError('La copia guardada no coincide con su hash.')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / path.name
    if target.exists():
        raise ValueError('El destino ya contiene un resultado.')
    shutil.copy2(path, target)
    return target


def recover(repository, run_id, destination, token, root=Path('.')):
    if not re.fullmatch(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+', repository) or not re.fullmatch(r'\d+', str(run_id)):
        raise ValueError('Repositorio o ID de ejecución inválidos.')
    if token:
        try:
            base = '/repos/' + repository
            with github_request(base + f'/actions/runs/{run_id}/artifacts?per_page=100', token) as response:
                data = json.loads(read_limited(response, 2 * 1024**2))
            artifacts = [a for a in data.get('artifacts', []) if a.get('name') == 'exambase-resultado' and not a.get('expired')]
            if len(artifacts) == 1 and type(artifacts[0].get('id')) is int:
                artifact = artifacts[0]
                body = artifact_bytes(base + f'/actions/artifacts/{artifact["id"]}/zip', token)
                digest = artifact.get('digest')
                if digest and digest != 'sha256:' + hashlib.sha256(body).hexdigest():
                    raise ValueError('El artefacto no coincide con el hash de GitHub.')
                target = extract_result(body, destination)
                return target, 'artifact'
        except (urllib.error.URLError, OSError, ValueError, zipfile.BadZipFile):
            # Sólo se usa una copia ya guardada; no se cambia de sitio de origen.
            pass
    return saved_backup(root, run_id, destination), 'repository'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', type=Path, default=Path('respaldo'))
    args = parser.parse_args()
    try:
        path, source = recover(os.environ.get('GITHUB_REPOSITORY', ''), args.run_id, args.output, os.environ.get('GH_TOKEN', ''))
        print(f'Respaldo recuperado desde {source}: {path.name}')
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.exit(1, str(exc) + '\n')

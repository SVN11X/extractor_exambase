"""Actualiza metadatos del catálogo; conserva lo anterior si un proveedor falla."""
from __future__ import annotations
import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
import extractor as core
from descargar import exam_from_url


def parse_vendor(source, vendor):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(source, 'html.parser')
    main = soup.find('main') or soup
    exams = {}
    for anchor in main.select('a[href]'):
        url = urljoin('https://www.exambase.com', anchor['href'])
        try:
            exam = exam_from_url(url)
        except (core.ExtractionError, ValueError):
            continue
        # Sólo portadas de examen con contador real; excluye navegación genérica.
        if '/practice-questions/' in url or urlsplit(url).hostname not in {'exambase.com', 'www.exambase.com'}:
            continue
        label = anchor.get_text(' ', strip=True)
        match = re.search(r'([\d,]+)\s+questions?\b', label, re.I)
        if not match:
            continue
        title = anchor.find(['h2', 'h3', 'h4', 'h5', 'h6'])
        code_node, name_node = anchor.select_one('.ebo-idx__code'), anchor.select_one('.ebo-idx__name')
        code = code_node.get_text(' ', strip=True) if code_node else exam['slug'].upper()
        displayed_name = name_node.get_text(' ', strip=True) if name_node else ''
        name = title.get_text(' ', strip=True) if title else displayed_name if displayed_name and displayed_name != vendor['vendor'] else code_node.get_text(' ', strip=True) if code_node else label[:match.start()].strip(' ·—-')
        if not name:
            name = exam['slug'].replace('-', ' ')
        exams[exam['key']] = {'id': exam['key'], 'url': url.split('?')[0].rstrip('/'), 'name': name, 'vendor': vendor['vendor'], 'vendor_slug': vendor['slug'], 'questions': int(match[1].replace(',', '')), 'code': code}
    if not exams:
        raise core.ExtractionError('No se encontraron enlaces de exámenes con contador en este proveedor.')
    return list(exams.values())


def update(path, slug, delay, downloader=None):
    path = Path(path)
    data = json.loads(path.read_text(encoding='utf-8'))
    selected = data['vendors'] if slug == 'all' else [v for v in data['vendors'] if v['slug'] == slug]
    if not selected:
        raise ValueError('Proveedor no reconocido en el índice.')
    source = downloader or core.Downloader(delay=delay, retries=1)
    errors, updated = [], []
    for vendor in selected:
        try:
            body, _, encoding = source.get('https://www.exambase.com/exams/' + vendor['slug'])
            found = parse_vendor(body.decode(encoding, 'replace'), vendor)
            data['exams'] = [e for e in data['exams'] if e.get('vendor_slug') != vendor['slug']] + found
            updated.append(vendor['slug'])
        except (core.ExtractionError, ValueError, OSError) as exc:
            errors.append({'vendor': vendor['slug'], 'error': str(exc)})
            if isinstance(exc, core.AccessStopped):
                break
    data['updated_at'] = datetime.now(timezone.utc).isoformat()
    data['exams'].sort(key=lambda e: (e['vendor'], e['name']))
    data['complete'] = len(updated) == len(data['vendors']) and not errors
    data['last_update'] = {'updated_vendors': updated, 'errors': errors, 'previous_entries_retained': True}
    core.write_json(path, data)
    return data['last_update']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor', default='all')
    parser.add_argument('--delay', type=float, default=5)
    parser.add_argument('--path', type=Path, default=Path('web/data/catalog.json'))
    args = parser.parse_args()
    if not 5 <= args.delay <= 120:
        parser.error('La pausa debe estar entre 5 y 120 segundos.')
    result = update(args.path, args.vendor, args.delay)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if not result['errors'] else 2)

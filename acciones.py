"""Cola reanudable para GitHub Actions; Scrapling es el único motor de acceso."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import descargar
from actualizar_catalogo import update as update_catalog
from migrar_bancos import migrate
from persistir_banco import atomic_json, bank_path, current_entries, persist


def read(path, default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else default


def stamp(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except (ValueError, AttributeError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def configuration(root):
    value = read(root/'automatizacion/config.json')
    limits = {'intervalo_segundos': (5, 120), 'max_examenes_por_lote': (1, 100),
              'presupuesto_minutos': (5, 270), 'minutos_por_examen': (1, 240),
              'actualizar_cada_dias': (1, 365), 'catalogo_cada_dias': (1, 365)}
    for key, (low, high) in limits.items():
        number = value.get(key)
        if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
            raise ValueError(f'Configuración inválida: {key} debe estar entre {low} y {high}.')
    if type(value['max_examenes_por_lote']) is not int or not isinstance(value.get('proveedores'), list) or not value['proveedores']:
        raise ValueError('Define proveedores y un límite entero de exámenes por lote.')
    return value


def providers(catalog, configured):
    known = {v['slug'] for v in catalog['vendors']}
    if any(v != 'all' and v not in known for v in configured):
        raise ValueError('Hay un proveedor desconocido en la configuración.')
    return list(dict.fromkeys([v for v in configured if v != 'all'] +
                             ([v['slug'] for v in catalog['vendors']] if 'all' in configured else [])))


def checkpoint(root, exam):
    """Una actualización completa siempre empieza de nuevo; un parcial se reanuda."""
    folder = bank_path(root, exam)
    for state_name, zip_name in [('progreso_estado.json', 'progreso.zip'), ('estado_ejecucion.json', 'resultado.zip')]:
        state = read(folder/state_name, {})
        path = folder/zip_name
        if state.get('resume_supported') and not state.get('execution_complete') and path.is_file():
            manifest = read(folder/'manifest_guardado.json', {})
            expected = manifest.get('checkpoint_sha256') if zip_name == 'progreso.zip' else manifest.get('sha256')
            if expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('El respaldo no coincide con su hash; se conserva para revisión.')
            return path
    return None


def summary(states, pending=0, errors=(), queue_info=None):
    lines = ['# Resultado de ExamBase', '']
    for state in states:
        exam = state.get('exam', {})
        lines += [f'## {exam.get("key", "Examen")}', '',
                  'Recopilación completa.' if state.get('execution_complete') else 'Recopilación parcial.',
                  f'Preguntas **{state.get("questions", 0)}/{exam.get("total") or "?"}** · '
                  f'Respuestas **{state.get("answers_present", 0)}**.',
                  f'Imágenes guardadas **{state.get("images_downloaded", 0)}/{state.get("images_found", 0)}**.',
                  f'Preguntas sin texto de explicación conservado **{len(state.get("missing_explanations", []))}**.', '']
        if state.get('stopped_reason'):
            lines += [str(state['stopped_reason']), '']
        if state.get('pages_recovered_offline'):
            lines += [f'Páginas con metadatos recuperados del respaldo: **{len(state["pages_recovered_offline"])}**.', '']
        if not state.get('execution_complete'):
            lines += ['La próxima ejecución del mismo examen recupera el avance válido. Consulta informe_validacion.json.', '']
    if queue_info is not None:
        lines += [f'Proveedor: **{queue_info["vendor"]}**.',
                  f'Exámenes sin banco: **{queue_info["new"]}**.',
                  f'Bancos parciales o actualizaciones pendientes: **{queue_info["partial"]}**.',
                  f'Elegibles para extracción automática ahora: **{queue_info["eligible"]}**.',
                  f'Parciales aplazados por el intervalo de reintento: **{queue_info["deferred"]}**.', '']
    elif pending:
        lines += [f'Exámenes elegibles pendientes en este proveedor: **{pending}**.', '']
    lines += [f'Error: {error}' for error in errors]
    return '\n'.join(lines) + '\n'


def write_summary(root, states, pending=0, errors=(), queue_info=None):
    output = root/'salida'
    output.mkdir(exist_ok=True)
    text = summary(states, pending, errors, queue_info)
    (output/'resumen.md').write_text(text, encoding='utf-8')
    print(text, flush=True)
    step = os.environ.get('GITHUB_STEP_SUMMARY')
    if step:
        with open(step, 'a', encoding='utf-8') as stream:
            stream.write(text)


def collect(root, url, config, minutes, collector=descargar.run):
    exam = descargar.exam_from_url(url)
    output = root/'trabajo'/f'examen-{exam["vendor"]}-{exam["slug"]}'
    resume = checkpoint(root, exam)
    started = time.monotonic()
    for attempt in range(2):
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)
        args = SimpleNamespace(exam_url=url, exam_name=None, mode='scrapling', delay=config['intervalo_segundos'],
                               output=output, resume_from=resume, headed=True,
                               max_minutes=minutes, page_limit=0, ocr=True, verification_wait=20)
        collector(args)
        state = read(output/'estado_ejecucion.json')
        if state is None:
            raise ValueError('El recopilador no produjo un estado verificable.')
        entry = persist(output, root, os.environ.get('GITHUB_RUN_ID', '0'))
        target = bank_path(root, exam)
        destination = root/'salida'/exam['vendor']/exam['slug']
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(target, destination)
        remaining = minutes - (time.monotonic()-started)/60
        if attempt == 0 and resume and state.get('restart_required') and not state.get('failure') and remaining >= 1:
            print('Cambió la paginación del respaldo: se conserva su copia y se inicia una captura nueva con Scrapling.',flush=True)
            resume, minutes = None, remaining
            continue
        return state, entry


def eligible(exams, index, config, now, *, manual=False):
    selected = []
    for exam in {e['id']: e for e in exams}.values():
        entry = index.get(exam['id'])
        attempt = (entry or {}).get('last_attempt') or entry or {}
        cooldown = 7 if attempt.get('status') == 'blocked' else 1
        # Una copia completa con un progreso nuevo pendiente debe continuar ese progreso.
        complete = bool(entry and entry.get('execution_complete') and not entry.get('checkpoint_path'))
        age = config['actualizar_cada_dias'] if complete else cooldown
        if entry and now - stamp(attempt.get('updated_at')) < timedelta(days=age) and not (manual and not complete and attempt.get('status') != 'blocked'):
            continue
        selected.append((0 if not entry else 2 if complete else 1, stamp(attempt.get('updated_at')), exam['id'], exam))
    return [item[-1] for item in sorted(selected, key=lambda row: row[:3])]


def queue_counts(exams, index, config, now, vendor):
    unique = {e['id']:e for e in exams}
    ready = {e['id'] for e in eligible(list(unique.values()),index,config,now)}
    partial = {key for key in unique if key in index and
               (not index[key].get('execution_complete') or index[key].get('checkpoint_path'))}
    return {'vendor':vendor, 'new':sum(key not in index for key in unique), 'partial':len(partial),
            'eligible':len(ready), 'deferred':len(partial-ready)}


def execute(root, mode, value=None, collector=descargar.run, catalog_updater=update_catalog, clock=time.monotonic, now=None):
    root = Path(root).resolve()
    now = now or datetime.now(timezone.utc)
    config = configuration(root)
    migrate(root)
    catalog_path = root/'catalogos/catalogo.json'
    catalog = read(catalog_path)
    state_path = root/'automatizacion/estado.json'
    queue = read(state_path, {'siguiente_proveedor': 0})
    turn = providers(catalog, config['proveedores'])
    states, errors, pending = [], [], 0
    queue_info = None
    started = clock()
    try:
        if mode == 'examen':
            state, _ = collect(root, value, config, config['minutos_por_examen'], collector)
            states.append(state)
            return 0 if state.get('execution_complete') else 2
        if mode == 'catalogo':
            # Un proveedor por turno evita recorrer 192 índices en una sola ejecución.
            slug = value if value != 'all' else turn[queue.get('siguiente_catalogo', 0) % len(turn)]
            result = catalog_updater(catalog_path, slug, config['intervalo_segundos'])
            errors.extend(error['error'] for error in result['errors'])
            if value == 'all':
                queue['siguiente_catalogo'] = (queue.get('siguiente_catalogo', 0) + 1) % len(turn)
            return 2 if errors else 0
        automatic = mode == 'automatico'
        position = queue.get('siguiente_proveedor', 0) % len(turn)
        known = {v['slug'] for v in catalog['vendors']}
        if not automatic and value not in known:
            raise ValueError('Proveedor no reconocido: usa un slug de catalogo.json.')
        # Busca el siguiente proveedor con trabajo o con índice por actualizar.
        for _ in range(len(turn) if automatic else 1):
            slug = turn[position] if automatic else value
            blocked = queue.get('proveedores_bloqueados', {}).get(slug)
            if automatic and blocked and now - stamp(blocked) < timedelta(days=7):
                position = (position + 1) % len(turn)
                continue
            outdated = now - stamp(catalog.get('vendor_updated_at', {}).get(slug)) >= timedelta(days=config['catalogo_cada_dias'])
            if outdated:
                result = catalog_updater(catalog_path, slug, config['intervalo_segundos'])
                catalog = read(catalog_path)
                if result['errors']:
                    errors.extend(error['error'] for error in result['errors'])
                    if any(error.get('blocked') for error in result['errors']):
                        queue.setdefault('proveedores_bloqueados', {})[slug] = now.isoformat()
                    if automatic:
                        position = (position + 1) % len(turn)
                    break
            index = {e['exam_key']: e for e in current_entries(root)['exams']}
            exams = [e for e in catalog['exams'] if slug in e.get('vendor_slugs', [e.get('vendor_slug')])]
            work = eligible(exams, index, config, now, manual=not automatic)
            if not work and automatic:
                position = (position + 1) % len(turn)
                continue
            for exam in work[:config['max_examenes_por_lote']]:
                remaining = config['presupuesto_minutos'] - (clock() - started)/60 - 5
                if remaining < 1:
                    break
                state, entry = collect(root, exam['url'], config, min(remaining, config['minutos_por_examen']), collector)
                states.append(state)
                index[entry['exam_key']] = entry
                # Guarda el banco y el cursor después de cada examen, incluso si el siguiente falla.
                queue['ultimo_examen'] = entry['exam_key']
                atomic_json(state_path, queue)
                if state.get('failure') or state.get('transport_failure'):
                    errors.append(state.get('stopped_reason') or 'Acceso pendiente.')
                    if state.get('failure'):
                        queue.setdefault('proveedores_bloqueados', {})[slug] = now.isoformat()
                    break
            # Se excluyen los intentados hoy por su pausa de reintento; el resto queda para el próximo lote.
            pending = len(eligible(exams, index, config, now))
            queue_info = queue_counts(exams,index,config,now,slug)
            if automatic and (pending == 0 or errors):
                position = (position + 1) % len(turn)
            break
        if automatic:
            queue['siguiente_proveedor'] = position
        return 2 if errors or any(not s.get('execution_complete') and not (s.get('stopped_reason') or '').startswith('Se alcanzó el presupuesto') for s in states) else 0
    except (descargar.core.ExtractionError, ValueError, OSError, KeyError) as exc:
        errors.append(str(exc))
        return 2
    finally:
        queue['ultimo_lote'] = now.isoformat()
        atomic_json(state_path, queue)
        write_summary(root, states, pending, errors, queue_info)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tarea', choices=['examen', 'proveedor', 'automatico', 'catalogo'])
    parser.add_argument('--exam-url')
    parser.add_argument('--vendor', default='all')
    parser.add_argument('--repo', type=Path, default=Path('.'))
    args = parser.parse_args()
    if args.tarea == 'examen' and not args.exam_url:
        parser.error('Se necesita --exam-url.')
    return execute(args.repo, args.tarea, args.exam_url if args.tarea == 'examen' else args.vendor)


if __name__ == '__main__':
    raise SystemExit(main())

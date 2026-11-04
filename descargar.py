#!/usr/bin/env python3
"""Recopilación desatendida: examen por URL, metadatos detectados, pausa segura.

Conserva un ZIP parcial para reanudar otra ejecución. El motor seleccionado
gestiona su sesión; los paquetes no incluyen perfiles ni cookies del navegador.
"""
from __future__ import annotations
import argparse
import contextlib
import functools
import hashlib
import json
import math
import os
import re
import time
import urllib.parse
import zipfile
import shutil
from pathlib import Path
from types import SimpleNamespace

import extractor as core
from capture_quality import page_quality, merge_page
from access_diagnostics import classify_access, annotate_access
from reference_support import attach_contexts, context_collections, key as context_key, reference_graph

CATALOG = json.loads((Path(__file__).parent / "catalogos" / "origen.json").read_text(encoding="utf-8"))
EXTERNAL = {urllib.parse.urlsplit(f["href"]).hostname.removeprefix("www.") for f in CATALOG["featured"] if f.get("href")}


class DatasetChanged(core.ExtractionError):
    """La fuente cambió de generación: es necesario recopilar desde cero."""


def exam_from_url(value):
    p = urllib.parse.urlsplit(value.strip())
    if p.scheme != "https" or p.username or p.password or p.port or not p.hostname:
        raise core.ExtractionError("Usa una URL HTTPS del examen sin credenciales ni puertos.")
    host = p.hostname.removeprefix("www.")
    if host == "exambase.com":
        m = re.fullmatch(r"/exams/([\w.-]+)/([\w.-]+)(?:/practice-questions/\d+)?/?", p.path)
        if not m:
            raise core.ExtractionError("Se necesita la URL de un examen concreto, no el índice de proveedores.")
        vendor, slug = m.groups()
        base = f"https://www.exambase.com/exams/{vendor}/{slug}/practice-questions/"
        key = f"{vendor}/{slug}"
    elif host in EXTERNAL and re.fullmatch(r"/(?:practice-questions/\d+/?)?", p.path or "/"):
        vendor, slug, key = host, host.split(".")[0], host
        base = f"https://{p.netloc}/practice-questions/"
    else:
        raise core.ExtractionError("El dominio no figura en ExamBase ni entre los sitios oficiales del catálogo adjunto.")
    return {"key": key, "vendor": vendor, "slug": slug, "name": slug.replace("-", " "), "base": base}


def detect_counts(exam, page):
    r = page["payload"]["result"]
    total, pages = r.get("total"), r.get("total_pages")
    per_page = r.get("per_page") or (len(r.get("items", [])) if r.get("page") == 1 else None)
    if not all(type(n) is int and n > 0 for n in (total, pages, per_page)) or total > 100000 or pages > 20000 or (total + per_page - 1) // per_page != pages:
        raise core.ExtractionError("No se detectaron totales y paginación coherentes en la primera página.")
    return {**exam, "total": total, "pages": pages, "per_page": per_page}


def validate_page(exam, page, number):
    r = page["payload"]["result"]
    if r.get("total") not in (None, exam["total"]) or r.get("total_pages") not in (None, exam["pages"]):
        raise DatasetChanged("El sitio cambió los totales durante la extracción; no se mezclarán versiones.")
    expected = list(range((number - 1) * exam["per_page"] + 1, min(number * exam["per_page"], exam["total"]) + 1))
    orders = [q.get("order") for q in r.get("items", [])]
    if r.get("page") != number or sorted(orders) != expected or len(set(orders)) != len(orders):
        raise core.ExtractionError(f"La página {number} no coincide con su numeración esperada.")
    url = urllib.parse.urlsplit(page["url"])
    wanted = urllib.parse.urlsplit(exam["base"])
    if url.hostname.removeprefix("www.") != wanted.hostname.removeprefix("www.") or url.path.rstrip("/") != (wanted.path + str(number)).rstrip("/"):
        raise core.ExtractionError("La página corresponde a otro examen o redirigió fuera de la ruta seleccionada.")


def restore(source, output, exam):
    if source.is_dir():
        files = list(source.rglob("*.zip"))
        if len(files) != 1:
            raise core.ExtractionError("El respaldo debe contener exactamente un ZIP de resultado.")
        source = files[0]
    with zipfile.ZipFile(source) as z:
        manifests = [i for i in z.infolist() if i.filename.endswith("/manifest_examen.json")]
        if len(manifests) != 1:
            raise core.ExtractionError("El ZIP no tiene un manifiesto único de esta herramienta.")
        info = manifests[0]
        meta = json.loads(z.read(info))
        if meta.get("key") != exam["key"] or meta.get("base") != exam["base"]:
            raise core.ExtractionError("El respaldo pertenece a otro examen; no se mezclará con el seleccionado.")
        detect_counts(meta, {"payload": {"result": {"page": 1, "total": meta.get("total"), "total_pages": meta.get("pages"), "per_page": meta.get("per_page"), "items": []}}})
        root = info.filename.rsplit("/", 1)[0] + "/"
        if sum(i.file_size for i in z.infolist()) > 1024**3 or len(z.infolist()) > 50000:
            raise core.ExtractionError("El respaldo supera los límites de importación.")
        for item in z.infolist():
            if item.is_dir():
                continue
            if not item.filename.startswith(root) or "\\" in item.filename:
                raise core.ExtractionError("Ruta inválida en el respaldo.")
            relative = Path(item.filename[len(root):])
            destination = (output / relative).resolve()
            if not relative.parts or ".." in relative.parts or not destination.is_relative_to(output.resolve()) or item.file_size > 30 * 1024**2 or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise core.ExtractionError("Archivo o ruta no admitidos en el respaldo.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(z.read(item))
        return meta


def reference_repair_pages(archive, captures):
    questions=list(archive.questions.values())
    unverified={q['number'] for q in questions if '_dom_card_html' in q['raw']}
    graph=reference_graph({'exam':archive.exam,'questions':questions,'contexts':archive.contexts,
                           'assets':archive.assets.assets,'report':{'dom_questions_requiring_context_review':sorted(unverified)}})
    if graph['complete']:
        return set()
    broken_sources={edge['from'] for edge in graph['unresolved']}
    pending_objects=(broken_sources & archive.contexts.keys()) | {item['object'] for item in graph['files_pending']}
    exam_key=archive.exam['key']
    pages={source['page'] for q in questions
           if q['number'] in unverified or f'{exam_key}:q:{q["number"]:05d}' in broken_sources
           for source in q['sources']}
    if pending_objects:
        for number, capture in captures.items():
            collections=context_collections(capture['payload'])
            if any((obj.get('_object_key') or context_key(kind,obj['id'])) in pending_objects
                   for kind, objects in collections.items() for obj in objects):
                pages.add(number)
    return pages or {1}


def recover_saved_metadata(output, exam, number, saved):
    """Relee capturas conservadas sin solicitudes y sin ejecutar sus scripts."""
    if saved.get('parser') != 'dom':
        return saved
    from browser_support import current_question_page
    from capture_quality import identity
    for subdir in ('', 'previas'):
        for suffix in ('.json', '.html'):
            path = output/'paginas_originales'/subdir/f'pagina_{number:05}{suffix}'
            if not path.is_file() or path.stat().st_size > 30*1024**2:
                continue
            try:
                if suffix == '.json':
                    snapshot = json.loads(path.read_text(encoding='utf-8'))
                    if snapshot.get('format') != 'captured_html_as_data':
                        continue
                    html = snapshot['html']
                    if snapshot.get('sha256_original') != hashlib.sha256(html.encode('utf-8')).hexdigest():
                        continue
                else:
                    html = path.read_text(encoding='utf-8')
                parsed = current_question_page(html, exam['base']+str(number), number, exam)
                if parsed.get('parser') == 'dom':
                    continue
                old_items, new_items = saved['payload']['result']['items'], parsed['payload']['result']['items']
                if [identity(q) for q in old_items] != [identity(q) for q in new_items]:
                    continue
                parsed = attach_contexts(merge_page(parsed, saved), [saved['payload'], parsed['payload']])
                for field in ('capture', 'transport'):
                    if field in saved:
                        parsed[field] = saved[field]
                parsed['offline_repair'] = {'source':path.relative_to(output).as_posix(),
                                            'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                return parsed
            except (core.ExtractionError, ValueError, TypeError, KeyError, OSError):
                continue
    return saved


def run(args, source_factory=None):
    exam = exam_from_url(args.exam_url)
    if getattr(args, 'exam_name', None):
        exam['name'] = args.exam_name[:150]
    slug = re.sub(r"[^a-zA-Z0-9_-]", "_", exam["key"])[:100]
    output = args.output / ("resultado_" + slug)
    output.mkdir(parents=True, exist_ok=True)
    if args.resume_from:
        exam = restore(args.resume_from, output, exam)
    elif (output / "manifest_examen.json").exists():
        meta = json.loads((output / "manifest_examen.json").read_text())
        if meta.get("key") != exam["key"] or meta.get("base") != exam["base"]:
            raise core.ExtractionError("La carpeta de salida pertenece a otro examen.")
        exam = meta
    assets = core.AssetStore(output, ocr="off")
    previous = output / "preguntas.json"
    if previous.exists():
        for key, item in json.loads(previous.read_text(encoding="utf-8")).get("assets", {}).items():
            path = (output / item.get("local_path", "")).resolve()
            if item.get("download_status") == "downloaded" and path.is_relative_to(output.resolve()) and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == item.get("sha256"):
                assets.assets[key] = item
    archive = core.Archive(output, assets, exam)
    # Carga primero todo el respaldo: un bloqueo al reparar una página no debe
    # hacer desaparecer del nuevo ZIP las páginas posteriores ya recuperadas.
    cached_pages={}
    cache_diagnostics=[]
    recovered_pages=[]
    if exam.get('total'):
        for saved_number in range(1,exam['pages']+1):
            path=output/'capturas'/f'pagina_{saved_number:05}.json'
            if not path.is_file():continue
            try:
                saved=json.loads(path.read_text(encoding='utf-8'))
                validate_page(exam,saved,saved_number)
                repaired = recover_saved_metadata(output,exam,saved_number,saved)
                if repaired is not saved:
                    saved = repaired
                    core.write_json(path,saved)
                    recovered_pages.append(saved_number)
                archive.add_page(saved,f'capturas/{path.name}')
                cached_pages[saved_number]=saved
            except (core.ExtractionError,ValueError,KeyError,TypeError) as exc:
                cache_diagnostics.append({'page':saved_number,'issue':str(exc)})
    damaged_assets={key for key,value in assets.assets.items() if value.get('download_status')!='downloaded'}
    damaged_pages={s['page'] for q in archive.questions.values() if any(ref['asset_id'] in damaged_assets for ref in q['image_refs']) for s in q['sources']}
    repair_references=reference_repair_pages(archive,cached_pages)
    offline_complete = bool(exam.get('total') and len(cached_pages) == exam['pages']
                            and not damaged_pages and not repair_references
                            and all(not any(page_quality(p)[k] for k in ('missing_answers','empty_questions','empty_choices')) for p in cached_pages.values()))
    if offline_complete:
        factory = lambda *_: contextlib.nullcontext(SimpleNamespace(assets=None))
    elif source_factory:
        factory = source_factory
    else:
        from scrapling_support import ScraplingSource
        factory=functools.partial(ScraplingSource,headed=getattr(args,'headed',False),
                                  verification_wait=getattr(args,'verification_wait',None))
    started = time.monotonic()
    stopped = None
    failure = None
    transport_failure = None
    restart_required = False
    number = 1
    metadata_retried = set()
    try:
        with factory(exam, output, args.delay) as source:
            assets.downloader = source.assets
            number = 1
            while True:
                if time.monotonic() - started > args.max_minutes * 60:
                    stopped = "Se alcanzó el presupuesto de tiempo; se conserva el progreso para otra ejecución."
                    break
                cache = output / "capturas" / f"pagina_{number:05}.json"
                saved=cached_pages.get(number)
                needs_refresh=not saved or any(page_quality(saved)[key] for key in ('missing_answers','empty_questions','empty_choices')) or number in damaged_pages or number in repair_references
                if needs_refresh:
                    if saved:
                        print(f'Página {number}: se conserva el respaldo y se revisa el contenido pendiente.',flush=True)
                        original=output/'paginas_originales'/f'pagina_{number:05}.html'
                        if original.is_file():
                            before=original.parent/'previas'/original.name
                            before.parent.mkdir(exist_ok=True)
                            if not before.exists():shutil.copyfile(original,before)
                    page=source.page(number)
                    if saved:
                        fresh=page
                        if saved['parser']!='dom' and fresh['parser']=='dom':
                            page=merge_page(saved,fresh)
                            for field in ('capture','transport','access_failure'):
                                page.pop(field,None)
                                if field in fresh:page[field]=fresh[field]
                        else:
                            page=merge_page(fresh,saved)
                        page=attach_contexts(page,[saved['payload'],fresh['payload']])
                else:page=saved
                if number == 1 and "total" not in exam:
                    exam.update(detect_counts(exam, page))
                    archive.exam = exam
                    core.write_json(output / "manifest_examen.json", exam)
                validate_page(exam, page, number)
                if needs_refresh:
                    core.write_json(cache, page)
                    cached_pages[number]=page
                    repair_assets={ref['asset_id'] for q in archive.questions.values() if any(s['page']==number for s in q['sources']) for ref in q['image_refs']} & damaged_assets
                    for key in repair_assets:assets.assets.pop(key,None)
                    archive.add_page(page, f"capturas/{cache.name}")
                print(f"Página {number}/{exam['pages']}: {len(archive.questions)}/{exam['total']} preguntas", flush=True)
                print(f"  Respuestas pendientes en esta página: {page_quality(page)['missing_answers']}",flush=True)
                transport = page.get('transport', {})
                if needs_refresh and page['parser'] == 'dom' and transport.get('engine') == 'scrapling':
                    print(f"  Metadatos pendientes. Respuestas de datos registradas por tipo: {transport.get('network_response_types', {})}. "
                          f"Registros sin decodificar: {len(transport.get('network_incomplete', []))}.",flush=True)
                if page.get('access_failure'):
                    detail=page['access_failure']
                    stopped_access=core.AccessStopped(f'La página {number} conserva preguntas y requiere completar el acceso: {detail["kind"]}.',kind=detail['kind'],code=detail.get('code'),page=number,url=page['url'])
                    stopped_access.detail.update(detail)
                    raise stopped_access
                if args.mode == 'scrapling' and page['parser'] == 'dom' and number not in metadata_retried:
                    # La primera captura ya está guardada. Una lectura adicional puede
                    # recuperar el objeto de datos tras la actualización de la página.
                    metadata_retried.add(number)
                    repair_references.add(number)
                    print(f'Página {number}: preguntas conservadas; segunda lectura para recuperar sus metadatos.',flush=True)
                    continue
                if number >= exam["pages"] or (args.page_limit and number >= args.page_limit):
                    if number < exam["pages"]:
                        stopped = "Se alcanzó el límite de páginas solicitado; puede reanudarse desde este ZIP."
                    break
                number += 1
    except core.AccessStopped as exc:
        stopped = str(exc)
        failure = {**exc.detail, 'page': exc.detail.get('page') or number, 'url': exc.detail.get('url') or exam['base']+str(number)}
        archive.errors.append({'page': number, 'issue': stopped, 'kind': failure['kind'], 'code': failure['code']})
    except core.TransportError as exc:
        stopped = str(exc)
        transport_failure = exc.detail
        archive.errors.append({'page':number, 'issue':stopped, 'transport_failure':transport_failure})
    except (core.ExtractionError, OSError, ValueError, KeyError, TypeError) as exc:
        stopped = str(exc)
        restart_required = isinstance(exc, DatasetChanged)
        archive.errors.append({"page": number, "issue": stopped})
    except KeyboardInterrupt:
        stopped = "Ejecución interrumpida; se conserva lo recuperado en el ZIP parcial."
        archive.errors.append({"issue": stopped})
    except Exception as exc:
        stopped = f"{type(exc).__name__}: {exc}"
        archive.errors.append({"issue": stopped})
    total, pages = exam.get("total", 0), exam.get("pages", 0)
    if "total" not in exam:
        archive.errors.append({"issue": "No se pudo detectar el total del examen. El resultado es parcial."})
    data = archive.save(total, pages)
    report = data["report"]
    if "total" not in exam:
        report["expected_questions"] = None
        report["expected_pages"] = None
    report["coverage_complete"] = bool(exam.get("total")) and len(archive.questions) == total and not report["missing_pages"] and not report["missing_question_numbers"]
    core.write_json(output / "informe_validacion.json", report)
    core.write_json(output / "preguntas.json", data)
    (output / "preguntas.md").write_text(core.make_markdown(data), encoding="utf-8")
    (output / "preguntas.html").write_text(core.make_html(data), encoding="utf-8")
    from paquetes import enrich
    data = enrich(output, ocr=getattr(args, "ocr", False))
    report = data["report"]
    # add_page registra el HTML antes de recuperar imágenes: sólo contar una
    # página cuando se conservaron todas sus preguntas, incluso si falla un recurso.
    saved_pages = [n for n in report['pages_present'] if all(q in archive.questions for q in range((n-1)*exam['per_page']+1, min(n*exam['per_page'], total)+1))]
    missing_answers=set(report['answers_missing'])
    answer_pages=sorted({s['page'] for q in data['questions'] if q['number'] in missing_answers for s in q['sources']})
    failed_assets=set(report['images_failed'])
    image_pages=sorted({s['page'] for q in data['questions'] if any(ref['asset_id'] in failed_assets for ref in q['image_refs']) for s in q['sources']})
    invalid_content=set(report['empty_questions']) | {item['question'] for item in report['empty_choices']}
    content_pages=sorted({s['page'] for q in data['questions'] if q['number'] in invalid_content for s in q['sources']})
    reference_pages=sorted(reference_repair_pages(archive,cached_pages))
    pending_pages=sorted((set(range(1,pages+1))-set(saved_pages)) | set(answer_pages) | set(image_pages) | set(content_pages) | set(reference_pages))
    next_page = pending_pages[0] if pending_pages else None if pages else 1
    success = report["coverage_complete"] and report['answers_complete'] and report['references_complete'] and not report['empty_questions'] and not report['empty_choices'] and not archive.errors and not report["images_failed"] and not report.get('conflicts')
    if not success and not stopped and missing_answers:stopped=f'Hay {len(missing_answers)} preguntas sin respuesta explícita. Reanuda para reparar las páginas pendientes.'
    if not success and not transport_failure and not failure and report['answers_unmarked_in_source'] and missing_answers == set(report['answers_unmarked_in_source']):
        stopped = f'La captura de origen no marca una respuesta correcta en las preguntas {report["answers_unmarked_in_source"]}. Se conserva su contenido y explicación; requieren revisión de la fuente.'
    if not success and not stopped and invalid_content:stopped=f'Hay {len(invalid_content)} preguntas con enunciados o alternativas vacíos; se requiere recuperar su contenido.'
    unverified_metadata = report.get('dom_questions_requiring_context_review', [])
    if not success and not stopped and not report['references_complete']:
        missing_links = len(report['unresolved_references'])
        pending_files = len(report['referenced_files_pending'])
        stopped = (f'Quedan {len(unverified_metadata)} preguntas con metadatos por verificar, '
                   f'{missing_links} referencias sin resolver y {pending_files} archivos referenciados pendientes. '
                   'Consulta para_ia/referencias.json.')
    status = 'complete' if success else 'blocked' if failure else 'partial' if saved_pages else 'failed'
    content_summary = {field: report.get(field, []) for field in
                       ('images_failed', 'images_requiring_review', 'missing_explanations')}
    content_summary.update(images_found=report['images_found'], images_downloaded=report['images_downloaded'])
    diagnostic = {'status': status, 'failure': failure, 'transport_failure':transport_failure, 'pages_saved': saved_pages, 'next_page': next_page,'pages_pending_answers':answer_pages,'pages_pending_images':image_pages,'pages_pending_references':reference_pages,'answers_present':report['answers_present'],'answers_missing':report['answers_missing'],'cache_diagnostics':cache_diagnostics}
    diagnostic['pages_retried_for_metadata'] = sorted(metadata_retried)
    diagnostic['pages_recovered_offline'] = recovered_pages
    diagnostic.update(content_summary)
    core.write_json(output / 'diagnostico_acceso.json', diagnostic)
    integrity_path = output / 'integridad_sha256.json'
    integrity = json.loads(integrity_path.read_text(encoding='utf-8'))
    integrity['files']['diagnostico_acceso.json'] = hashlib.sha256((output / 'diagnostico_acceso.json').read_bytes()).hexdigest()
    core.write_json(integrity_path, integrity)
    result_zip = core.create_zip(output)
    state = {"exam": exam, "mode": args.mode, "questions": len(archive.questions), "coverage_complete": report["coverage_complete"], "execution_complete": success, "stopped_reason": stopped, "zip": result_zip.name, "review_pending": not report["collection_complete"], 'status': status, 'failure': failure, 'pages_saved': saved_pages, 'next_page': next_page, 'resume_supported': bool(saved_pages and exam.get('total')), 'runner_environment': os.environ.get('RUNNER_ENVIRONMENT', 'local')}
    state.update(answers_present=report['answers_present'],answers_missing=report['answers_missing'],answers_complete=report['answers_complete'],pages_pending_answers=answer_pages,pages_pending_images=image_pages)
    state['answers_unmarked_in_source'] = report['answers_unmarked_in_source']
    state.update(references_complete=report['references_complete'],objects_preserved=report['objects_preserved'],unresolved_references=report['unresolved_references'],metadata_unverified_questions=unverified_metadata,pages_pending_references=reference_pages,referenced_files_pending=report['referenced_files_pending'])
    state['pages_retried_for_metadata'] = sorted(metadata_retried)
    state['restart_required'] = restart_required
    state['transport_failure'] = transport_failure
    state['pages_recovered_offline'] = recovered_pages
    state.update(content_summary)
    core.write_json(args.output / "estado_ejecucion.json", state)
    print(json.dumps(state, ensure_ascii=False, indent=2), flush=True)
    if failure:
        label = 'Acceso rechazado por el sitio' if failure['kind'] == 'verification_rejected' else 'Acceso sin completar'
        hint = f"{label} en página {failure['page']}; {len(archive.questions)}/{exam.get('total') or '?'} preguntas conservadas. Código: {failure.get('code') or failure['kind']}. El ZIP parcial permite reanudar; repetir con el mismo cliente puede volver a bloquearse."
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            print('::error title='+label+'::'+hint.replace('%','%25').replace('\r','%0D').replace('\n','%0A'), flush=True)
        else:
            print(hint, flush=True)
    return 0 if success else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exam-url", required=True)
    parser.add_argument("--exam-name", help="Nombre para el lector y el historial")
    parser.add_argument("--mode", choices=["scrapling"], default="scrapling", help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, default=Path("salida"))
    parser.add_argument("--delay", type=float, default=10)
    parser.add_argument("--page-limit", type=int, default=0)
    parser.add_argument("--max-minutes", type=float, default=300)
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--ocr", action="store_true", help="Transcribir imágenes con Tesseract, siempre sin verificar")
    parser.add_argument("--headed", action="store_true", help="Navegador Scrapling visible; requiere pantalla real o Xvfb")
    parser.add_argument("--verification-wait",type=int,metavar="SEGUNDOS",help="Tiempo para completar una comprobación del sitio con scrapling --headed (1 a 300)")
    args = parser.parse_args(argv)
    if not math.isfinite(args.delay) or not math.isfinite(args.max_minutes) or args.delay < 5 or args.delay > 120 or args.page_limit < 0 or args.max_minutes <= 0:
        parser.error("delay debe estar entre 5 y 120; page-limit no puede ser negativo; max-minutes debe ser positivo")
    if args.verification_wait is not None and (args.mode!='scrapling' or not args.headed or not 1<=args.verification_wait<=300):
        parser.error("verification-wait requiere --mode scrapling --headed y un valor entre 1 y 300 segundos")
    try:
        return run(args)
    except (core.ExtractionError, ValueError, OSError, zipfile.BadZipFile) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())

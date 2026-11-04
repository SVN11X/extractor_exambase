"""Decodificación de datos de navegador; no abre sesiones por su cuenta."""
from __future__ import annotations

import json
import copy
import re
import time
import urllib.parse
from pathlib import Path


def expand_flat_data(values, resolve_deferred=None):
    """Decodifica las referencias de datos JSON de Svelte; no ejecuta código.

    Se conserva por separado el JSON original. Tipos especiales quedan como
    datos etiquetados; no se convierten en objetos ejecutables.
    """
    if not isinstance(values, list) or not values:
        return values
    cache, active = {}, set()

    def resolve(index):
        if not isinstance(index, int) or isinstance(index, bool):
            raise ValueError("Referencia inválida")
        if index in {-1, -2}:
            return None
        if index == -3:
            return float("nan")
        if index == -4:
            return float("inf")
        if index == -5:
            return float("-inf")
        if index == -6:
            return 0
        if not 0 <= index < len(values) or index in active:
            raise ValueError("Referencia circular o fuera de rango")
        if index in cache:
            return cache[index]
        active.add(index)
        raw = values[index]
        if isinstance(raw, dict):
            obj = {key: resolve(value) for key, value in raw.items()}
        elif isinstance(raw, list):
            if len(raw) == 2 and raw[0] == 'Promise' and resolve_deferred:
                obj = resolve_deferred(resolve(raw[1]))
            elif raw and isinstance(raw[0], str):
                obj = {"_type": raw[0], "values": raw[1:]}
            else:
                obj = [resolve(value) for value in raw]
        else:
            obj = raw
        active.remove(index)
        cache[index] = obj
        return obj

    return resolve(0)


def decode_network_response(body, media_type):
    """Lee JSON y los datos de navegación o acciones de SvelteKit."""
    chunks = {}
    if media_type == 'text/sveltekit-data':
        records = [json.loads(line) for line in body.splitlines() if line.strip()]
        if not records or not isinstance(records[0], dict) or records[0].get('type') != 'data':
            raise ValueError('Falta la cabecera de datos de navegación.')
        value = records[0]
        chunks = {record['id']: record['data'] for record in records[1:]
                  if isinstance(record, dict) and record.get('type') == 'chunk'
                  and type(record.get('id')) is int and 'data' in record}
    else:
        value = json.loads(body)

    if not isinstance(value, dict):
        return value
    if value.get('type') == 'success' and isinstance(value.get('data'), str):
        return {**value, 'data': expand_flat_data(json.loads(value['data']))}
    if value.get('type') != 'data':
        return value
    if not isinstance(value.get('nodes'), list):
        if isinstance(value.get('data'), list):
            return {**value, 'data': expand_flat_data(value['data'])}
        return value

    active = set()
    decoded = {}

    def resolve_deferred(identifier):
        if type(identifier) is not int or identifier not in chunks or identifier in active:
            return {'_type': 'Promise', 'id': identifier}
        if identifier not in decoded:
            active.add(identifier)
            try:
                decoded[identifier] = expand_flat_data(chunks[identifier], resolve_deferred)
            finally:
                active.remove(identifier)
        return decoded[identifier]

    return [expand_flat_data(node['data'], resolve_deferred) for node in value['nodes']
            if isinstance(node, dict) and node.get('type') == 'data' and 'data' in node]


def network_payloads(value):
    """Encuentra sólo los datos de preguntas entregados a la pestaña."""
    found = []

    def walk(obj):
        if isinstance(obj, dict):
            result = obj.get("result")
            if isinstance(result, dict) and result.get("kind") == "questions" and isinstance(result.get("items"), list):
                from reference_support import attach_contexts
                payload={k: v for k,v in obj.items() if k in {'result','page','discussions','topicId'}}
                found.append(attach_contexts({'payload':payload},obj)['payload'])
                return
            if obj.get("kind") == "questions" and isinstance(obj.get("items"), list):
                found.append({"result": obj})
                return
            if obj.get("type") == "data" and isinstance(obj.get("data"), list):
                try:
                    walk(expand_flat_data(obj["data"]))
                except (ValueError, IndexError, TypeError, RecursionError):
                    pass
            for child in obj.values():
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(obj, list):
            for child in obj:
                if isinstance(child, (dict, list)):
                    walk(child)

    walk(value)
    return found


def choose_page(candidates, number, source, *, exam=None):
    # Más reciente primero: no mezclar los datos de otra página de la sesión.
    for payload in reversed(candidates):
        if payload.get("result", {}).get("page") == number:
            page = {"url": source, "parser": "browser-network", "payload": payload, "warnings": []}
            if exam is not None:
                from descargar import detect_counts, validate_page
                from extractor import ExtractionError
                try:
                    validate_page(exam if exam.get('total') else detect_counts(exam, page), page, number)
                except (ExtractionError, ValueError, KeyError, TypeError, AttributeError):
                    continue
            return page
    return None


def verification_error(source, core):
    """Detectar un fallo ya mostrado; no tocar el widget ni reintentarlo."""
    root = core.TreeReader(source).root
    headings = [n.text().strip().lower().replace("’", "'") for n in root.walk() if n.tag in {"h1", "h2", "h3", "h4", "h5"}]
    if not any("verification didn't go through" in h or "verification failed" in h for h in headings):
        return None
    visible = core.readable(source)
    match = re.search(r"\berror\s*[:(]?\s*(\d{6})\b", visible, re.I)
    return match.group(1) if match else "sin código visible"


def align_numbering(candidate, visible, metadata, number):
    """Vincula el orden interno con el número mostrado sólo con contenido idéntico."""
    from capture_quality import identity
    from descargar import validate_page
    from extractor import ExtractionError
    result = candidate['payload']['result']
    if result.get('kind') != 'questions' or result.get('page') != number:
        raise ExtractionError('Los datos corresponden a otra página.')
    source_items = result.get('items') or []
    visible_items = visible['payload']['result']['items']
    identities = [identity(question) for question in visible_items]
    if len(source_items) != len(visible_items) or len(set(identities)) != len(identities):
        raise ExtractionError('No hay una correspondencia única entre datos y preguntas visibles.')
    if [identity(question) for question in source_items] != identities:
        raise ExtractionError('Los datos y las preguntas visibles tienen contenido distinto.')
    aligned = copy.deepcopy(candidate)
    pairs = []
    for question, shown in zip(aligned['payload']['result']['items'], visible_items):
        if question.get('order') != shown['order']:
            pairs.append({'source_id':question.get('id'), 'source_order':question.get('order'), 'number':shown['order']})
            question['source_order'] = question.get('order')
            question['order'] = shown['order']
    # Conserva la URL y los contadores originales: no permite reparar otro examen
    # ni ocultar un cambio de totales como si fuera un cambio de numeración.
    validate_page(metadata, aligned, number)
    if pairs:
        aligned['numbering_alignment'] = {'method':'identical_visible_content', 'questions':pairs}
    return aligned


def current_question_page(source, url, number, exam, preferred=None, *, candidates=()):
    """Acepta sólo preguntas completas de la URL y numeración solicitadas.

    Una SPA puede conservar scripts iniciales o avisos ocultos de otra página.
    El DOM correcto tiene prioridad sobre esos residuos. No resuelve desafíos.
    """
    import extractor as core
    from descargar import detect_counts, validate_page, DatasetChanged
    from html_support import soup_page
    from capture_quality import merge_page, identity
    attempts = []
    changed = None
    valid = []
    visible = None
    try:
        visible = soup_page(source, url)
        validate_page(exam if exam.get('total') else detect_counts(exam, visible), visible, number)
    except (core.ExtractionError, ValueError, KeyError, TypeError):
        visible = None
    readers = ([lambda: preferred] if preferred else []) + [
        *[lambda payload=payload: {'url':url, 'parser':'browser-network', 'payload':payload, 'warnings':[]}
          for payload in reversed(candidates) if payload.get('result',{}).get('page') == number],
        lambda: core.parse_page(source, url, expected_page=number),
        lambda: visible if visible else soup_page(source, url),
    ]
    for read in readers:
        try:
            candidate = read()
            metadata = exam if exam.get('total') else detect_counts(exam, candidate)
            try:
                validate_page(metadata, candidate, number)
            except DatasetChanged:
                raise
            except core.ExtractionError:
                if not visible or candidate.get('parser') == 'dom':
                    raise
                candidate = align_numbering(candidate, visible, metadata, number)
            if visible and candidate.get('parser') != 'dom':
                actual = {q['order']:identity(q) for q in candidate['payload']['result']['items']}
                shown = {q['order']:identity(q) for q in visible['payload']['result']['items']}
                if actual != shown:
                    raise core.ExtractionError('Los datos no corresponden al contenido visible de estas preguntas.')
            valid.append(candidate)
        except (core.ExtractionError, ValueError, KeyError, TypeError) as exc:
            if isinstance(exc, DatasetChanged):
                changed = exc
            attempts.append(str(exc))
    if valid:
        result = valid[0]
        for candidate in valid[1:]:result = merge_page(result,candidate)
        return result
    if changed:
        raise changed
    raise core.ExtractionError(attempts[-1] if attempts else 'No hay preguntas válidas de esta página.')

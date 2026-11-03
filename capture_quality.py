"""Cobertura de preguntas y respuestas, separada de la revisión académica."""
import copy
import re
import extractor as core


def raw_answered(question):
    choices = question.get('choices') or []
    return bool(question.get('answer_image_url')) or any(c.get('is_correct') is True and re.fullmatch(r'[A-Z]',str(c.get('letter',''))) for c in choices)


def page_quality(page):
    questions = page['payload']['result'].get('items') or []
    return {'questions':len(questions),'missing_answers':[q.get('order') for q in questions if not raw_answered(q)],
            'missing_explanations':[q.get('order') for q in questions if not q.get('solution_text')],
            'empty_choices':[q.get('order') for q in questions if any(not core.readable(c.get('text','')).strip() and not core.scan_images({'text':c.get('text','')}) for c in q.get('choices') or [])],
            'empty_questions':[q.get('order') for q in questions if not core.readable(q.get('question_text','')).strip() and not core.scan_images({'question_text':q.get('question_text','')})]}


def identity(question):
    clean=lambda value:re.sub(r'\s+',' ',core.readable(value or '')).strip()
    media=lambda value:tuple(ref['source'] for ref in core.scan_images({'text':value or ''}))
    return (clean(question.get('question_text')),media(question.get('question_text')),tuple((c.get('letter'),clean(c.get('text')),media(c.get('text'))) for c in question.get('choices') or []))


def merge_page(base, supplement):
    """Conserva metadatos y sólo añade claves/explicaciones de preguntas idénticas."""
    merged=copy.deepcopy(base)
    extra={q.get('order'):q for q in supplement['payload']['result']['items']}
    enriched=[]
    for question in merged['payload']['result']['items']:
        other=extra.get(question.get('order'))
        if not other or identity(question)!=identity(other):continue
        first={c['letter'] for c in question.get('choices') or [] if c.get('is_correct') is True}
        second={c['letter'] for c in other.get('choices') or [] if c.get('is_correct') is True}
        if first and second and first!=second:
            raise core.ExtractionError(f'Claves explícitas contradictorias para la pregunta {question["order"]}; se conservan los originales para revisar.')
        changed=False
        if not first and second:
            for choice in question.get('choices') or []:
                if choice.get('letter') in second:choice['is_correct']=True
            changed=True
        for field in ('solution_text','answer_image_url'):
            if not question.get(field) and other.get(field):question[field]=other[field];changed=True
        if changed:enriched.append(question['order'])
    if enriched:
        merged.setdefault('enrichment',[]).append({'parser':supplement.get('parser'),'questions':enriched})
    return merged


def answers_report(data):
    missing=[];empty=[];empty_choices=[]
    for question in data['questions']:
        letters={c.get('letter') for c in question.get('choices') or []}
        answer=question.get('correct_choices') or []
        if not (answer and all(isinstance(c,str) and re.fullmatch(r'[A-Z]',c) and c in letters for c in answer)) and not question.get('answer_image_url'):
            missing.append(question['number'])
        if not question.get('question_text','').strip() and not core.scan_images({'question_html':question.get('question_html','')}):empty.append(question['number'])
        for choice in question.get('choices') or []:
            if not choice.get('text','').strip() and not core.scan_images({'html':choice.get('html','')}):empty_choices.append({'question':question['number'],'letter':choice.get('letter')})
    return {'answers_present':len(data['questions'])-len(missing),'answers_missing':missing,
            'answers_complete':bool(data['questions']) and not missing,'empty_questions':empty,'empty_choices':empty_choices}

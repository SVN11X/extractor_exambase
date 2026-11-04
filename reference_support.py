"""Objetos y referencias explícitas. No inventa relaciones ni consulta URLs ocultas."""
import copy
import json
import urllib.parse

COLLECTIONS={'topics':'topics','series':'series','case_studies':'case_studies','caseStudies':'case_studies',
             'contexts':'context','context_objects':'context','objects':'object','attachments':'attachment','exhibits':'exhibit','scenarios':'scenario'}
SINGULAR={'topic':'topics','case_study':'case_studies','caseStudy':'case_studies','context':'context','scenario':'scenario','attachment':'attachment','exhibit':'exhibit'}
FIELDS={'topic_id':'topics','topicId':'topics','series_id':'series','seriesId':'series','case_study_id':'case_studies','caseStudyId':'case_studies',
        'context_id':'context','scenario_id':'scenario','exhibit_id':'exhibit','attachment_id':'attachment'}


def key(kind,identifier):
    return f'{kind}:{identifier}' if kind in {'topics','series','case_studies'} else f'objects:{kind}:{identifier}'


def foreign_fields(raw):
    result=[]
    for container in [raw,raw.get('type_data') or {}]:
        if not isinstance(container,dict):continue
        for field,value in container.items():
            if field.endswith('_id') and field not in FIELDS and field not in {'id','question_id','exam_id','source_id'} and value is not None:
                result.append({'field':field,'source_id':value,'target':key(field[:-3],value)})
    return result


def context_collections(value):
    found={name:{} for name in ('topics','series','case_studies','objects')}
    def add(kind,obj):
        if not isinstance(obj,dict) or obj.get('id') is None:return
        if kind=='object':kind=str(obj.get('_object_kind') or obj.get('kind') or obj.get('type') or 'object')
        object_key=key(kind,obj['id'])
        item=copy.deepcopy(obj)
        if kind not in {'topics','series','case_studies'}:item.update(_object_key=object_key,_object_kind=kind)
        found[kind if kind in found else 'objects'][object_key]=item
    def walk(obj,depth=0):
        if depth>25:return
        if isinstance(obj,dict):
            for field,kind in COLLECTIONS.items():
                items=obj.get(field)
                if isinstance(items,dict):items=[items] if items.get('id') is not None else list(items.values())
                if isinstance(items,list):
                    for item in items:add(kind,item)
            for field,kind in SINGULAR.items():
                if isinstance(obj.get(field),dict):add(kind,obj[field])
            kind=obj.get('kind')
            if kind in SINGULAR:add(SINGULAR[kind],obj)
            for item in obj.values():
                if isinstance(item,(dict,list)):walk(item,depth+1)
        elif isinstance(obj,list):
            for item in obj:walk(item,depth+1)
    walk(value)
    return {kind:list(items.values()) for kind,items in found.items()}


def attach_contexts(page, values):
    result=copy.deepcopy(page)
    collections=context_collections(values)
    for kind,items in collections.items():
        if not items and kind not in result['payload']['result']:continue
        current=result['payload']['result'].get(kind) or []
        if isinstance(current,dict):current=list(current.values())
        unique={item.get('_object_key') or key(kind,item.get('id')):item for item in current if isinstance(item,dict)}
        for item in items:unique[item.get('_object_key') or key(kind,item.get('id'))]=item
        result['payload']['result'][kind]=list(unique.values())
    return result


def question_refs(raw):
    refs=[]
    for container in [raw,raw.get('type_data') or {}]:
        if not isinstance(container,dict):continue
        for field,kind in FIELDS.items():
            if container.get(field) is not None:refs.append(key(kind,container[field]))
        for field,kind in SINGULAR.items():
            obj=container.get(field)
            if isinstance(obj,dict) and obj.get('id') is not None:refs.append(key(kind,obj['id']))
        for field,kind in [('attachment_ids','attachment'),('context_ids','context'),('exhibit_ids','exhibit')]:
            for identifier in container.get(field) or []:refs.append(key(kind,identifier))
        for field,kind in [('attachments','attachment'),('contexts','context'),('exhibits','exhibit')]:
            for obj in container.get(field) or []:
                if isinstance(obj,dict) and obj.get('id') is not None:refs.append(key(kind,obj['id']))
        for obj in container.get('object_refs') or []:
            if isinstance(obj,dict) and obj.get('id') is not None:refs.append(key(str(obj.get('kind') or obj.get('type') or 'object'),obj['id']))
    return list(dict.fromkeys(refs))


def reference_graph(data):
    exam=data['exam']['key'];questions=data['questions'];objects=data.get('contexts',{})
    qids={str(q['id']):f'{exam}:q:{q["number"]:05d}' for q in questions if q.get('id') is not None}
    nodes=[{'id':f'{exam}:q:{q["number"]:05d}','type':'question','number':q['number'],'source_id':q.get('id')} for q in questions]
    nodes += [{'id':k,'type':'object','source_id':v['raw'].get('id'),'raw':v['raw']} for k,v in objects.items()]
    edges=[];unresolved=[];files=[]
    for q in questions:
        for target in q.get('context_refs',[]):
            edge={'from':f'{exam}:q:{q["number"]:05d}','to':target,'relation':'context'};edges.append(edge)
            if target not in objects:unresolved.append(edge)
        for item in foreign_fields(q.get('raw') or {}):
            if item['target'] in q.get('context_refs',[]):continue
            if item['target'] in objects:
                edges.append({'from':f'{exam}:q:{q["number"]:05d}','to':item['target'],'relation':'context'})
            else:
                unresolved.append({'from':f'{exam}:q:{q["number"]:05d}','to':None,'field':item['field'],'source_id':item['source_id'],'relation':'unclassified_reference'})
    for object_key,obj in objects.items():
        raw=obj['raw'];targets=raw.get('question_ids') or []
        if raw.get('question_id') is not None:targets=[*targets,raw['question_id']]
        for identifier in targets:
            target=qids.get(str(identifier));edge={'from':object_key,'to':target,'source_question_id':identifier,'relation':'question'};edges.append(edge)
            if target is None:unresolved.append(edge)
        for target in question_refs(raw):
            if target==object_key:continue
            edge={'from':object_key,'to':target,'relation':'object'};edges.append(edge)
            if target not in objects:unresolved.append(edge)
        for item in foreign_fields(raw):
            edge={'from':object_key,'to':item['target'] if item['target'] in objects else None,'field':item['field'],'source_id':item['source_id'],'relation':'object'}
            edges.append(edge)
            if edge['to'] is None:unresolved.append(edge)
        for field in ('attachment_url','file_url','download_url'):
            if isinstance(raw.get(field),str):
                address=urllib.parse.urljoin(data['exam'].get('base') or '',raw[field])
                if not any(a.get('source_url')==address and a.get('download_status')=='downloaded' for a in data.get('assets',{}).values()):files.append({'object':object_key,'field':field,'url':raw[field],'status':'reference_preserved_not_downloaded'})
    pending=data['report'].get('dom_questions_requiring_context_review') or []
    return {'schema_version':'1.0','nodes':nodes,'edges':edges,'unresolved':unresolved,'files_pending':files,
            'metadata_unverified_questions':pending,'complete':not unresolved and not files and not pending}

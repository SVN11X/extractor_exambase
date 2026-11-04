import contextlib
import copy
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import acciones
import descargar
import paquetes
from actualizar_catalogo import update
from migrar_bancos import migrate
from persistir_banco import persist, current_entries
from scrapling_support import ScraplingAssets
from test_actions import page


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'automatizacion').mkdir()
        (self.root/'catalogos').mkdir()
        config = json.loads((Path(__file__).parents[1]/'automatizacion/config.json').read_text())
        config['max_examenes_por_lote'] = 1
        (self.root/'automatizacion/config.json').write_text(json.dumps(config))
        catalog = {'vendors':[{'slug':'cisco','vendor':'Cisco'},{'slug':'google-cloud','vendor':'Google Cloud'}],
                   'exams':[{'id':f'cisco/{key}','url':f'https://www.exambase.com/exams/cisco/{key}','name':key,'vendor':'Cisco','vendor_slug':'cisco'} for key in ('uno','dos')],
                   'vendor_updated_at':{'cisco':datetime.now(timezone.utc).isoformat(),'google-cloud':datetime.now(timezone.utc).isoformat()}}
        (self.root/'catalogos/catalogo.json').write_text(json.dumps(catalog))
        self.calls=[]
    def tearDown(self):
        self.temp.cleanup()
    def collector(self, args, blocked=False, partial=False):
        self.calls.append(args)
        class Source:
            assets=None
            def __init__(self, exam, *_): self.exam=exam
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def page(self, number):
                if blocked:
                    raise descargar.core.AccessStopped('Bloqueo sintético 600010',kind='verification_rejected',code='600010')
                return page(self.exam,number)
        if partial:args.page_limit=1
        return descargar.run(args, Source)
    def execute(self, mode, value=None, **kw):
        with contextlib.redirect_stdout(io.StringIO()):
            return acciones.execute(self.root,mode,value,collector=kw.pop('collector',self.collector),**kw)
    def folder(self, slug='uno'):
        return self.root/'bancos/cisco'/slug
    def generate(self, folder, partial=False):
        args=SimpleNamespace(exam_url='https://www.exambase.com/exams/cisco/uno',output=self.root/folder,resume_from=None,mode='scrapling',delay=5,max_minutes=10,page_limit=0,headed=True)
        with contextlib.redirect_stdout(io.StringIO()):self.collector(args,partial=partial)
        return args.output

    def test_individual_update_replaces_same_path_and_starts_fresh(self):
        self.assertEqual(self.execute('examen','https://www.exambase.com/exams/cisco/uno'),0)
        self.assertEqual(self.execute('examen','https://www.exambase.com/exams/cisco/uno'),0)
        self.assertIsNone(self.calls[-1].resume_from)
        self.assertEqual(self.calls[-1].mode,'scrapling')
        self.assertEqual(list((self.root/'bancos/cisco').iterdir()),[self.folder()])
        self.assertEqual(len(current_entries(self.root)['exams']),1)

    def test_partial_refresh_keeps_complete_and_resumes_one_checkpoint(self):
        self.execute('examen','https://www.exambase.com/exams/cisco/uno')
        original=(self.folder()/'resultado.zip').read_bytes()
        self.execute('examen','https://www.exambase.com/exams/cisco/uno',collector=lambda args:self.collector(args,partial=True))
        self.assertEqual((self.folder()/'resultado.zip').read_bytes(),original)
        self.assertTrue((self.folder()/'progreso.zip').exists())
        self.assertEqual(self.execute('examen','https://www.exambase.com/exams/cisco/uno'),0)
        self.assertEqual(self.calls[-1].resume_from,self.folder()/'progreso.zip')
        self.assertFalse((self.folder()/'progreso.zip').exists())
        self.assertEqual(len(list(self.folder().glob('*.zip'))),1)

    def test_first_partial_is_resumed_automatically(self):
        self.execute('examen','https://www.exambase.com/exams/cisco/uno',collector=lambda args:self.collector(args,partial=True))
        self.assertEqual(self.execute('examen','https://www.exambase.com/exams/cisco/uno'),0)
        self.assertEqual(self.calls[-1].resume_from,self.folder()/'resultado.zip')

    def test_publication_failure_restores_previous_bank_and_index(self):
        self.execute('examen','https://www.exambase.com/exams/cisco/uno')
        old=(self.folder()/'resultado.zip').read_bytes()
        index=(self.root/'bancos/index.json').read_bytes()
        output=self.generate('replacement')
        with patch('persistir_banco.atomic_json',side_effect=OSError('disco lleno')):
            with self.assertRaises(OSError):persist(output,self.root,'8')
        self.assertEqual((self.folder()/'resultado.zip').read_bytes(),old)
        self.assertEqual((self.root/'bancos/index.json').read_bytes(),index)
        self.assertFalse(any(p.name.startswith('.') for p in (self.root/'bancos/cisco').iterdir()))

    def test_backup_tampering_is_rejected_without_overwrite(self):
        self.execute('examen','https://www.exambase.com/exams/cisco/uno',collector=lambda args:self.collector(args,partial=True))
        path=self.folder()/'resultado.zip'
        path.write_bytes(path.read_bytes()+b'changed')
        before=path.read_bytes()
        self.assertEqual(self.execute('examen','https://www.exambase.com/exams/cisco/uno'),2)
        self.assertEqual(path.read_bytes(),before)

    def test_batches_continue_next_exam_and_rotate_provider(self):
        self.assertEqual(self.execute('automatico'),0)
        self.assertEqual(self.calls[-1].exam_url.rsplit('/',1)[-1],'dos')
        queue=json.loads((self.root/'automatizacion/estado.json').read_text())
        self.assertEqual(queue['siguiente_proveedor'],0)
        self.assertEqual(self.execute('automatico'),0)
        self.assertEqual(self.calls[-1].exam_url.rsplit('/',1)[-1],'uno')
        queue=json.loads((self.root/'automatizacion/estado.json').read_text())
        self.assertEqual(queue['siguiente_proveedor'],1)
        self.assertEqual(len(current_entries(self.root)['exams']),2)

    def test_block_stops_batch_and_defers_provider(self):
        cfg=self.root/'automatizacion/config.json';data=json.loads(cfg.read_text());data['max_examenes_por_lote']=10;cfg.write_text(json.dumps(data))
        self.assertEqual(self.execute('automatico',collector=lambda args:self.collector(args,blocked=True)),2)
        self.assertEqual(len(self.calls),1)
        self.assertIn('cisco',json.loads((self.root/'automatizacion/estado.json').read_text())['proveedores_bloqueados'])
        state=json.loads((self.folder('dos')/'estado_ejecucion.json').read_text())
        self.assertEqual(state['questions'],0)
        self.assertIn('600010',(self.root/'salida/resumen.md').read_text())

    def test_budget_stops_before_next_exam(self):
        cfg=self.root/'automatizacion/config.json';data=json.loads(cfg.read_text());data['max_examenes_por_lote']=10;cfg.write_text(json.dumps(data))
        self.assertEqual(self.execute('automatico',clock=iter([0,0,240*60]).__next__),0)
        self.assertEqual(len(self.calls),1)
        self.assertIn('**1**',(self.root/'salida/resumen.md').read_text())

    def test_catalog_block_does_not_start_exam_or_delete_previous_catalog(self):
        path=self.root/'catalogos/catalogo.json';data=json.loads(path.read_text());data['vendor_updated_at']={};path.write_text(json.dumps(data))
        def updater(path,slug,delay):
            source=SimpleNamespace(get=lambda _:(_ for _ in ()).throw(descargar.core.AccessStopped('bloqueado')))
            return update(path,slug,delay,source)
        self.assertEqual(self.execute('automatico',catalog_updater=updater),2)
        self.assertFalse(self.calls)
        self.assertEqual(sorted(json.loads(path.read_text())['exams'],key=lambda e:e['id']), sorted(data['exams'],key=lambda e:e['id']))

    def test_incomplete_catalog_is_not_marked_as_complete(self):
        path=self.root/'catalogos/catalogo.json';data=json.loads(path.read_text());data['vendors'][0]['liveCount']=2;path.write_text(json.dumps(data))
        source=SimpleNamespace(get=lambda _: (b'<main><a href="/exams/cisco/uno">Uno 7 questions</a></main>','text/html','utf-8'))
        result=update(path,'cisco',5,source)
        self.assertTrue(result['errors'])
        self.assertEqual(sorted(json.loads(path.read_text())['exams'],key=lambda e:e['id']), sorted(data['exams'],key=lambda e:e['id']))

    def test_alias_catalogs_keep_both_memberships_without_duplicate_exams(self):
        path=self.root/'catalogos/catalogo.json'
        data=json.loads(path.read_text());data['vendors'].append({'slug':'google','vendor':'Google'});path.write_text(json.dumps(data))
        source=SimpleNamespace(get=lambda _: (b'<main><a href="/exams/google/demo">Demo 7 questions</a></main>','text/html','utf-8'))
        update(path,'google-cloud',5,source);update(path,'google',5,source)
        matches=[e for e in json.loads(path.read_text())['exams'] if e['id']=='google/demo']
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0]['vendor_slugs'],['google','google-cloud'])

    def test_migration_prefers_complete_over_newer_partial_and_is_idempotent(self):
        complete=self.generate('old-complete');partial=self.generate('old-partial',partial=True)
        rows=[]
        for run,output in [('10',complete),('20',partial)]:
            target=self.root/'bancos/cisco_uno-abcd1234'/run;target.mkdir(parents=True)
            state=json.loads((output/'estado_ejecucion.json').read_text());archive=output/state['zip']
            shutil.copy2(archive,target/archive.name);shutil.copy2(output/'estado_ejecucion.json',target/'estado_ejecucion.json')
            rows.append({'run_id':run,'zip_path':str((target/archive.name).relative_to(self.root)),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'generated_at':run})
        (self.root/'bancos/index.json').write_text(json.dumps({'schema_version':'1.0','runs':rows}))
        self.assertEqual(migrate(self.root),{'migrated':2,'exams':1})
        self.assertFalse((self.root/'bancos/cisco_uno-abcd1234').exists())
        self.assertEqual(current_entries(self.root)['exams'][0]['run_id'],'10')
        self.assertEqual(migrate(self.root),{'migrated':0,'exams':1})

    def test_exports_preserve_html_as_data_and_do_not_ship_scripts(self):
        output=self.generate('export')
        material=output/'resultado_cisco_uno'
        originals=material/'paginas_originales';originals.mkdir()
        html='<script>location="https://example.invalid"</script><h1>Captura</h1>'
        (originals/'pagina_00001.html').write_text(html)
        (material/'lector.js').write_text('legacy')
        result=paquetes.enrich(material)
        saved=json.loads((originals/'pagina_00001.json').read_text())
        self.assertEqual(saved['html'],html)
        self.assertEqual(saved['sha256_original'],hashlib.sha256(html.encode()).hexdigest())
        self.assertFalse((material/'lector.js').exists())
        self.assertFalse(list(originals.glob('*.html')))
        reader=(material/'preguntas.html').read_text()
        self.assertNotIn('<script',reader)
        self.assertIn("script-src 'none'",reader)
        self.assertIn('details open',reader)
        self.assertEqual(len(result['questions']),7)
        self.assertEqual(result['export_security']['antivirus_verdict'],'not_scanned')

    def test_changed_totals_restart_a_stale_partial_without_mixing_versions(self):
        self.execute('examen','https://www.exambase.com/exams/cisco/uno',collector=lambda args:self.collector(args,partial=True))
        resumed=[]
        def changed(args):
            resumed.append(args.resume_from)
            class Source:
                assets=None
                def __init__(self,exam,*_):self.exam=exam
                def __enter__(self):return self
                def __exit__(self,*_):pass
                def page(self,number):
                    result=page(self.exam,number,total=9)
                    for q in result['payload']['result']['items']:q['question_text']='Nueva versión '+str(q['order'])
                    return result
            return descargar.run(args,Source)
        self.assertEqual(self.execute('examen','https://www.exambase.com/exams/cisco/uno',collector=changed),0)
        self.assertEqual(len(resumed),2)
        self.assertIsNotNone(resumed[0]);self.assertIsNone(resumed[1])
        with zipfile.ZipFile(self.folder()/'resultado.zip') as z:
            data=json.loads(z.read(next(n for n in z.namelist() if n.endswith('/preguntas.json'))))
        self.assertEqual(len(data['questions']),9)
        self.assertTrue(all(q['question_text'].startswith('Nueva versión') for q in data['questions']))

    def test_current_catalog_count_allows_a_removed_exam(self):
        path=self.root/'catalogos/catalogo.json';data=json.loads(path.read_text());data['vendors'][0]['liveCount']=2;path.write_text(json.dumps(data))
        source=SimpleNamespace(get=lambda _: (b'<main><h1>Cisco</h1><p>1 exam</p><a href="/exams/cisco/uno">Uno 7 questions</a></main>','text/html','utf-8'))
        self.assertFalse(update(path,'cisco',5,source)['errors'])
        result=json.loads(path.read_text())
        self.assertEqual([e['id'] for e in result['exams']],['cisco/uno'])
        self.assertEqual(result['vendors'][0]['liveCount'],1)

    def test_summary_distinguishes_partial_banks_from_cooldown(self):
        self.execute('proveedor','cisco',collector=lambda args:self.collector(args,partial=True))
        from acciones import queue_counts, summary, read
        catalog=read(self.root/'catalogos/catalogo.json')
        index={e['exam_key']:e for e in current_entries(self.root)['exams']}
        counts=queue_counts(catalog['exams'],index,acciones.configuration(self.root),datetime.now(timezone.utc),'cisco')
        self.assertEqual(counts['partial'],1)
        self.assertEqual(counts['new'],1)
        self.assertEqual(counts['deferred'],1)
        text=summary([],queue_info=counts)
        self.assertIn('Bancos parciales o actualizaciones pendientes: **1**',text)
        self.assertNotIn('Exámenes elegibles pendientes en este proveedor: **0**',text)

    def test_manual_provider_can_continue_a_partial_without_waiting_a_day(self):
        self.execute('examen','https://www.exambase.com/exams/cisco/uno',collector=lambda args:self.collector(args,partial=True))
        catalog=acciones.read(self.root/'catalogos/catalogo.json')
        index={e['exam_key']:e for e in current_entries(self.root)['exams']}
        exams=[e for e in catalog['exams'] if e['id']=='cisco/uno']
        self.assertEqual(acciones.eligible(exams,index,acciones.configuration(self.root),datetime.now(timezone.utc)),[])
        self.assertEqual(len(acciones.eligible(exams,index,acciones.configuration(self.root),datetime.now(timezone.utc),manual=True)),1)

    def test_transport_error_stops_the_batch_without_claiming_an_access_block(self):
        cfg=self.root/'automatizacion/config.json';data=json.loads(cfg.read_text());data['max_examenes_por_lote']=10;cfg.write_text(json.dumps(data))
        def broken(args):
            self.calls.append(args)
            class Source:
                assets=None
                def __init__(self,exam,*_):self.exam=exam
                def __enter__(self):return self
                def __exit__(self,*_):pass
                def page(self,n):
                    from access_diagnostics import transport_exception
                    if n==2:raise transport_exception(Exception('net::ERR_HTTP_RESPONSE_CODE_FAILURE'),self.exam['base']+'2',2)
                    return page(self.exam,n)
            return descargar.run(args,Source)
        self.assertEqual(self.execute('automatico',collector=broken),2)
        self.assertEqual(len(self.calls),1)
        queue=json.loads((self.root/'automatizacion/estado.json').read_text())
        self.assertNotIn('cisco',queue.get('proveedores_bloqueados',{}))
        self.assertIn('ERR_HTTP_RESPONSE_CODE_FAILURE',(self.root/'salida/resumen.md').read_text())

    def test_scrapling_images_use_only_same_session_bytes(self):
        assets=ScraplingAssets(SimpleNamespace(exam={'base':'https://www.exambase.com/exams/cisco/demo/'}))
        url='https://www.exambase.com/media/one.png'
        assets.update({},[{'url':url,'data':'data:image/png;base64,aW1hZ2U='}])
        self.assertEqual(assets.get(url)[0],b'image')
        with self.assertRaises(descargar.core.ExtractionError):assets.get('https://elsewhere.test/one.png')
        assets.update({},[{'url':url,'status':403}])
        with self.assertRaises(descargar.core.AccessStopped):assets.get(url)


if __name__=='__main__':unittest.main()

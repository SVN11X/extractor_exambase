"""Captura de controles de contenido; no pulsa ni reinicia desafíos de acceso."""
import json
from pathlib import Path

SCRIPT = Path(__file__).with_name('capture_page.js').read_text(encoding='utf-8')


def capture_script(number, exam, *, images=False):
    expected = None
    if exam.get('total') and exam.get('per_page'):
        expected = min(exam['per_page'], max(0, exam['total']-(number-1)*exam['per_page']))
    options = {'page':number,'expectedCount':expected,'waitMs':20000,'revealMs':28000,'imageMs':12000,'images':images}
    return SCRIPT.replace('__EXAMBASE_CAPTURE_OPTIONS__',json.dumps(options))

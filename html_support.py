"""Lectura de preguntas HTML con Beautiful Soup, sin acceso de red."""
import re
import extractor as core

def soup_page(source, url):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(source, 'html.parser')
    items = []
    for heading in soup.select('h4.card-title'):
        match = re.fullmatch(r'Question\s+(\d+)', heading.get_text(' ', strip=True))
        card = heading.find_parent(class_='card')
        if not match or not card:
            continue
        rich = card.select('.exambase-question__rich-text')
        if not rich:
            continue
        choices = []
        for li in card.select('.list-group-item'):
            letter = next((s.get_text(strip=True) for s in li.select('span') if re.fullmatch('[A-Z]', s.get_text(strip=True))), None)
            body = li.select_one('.exambase-question__rich-text')
            if letter and body:
                correct = core.dom_choice_is_correct(str(li))
                choices.append({'letter': letter, 'text': body.decode_contents(), 'is_correct': True if correct else None})
        explanation = ''
        for header in card.select('.card-header'):
            if header.get_text(' ', strip=True) == 'Explanation':
                body = header.parent.select_one('.exambase-question__rich-text')
                if body:
                    explanation = body.decode_contents()
        items.append({'id': None, 'order': int(match[1]), 'question_text': rich[0].decode_contents(), 'solution_text': explanation, 'choices': choices, 'type_data': {}, '_dom_card_html': str(card)})
    if not items:
        return core.parse_page(source, url)
    counts = re.search(r'Showing\s+(?:\d+\s*(?:[-–]|to)\s*)?\d+\s+of\s+(\d+)\s*[·•]\s*page\s+(\d+)\s+of\s+(\d+)', soup.get_text(' ', strip=True))
    page = re.search(r'/practice-questions/(\d+)', url)
    return {'url': url, 'parser': 'dom', 'warnings': ['Beautiful Soup leyó el DOM visible; metadatos de contexto pendientes de revisión.'], 'payload': {'result': {'kind': 'questions', 'page': int(counts[2]) if counts else int(page[1]) if page else None, 'total': int(counts[1]) if counts else None, 'total_pages': int(counts[3]) if counts else None, 'items': items, 'topics': [], 'series': [], 'case_studies': []}}}

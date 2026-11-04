"""Clasifica evidencia de acceso sin atribuir todo HTTP 403 a un antibot."""
import re
import extractor as core


def classify_access(source, status=None):
    root=core.TreeReader(source).root
    def visible(node):
        while node:
            if 'hidden' in node.attrs or node.attrs.get('aria-hidden')=='true' or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden',node.attrs.get('style',''),re.I):return False
            node=node.parent
        return True
    headings=' '.join(n.text().strip() for n in root.walk() if n.tag in {'title','h1','h2','h3'} and visible(n)).lower().replace('’',"'")
    text=core.readable(source)
    provider='cloudflare' if re.search(r'cloudflare|challenges\.cloudflare\.com|cf-chl-|cf-turnstile',source,re.I) else None
    code=re.search(r'\berror\s*[:(]?\s*([36]\d{5})\b',text,re.I)
    ray=re.search(r'Cloudflare Ray ID\s*:?\s*([a-f0-9]{12,32})',text,re.I)
    if 'verification failed' in headings or "verification didn't go through" in headings:
        return {'kind':'verification_rejected','code':code[1] if code else None,'provider':provider or 'cloudflare','retryable':False,'ray_id':ray[1] if ray else None}
    if provider and re.search(r'access denied|sorry, you have been blocked|attention required',headings):
        return {'kind':'bot_access_denied','code':str(status) if status else None,'provider':provider,'retryable':False}
    if provider and re.search(r'just a moment|checking (your browser|that you.re human)|verify (you are|that you.re) human|verifying you are human',headings):
        return {'kind':'challenge_pending','code':code[1] if code else None,'provider':provider,'retryable':False}
    if any(n.tag=='iframe' and 'challenges.cloudflare.com' in n.attrs.get('src','') and visible(n) for n in root.walk()):
        return {'kind':'challenge_pending','code':None,'provider':'cloudflare','retryable':False}
    if status==429:return {'kind':'rate_limited','code':'429','provider':None,'retryable':False}
    if status in {401,403}:return {'kind':'http_access_rejected','code':str(status),'provider':None,'retryable':False}
    if re.search(r'^(sign in|log in|iniciar sesi.n)$',headings.strip()):return {'kind':'authentication_required','code':None,'provider':None,'retryable':False}
    return None


def annotate_access(page, source):
    from capture_quality import page_quality
    if page_quality(page)['missing_answers'] or page.get('parser') == 'dom':
        detail=classify_access(source)
        if detail:page['access_failure']=detail
    return page

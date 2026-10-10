#!/usr/bin/env python3
"""Bounded PDF parser worker. Input/output are private pipes, never instructions."""
import json, sys, os

def main():
    # A hostile compressed PDF must not exhaust the invoice server.
    try:
        import resource
        baseline=int(open('/proc/self/statm').read().split()[0])*os.sysconf('SC_PAGE_SIZE') if sys.platform=='linux' else 384*1024*1024
        ceiling=baseline+128*1024*1024
        resource.setrlimit(resource.RLIMIT_AS,(ceiling,ceiling))
        resource.setrlimit(resource.RLIMIT_DATA,(128*1024*1024,128*1024*1024))
        resource.setrlimit(resource.RLIMIT_CPU,(8,8))
    except ImportError:
        raise SystemExit('PDF import needs resource limits (Linux or macOS)')
    from io import BytesIO
    from pypdf import PdfReader
    content=sys.stdin.buffer.read(10*1024*1024+1)
    if len(content)>10*1024*1024 or not content.startswith(b'%PDF-'): raise ValueError('Invalid PDF')
    reader=PdfReader(BytesIO(content))
    if reader.is_encrypted or not 1<=len(reader.pages)<=50: raise ValueError('Invalid PDF')
    parts=[];remaining=60000
    for page in reader.pages:
        value=(page.extract_text() or '')[:remaining]
        parts.append(value);remaining-=len(value)+1
        if remaining<=0:break
    print(json.dumps('\n'.join(parts)[:60000]))

if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('PDF could not be read within import limits')

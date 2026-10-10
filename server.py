#!/usr/bin/env python3
import json, secrets, os, base64, hmac, hashlib
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit
import invoices as app

TOKEN=secrets.token_urlsafe(32)
PUBLIC_HOST=os.environ.get('INVOICE_HOST','')
AUTH_PATH=app.DATA/'auth.json'
AUTH=json.loads(AUTH_PATH.read_text()) if PUBLIC_HOST and AUTH_PATH.exists() else None
if PUBLIC_HOST and not AUTH: raise SystemExit('Configure private data/auth.json before exposing a public hostname')
class Handler(BaseHTTPRequestHandler):
    def respond(self,content,status=200,kind='application/json',filename=None):
        if not isinstance(content,bytes): content=json.dumps(content).encode()
        self.send_response(status); self.send_header('Content-Type',kind)
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
        if filename: self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers(); self.wfile.write(content)
    def trusted(self):
        return self.headers.get('Host') in ['127.0.0.1:8767','localhost:8767',PUBLIC_HOST]
    def authorised(self):
        if not PUBLIC_HOST: return True
        try:
            raw=base64.b64decode(self.headers.get('Authorization','').removeprefix('Basic ')).decode()
            user,password=raw.split(':',1)
            hashed=hashlib.scrypt(password.encode(),salt=bytes.fromhex(AUTH['salt']),n=16384,r=8,p=1).hex()
            if hmac.compare_digest(user,AUTH['user']) and hmac.compare_digest(hashed,AUTH['hash']): return True
        except (ValueError,UnicodeError): pass
        self.send_response(401); self.send_header('WWW-Authenticate','Basic realm="Private invoices", charset="UTF-8"')
        self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(b'Private invoice records. Sign in to continue.')
        return False
    def do_GET(self):
        if not self.trusted(): return self.respond({'error':'Invalid host'},403)
        if not self.authorised(): return
        path=urlsplit(self.path).path
        try:
            if path=='/api/state': return self.respond(dict(settings=app.settings(),invoices=app.listing(),token=TOKEN))
            if path in ['/','/app.js','/style.css']:
                name={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[path]
                kind={'/':'text/html; charset=utf-8','/app.js':'text/javascript','/style.css':'text/css'}[path]
                return self.respond((app.ROOT/'static'/name).read_bytes(),kind=kind)
            parts=path.strip('/').split('/')
            if len(parts)==3 and parts[0]=='files':
                identifier,name=parts[1:]; app.get(identifier)
                if name not in ['invoice.pdf','preview.eml','customer.eml','handoff.json']: raise ValueError('File not found')
                manifest=app.export(identifier)
                actual=identifier+'.pdf' if name=='invoice.pdf' else name
                kind='application/pdf' if name.endswith('.pdf') else 'message/rfc822' if name.endswith('.eml') else 'application/json'
                return self.respond((app.DATA/'exports'/identifier/actual).read_bytes(),kind=kind,filename=actual)
            return self.respond({'error':'Not found'},404)
        except (ValueError,KeyError,TypeError) as exc: self.respond({'error':str(exc)},400)
    def do_POST(self):
        if not self.authorised(): return
        if not self.trusted() or self.headers.get('X-Invoice-Token')!=TOKEN: return self.respond({'error':'Refresh this local page'},403)
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<15000000: raise ValueError('Request too large or empty')
            data=json.loads(self.rfile.read(size)); path=urlsplit(self.path).path
            if path=='/api/settings': result=app.save_settings(data)
            elif path=='/api/prepare': result=app.prepare(data)
            elif path=='/api/export': result=app.export(data['id'],sync=data.get('sync_brain',False))
            elif path=='/api/import': result=app.import_pdf(base64.b64decode(data.pop('pdf_base64'),validate=True),data)
            elif path=='/api/review-import': result=app.review_import(data.pop('id'),data)
            elif path=='/api/record': result=app.record(data['id'],data['status'],data['receipt'])
            else: return self.respond({'error':'Not found'},404)
            if path in ['/api/prepare','/api/import','/api/review-import','/api/record'] and app.settings()['vault']:
                try: result['brain_note']=app.export(result['id'],sync=True)['brain_note']
                except (ValueError,OSError) as exc: result['brain_warning']='Saved locally. Second brain needs retry: '+str(exc)
            self.respond(result)
        except (ValueError,KeyError,TypeError) as exc: self.respond({'error':str(exc)},400)
        except Exception as exc:
            self.log_error('%s',exc); self.respond({'error':'Operation failed. Your saved invoice is retained; check the local log.'},500)

if __name__=='__main__':
    print("Tyler's invoices: http://127.0.0.1:8767",flush=True)
    ThreadingHTTPServer(('127.0.0.1',8767),Handler).serve_forever()

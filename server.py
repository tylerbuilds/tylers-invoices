#!/usr/bin/env python3
import json, secrets, os, base64, hmac, hashlib, threading
from http.server import ThreadingHTTPServer as BaseHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit
import invoices as app
from cloudflare_access import owner_authorised

TOKEN=secrets.token_urlsafe(32)
PUBLIC_HOST=os.environ.get('INVOICE_HOST','')
AUTH_PATH=app.DATA/'auth.json'
AUTH=json.loads(AUTH_PATH.read_text()) if PUBLIC_HOST and AUTH_PATH.exists() else None
if PUBLIC_HOST and not AUTH: raise SystemExit('Configure private data/auth.json before exposing a public hostname')
class ThreadingHTTPServer(BaseHTTPServer):
    """Bound threads, expensive authentication and stalled client lifetime."""
    daemon_threads=True
    def __init__(self,*args,**kwargs):
        self.slots=threading.BoundedSemaphore(4)
        super().__init__(*args,**kwargs)
    def get_request(self):
        request,address=super().get_request();request.settimeout(5)
        return request,address
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):
            try:request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            finally:self.shutdown_request(request)
            return
        try:super().process_request(request,address)
        except Exception:
            self.slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()

class Handler(BaseHTTPRequestHandler):
    def respond(self,content,status=200,kind='application/json',filename=None):
        if not isinstance(content,bytes): content=json.dumps(content).encode()
        self.send_response(status); self.send_header('Content-Type',kind)
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
        if filename: self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers(); self.wfile.write(content)
    def trusted(self):
        return self.headers.get('Host') in [f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}',PUBLIC_HOST]
    def authorised(self):
        if not PUBLIC_HOST: return True
        if owner_authorised(self.headers.get('Cf-Access-Jwt-Assertion')): return True
        try:
            header=self.headers.get('Authorization','')
            if not header.startswith('Basic ') or len(header)>2000: raise ValueError('Invalid credentials')
            raw=base64.b64decode(header[6:],validate=True).decode()
            user,password=raw.split(':',1)
            if not hmac.compare_digest(user,AUTH['user']): raise ValueError('Invalid credentials')
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
        except FileNotFoundError: self.respond({'error':'File not found'},404)
        except (ValueError,KeyError,TypeError) as exc: self.respond({'error':str(exc)},400)
    def do_POST(self):
        if not self.trusted(): return self.respond({'error':'Invalid host'},403)
        if not self.authorised(): return
        if not self.trusted() or self.headers.get('X-Invoice-Token')!=TOKEN: return self.respond({'error':'Refresh the page and try again.'},403)
        try:
            if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json': raise ValueError('Send application/json')
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<15000000: raise ValueError('Request too large or empty')
            raw=self.rfile.read(size)
            if len(raw)!=size: raise ValueError('Incomplete request body')
            try:data=app.object_value(json.loads(raw,parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Invalid JSON number'))))
            except RecursionError: raise ValueError('JSON is nested too deeply')
            path=urlsplit(self.path).path
            if path=='/api/settings': result=app.save_settings(data)
            elif path=='/api/prepare': result=app.prepare(data)
            elif path=='/api/export': result=app.export(data['id'],sync=data.get('sync_brain',False))
            elif path=='/api/import': result=app.import_pdf(base64.b64decode(data.pop('pdf_base64'),validate=True),data)
            elif path=='/api/review-import': result=app.review_import(data.pop('id'),data)
            elif path=='/api/record': result=app.record(data['id'],data['status'],data['receipt'])
            else: return self.respond({'error':'Not found'},404)
            if path in ['/api/prepare','/api/import','/api/review-import','/api/record'] and app.settings()['vault']:
                try: result['brain_note']=app.export(result['id'],sync=True)['brain_note']
                except (ValueError,OSError) as exc: result['brain_warning']='Your invoice is saved, but the Obsidian copy failed. '+str(exc)
            self.respond(result)
        except (ValueError,KeyError,TypeError,TimeoutError) as exc: self.respond({'error':str(exc)},400)
        except Exception as exc:
            self.log_error('%s',exc); self.respond({'error':'Something went wrong. Any invoice already saved is still in your invoice list.'},500)

if __name__=='__main__':
    print("Tyler's invoices: http://127.0.0.1:8767",flush=True)
    ThreadingHTTPServer(('127.0.0.1',8767),Handler).serve_forever()

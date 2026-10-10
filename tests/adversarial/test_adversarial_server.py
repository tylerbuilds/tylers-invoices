"""Real isolated HTTP server: no production state, credentials or outbound APIs."""
import base64, hashlib, http.client, json, tempfile, threading, unittest
from pathlib import Path
import invoices as app
import server

class AdversarialHTTP(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=app.DATA;app.DATA=Path(self.tmp.name)
        self.old_host=server.PUBLIC_HOST;self.old_auth=server.AUTH
        server.PUBLIC_HOST='invoices.example.invalid'
        server.AUTH=dict(user='owner',salt='12'*16,hash=hashlib.scrypt(b'fictional-password',salt=bytes.fromhex('12'*16),n=16384,r=8,p=1).hex())
        self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join();server.PUBLIC_HOST=self.old_host;server.AUTH=self.old_auth;app.DATA=self.old;self.tmp.cleanup()
    def request(self,path='/api/state',method='GET',body=None,auth=True,host=True,token=True,kind='application/json'):
        headers={'Host':server.PUBLIC_HOST if host else 'attacker.invalid'}
        if auth:headers['Authorization']='Basic '+base64.b64encode(b'owner:fictional-password').decode()
        if token:headers['X-Invoice-Token']=server.TOKEN
        headers['Content-Type']=kind
        connection=http.client.HTTPConnection(*self.http.server_address,timeout=3)
        connection.request(method,path,body,headers);response=connection.getresponse();content=response.read();connection.close()
        return response.status,content
    def test_auth_host_and_csrf_are_required(self):
        self.assertEqual(self.request(auth=False)[0],401)
        self.assertEqual(self.request(host=False)[0],403)
        self.assertEqual(self.request('/api/settings','POST','{}',token=False)[0],403)
        self.assertEqual(app.settings()['name'],'')
    def test_wrong_content_type_is_rejected(self):
        self.assertEqual(self.request('/api/settings','POST','{}',kind='text/plain')[0],400)
    def test_top_level_json_types_never_crash(self):
        for value in [None,[],True,0,'text']:
            with self.subTest(value=value):self.assertEqual(self.request('/api/prepare','POST',json.dumps(value))[0],400)
    def test_deep_json_is_rejected_and_server_recovers(self):
        self.assertEqual(self.request('/api/settings','POST','['*1500+'0'+']'*1500)[0],400)
        self.assertEqual(self.request()[0],200)
    def test_imported_email_file_returns_not_found(self):
        app.save_settings(dict(name='Example',address='Example',email='sender@example.com',preview_email='owner@example.com',payment_details='Fictional'))
        invoice=app.prepare(dict(customer=dict(name='Client',address='Example',email='client@example.org'),items=[dict(description='Work',quantity='1',rate='10')]))
        imported=app.import_pdf(app.pdf(invoice),{})
        self.assertEqual(self.request('/files/'+imported['id']+'/preview.eml')[0],404)
    def test_corrupt_database_error_is_readable_without_reset(self):
        app.DATA.mkdir(exist_ok=True);path=app.DATA/'invoices.sqlite3';path.write_bytes(b'SQLite format 3\x00broken')
        status,body=self.request();self.assertIn(status,(400,503));self.assertIn(b'error',body);self.assertEqual(path.read_bytes(),b'SQLite format 3\x00broken')

if __name__=='__main__':unittest.main()

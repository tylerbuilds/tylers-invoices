import json, tempfile, unittest
from pathlib import Path
from decimal import Decimal
from email import policy
from email.parser import BytesParser
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pypdf import PdfReader
import invoices as app

class InvoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.old=app.DATA; app.DATA=Path(self.tmp.name)/'data'
        self.vault=Path(self.tmp.name)/'vault'; self.vault.mkdir()
        app.save_settings(dict(name='Example Studio Ltd',address='1 Example Road\nLondon',email='hello@example.com',preview_email='owner@example.com',payment_details='Pay by bank transfer',vault=str(self.vault)))
    def tearDown(self): app.DATA=self.old; self.tmp.cleanup()
    def request(self): return dict(customer=dict(name='Client Ltd',email='accounts@example.org',address='2 Sample Street'),items=[dict(description='Consulting & delivery',quantity='2.5',unit='days',rate='300')],date='2026-10-10',request_key='one')
    def test_totals_pdf_and_attached_drafts(self):
        invoice=app.prepare(self.request()); self.assertEqual(invoice['total'],'750.00')
        export=app.export(invoice['id'],True); pdf=Path(export['pdf']).read_bytes()
        self.assertIn('750.00',PdfReader(BytesIO(pdf)).pages[0].extract_text()); self.assertTrue(Path(export['brain_note']).exists())
        for kind,target in [('preview','owner@example.com'),('customer','accounts@example.org')]:
            msg=BytesParser(policy=policy.default).parsebytes(Path(export[kind+'_email']).read_bytes())
            self.assertEqual(msg['To'],target); self.assertEqual(next(msg.iter_attachments()).get_payload(decode=True),pdf)
        self.assertEqual(app.export(invoice['id'])['pdf_sha256'],export['pdf_sha256'])
    def test_idempotency_and_collision(self):
        first=app.prepare(self.request()); self.assertEqual(app.prepare(self.request())['id'],first['id'])
        request=self.request(); request['items'][0]['rate']='400'
        with self.assertRaises(ValueError): app.prepare(request)
        self.assertEqual(len(app.listing()),1)
    def test_parallel_numbers(self):
        def create(n):
            request=self.request(); request['request_key']=str(n); return app.prepare(request)['id']
        with ThreadPoolExecutor(max_workers=4) as pool: ids=list(pool.map(create,range(12)))
        self.assertEqual(len(set(ids)),12)
    def test_bad_money_headers_and_dates(self):
        for value in ['NaN','Infinity','-1','0','1e1000']:
            request=self.request(); request['items'][0]['quantity']=value
            with self.assertRaises(ValueError): app.prepare(request)
        request=self.request(); request['customer']['email']='x@example.com\nBcc: leak@example.com'
        with self.assertRaises(ValueError): app.prepare(request)
        request=self.request(); request['due']='2025-01-01'
        with self.assertRaises(ValueError): app.prepare(request)
    def test_receipt_state_machine(self):
        invoice=app.prepare(self.request())
        with self.assertRaises(ValueError): app.record(invoice['id'],'paid','receipt')
        with self.assertRaises(ValueError): app.record(invoice['id'],'sent','')
        app.record(invoice['id'],'sent','gmail:message1'); paid=app.record(invoice['id'],'paid','bank:receipt1')
        self.assertIn('gmail:message1',paid['receipt']); self.assertIn('bank:receipt1',paid['receipt'])
    def test_import_dedup_preserves_original(self):
        invoice=app.prepare(self.request()); content=app.pdf(invoice)
        imported=app.import_pdf(content,dict(filename='old.pdf',source='gmail:one'))
        self.assertEqual(imported['status'],'imported_review')
        duplicate=app.import_pdf(content,dict(filename='renamed.pdf',source='gmail:two'))
        self.assertEqual(imported['id'],duplicate['id']); self.assertEqual(len(duplicate['sources']),2)
        export=app.export(imported['id'],True); self.assertEqual(Path(export['pdf']).read_bytes(),content)
        app.review_import(imported['id'],dict(customer='Confirmed client',total='750',date='2026-10-10'))
        self.assertEqual(app.get(imported['id'])['total'],'750.00')
    def test_import_rejects_fake_pdf(self):
        with self.assertRaises(ValueError): app.import_pdf(b'hello',{})
        with self.assertRaises(ValueError): app.import_pdf(b'%PDF-broken',{})
    def test_path_traversal_and_unavailable_vault(self):
        with self.assertRaises(ValueError): app.get('../settings')
        invoice=app.prepare(self.request()); app.save_settings({'vault':'/missing/vault'})
        with self.assertRaises(ValueError): app.export(invoice['id'],True)
        self.assertEqual(app.get(invoice['id'])['total'],'750.00')

if __name__=='__main__': unittest.main()

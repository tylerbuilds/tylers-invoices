"""All eight sweep categories. Each test owns a temporary database and vault."""
import copy, json, sqlite3, tempfile, unittest, zlib
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import invoices as app

class AdversarialInvoices(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=app.DATA;app.DATA=Path(self.tmp.name)/'data'
        self.vault=Path(self.tmp.name)/'vault';self.vault.mkdir()
        app.save_settings(dict(name='Example Ltd',address='1 Example Road',email='sender@example.com',preview_email='owner@example.com',payment_details='Example payment instructions',vault=str(self.vault)))
        self.request=dict(request_key='fixture',customer=dict(name='Customer',email='client@example.org',address='2 Example Road'),items=[dict(description='Work',quantity='2.5',unit='days',rate='300')],date='2026-10-10')
    def tearDown(self):app.DATA=self.old;self.tmp.cleanup()
    def invoice(self):return app.prepare(copy.deepcopy(self.request))
    def imported(self):return app.import_pdf(app.pdf(self.invoice()),dict(customer='Customer',customer_email='client@example.org',total='750',date='2026-10-10',source='gmail:fixture'))
    def test_top_level_type_confusion(self):
        for method in [app.prepare,app.save_settings]:
            for value in [None,[],1,True,'text']:
                with self.subTest(method=method.__name__,value=value),self.assertRaises(ValueError):method(value)
    def test_nested_type_confusion(self):
        for key,value in [('customer',None),('customer',[]),('items',[None]),('items',['work']),('items',{})]:
            request=copy.deepcopy(self.request);request[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):app.prepare(request)
        self.assertEqual(app.listing(),[])
    def test_boolean_and_fractional_settings_are_rejected(self):
        for key in ['next_number','due_days']:
            for value in [True,False,1.5,'1.5',None,[],{}]:
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):app.save_settings({key:value})
        self.assertEqual(app.settings()['next_number'],1)
    def test_whitespace_optional_email_not_falsy_type(self):
        for value in [None,0,False,[],{}]:
            with self.subTest(value=value),self.assertRaises(ValueError):app.email(value,False)
        self.assertEqual(app.email('',False),'')
    def test_numeric_exhaustion_and_precision_bounds(self):
        for value in ['1e-1000000','1.'+'0'*100000+'1','0.0000001',True,[],{}]:
            request=copy.deepcopy(self.request);request['items'][0]['quantity']=value
            with self.subTest(value=str(value)[:30]),self.assertRaises(ValueError):app.prepare(request)
        self.assertEqual(app.listing(),[])
    def test_decimal_line_rounding_boundary(self):
        request=copy.deepcopy(self.request);request['items'][0].update(quantity='0.5',rate='0.01')
        self.assertEqual(app.prepare(request)['total'],'0.01')
    def test_bidi_and_control_characters(self):
        for value in ['name\u202eexe','name\x00','name\u2066hidden','name\x1b[31m']:
            request=copy.deepcopy(self.request);request['customer']['name']=value
            with self.subTest(value=value),self.assertRaises(ValueError):app.prepare(request)
    def test_hundred_thousand_items_rejected_without_writes(self):
        request=copy.deepcopy(self.request);request['items']=[request['items'][0]]*100000
        with self.assertRaises(ValueError):app.prepare(request)
        self.assertEqual(app.listing(),[])
    def test_parallel_duplicate_key_is_one_invoice(self):
        with ThreadPoolExecutor(max_workers=8) as pool:ids=list(pool.map(lambda _:app.prepare(copy.deepcopy(self.request))['id'],range(24)))
        self.assertEqual(len(set(ids)),1);self.assertEqual(len(app.listing()),1)
    def test_partial_settings_update_preserves_parallel_numbers(self):
        self.invoice();app.save_settings({'name':'Updated name'})
        self.assertEqual(app.settings()['next_number'],2)
        with self.assertRaises(ValueError):app.save_settings({'next_number':1})
    def test_sent_and_paid_imports_cannot_be_rewritten(self):
        invoice=self.imported();app.record(invoice['id'],'sent','gmail:actual-sent')
        fields=dict(customer='Attacker',total='1',date='2026-10-10')
        with self.assertRaises(ValueError):app.review_import(invoice['id'],fields)
        app.record(invoice['id'],'paid','bank:actual-payment')
        with self.assertRaises(ValueError):app.review_import(invoice['id'],fields)
        self.assertEqual(app.get(invoice['id'])['total'],'750.00')
    def test_parallel_import_sources_are_not_lost(self):
        content=app.pdf(self.invoice())
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda n:app.import_pdf(content,dict(source='gmail:'+str(n))),range(18)))
        self.assertEqual(len({r['id'] for r in results}),1)
        self.assertEqual(len(app.get(results[0]['id'])['sources']),18)
    def test_import_metadata_type_confusion(self):
        content=app.pdf(self.invoice())
        for value in [None,[],True,'text']:
            with self.subTest(value=value),self.assertRaises(ValueError):app.import_pdf(content,value)
        for key,value in [('filename',None),('customer_email','bad\nBcc: victim@example.org'),('date',True),('total',False)]:
            with self.subTest(key=key),self.assertRaises(ValueError):app.import_pdf(content,{key:value})
    def test_corrupt_settings_fail_closed(self):
        with closing(sqlite3.connect(app.DATA/'invoices.sqlite3')) as db, db:db.execute('UPDATE settings SET payload=?',('[null]',))
        with self.assertRaises(ValueError):app.settings()
        with closing(sqlite3.connect(app.DATA/'invoices.sqlite3')) as db, db:self.assertEqual(db.execute('SELECT payload FROM settings').fetchone()[0],'[null]')
    def test_corrupt_invoice_id_cannot_escape_storage(self):
        invoice=self.invoice()
        with closing(sqlite3.connect(app.DATA/'invoices.sqlite3')) as db, db:
            payload=json.loads(db.execute('SELECT payload FROM invoices').fetchone()[0]);payload['id']='../../outside'
            db.execute('UPDATE invoices SET payload=?',(json.dumps(payload),))
        with self.assertRaises(ValueError):app.export(invoice['id'],True)
        self.assertFalse((Path(self.tmp.name)/'outside').exists())
    def test_truncated_database_is_not_reset(self):
        data=app.DATA/'invoices.sqlite3';data.write_bytes(b'SQLite format 3\x00broken')
        with self.assertRaises(ValueError):app.listing()
        self.assertEqual(data.read_bytes(),b'SQLite format 3\x00broken')
    def test_sql_and_path_injection(self):
        request=copy.deepcopy(self.request);request['customer']['name']="Robert'); DROP TABLE invoices; --"
        invoice=app.prepare(request);self.assertEqual(len(app.listing()),1)
        for identifier in ['../settings','TI-00001/../../secrets','%2e%2e','TI-00001\x00']:
            with self.subTest(identifier=identifier),self.assertRaises(ValueError):app.get(identifier)
        self.assertEqual(app.get(invoice['id'])['customer']['name'],request['customer']['name'])
    def test_pdf_html_and_yaml_injection_is_inert(self):
        request=copy.deepcopy(self.request);request['customer']['name']='![](https://attacker.invalid/pixel)\n---\nstatus: paid\n<script>steal()</script>'
        invoice=app.prepare(request);result=app.export(invoice['id'],True)
        note=Path(result['brain_note']).read_text()
        self.assertNotIn('<script>steal()</script>',note)
        self.assertNotIn('![](https://attacker.invalid/pixel)',note)
        self.assertIn('status: prepared',note)
    def test_foreign_note_and_attachment_are_preserved(self):
        invoice=self.invoice();target=self.vault/'01_Projects'/'tylers-invoices'/'Invoices'/f"{invoice['id']}.md"
        target.parent.mkdir(parents=True);target.write_text('My manual note')
        attachment=self.vault/'Attachments'/'Tylers Invoices'/f"{invoice['id']}.pdf";attachment.parent.mkdir(parents=True);attachment.write_bytes(b'my original file')
        with self.assertRaises(ValueError):app.export(invoice['id'],True)
        self.assertEqual(target.read_text(),'My manual note');self.assertEqual(attachment.read_bytes(),b'my original file')
    def test_symlinked_vault_attachment_cannot_overwrite_other_file(self):
        invoice=self.invoice();outside=Path(self.tmp.name)/'outside';outside.mkdir()
        (self.vault/'Attachments').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):app.export(invoice['id'],True)
        self.assertEqual(list(outside.iterdir()),[])
    def test_interrupted_atomic_write_preserves_previous_file(self):
        path=app.DATA/'original.txt';path.write_bytes(b'original')
        with patch('invoices.os.replace',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):app.atomic(path,b'changed')
        self.assertEqual(path.read_bytes(),b'original')
        self.assertEqual([p.name for p in app.DATA.iterdir() if p.name!='invoices.sqlite3'],['original.txt'])
    def test_exhausted_number_range_is_not_allocated(self):
        app.save_settings({'next_number':999999999});self.invoice()
        request=copy.deepcopy(self.request);request['request_key']='another'
        with self.assertRaises(ValueError):app.prepare(request)
        self.assertEqual(len(app.listing()),1)

    def test_compressed_pdf_cannot_exhaust_server(self):
        """A tiny upload expands beyond the parser's private heap limit."""
        from io import BytesIO
        from pypdf import PdfWriter
        from pypdf.generic import EncodedStreamObject, NameObject
        compressor=zlib.compressobj();pieces=[]
        for _ in range(160):pieces.append(compressor.compress(b' '*1024*1024))
        pieces.append(compressor.flush())
        stream=EncodedStreamObject();stream._data=b''.join(pieces);stream[NameObject('/Filter')]=NameObject('/FlateDecode')
        writer=PdfWriter();page=writer.add_blank_page(width=100,height=100)
        page[NameObject('/Contents')]=writer._add_object(stream)
        output=BytesIO();writer.write(output)
        self.assertLess(len(output.getvalue()),1024*1024)
        with self.assertRaises(ValueError):app.import_pdf(output.getvalue(),{})
        self.assertEqual(app.listing(),[])
        self.assertEqual(self.invoice()['total'],'750.00')
    def test_parallel_status_transitions_keep_one_receipt(self):
        invoice=self.invoice()
        def transition(n):
            try:return app.record(invoice['id'],'sent','fixture:'+str(n))
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(transition,range(16)))
        self.assertEqual(sum(value is not None for value in results),1)
        self.assertEqual(app.get(invoice['id'])['receipt'].count('fixture:'),1)
    def test_parallel_settings_updates_keep_invoice_numbers(self):
        def update(n):
            if n%2:app.save_settings({'name':'Updated Example'})
            else:
                request=copy.deepcopy(self.request);request['request_key']=str(n);app.prepare(request)
        with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(update,range(40)))
        self.assertEqual(len(app.listing()),20);self.assertEqual(app.settings()['next_number'],21)

if __name__=='__main__':unittest.main()

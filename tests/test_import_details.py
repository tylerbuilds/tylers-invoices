from tests import test_invoices as existing_tests
from import_details import extract_details
import invoices as app
import unittest
class ImportDetailTests(unittest.TestCase):
    setUp=existing_tests.InvoiceTests.setUp
    tearDown=existing_tests.InvoiceTests.tearDown
    request=existing_tests.InvoiceTests.request
    def test_real_pdf_extracts_customer_number_total_and_date(self):
        invoice=app.prepare(self.request())
        imported=app.import_pdf(app.pdf(invoice),{'filename':'previous.pdf'})
        self.assertEqual(imported['customer']['name'],'Client Ltd')
        self.assertEqual(imported['customer']['address'],'2 Sample Street')
        self.assertEqual(imported['invoice_number'],invoice['id'])
        self.assertEqual(imported['total'],'750.00')
        self.assertEqual(imported['date'],'2026-10-10')
        self.assertEqual(imported['status'],'imported_review')
    def test_explicit_merge_uses_known_customer_without_changing_original(self):
        invoice=app.prepare(self.request()); content=app.pdf(invoice)
        imported=app.import_pdf(content,{'customer':'Client old name','customer_email':'old@example.org'})
        updated=app.review_import(imported['id'],{'customer':'Client old name','total':'750','date':'2026-10-10','customer_reference':invoice['id'],'invoice_number':'OLD-37'})
        self.assertEqual(updated['customer'],invoice['customer'])
        self.assertEqual(updated['invoice_number'],'OLD-37')
        self.assertEqual((app.DATA/'imports'/f"{imported['id']}.pdf").read_bytes(),content)
        self.assertEqual(app.get(invoice['id'])['customer'],invoice['customer'])
    def test_multiline_zoho_fields(self):
        v=extract_details('Invoice#\n0036\nInvoice Date\n26 September\n2026\nTotal\n£1200.00\nBill To\nSifted Ltd\nLondon\nUnited Kingdom\nItem Name\nWork')
        self.assertEqual(v['invoice_number'],'0036');self.assertEqual(v['date'],'2026-09-26')
        self.assertEqual(v['customer']['name'],'Sifted Ltd');self.assertEqual(v['total'],'1200.00')
    def test_unknown_customer_not_guessed_from_sender(self):
        v=extract_details('MorpheOS LTD\nPayment info\nAccount name: MorpheOS LTD')
        self.assertNotIn('customer',v)

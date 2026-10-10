import json, os, subprocess, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class ContractTests(unittest.TestCase):
    def call(self, request):
        with tempfile.TemporaryDirectory() as data:
            p=subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'openclaw_bridge.py')],input=json.dumps(request),text=True,capture_output=True,env={**os.environ,'TYLER_INVOICES_DATA':data})
            return p.returncode,json.loads(p.stdout)
    def test_doctor_exposes_contract(self):
        code,result=self.call({'action':'doctor'})
        self.assertEqual(code,0)
        self.assertIn('address',result['prepare_contract']['required']['customer'])
    def test_flat_customer_reports_field(self):
        code,result=self.call({'action':'prepare','values':{'customer':'Example'}})
        self.assertEqual(code,1);self.assertEqual(result['field'],'values.customer')
    def test_missing_address_reports_field(self):
        code,result=self.call({'action':'prepare','values':{'customer':{'name':'Example','email':'accounts@example.org'}}})
        self.assertEqual(code,1);self.assertEqual(result['field'],'values.customer.address')
    def test_wrong_rate_key_reports_field(self):
        code,result=self.call({'action':'prepare','values':{'customer':{'name':'Example','email':'accounts@example.org','address':'Example Street'},'items':[{'description':'Work','quantity':4,'unit_price':300}]}})
        self.assertEqual(code,1);self.assertEqual(result['field'],'values.items[0].rate')
if __name__=='__main__':unittest.main()

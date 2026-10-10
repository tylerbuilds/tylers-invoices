#!/usr/bin/env python3
"""Exercise the agent CLI with fictional data in disposable storage. Never sends mail."""
import json, os, subprocess, sys, tempfile
from email import policy
from email.parser import BytesParser
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def main():
    with tempfile.TemporaryDirectory(prefix='invoice-agent-check-') as temporary:
        folder=Path(temporary);vault=folder/'vault';vault.mkdir()
        env=os.environ | {'TYLER_INVOICES_DATA':str(folder/'data')}
        def run(*arguments,value=None):
            command=[sys.executable,str(ROOT/'invoices.py'),*arguments]
            if value is not None:command+=['--json','-']
            result=subprocess.run(command,input=json.dumps(value) if value is not None else None,text=True,capture_output=True,env=env,timeout=30,check=True)
            return json.loads(result.stdout)
        run('settings',value=dict(name='Example Studio Ltd',address='1 Example Road',email='sender@example.com',preview_email='owner@example.com',payment_details='Fictional payment instructions',vault=str(vault)))
        request=dict(request_key='disposable-check',customer=dict(name='Example Customer',email='customer@example.org',address='2 Example Road'),date='2026-10-10',items=[dict(description='Example work',quantity='2.5',unit='days',rate='300')])
        invoice=run('prepare',value=request);identifier=invoice['id']
        assert invoice['total']=='750.00' and run('prepare',value=request)['id']==identifier
        export=run('export',identifier,'--sync-brain');original=Path(export['pdf']).read_bytes()
        for kind,target in [('preview','owner@example.com'),('customer','customer@example.org')]:
            draft=BytesParser(policy=policy.default).parsebytes(Path(export[kind+'_email']).read_bytes())
            assert draft['To']==target and next(draft.iter_attachments()).get_payload(decode=True)==original
        assert Path(export['brain_note']).exists()
        imported=run('import',value=dict(file=export['pdf'],filename='example.pdf',source='fixture:disposable-sent-message'))
        duplicate=run('import',value=dict(file=export['pdf'],source='fixture:second-source'))
        assert imported['id']==duplicate['id'] and len(duplicate['sources'])==2
        run('review-import',imported['id'],value=dict(customer='Example Customer',customer_email='customer@example.org',total='750.00',date='2026-10-10',currency='GBP'))
        run('record',imported['id'],'sent','--receipt','fixture:disposable-sent-message')
        run('record',imported['id'],'paid','--receipt','fixture:disposable-payment')
        imported_export=run('export',imported['id'],'--sync-brain')
        assert Path(imported_export['pdf']).read_bytes()==original
        assert run('show',imported['id'])['status']=='paid' and len(run('list'))==2
        readiness=run('doctor');assert readiness['ready_to_prepare']
        print(json.dumps(dict(ok=True,checks=['CLI settings and readiness','decimal totals','idempotent preparation','PDF attachment bytes','preview and customer recipients','Obsidian export','original PDF preservation','import deduplication and source references','import review','receipt status transitions','list and show'],live_data_touched=False,emails_sent=0),indent=2))

if __name__=='__main__':main()

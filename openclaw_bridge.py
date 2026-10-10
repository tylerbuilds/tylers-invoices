#!/usr/bin/env python3
"""Fixed invoice operations for the optional OpenClaw tool; no shell or mail."""
import base64, json, sys
import invoices as app


def dispatch(request):
    app.object_value(request);action=request.get('action');values=request.get('values',{})
    app.object_value(values)
    if action=='smoke':
        import subprocess
        result=subprocess.run([sys.executable,str(app.ROOT/'agent_smoke.py')],capture_output=True,text=True,timeout=45,check=True)
        return json.loads(result.stdout)
    if action=='doctor':return app.doctor() | {'prepare_contract': {
        'envelope': {'action':'prepare','values':'invoice object'},
        'required': {'customer': {'name':'non-empty string','email':'valid email address','address':'non-empty string'},
                     'items':[{'description':'non-empty string','quantity':'positive number or numeric string','rate':'non-negative number or numeric string','unit':'days (default)'}]},
        'optional': {'request_key':'stable retry key','date':'YYYY-MM-DD','due':'YYYY-MM-DD','notes':'string'},
        'next_step': {'action':'export','values':{'id':'returned invoice ID','sync_brain':True}},
        'customer_lookup':'Use list then show on a previous invoice. Confirm billing details from its original extracted_text if the imported customer address is empty. Never invent missing details.'}}
    if action=='settings':
        app.save_settings(values)
        return dict(updated=True,readiness=app.doctor())
    if action=='list':return [{key:value.get(key) for key in ('id','customer','currency','total','date','due','status','receipt')} for value in app.listing()]
    if action=='show':return app.get(values.get('id'))
    if action=='prepare':
        customer=values.get('customer')
        if not isinstance(customer,dict):return {'error':'values.customer must be an object with name, email and address','field':'values.customer'}
        for key in ('name','email','address'):
            if not isinstance(customer.get(key),str) or not customer[key].strip():
                return {'error':f'values.customer.{key} is required and must be a non-empty string','field':f'values.customer.{key}'}
        if not isinstance(values.get('items'),list) or not 1<=len(values['items'])<=100:
            return {'error':'values.items must contain 1 to 100 line item objects','field':'values.items'}
        for i,row in enumerate(values['items']):
            if not isinstance(row,dict):return {'error':'Each line item must be an object','field':f'values.items[{i}]'}
            for key in ('description','quantity','rate'):
                if key not in row:return {'error':f'Line item requires {key}','field':f'values.items[{i}].{key}'}
        try:return app.prepare(values)
        except ValueError as exc:
            # prepare validation messages contain labels, never payment values.
            message=str(exc)
            if message.startswith(('Invalid','Enter a valid','Add your','Add between','Rates support','Dates must','The due date','Request key','Invoice number','Customer','Description','Unit','Notes','Expected')):
                return {'error':message,'action':'prepare','help':'Run doctor for prepare_contract; preserve request_key when retrying.'}
            raise
    if action=='export':
        sync=values.get('sync_brain',False)
        if not isinstance(sync,bool):raise ValueError('sync_brain must be a boolean')
        return app.export(values.get('id'),sync)
    if action=='import':
        values=values.copy();encoded=values.pop('pdf_base64',None)
        if not isinstance(encoded,str) or len(encoded)>14*1024*1024:raise ValueError('Supply PDF bytes as pdf_base64, up to 10 MB decoded')
        return app.import_pdf(base64.b64decode(encoded,validate=True),values)
    if action=='review-import':return app.review_import(values.pop('id',None),values)
    if action=='record':return app.record(values.get('id'),values.get('status'),values.get('receipt'))
    raise ValueError('Unknown invoice action')


def main():
    try:
        raw=sys.stdin.buffer.read(15*1024*1024+1)
        if len(raw)>15*1024*1024:raise ValueError('Request too large')
        result=dispatch(json.loads(raw))
        print(json.dumps(result))
        if isinstance(result,dict) and "error" in result:return 1
    except (ValueError,TypeError,KeyError,OSError,RecursionError):
        print(json.dumps({'error':'Invoice operation failed. Check required fields, state and storage; use doctor for readiness.'}))
        return 1
    return 0

if __name__=='__main__':raise SystemExit(main())

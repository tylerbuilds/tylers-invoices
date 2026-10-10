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
    if action=='doctor':return app.doctor()
    if action=='settings':
        app.save_settings(values)
        return dict(updated=True,readiness=app.doctor())
    if action=='list':return [{key:value.get(key) for key in ('id','customer','currency','total','date','due','status','receipt')} for value in app.listing()]
    if action=='show':return app.get(values.get('id'))
    if action=='prepare':return app.prepare(values)
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
    except (ValueError,TypeError,KeyError,OSError,RecursionError):
        print(json.dumps({'error':'Invoice operation failed. Check required fields, state and storage; use doctor for readiness.'}))
        return 1
    return 0

if __name__=='__main__':raise SystemExit(main())

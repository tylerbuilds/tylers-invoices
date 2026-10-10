#!/usr/bin/env python3
"""Local invoice preparation. No credentials, network sends or approval authority."""
from contextlib import contextmanager
import argparse, datetime as dt, hashlib, json, os, re, secrets, sqlite3, tempfile, unicodedata, subprocess, sys, threading
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('TYLER_INVOICES_DATA', ROOT / 'data'))
PDF_LOCK=threading.BoundedSemaphore(1)
DEFAULTS = dict(name='', address='', email='', preview_email='', payment_details='', currency='GBP', due_days=30,
                vault='', prefix='TI', next_number=1)

@contextmanager
def database():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(DATA / 'invoices.sqlite3', timeout=30)
    os.chmod(DATA / 'invoices.sqlite3',0o600)
    db.row_factory = sqlite3.Row
    try:
        db.execute('CREATE TABLE IF NOT EXISTS invoices (id TEXT PRIMARY KEY, request_key TEXT UNIQUE, payload TEXT NOT NULL, status TEXT NOT NULL, receipt TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
        db.commit()
        with db: yield db
    except sqlite3.DatabaseError as exc:
        raise ValueError('Invoice storage cannot be read. Restore a verified backup; do not reset it.') from exc
    finally: db.close()

def object_value(value):
    if not isinstance(value,dict): raise ValueError('Expected a JSON object')
    return value

def stored_settings(row):
    try: return DEFAULTS | object_value(json.loads(row[0]) if row else {})
    except (ValueError, TypeError) as exc: raise ValueError('Invalid stored settings') from exc


def settings():
    with database() as db:
        row = db.execute('SELECT payload FROM settings WHERE id=1').fetchone()
    return stored_settings(row)

def email(value, required=True):
    if value == '' and isinstance(value,str) and not required: return ''
    if not isinstance(value,str) or len(value)>320 or not re.fullmatch(r'[^\s@<>;,]+@[^\s@<>;,]+\.[^\s@<>;,]+', value):
        raise ValueError('Enter a valid email address')
    text(value,'Email address',False,320)
    return value

def text(value, label, required=True, limit=3000):
    if not isinstance(value,str) or len(value)>limit or any((unicodedata.category(c) in ('Cc','Cf')) and c not in '\n\t' for c in value):
        raise ValueError(f'Invalid {label}')
    if required and not value.strip(): raise ValueError(f'{label} is required')
    return value.strip()

def save_settings(values):
    object_value(values)
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        current=stored_settings(db.execute('SELECT payload FROM settings WHERE id=1').fetchone())
        conf=current | {k:v for k,v in values.items() if k in DEFAULTS}
        for key in ['name','address','payment_details','vault']: conf[key] = text(conf[key],key,False)
        for key in ['email','preview_email']: conf[key] = email(conf[key],False)
        if conf['currency'] not in ['GBP','EUR','USD']: raise ValueError('Currency must be GBP, EUR or USD')
        if not isinstance(conf['prefix'],str) or not re.fullmatch('[A-Z][A-Z0-9-]{0,15}',conf['prefix']): raise ValueError('Invalid invoice prefix')
        for key in ['next_number','due_days']:
            if isinstance(conf[key],bool) or not isinstance(conf[key],(int,str)) or not re.fullmatch('[0-9]{1,9}',str(conf[key])): raise ValueError('Invalid number or payment terms')
            conf[key]=int(conf[key])
        if not 1 <= conf['next_number'] <= 999999999 or not 0 <= conf['due_days'] <= 365: raise ValueError('Invalid number or payment terms')
        if conf['prefix']==current['prefix'] and conf['next_number']<current['next_number']: raise ValueError('Invoice numbers cannot go backwards')
        db.execute('INSERT OR REPLACE INTO settings VALUES (1,?)',(json.dumps(conf),))
    return conf

def decimal(value, label, allow_zero=False):
    if isinstance(value,bool) or not isinstance(value,(str,int,float,Decimal)) or len(str(value))>40: raise ValueError(f'Invalid {label}')
    try: result = Decimal(str(value))
    except (InvalidOperation,ValueError): raise ValueError(f'Invalid {label}')
    if not result.is_finite() or result < 0 or (result == 0 and not allow_zero) or result > Decimal('100000000'):
        raise ValueError(f'Invalid {label}')
    if result.as_tuple().exponent < -6: raise ValueError(f'Invalid {label}: at most six decimal places')
    return result

def money(value): return str(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))

def prepare(request):
    object_value(request)
    conf=settings()
    for key in ['name','address','email','payment_details','preview_email']:
        if not conf[key]:
            label = {'name': 'name or company', 'address': 'address', 'email': 'work email', 'payment_details': 'bank or payment details', 'preview_email': 'preview email'}[key]
            raise ValueError(f'Add your {label} in Settings first.')
    customer=object_value(request.get('customer',{}))
    customer={'name':text(customer.get('name',''),'Customer name'), 'email':email(customer.get('email','')),
              'address':text(customer.get('address',''),'Customer address')}
    rows=request.get('items',[])
    if not isinstance(rows,list) or not 1 <= len(rows) <= 100: raise ValueError('Add between 1 and 100 line items')
    items=[]
    for row in rows:
        object_value(row)
        qty=decimal(row.get('quantity',''),'quantity'); rate=decimal(row.get('rate',''),'rate',True)
        if rate != rate.quantize(Decimal('.01')): raise ValueError('Rates support at most two decimal places')
        items.append(dict(description=text(row.get('description',''),'Description'), quantity=str(qty),
                          unit=text(row.get('unit','days'),'Unit',True,40), rate=money(rate), amount=money(qty*rate)))
    for key in ('date','due'):
        if key in request and not isinstance(request[key],str): raise ValueError('Dates must be ISO date strings')
    try:
        date=dt.date.fromisoformat(text(request.get('date') or dt.date.today().isoformat(),'Invoice date',limit=10))
        due=dt.date.fromisoformat(text(request.get('due') or (date+dt.timedelta(days=conf['due_days'])).isoformat(),'Due date',limit=10))
    except (TypeError,OverflowError) as exc: raise ValueError('Invalid invoice or due date') from exc
    if due<date: raise ValueError('The due date must be on or after the invoice date.')
    invoice=dict(customer=customer,items=items,date=str(date),due=str(due),currency=conf['currency'],
                 notes=text(request.get('notes',''),'Notes',False),sender={k:conf[k] for k in ['name','address','email','payment_details','preview_email']},
                 total=money(sum(Decimal(i['amount']) for i in items)),created_at=dt.datetime.now(dt.timezone.utc).isoformat())
    key=text(request.get('request_key',''),'Request key',False,200) or secrets.token_hex(16)
    # Hash the caller's payload, excluding the retry key, so retries cannot silently change the invoice.
    fingerprint=hashlib.sha256(json.dumps({k:v for k,v in request.items() if k!='request_key'},sort_keys=True).encode()).hexdigest()
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        existing=db.execute('SELECT payload FROM invoices WHERE request_key=?',(key,)).fetchone()
        if existing:
            old=json.loads(existing[0])
            if old['fingerprint']!=fingerprint: raise ValueError('Request key already belongs to a different invoice')
            return old
        row=db.execute('SELECT payload FROM settings WHERE id=1').fetchone()
        live=stored_settings(row)
        number=live['next_number']
        while db.execute('SELECT 1 FROM invoices WHERE id=?',(f"{live['prefix']}-{number:05d}",)).fetchone(): number+=1
        if number>999999999: raise ValueError('Invoice number range exhausted; choose a new prefix')
        invoice.update(id=f"{live['prefix']}-{number:05d}",request_key=key,fingerprint=fingerprint)
        live['next_number']=number+1
        db.execute('INSERT OR REPLACE INTO settings VALUES(1,?)',(json.dumps(live),))
        db.execute('INSERT INTO invoices VALUES(?,?,?,\'prepared\',NULL)',(invoice['id'],key,json.dumps(invoice)))
    return invoice

def stored_invoice(row):
    try:
        value=object_value(json.loads(row['payload']))
        if value.get('id')!=row['id'] or row['status'] not in ('prepared','imported_review','sent','paid','void'): raise ValueError('Invalid stored invoice')
        for key in ('date','due'):
            if value.get(key): dt.date.fromisoformat(text(value[key],key,limit=10))
        if value.get('currency') not in ('GBP','EUR','USD'): raise ValueError('Invalid stored currency')
        if not isinstance(value.get('total'),str) or (value['total'] and not re.fullmatch(r'[0-9]{1,20}\.[0-9]{2}',value['total'])): raise ValueError('Invalid stored total')
        object_value(value.get('customer'));object_value(value.get('sender'))
        if not isinstance(value.get('items'),list): raise ValueError('Invalid stored line items')
        return value | dict(status=row['status'],receipt=row['receipt'])
    except (ValueError,TypeError) as exc: raise ValueError('Invalid stored invoice') from exc


def get(identifier):
    if not isinstance(identifier,str) or not re.fullmatch(r'(?:[A-Z][A-Z0-9-]{0,30}-[0-9]{5,10}|IMP-[a-f0-9]{24})',identifier): raise ValueError('Invalid invoice ID')
    with database() as db: row=db.execute('SELECT * FROM invoices WHERE id=?',(identifier,)).fetchone()
    if not row: raise ValueError('Invoice not found')
    return stored_invoice(row)

def listing():
    with database() as db:
        return [stored_invoice(r) for r in db.execute('SELECT * FROM invoices ORDER BY rowid DESC')]

def atomic(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out: out.write(data)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def pdf(invoice):
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
    from reportlab.lib.pagesizes import A4
    buf=BytesIO(); styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name='SmallInvoice',fontName='Helvetica',fontSize=10,leading=15,textColor=colors.HexColor('#273747')))
    p=lambda s: Paragraph(escape(str(s)).replace('\n','<br/>'),styles['SmallInvoice'])
    story=[Paragraph('INVOICE',styles['Title']),Spacer(1,18),p(invoice['sender']['name']),p(invoice['sender']['address']),p(invoice['sender']['email']),Spacer(1,22)]
    story += [Table([[p('BILL TO\n'+invoice['customer']['name']+'\n'+invoice['customer']['address']),p(f"{invoice['id']}\nIssued: {invoice['date']}\nDue: {invoice['due']}")]],colWidths=[315,180]),Spacer(1,24)]
    rows=[[p('Work'),p('Quantity'),p('Rate'),p('Amount')]]
    for i in invoice['items']: rows.append([p(i['description']),p(i['quantity']+' '+i['unit']),p(i['rate']),p(i['amount'])])
    table=Table(rows,colWidths=[260,85,75,75],repeatRows=1,hAlign='LEFT',splitInRow=1)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef2f6')),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10),('LINEBELOW',(0,0),(-1,-1),.4,colors.HexColor('#dce2e9'))]))
    story += [table,Spacer(1,18),Paragraph(f"Total due: {invoice['currency']} {invoice['total']}",styles['Heading2']),Spacer(1,20),p('Payment details'),p(invoice['sender']['payment_details'])]
    if invoice['notes']: story += [Spacer(1,20),p(invoice['notes'])]
    def footer(canvas,doc):
        canvas.setFont('Helvetica',8); canvas.drawString(50,28,invoice['id']); canvas.drawRightString(545,28,f'Page {doc.page}')
    SimpleDocTemplate(buf,pagesize=A4,rightMargin=50,leftMargin=50,topMargin=45,bottomMargin=50,title=invoice['id'],author=invoice['sender']['name'],invariant=1).build(story,onFirstPage=footer,onLaterPages=footer)
    return buf.getvalue()

def export(identifier, sync=False):
    invoice=get(identifier); folder=DATA/'exports'/identifier
    if invoice.get('imported'):
        content=(DATA/'imports'/f'{identifier}.pdf').read_bytes()
        atomic(folder/f'{identifier}.pdf',content)
        manifest=dict(invoice_id=identifier,status=invoice['status'],pdf=str(folder/f'{identifier}.pdf'),pdf_sha256=hashlib.sha256(content).hexdigest())
        if sync: manifest['brain_note']=sync_brain(invoice,folder)
        return manifest
    content=pdf(invoice); atomic(folder/f'{identifier}.pdf',content)
    body=f"Hello {invoice['customer']['name']},\n\nPlease find attached invoice {identifier} for {invoice['currency']} {invoice['total']}, due {invoice['due']}.\n\nThank you,\n{invoice['sender']['name']}\n"
    artifacts={}
    for kind,to in [('customer',invoice['customer']['email']),('preview',invoice['sender']['preview_email'])]:
        msg=EmailMessage(policy=SMTP); msg['From']=invoice['sender']['email']; msg['To']=to
        msg['Subject']=('PREVIEW - ' if kind=='preview' else '')+f"Invoice {identifier} - {invoice['currency']} {invoice['total']}"
        msg['X-Unsent']='1'
        msg.set_content((f"Review only. Intended customer: {invoice['customer']['email']}\n\n" if kind=='preview' else '')+body)
        msg.add_attachment(content,maintype='application',subtype='pdf',filename=f'{identifier}.pdf')
        msg.set_boundary('invoice-'+identifier+'-'+kind)
        path=folder/f'{kind}.eml'; atomic(path,msg.as_bytes()); artifacts[kind+'_email']=str(path)
    manifest=dict(invoice_id=identifier,status=invoice['status'],pdf=str(folder/f'{identifier}.pdf'),pdf_sha256=hashlib.sha256(content).hexdigest(),
                  preview_to=invoice['sender']['preview_email'],customer_to=invoice['customer']['email'],requires_current_customer_send_approval=True,**artifacts)
    atomic(folder/'handoff.json',json.dumps(manifest,indent=2).encode())
    atomic(folder/'invoice.json',json.dumps(invoice,indent=2).encode())
    if sync: manifest['brain_note']=sync_brain(invoice,folder)
    return manifest

def sync_brain(invoice,folder):
    import subprocess
    processes=subprocess.run(['ps','-axo','pid,args'],capture_output=True,text=True,check=True).stdout
    busy=re.compile(r'(?:[p]ython\S* .*my_agent_os\.(?:qmd_refresh|state_contracts|chief_of_staff)|/[a]gent-os-qmd |/[i]nfra-qmd-refresh )')
    if busy.search(processes): raise ValueError('Obsidian is busy. Try saving to Obsidian again later.')
    vault=Path(settings()['vault']).expanduser()
    if not settings()['vault'] or not vault.is_dir(): raise ValueError('Cannot open your Obsidian folder. Check the path in Settings.')
    # Ordinary notes only; never mutate Command Centre state or qmd databases.
    target=vault/'01_Projects'/'tylers-invoices'/'Invoices'
    attachment=vault/'Attachments'/'Tylers Invoices'/f"{invoice['id']}.pdf"
    path=target/f"{invoice['id']}.md"
    marker='<!-- Generated by Tylers Invoices; keep manual notes separately. -->\n'
    for destination in (attachment,path):
        current=destination
        while current!=vault:
            if current.is_symlink(): raise ValueError('Obsidian export paths must not contain symlinks')
            current=current.parent
    if path.exists() and marker not in path.read_text(): raise ValueError('An existing Obsidian note has the same filename. Rename that note before trying again.')
    if attachment.exists() and not path.exists(): raise ValueError('An existing attachment has the same filename')
    content=(folder/f"{invoice['id']}.pdf").read_bytes()
    if attachment.exists() and attachment.read_bytes()!=content: raise ValueError('Existing Obsidian attachment differs; preserve it and check the conflict')
    atomic(attachment,content)
    safe=lambda value: re.sub(r'([\\`*_{}\[\]()<>#!|])',r'\\\1',str(value)).replace('\n',' ')
    note=f"---\ntype: invoice\ninvoice_id: {invoice['id']}\nstatus: {invoice['status']}\ndate: {invoice['date']}\ndue: {invoice['due']}\ncurrency: {invoice['currency']}\namount: {invoice['total']}\n---\n\n# {invoice['id']}\n\nCustomer: {safe(invoice['customer']['name'])} ({safe(invoice['customer']['email'])})\n\n"
    for i in invoice['items']: note+=f"- {safe(i['description'])}: {i['quantity']} {safe(i['unit'])} at {invoice['currency']} {i['rate']} = {i['amount']}\n"
    note+=f"\nTotal: {invoice['currency']} {invoice['total']}\n\n[[Attachments/Tylers Invoices/{invoice['id']}.pdf|Invoice PDF]]\n\nPrepared locally; sending needs a current approval and a delivery receipt.\n"
    if invoice.get('imported'):
        note+='\nOriginal file: '+safe(invoice['original_filename'])+'\n\nSources:\n'+'\n'.join('- '+safe(src) for src in invoice.get('sources',[invoice['source']]))+'\n\n## Extracted invoice text (source data)\n\n'+'\n'.join('    '+line for line in invoice['extracted_text'].splitlines())+'\n'
    if invoice.get('receipt'): note+=f"\nReceipt: {safe(invoice['receipt'])}\n"
    atomic(path,(marker+note).encode()); return str(path)

def record(identifier,status,receipt):
    invoice=get(identifier)
    transitions={'imported_review':{'sent','void'},'prepared':{'sent','void'},'sent':{'paid','void'},'paid':set(),'void':set()}
    if status not in transitions[invoice['status']]: raise ValueError('This invoice cannot be changed to that status.')
    if invoice.get('imported') and status=='sent' and (not invoice['total'] or not invoice['date'] or invoice['customer']['name']=='Unconfirmed customer'):
        raise ValueError('Add the customer, amount and date before marking this invoice as sent.')
    receipt=text(receipt,'Email link, payment reference or reason')
    with database() as db:
        cur=db.execute('UPDATE invoices SET status=?,receipt=? WHERE id=? AND status=?',(status,(invoice.get('receipt')+'\n' if invoice.get('receipt') else '')+receipt,identifier,invoice['status']))
        if cur.rowcount!=1: raise ValueError('This invoice has changed. Refresh the page and try again.')
    return get(identifier)

def import_pdf(content, metadata):
    object_value(metadata)
    text(metadata.get('filename','invoice.pdf'),'Filename')
    email(metadata.get('customer_email',''),False)
    text(metadata.get('date',''),'Date',False)
    if 'total' in metadata and metadata['total'] != '': decimal(metadata['total'],'total',True)
    if not isinstance(content,bytes) or len(content)>10*1024*1024 or not content.startswith(b'%PDF-'): raise ValueError('Choose a PDF under 10 MB')
    try:
        with PDF_LOCK:
            parsed=subprocess.run([sys.executable,str(ROOT/'pdf_extract.py')],input=content,capture_output=True,timeout=12,check=True)
        extracted=json.loads(parsed.stdout)
    except (subprocess.SubprocessError,ValueError,OSError) as exc: raise ValueError('Unable to read PDF within import limits (10 MB, 50 pages, 12 seconds, 128 MB)') from exc
    digest=hashlib.sha256(content).hexdigest(); identifier='IMP-'+digest[:24]
    source=text(metadata.get('source','Manual PDF upload'),'Source',True)
    customer=text(metadata.get('customer','Unconfirmed customer'),'Customer',True)
    total=metadata.get('total','')
    total=money(decimal(total,'total',True)) if total else ''
    currency=metadata.get('currency',settings()['currency'])
    if currency not in ['GBP','EUR','USD']: raise ValueError('Unsupported currency')
    date=metadata.get('date','')
    if date: dt.date.fromisoformat(date)
    invoice=dict(id=identifier,imported=True,customer={'name':customer,'email':metadata.get('customer_email',''),'address':''},
                 currency=currency,total=total,date=date,due='',items=[],sender=settings(),notes='',created_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                 original_filename=Path(metadata.get('filename','invoice.pdf')).name,extracted_text=extracted,source=source,sha256=digest)
    atomic(DATA/'imports'/f'{identifier}.pdf',content)
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT payload FROM invoices WHERE id=?',(identifier,)).fetchone()
        if row:
            old=json.loads(row[0]); sources=old.get('sources',[old['source']])
            if source not in sources: sources.append(source)
            old['sources']=sources
            db.execute('UPDATE invoices SET payload=? WHERE id=?',(json.dumps(old),identifier))
        else:
            db.execute('INSERT INTO invoices VALUES(?,?,?,\'imported_review\',NULL)',(identifier,digest,json.dumps(invoice)))
    return get(identifier)

def review_import(identifier, values):
    object_value(values)
    invoice=get(identifier)
    if invoice['status']!='imported_review': raise ValueError('Sent, paid and cancelled invoices cannot be edited')
    if not invoice.get('imported'): raise ValueError('Only imports can be edited here')
    invoice['customer']['name']=text(values.get('customer',''),'Customer name')
    invoice['customer']['email']=email(values.get('customer_email',''),False)
    invoice['total']=money(decimal(values.get('total',''),'total',True))
    invoice['date']=str(dt.date.fromisoformat(values['date']))
    invoice['currency']=values.get('currency','GBP')
    if invoice['currency'] not in ['GBP','EUR','USD']: raise ValueError('Unsupported currency')
    for key in ['status','receipt']: invoice.pop(key,None)
    with database() as db:
        cur=db.execute("UPDATE invoices SET payload=? WHERE id=? AND status='imported_review'",(json.dumps(invoice),identifier))
        if cur.rowcount!=1: raise ValueError('Invoice changed; reload it')
    return get(identifier)

def doctor():
    conf=settings()
    missing=[k for k in ('name','address','email','payment_details','preview_email') if not conf[k]]
    return dict(ready_to_prepare=not missing,missing_settings=missing,data_directory=str(DATA.resolve()),
                invoice_count=len(listing()),vault_configured=bool(conf['vault']),
                vault_available=bool(conf['vault']) and Path(conf['vault']).expanduser().is_dir(),
                mail_transport='external',can_send_mail=False)

def main():
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest='command',required=True)
    for command in ['prepare','settings','import']:
        p=sub.add_parser(command); p.add_argument('--json',required=True,help='JSON file, or - for stdin')
    sub.add_parser('list'); sub.add_parser('doctor')
    p=sub.add_parser('review-import');p.add_argument('id');p.add_argument('--json',required=True)
    for command in ['show','export']:
        p=sub.add_parser(command); p.add_argument('id')
        if command=='export': p.add_argument('--sync-brain',action='store_true')
    p=sub.add_parser('record'); p.add_argument('id'); p.add_argument('status',choices=['sent','paid','void']); p.add_argument('--receipt',required=True)
    args=parser.parse_args()
    try:
        if args.command in ['prepare','settings','import','review-import']:
            import sys
            value=json.load(sys.stdin if args.json=='-' else open(args.json))
            object_value(value)
            result=review_import(args.id,value) if args.command=='review-import' else prepare(value) if args.command=='prepare' else import_pdf(Path(value.pop('file')).read_bytes(),value) if args.command=='import' else save_settings(value)
        elif args.command=='doctor': result=doctor()
        elif args.command=='list': result=listing()
        elif args.command=='show': result=get(args.id)
        elif args.command=='export': result=export(args.id,args.sync_brain)
        else: result=record(args.id,args.status,args.receipt)
        print(json.dumps(result,indent=2))
    except (ValueError,KeyError,TypeError,OSError,RecursionError) as exc: parser.exit(1,json.dumps({'error':str(exc)})+'\n')

if __name__=='__main__': main()

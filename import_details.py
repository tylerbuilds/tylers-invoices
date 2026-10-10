"""Conservative extraction of labelled invoice fields; source text is data."""
import re, datetime as dt

def extract_details(content, filename=''):
    lines=[x.strip() for x in content.splitlines() if x.strip()]
    result={}; customer={}
    number=re.search(r'(?:Invoice\s*(?:number|no\.?|#)|INVOICE)\s*[:#]?\s*\n?\s*([A-Z]*[- ]?\d[\w-]{0,39})',content,re.I)
    if not number:number=re.search(r'\b((?:INV|TI)[- ]\d{2,12})\b',content,re.I)
    if number:result['invoice_number']=number.group(1).strip()
    elif (m:=re.search(r'\b(INV[- ]\d{2,12})\b',filename,re.I)):result['invoice_number']=m.group(1)
    for label,key in [('Invoice Date','date'),('Issued','date'),('Due Date','due'),('Due','due')]:
        m=re.search(r'(?im)^'+label+r'\s*:?\s*(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})',content)
        if m:
            value=' '.join(m.group(1).split())
            for fmt in ('%Y-%m-%d','%d/%m/%Y','%d %B %Y','%d %b %Y'):
                try:result[key]=dt.datetime.strptime(value,fmt).date().isoformat();break
                except ValueError:pass
    m=re.search(r'(?im)^Total\s*(?:Due)?\s*:?\s*(?:(GBP|EUR|USD)\s*)?([£€$])?\s*([\d,]+\.\d{2})\s*$',content)
    if m:
        result['total']=m.group(3).replace(',','');result['currency']=m.group(1) or {'£':'GBP','€':'EUR','$':'USD'}.get(m.group(2),'GBP')
    start=next((i+1 for i,l in enumerate(lines) if re.fullmatch(r'Bill\s*To\s*:?',l,re.I)),None)
    if start is not None:
        block=[]
        for l in lines[start:start+12]:
            if re.match(r'(?i)^(?:item\b|description\b|work\b|quantity\b|invoice\b|issued\b|due\b|[A-Z]+-\d|company\s+no\b|#(?:\s|$))',l):break
            block.append(l)
        if block:
            customer['name']=block[0]
            addresses=[]
            for l in block[1:]:
                if re.fullmatch(r'[^\s@<>;,]+@[^\s@<>;,]+\.[^\s@<>;,]+',l):customer['email']=l
                else:addresses.append(l)
            customer['address']='\n'.join(addresses)
    # Zoho layouts sometimes omit Bill To but place the customer after Balance Due.
    if not customer:
        for i,l in enumerate(lines[:-2]):
            if l.lower()=='balance due' and re.fullmatch(r'[£€$]?[\d,.]+',lines[i+1]) and not re.match(r'(?i)^(#|description|payment|total)',lines[i+2]):
                customer['name']=lines[i+2];break
    if customer:result['customer']=customer
    return result

let state, requestKey = crypto.randomUUID();
const $ = s => document.querySelector(s);
const notice = s => { $('#notice').textContent = s; };
const statusName = s => ({prepared: 'Draft', imported_review: 'Check details', sent: 'Sent', paid: 'Paid', void: 'Cancelled'}[s] || s);
const actionName = s => ({sent: 'Mark as sent', paid: 'Mark as paid', void: 'Cancel invoice'}[s]);
const withWarning = (message, result) => message + (result.brain_warning ? ' ' + result.brain_warning : '');

async function api(path, data) {
  const res = await fetch('/api/' + path, {
    method: data ? 'POST' : 'GET',
    headers: data ? {'Content-Type': 'application/json', 'X-Invoice-Token': state.token} : {},
    body: data ? JSON.stringify(data) : undefined
  });
  const result = await res.json();
  if (!res.ok) throw Error(result.error);
  return result;
}
function tab(name) {
  document.querySelectorAll('main>section').forEach(s => s.hidden = s.id !== name);
  document.querySelectorAll('nav button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
}
document.querySelectorAll('nav button').forEach(b => b.onclick = () => tab(b.dataset.tab));
function node(tag, text) {
  const el = document.createElement(tag);
  el.textContent = text;
  return el;
}
function addItem() {
  const el = document.createElement('div');
  el.className = 'item';
  el.innerHTML = '<label>Description<input class="description" required placeholder="Consulting, 1-5 October"></label><label>Quantity<input class="quantity" type="number" min="0.001" step="any" value="1" required></label><label>Unit<input class="unit" value="days" required></label><label>Rate<input class="rate" type="number" min="0" step="0.01" placeholder="500" required></label><button type="button" aria-label="Remove line">×</button>';
  el.querySelector('button').onclick = () => { el.remove(); total(); };
  el.oninput = () => { requestKey = crypto.randomUUID(); total(); };
  $('#items').append(el);
}
$('#add-item').onclick = addItem;
function total() {
  let sum = 0;
  document.querySelectorAll('.item').forEach(el => {
    sum += Math.round((Number(el.querySelector('.quantity').value) * Number(el.querySelector('.rate').value) + Number.EPSILON) * 100) / 100;
  });
  $('#total').textContent = (state?.settings.currency || 'GBP') + ' ' + sum.toFixed(2);
}
function download(i, file, label) {
  const a = node('a', label);
  a.href = '/files/' + i.id + '/' + file;
  a.download = file;
  return a;
}
function saveToBrain(i) {
  const button = node('button', 'Save to Obsidian');
  button.type = 'button';
  button.className = 'secondary';
  button.onclick = async () => {
    try { await api('export', {id: i.id, sync_brain: true}); notice('Saved to Obsidian.'); }
    catch (e) { notice(e.message); }
  };
  return button;
}
function statusControls(i, el, render) {
  const current = i.status || 'prepared';
  const statuses = current === 'prepared' || current === 'imported_review' ? ['sent', 'void'] : current === 'sent' ? ['paid', 'void'] : [];
  if (!statuses.length) return;
  const details = document.createElement('details');
  details.className = 'receipt';
  details.append(node('summary', 'Update status'));
  const label = node('label', 'Email link, payment reference or reason for cancellation');
  const input = document.createElement('input');
  input.placeholder = 'Add a reference';
  label.append(input);
  details.append(label);
  statuses.forEach(status => {
    const button = node('button', actionName(status));
    button.type = 'button';
    button.onclick = async () => {
      try {
        if (i.imported && status === 'sent' && (!i.total || !i.date)) throw Error('Add the amount and invoice date first.');
        const updated = await api('record', {id: i.id, status, receipt: input.value});
        el.replaceWith(render(updated));
        await refresh();
        notice(withWarning('Invoice marked as ' + statusName(status).toLowerCase() + '.', updated));
      } catch (e) { notice(e.message); }
    };
    details.append(button);
  });
  el.append(details);
}
function recordHeader(i) {
  const head = node('div', '');
  head.className = 'record-head';
  head.append(node('h3', i.imported ? i.customer.name : i.id + ' · ' + i.customer.name));
  const badge = node('span', statusName(i.status || 'prepared'));
  badge.className = 'badge';
  head.append(badge);
  return head;
}
function card(i) {
  if (i.imported) return importedCard(i);
  const el = node('div', '');
  el.className = 'card';
  el.append(recordHeader(i), node('p', i.currency + ' ' + i.total + ' · Due ' + i.due));
  const links = node('div', '');
  links.className = 'links';
  links.append(download(i, 'invoice.pdf', 'Download PDF'), download(i, 'preview.eml', 'Download preview email'), download(i, 'customer.eml', 'Download customer email'));
  el.append(links);
  const help = document.createElement('details');
  help.append(node('summary', 'How to send it'), node('p', 'Open the email file in your mail app. The PDF is attached. Check the invoice, then send it.'));
  el.append(help);
  statusControls(i, el, card);
  const extra = document.createElement('details');
  extra.append(node('summary', 'Obsidian and Zeus'), saveToBrain(i), node('p', 'Zeus needs your permission before emailing a customer.'), download(i, 'handoff.json', 'Download invoice data'));
  el.append(extra);
  return el;
}
async function refresh() {
  state = await api('state');
  for (const [k, v] of Object.entries(state.settings)) {
    const field = $('#settings-form').elements.namedItem(k);
    if (field) field.value = v;
  }
  const records = $('#invoice-list');
  records.replaceChildren();
  if (!state.invoices.length) records.append(node('p', 'No invoices yet.'));
  state.invoices.forEach(i => records.append(card(i)));
  total();
}
$('#settings-form').onsubmit = async e => {
  e.preventDefault();
  try {
    await api('settings', Object.fromEntries(new FormData(e.target)));
    await refresh();
    notice('Settings saved.');
  } catch (e) { notice(e.message); }
};
$('#invoice-form').oninput = () => requestKey = crypto.randomUUID();
$('#invoice-form').onsubmit = async e => {
  e.preventDefault();
  const button = e.target.querySelector('[type=submit]');
  button.disabled = true;
  try {
    const f = Object.fromEntries(new FormData(e.target));
    const items = [...document.querySelectorAll('.item')].map(el => Object.fromEntries(['description', 'quantity', 'unit', 'rate'].map(k => [k, el.querySelector('.' + k).value])));
    const i = await api('prepare', {request_key: requestKey, customer: {name: f.customer_name, email: f.customer_email, address: f.customer_address}, items, date: f.date, due: f.due, notes: f.notes});
    await api('export', {id: i.id});
    $('#prepared').replaceChildren(node('h2', 'Invoice created'), card(i));
    await refresh();
    notice(withWarning('Invoice saved.', i));
  } catch (e) { notice(e.message); }
  finally { button.disabled = false; }
};
const date = new Date();
$('#invoice-form').elements.date.value = date.toISOString().slice(0, 10);
date.setDate(date.getDate() + 30);
$('#invoice-form').elements.due.value = date.toISOString().slice(0, 10);
addItem();
refresh().then(() => {
  if (!state.settings.name) { notice('Add your details to get started.'); tab('settings'); }
}).catch(e => notice(e.message));

function importedCard(i) {
  const el = node('div', '');
  el.className = 'card';
  el.append(recordHeader(i), node('p', (i.total ? i.currency + ' ' + i.total : 'Add amount') + (i.date ? ' · ' + i.date : ' · Add date')));
  el.append(download(i, 'invoice.pdf', 'Download PDF'));
  const edit = document.createElement('details');
  edit.open = i.status === 'imported_review';
  edit.append(node('summary', i.status === 'imported_review' ? 'Check invoice details' : 'Edit details'));
  const form = document.createElement('form');
  form.className = 'grid';
  for (const [k, label, val, type] of [['customer', 'Customer', i.customer.name, 'text'], ['customer_email', 'Email', i.customer.email, 'email'], ['total', 'Total', i.total, 'number'], ['date', 'Invoice date', i.date, 'date'], ['currency', 'Currency', i.currency, 'text']]) {
    const l = node('label', label), input = document.createElement('input');
    input.name = k;
    input.value = val;
    input.type = type;
    if (k === 'total') { input.step = '0.01'; input.min = '0'; }
    input.required = k !== 'customer_email';
    l.append(input);
    form.append(l);
  }
  form.append(node('button', 'Save details'));
  form.onsubmit = async e => {
    e.preventDefault();
    try {
      const updated = await api('review-import', {id: i.id, ...Object.fromEntries(new FormData(form))});
      el.replaceWith(importedCard(updated));
      await refresh();
      notice(withWarning('Details saved.', updated));
    } catch (e) { notice(e.message); }
  };
  edit.append(form);
  el.append(edit);
  statusControls(i, el, importedCard);
  const source = document.createElement('details');
  source.append(node('summary', 'Original file and email'));
  source.append(node('p', i.original_filename), node('p', (i.sources || [i.source]).join('\n')));
  const text = document.createElement('details');
  text.append(node('summary', 'Text from the PDF'), node('pre', i.extracted_text || 'This PDF has no readable text. Open it to check the details.'));
  source.append(text);
  el.append(source);
  const brain = document.createElement('details');
  brain.append(node('summary', 'Obsidian'), saveToBrain(i));
  el.append(brain);
  return el;
}
async function importFiles(files) {
  for (const file of files) {
    try {
      if (file.size > 10 * 1024 * 1024) throw Error('Choose a PDF under 10 MB.');
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = '';
      for (let j = 0; j < bytes.length; j += 32768) binary += String.fromCharCode(...bytes.subarray(j, j + 32768));
      const result = await api('import', {filename: file.name, source: 'Manual PDF upload', pdf_base64: btoa(binary)});
      $('#import-results').append(importedCard(result));
      notice(withWarning('Saved ' + file.name + '.', result));
    } catch (e) { notice(e.message); }
  }
  await refresh();
}
$('#import-files').onchange = e => importFiles(e.target.files);
const drop = $('#dropzone');
drop.ondragover = e => { e.preventDefault(); drop.classList.add('drag'); };
drop.ondragleave = () => drop.classList.remove('drag');
drop.ondrop = e => { e.preventDefault(); drop.classList.remove('drag'); importFiles(e.dataTransfer.files); };

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, existsSync, mkdirSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { createInvoiceTool, invoiceEnvironment } from './runtime.mjs';

function toolFor(config, agentId = 'owner') {
  return createInvoiceTool(config, {agentId, sessionKey: `agent:${agentId}:invoice-test`});
}
const configFor = folder => ({projectPath: resolve('.'), dataDirectory: folder, allowedAgentIds: ['owner']});

test('agent scope is enforced and paths must be absolute', () => {
  const config = configFor('/tmp/fictional-invoice-data');
  assert.equal(toolFor(config, 'unapproved'), null);
  assert.throws(() => toolFor({...config, projectPath: '.'}), /absolute/);
  assert.throws(() => toolFor({...config, allowedAgentIds: []}), /agent/);
});

test('unknown actions and type confusion never launch a process', async () => {
  const tool = toolFor(configFor('/nonexistent-invoice-test-data'));
  for (const params of [null, {action: 'send'}, {action: 'doctor', values: []}, {action: 'doctor', values: null}]) {
    assert.equal((await tool.execute('fixture', params)).isError, true);
  }
});

test('real bridge readiness and smoke use isolated data', async () => {
  const folder = mkdtempSync(join(tmpdir(), 'invoice-plugin-test-'));
  try {
    const tool = toolFor(configFor(folder));
    const readiness = await tool.execute('fixture', {action: 'doctor'});
    assert.equal(readiness.isError, false);
    assert.equal(readiness.details.ready_to_prepare, false);
    assert.equal(readiness.details.invoice_count, 0);
    const smoke = await tool.execute('fixture', {action: 'smoke'});
    assert.equal(smoke.isError, false);
    assert.equal(smoke.details.ok, true);
    assert.equal(smoke.details.live_data_touched, false);
    assert.equal(smoke.details.emails_sent, 0);
    assert.equal((await tool.execute('fixture', {action: 'doctor'})).details.invoice_count, 0);
  } finally {rmSync(folder, {recursive: true, force: true});}
});

test('payload shell metacharacters remain data', async () => {
  const folder = mkdtempSync(join(tmpdir(), 'invoice-plugin-test-'));
  try {
    const marker = join(folder, 'injection-ran');
    const tool = toolFor(configFor(folder));
    const response = await tool.execute('fixture', {action: 'settings', values: {name: `$(touch ${marker})`}});
    assert.equal(response.isError, false);
    assert.equal(existsSync(marker), false);
    assert.equal((await tool.execute('fixture', {action: 'doctor'})).details.invoice_count, 0);
  } finally {rmSync(folder, {recursive: true, force: true});}
});

test('parallel operations return busy rather than unbounded subprocesses', async () => {
  const folder = mkdtempSync(join(tmpdir(), 'invoice-plugin-test-'));
  try {
    const tool = toolFor(configFor(folder));
    const first = tool.execute('fixture', {action: 'smoke'});
    const second = await tool.execute('fixture', {action: 'doctor'});
    assert.equal(second.isError, true);
    assert.match(second.details.error, /busy/);
    assert.equal((await first).details.ok, true);
  } finally {rmSync(folder, {recursive: true, force: true});}
});

test('gateway secrets and Python injection variables are not inherited', () => {
  const env = invoiceEnvironment({PATH: '/usr/bin', HOME: '/home/example', OPENAI_API_KEY: 'fictional-private-key', PYTHONPATH: '/attacker', NODE_OPTIONS: '--inspect', TYLER_INVOICES_DATA: '/wrong'}, '/canonical');
  assert.equal(env.OPENAI_API_KEY, undefined);
  assert.equal(env.PYTHONPATH, undefined);
  assert.equal(env.NODE_OPTIONS, undefined);
  assert.equal(env.TYLER_INVOICES_DATA, '/canonical');
  assert.equal(env.HOME, '/home/example');
});

test('every invoice action works through the real scoped bridge', async () => {
  const folder = mkdtempSync(join(tmpdir(), 'invoice-plugin-workflow-'));
  try {
    const vault = join(folder, 'vault'); mkdirSync(vault);
    const tool = toolFor(configFor(join(folder, 'data')));
    const call = async (action, values = {}) => {
      const response = await tool.execute('fixture', {action, values});
      assert.equal(response.isError, false, JSON.stringify(response.details));
      return response.details;
    };
    await call('settings', {name: 'Example', address: '1 Example Road', email: 'sender@example.com', preview_email: 'owner@example.com', payment_details: 'Fictional payment instructions', vault});
    const request = {request_key: 'bridge-fixture', customer: {name: 'Example Client', email: 'client@example.org', address: '2 Example Road'}, items: [{description: 'Example work', quantity: '3', rate: '500'}], date: '2026-10-10'};
    const invoice = await call('prepare', request);
    assert.equal(invoice.total, '1500.00');
    assert.equal((await call('prepare', request)).id, invoice.id);
    const exported = await call('export', {id: invoice.id, sync_brain: true});
    const pdf = readFileSync(exported.pdf);
    assert.equal(existsSync(exported.brain_note), true);
    const imported = await call('import', {pdf_base64: pdf.toString('base64'), filename: 'example.pdf', source: 'fixture:sent-message'});
    await call('review-import', {id: imported.id, customer: 'Example Client', customer_email: 'client@example.org', total: '1500', date: '2026-10-10', currency: 'GBP'});
    await call('record', {id: imported.id, status: 'sent', receipt: 'fixture:disposable-sent-message'});
    await call('record', {id: imported.id, status: 'paid', receipt: 'fixture:disposable-payment'});
    assert.equal((await call('show', {id: imported.id})).status, 'paid');
    const original = await call('export', {id: imported.id, sync_brain: true});
    assert.deepEqual(readFileSync(original.pdf), pdf);
    assert.equal((await call('list')).length, 2);
    assert.equal((await call('doctor')).ready_to_prepare, true);
  } finally {rmSync(folder, {recursive: true, force: true});}
});

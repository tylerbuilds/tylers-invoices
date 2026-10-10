import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, existsSync } from 'node:fs';
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

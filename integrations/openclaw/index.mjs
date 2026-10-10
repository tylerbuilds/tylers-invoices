import { defineToolPlugin } from 'openclaw/plugin-sdk/tool-plugin';
import { readFileSync } from 'node:fs';
import { createInvoiceTool } from './runtime.mjs';

const manifest = JSON.parse(readFileSync(new URL('./openclaw.plugin.json', import.meta.url), 'utf8'));
export default defineToolPlugin({
  id: manifest.id,
  name: manifest.name,
  description: manifest.description,
  configSchema: manifest.configSchema,
  tools: tool => [tool({
    name: 'tylers_invoices',
    description: 'Scoped invoice PDFs, drafts, imports and Obsidian. Use doctor then smoke to check readiness; no mail is sent.',
    parameters: {
      type: 'object', additionalProperties: false, required: ['action'],
      properties: {
        action: {type: 'string', enum: ['doctor', 'smoke', 'settings', 'list', 'show', 'prepare', 'export', 'import', 'review-import', 'record']},
        values: {type: 'object', additionalProperties: true},
      },
    },
    factory: ({config, toolContext}) => createInvoiceTool(config, toolContext),
  })],
});

# Test scope

Run the retained checks with:

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python agent_smoke.py
node --test integrations/openclaw/index.test.mjs
```

The tests use temporary databases and vaults, fictional addresses and fake authentication. HTTP tests start a real server on an ephemeral loopback port. They do not contact email providers, change production records or write to a real Obsidian vault.

## Adversarial sweep

The Agent OS `adversarial-sweep` workflow was used: write reproductions, run them, fix the failures and retain the tests. The original eight invoice tests also remain.

| Category | Checks |
| --- | --- |
| Malformed input | Invalid JSON, wrong content type, oversized lists, control and bidirectional characters |
| Races | Repeated request keys, concurrent numbering/settings updates, simultaneous import sources and status changes |
| Boundaries | Half-cent rounding, quantity precision, payment terms, exhausted invoice numbers |
| Resource exhaustion | 100,000 items, extreme decimal exponents, deeply nested JSON, compressed PDF expansion |
| Corrupt state | Invalid stored JSON, mismatched stored IDs, truncated SQLite files, interrupted atomic writes |
| Type confusion | Booleans, fractions, nulls, lists and scalars in object/string/integer fields |
| Injection | SQL, email headers, paths, PDF markup, Markdown images and YAML-like content |
| Invalid assumptions | Editing sent/paid imports, foreign vault files, symlinked folders, unavailable email files |

The sweep found and fixed malformed-input crashes, lost import source references, unsafe edits to sent imports, invoice-number resets/exhaustion, unbounded decimal inputs, active Markdown in generated notes, foreign attachment overwrites and symlinked vault exports. HTTP fixes reject wrong content types and nested JSON, return a readable error for unavailable files, and bound client concurrency/timeouts. PDF extraction now runs in a limited child process rather than the web server.

`agent_smoke.py` exercises the actual JSON CLI. It verifies decimal totals, idempotency, original PDF bytes, attachment bytes and recipients, Obsidian files, import review/deduplication, receipts, list/show and readiness. Its sent/payment references are explicitly fictional and exist only in disposable storage. It never sends a message.

Passing tests establish these behaviours on the tested runtime. They don't independently verify email delivery, a user's reverse proxy, physical-device access, backups or every possible hostile PDF. Agents must test their own execution route and report missing settings or email tools separately.

The optional OpenClaw plugin tests run real bridge processes with temporary storage. They check agent scoping, absolute path configuration, rejected actions/types, disposable workflow execution, shell metacharacters remaining data and bounded concurrency. The gateway connection is a separate live check; a plugin test alone doesn't prove gateway access.

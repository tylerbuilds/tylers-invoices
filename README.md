# Tyler's invoices

Make PDF invoices, prepare emails with the PDF attached, and keep a record of what you've sent. Use the web app or ask your agent to do it.

Python, SQLite and plain HTML. Two dependencies. No Node, subscriptions or background jobs. Run it on your computer, or on a small server and open it in your browser. Each person runs their own private copy. MIT licensed.

A bundled OpenClaw tool supports the same workflow through a scoped integration, including installations that block general shell execution.

**Using OpenClaw, Zeus, Codex or another agent?** [Copy this setup prompt into your agent](docs/agent-setup.md#paste-this-into-your-agent). It covers installation, private settings, testing, email and Obsidian.

## Get started

Requires Python 3.11+ on Linux or macOS, Git and Python's `venv` module.

```sh
git clone https://github.com/tylerbuilds/tylers-invoices.git
cd tylers-invoices
./start
```

Open **http://127.0.0.1:8767**. In **Settings**, add your business details, payment instructions, work email and preview email. Add your Obsidian folder if you want copies there. Leave it blank to keep records only in the app.

For an agent or a service manager, install without starting the web server:

```sh
./start --setup-only
.venv/bin/python agent_smoke.py
```

The smoke check uses a temporary database and fictional invoices. It checks PDFs, attached email drafts, imports, receipts and Obsidian export, then removes its temporary files. It never sends mail or consumes your real invoice numbers.

## Make and send an invoice

1. Enter the customer, work, days or hours, and rates. Click **Create invoice**.
2. Download the PDF or **Download preview email**. The `.eml` draft contains the PDF and is addressed to your preview email.
3. Check the invoice. Send the customer draft through your mail app, or ask your agent to use its existing mail connection.
4. Mark it sent with the actual message link or ID. Mark it paid when you have payment evidence.

The app creates drafts; your email app or agent sends them. An agent must get your approval before emailing a customer. A saved draft or a recorded status does not independently prove delivery.

Invoices keep the sender details and rates from when they were created. Cancel an incorrect invoice and create a replacement. Sent, paid and cancelled imports cannot be edited.

## Import old invoices

Drop PDFs into **Import**, then check the customer, amount and invoice date. Originals are kept byte-for-byte. Uploading the same PDF again keeps one record and adds its source reference.

Agents can search your sent mail through their existing authorised email tools and import the attachments. They must check the parent message, recipient and sent date. A supplier bill, self-preview or draft isn't a sent customer invoice. See [the agent instructions](AGENTS.md#historical-email-import).

PDFs must be unencrypted, under 10 MB and at most 50 pages. Extraction runs in a separate process with a time limit and a 128 MB heap limit. There is no OCR or automatic field guessing. Different revisions remain separate records.

## Agent commands

Run these on the machine holding your invoice database. JSON inputs can come from a private file or stdin with `--json -`.

```sh
.venv/bin/python invoices.py doctor
.venv/bin/python invoices.py settings --json /private/settings.json
.venv/bin/python invoices.py prepare --json /private/request.json
.venv/bin/python invoices.py export TI-00001 --sync-brain
.venv/bin/python invoices.py list
.venv/bin/python invoices.py show TI-00001
.venv/bin/python invoices.py import --json /private/import.json
.venv/bin/python invoices.py review-import IMP-0123456789abcdef01234567 --json /private/review.json
.venv/bin/python invoices.py record TI-00001 sent --receipt 'mail:actual-sent-message-id'
.venv/bin/python invoices.py record TI-00001 paid --receipt 'bank:actual-payment-reference'
```

`doctor` reports missing settings without printing their values. `settings` updates only supplied fields. `prepare` assigns a number and freezes the invoice details. `export` writes the PDF, preview/customer drafts and `handoff.json`; `--sync-brain` also writes the Obsidian copy. Imports export their original PDF, without email drafts. `review-import` corrects an import while it's in review. `record` accepts `sent`, `paid` or `void` and requires a receipt or reason.

Use a stable `request_key` for retries. The same request returns the same invoice; changing its content while reusing the key is rejected. Number allocation and duplicate imports use SQLite transactions.

A fictional request:

```json
{
  "request_key": "example-project-october-v1",
  "customer": {
    "name": "Example Client Ltd",
    "email": "accounts@example.org",
    "address": "2 Example Street"
  },
  "date": "2026-10-10",
  "items": [
    {"description": "Consulting, 5–7 October", "quantity": "3", "unit": "days", "rate": "500.00"}
  ],
  "notes": "Project reference EX-1"
}
```

See [AGENTS.md](AGENTS.md) for sending and import rules, and [the setup guide](docs/agent-setup.md) for settings and HTTP examples.

## Storage and Obsidian

Private settings, the database, imported PDFs and email drafts live in ignored `data/`. Set `TYLER_INVOICES_DATA` to use another directory. **Never commit that directory or your private input files.** The public repository contains only source and fictional examples.

Back up the whole data directory and your vault. Stop the service while copying the database, or use SQLite's online backup API; copying a database during a write can produce an incomplete backup.

Web changes save to Obsidian when a vault is configured. The CLI requires `export --sync-brain`. Generated notes go under `01_Projects/tylers-invoices/Invoices`, with PDFs under `Attachments/Tylers Invoices`. Keep manual notes separately. Conflicting files and symlinked export paths are rejected. Busy or unavailable vaults leave the invoice saved locally; retry the export later. The app doesn't change Command Centre state, schedulers or search indexes.

| Setting | Default / purpose |
| --- | --- |
| `name`, `address`, `email` | Required sender details; initially blank |
| `preview_email`, `payment_details` | Required for new invoices; initially blank |
| `currency` | `GBP`; also `EUR` or `USD` |
| `due_days` | `30`; allowed 0–365 |
| `prefix`, `next_number` | `TI`, `1`; numbers cannot go backwards within the current prefix |
| `vault` | Blank; absolute path to an existing Obsidian folder |

Quantities support six decimal places; rates support two. Each line is rounded to two decimal places with decimal arithmetic. There are no VAT calculations, credit notes, exchange-rate conversions, recurring invoices or multi-user accounts.

## Private web hosting

Use one always-on host and one live database. The browser doesn't hold your records. Run the app behind HTTPS using a reverse proxy or Cloudflare Tunnel; it binds only `127.0.0.1:8767`.

1. Choose a private data directory and set `TYLER_INVOICES_DATA`.
2. Run `.venv/bin/python configure_auth.py` to set a strong password locally. Keep it in your password manager.
3. Set `INVOICE_HOST` to your hostname, without `https://` or a path. Configure the proxy to preserve that Host header.
4. Adapt [the user-service template](deploy/tylers-invoices.service) to your installation. Install only the invoice service; reuse your existing proxy and mail connection.
5. Check that unauthenticated requests receive `401` before exposing the route.

Public-host mode requires authentication on every request and refuses to start without `auth.json`. Local mode trusts loopback users; don't expose it by proxy without setting `INVOICE_HOST`. HTTPS and access controls remain the operator's responsibility. Requests have bounded concurrency and timeouts; this is a small single-owner service.

## Checks

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python agent_smoke.py
# Optional OpenClaw plugin checks (requires Node, already used by OpenClaw):
node --test integrations/openclaw/index.test.mjs
```

The retained adversarial tests cover malformed inputs, concurrent updates, number limits, resource exhaustion, corrupt storage, type confusion, injection and incorrect state assumptions. They use temporary files, databases and vaults. See [the test notes](docs/testing.md) for the scope and limits.

## If something goes wrong

| Problem | What to do |
| --- | --- |
| Missing sender or payment details | Run `invoices.py doctor`, then fill those fields in Settings. |
| Missing `venv` or `ensurepip` | Install your system's Python venv package, then run `./start` again. |
| Address already in use | Check for an existing instance or service. Use it rather than starting another copy. |
| Changed dependencies after an update | Run `.venv/bin/python -m pip install -r requirements.txt`. |
| Obsidian export failed | Check the vault path and file conflict; retry `export ID --sync-brain`. |
| PDF import rejected | Check size, page count and encryption. Inspect it separately if extraction exceeds the limits. |
| Public route gives `403` | Check that the proxy preserves `INVOICE_HOST`. |
| Storage cannot be read | Stop writes and restore a verified backup. Don't delete or reset the database. |

<details>
<summary>About contributions</summary>

*About Contributions:* Please don't take this the wrong way, but I do not accept outside contributions for any of my projects. I simply don't have the mental bandwidth to review anything, and it's my name on the thing, so I'm responsible for any problems it causes; thus, the risk-reward is highly asymmetric from my perspective. I'd also have to worry about other "stakeholders," which seems unwise for tools I mostly make for myself for free. Feel free to submit issues, and even PRs if you want to illustrate a proposed fix, but know I won't merge them directly. Instead, I'll have Claude or Codex review submissions via `gh` and independently decide whether and how to address them. Bug reports in particular are welcome. Sorry if this offends, but I want to avoid wasted time and hurt feelings. I understand this isn't in sync with the prevailing open-source ethos that seeks community contributions, but it's the only way I can move at this velocity and keep my sanity.

</details>

[MIT licence](LICENSE).

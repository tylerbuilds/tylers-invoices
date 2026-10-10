# Tyler's invoices

A small, private invoice workspace for humans and agents. Python, SQLite and plain HTML/JavaScript. No Node runtime, framework, background jobs, analytics or email credentials. MIT licensed.

Create PDFs from days/hours and rates, download email drafts with the PDF already attached, and keep a searchable Obsidian record. Import historical PDFs by drag-and-drop or through the JSON interface. Keep original documents, extracted text, customer details, delivery evidence and payment receipts together.

## Start

Requires Python 3.11+. Run `./start`, then open http://127.0.0.1:8767. First run creates a virtual environment and installs the two pinned Python dependencies. Add your sender, payment and preview-email details in Settings. Enter a vault path to enable Obsidian export. The app is single-owner; other people can run their own copy.

Everything private lives in ignored `data/`: settings, SQLite database, PDFs, imported files and email drafts. Back up that directory together with your vault. `TYLER_INVOICES_DATA` can point to another private directory. Never commit runtime data, screenshots containing real details, or credentials.

## Workflow

1. Enter the customer, work, quantities and rates. Prepare an invoice.
2. Download the PDF or the preview email draft. Open `.eml` in a compatible email application; the PDF is attached and the preview is addressed to you.
3. Review the recipient, dates, lines, total and payment details. Send the customer draft manually, or ask your agent to use its existing approved mail connection.
4. Record the actual sent-message receipt, then the payment receipt when paid.
5. Save to second brain. The app writes only its generated notes under `01_Projects/tylers-invoices/Invoices` and PDFs under `Attachments/Tylers Invoices`. Manual notes belong in separate notes. It does not change scheduler ownership, Command Centre state or qmd indexes.

Nothing sends mail automatically. Email sending is performed by your mail application or existing agent transport, under its current approval rules. This app has no power to approve sends. A recorded receipt is operator/agent-supplied evidence, not independent delivery verification.

New invoices are immutable snapshots. Void an incorrect invoice and prepare a replacement; do not overwrite a sent invoice. Money is calculated using decimal arithmetic with each line rounded to two decimal places. GBP, EUR and USD are supported. This first version has no VAT calculation, credit notes or foreign-exchange conversion.

## Import

Drop unencrypted PDF invoices (up to 10 MB / 50 pages) into Import invoices. Originals are preserved byte-for-byte and deduplicated by SHA-256. Extracted text assists review; this version does not perform OCR or guess tax/amount/customer fields. Confirm those fields yourself or let your agent read the PDF.

Imports start as `imported_review`. A PDF alone does not prove delivery. Only record `sent` after reviewing customer/amount/date and supplying a real sent-message reference. Supplier bills and self-previews are not customer invoices. Revised PDFs remain separate records even if their printed invoice number matches.

## Agent interface

See [AGENTS.md](AGENTS.md) for preparation, email search/import and approval instructions. CLI output is JSON:

```sh
.venv/bin/python invoices.py settings --json /private/settings.json
.venv/bin/python invoices.py prepare --json /private/request.json
.venv/bin/python invoices.py export TI-00001 --sync-brain
.venv/bin/python invoices.py list
.venv/bin/python invoices.py import --json /private/import.json
.venv/bin/python invoices.py record TI-00001 sent --receipt 'gmail:actual-message-id'
```

A stable `request_key` makes retries idempotent. Reusing a key for a changed request is rejected. Invoice numbers are allocated in a SQLite transaction.

The same operations are available at `/api/settings`, `/api/prepare`, `/api/export`, `/api/import`, `/api/review-import`, `/api/record` and `/api/state`. JSON POST requests require the `X-Invoice-Token` from authenticated `/api/state`. `/files/{id}/invoice.pdf` downloads the original or generated PDF; new invoices additionally support `preview.eml`, `customer.eml` and `handoff.json`.

## Private web hosting

Run on an always-on host behind an HTTPS reverse proxy or Cloudflare Tunnel; no app process runs on your laptop. The server binds only `127.0.0.1:8767`. Set `INVOICE_HOST` to your public hostname and create private `data/auth.json` using `configure_auth.py`; the server refuses public-host mode without an auth configuration. Every request requires HTTP Basic authentication in public-host mode. Use HTTPS only. Your proxy must preserve the configured Host header. Other users configure their own hostname and credentials.

`deploy/tylers-invoices.service` is a user-service template. It introduces only the invoice web service, with no jobs or schedulers. Authenticate before exposing the route. Keep auth and settings outside the public source repository. SQLite/PDFs stay on your host; browser storage is not the source of truth.

## Checks

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests cover decimal totals, PDF content, email recipients and attachments, idempotent retries, concurrent numbering, invalid inputs, state transitions, original-file preservation, deduplication and unavailable vault recovery.

#!/usr/bin/env python3
"""Create a private login. Reads an optional password from stdin, never argv."""
import getpass, hashlib, json, secrets, sys
import invoices as app
password=sys.stdin.readline().rstrip('\n') if not sys.stdin.isatty() else getpass.getpass('Private web password (at least 16 characters): ')
if len(password)<16: raise SystemExit('Use at least 16 characters')
salt=secrets.token_bytes(16)
app.atomic(app.DATA/'auth.json',json.dumps({'user':'owner','salt':salt.hex(),'hash':hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1).hex()}).encode())
print('Private login configured for user owner.')

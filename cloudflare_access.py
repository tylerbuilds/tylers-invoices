"""Optional owner SSO. An email header or unsigned JWT never grants access."""
import os
import re
import time
import jwt

FIELDS = ('CF_ACCESS_ISSUER', 'CF_ACCESS_AUDIENCE', 'CF_ACCESS_ALLOWED_EMAIL', 'CF_ACCESS_ALLOWED_SUBJECT')
CONFIG = {name: os.environ.get(name, '') for name in FIELDS}
if any(CONFIG.values()) and not all(CONFIG.values()):
    raise RuntimeError('Complete Cloudflare Access configuration is required')
CLIENT = None
if all(CONFIG.values()):
    if not re.fullmatch(r'https://[a-z0-9-]+\.cloudflareaccess\.com', CONFIG['CF_ACCESS_ISSUER']):
        raise RuntimeError('Invalid Cloudflare Access issuer')
    CLIENT = jwt.PyJWKClient(CONFIG['CF_ACCESS_ISSUER'] + '/cdn-cgi/access/certs',
                            lifespan=600, timeout=5, cooldown_duration=30)


def owner_authorised(token):
    if CLIENT is None or not isinstance(token, str) or not 0 < len(token) <= 16384:
        return False
    try:
        header = jwt.get_unverified_header(token)
        if header.get('alg') != 'RS256' or header.get('crit'):
            return False
        key = CLIENT.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=['RS256'],
                            issuer=CONFIG['CF_ACCESS_ISSUER'], audience=CONFIG['CF_ACCESS_AUDIENCE'],
                            options={'require': ['exp', 'iat', 'sub', 'email']})
        return (claims['email'] == CONFIG['CF_ACCESS_ALLOWED_EMAIL'] and
                claims['sub'] == CONFIG['CF_ACCESS_ALLOWED_SUBJECT'] and
                type(claims['iat']) in (int, float) and type(claims['exp']) in (int, float) and
                0 < claims['exp'] - claims['iat'] <= 86400 and
                claims['iat'] <= time.time() < claims['exp'])
    except Exception:
        # Never log tokens, provider headers or credentials.
        return False

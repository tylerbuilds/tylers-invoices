import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
import cloudflare_access as access


class OwnerAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        now = int(time.time())
        self.claims = dict(iss='https://fixture.cloudflareaccess.com', aud=['fixture-audience'],
                           email='owner@example.org', sub='fixture-owner', iat=now-22*3600, exp=now+2*3600)
        config=dict(CF_ACCESS_ISSUER=self.claims['iss'], CF_ACCESS_AUDIENCE='fixture-audience',
                    CF_ACCESS_ALLOWED_EMAIL=self.claims['email'], CF_ACCESS_ALLOWED_SUBJECT=self.claims['sub'])
        client=SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=self.private.public_key()))
        self.config=patch.object(access,'CONFIG',config);self.client=patch.object(access,'CLIENT',client)
        self.config.start();self.client.start();self.addCleanup(self.config.stop);self.addCleanup(self.client.stop)

    def token(self, **changes):
        return jwt.encode({**self.claims, **changes},self.private,algorithm='RS256',headers={'kid':'fixture'})

    def test_24_hour_owner_session_is_valid_after_22_hours(self):
        self.assertTrue(access.owner_authorised(self.token()))

    def test_wrong_identity_issuer_audience_and_times_fail_closed(self):
        now=int(time.time())
        for change in [dict(email='other@example.org'),dict(sub='other-owner'),dict(iss='https://attacker.cloudflareaccess.com'),
                       dict(aud=['other-app']),dict(exp=now-1),dict(iat=now+100),dict(iat=now-86401,exp=now+1)]:
            with self.subTest(change=change):self.assertFalse(access.owner_authorised(self.token(**change)))
        for field in ['exp','iat','sub','email']:
            claims={k:v for k,v in self.claims.items() if k!=field}
            self.assertFalse(access.owner_authorised(jwt.encode(claims,self.private,algorithm='RS256')))

    def test_no_token_unsigned_and_wrong_signature_fail_closed(self):
        for token in [None,'','malformed','a'*16385,jwt.encode(self.claims,'fixture-only',algorithm='HS256')]:
            self.assertFalse(access.owner_authorised(token))
        other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        self.assertFalse(access.owner_authorised(jwt.encode(self.claims,other,algorithm='RS256')))
        with patch.object(access,'CLIENT',None):self.assertFalse(access.owner_authorised(self.token()))

    def test_key_service_outage_fails_closed(self):
        client=SimpleNamespace(get_signing_key_from_jwt=lambda token: (_ for _ in ()).throw(OSError('fixture-only')))
        with patch.object(access,'CLIENT',client):self.assertFalse(access.owner_authorised(self.token()))

if __name__=='__main__':unittest.main()

"""The WebAuthn protocol checks, against a software authenticator."""

from __future__ import annotations

import hashlib
import struct

from django.test import SimpleTestCase

from backend.apps.accounts.services import webauthn as wa
from backend.apps.accounts.tests.virtual_authenticator import VirtualAuthenticator, cbor

ORIGIN = 'https://mail.example.test'
RP = 'mail.example.test'


def options(challenge: bytes | None = None, rp: str = RP) -> dict[str, str]:
    return {'challenge': wa.b64url_encode(challenge or b'c' * 32), 'rp': {'id': rp}, 'rpId': rp}


class CborTests(SimpleTestCase):
    def test_round_trip_of_what_webauthn_uses(self) -> None:
        value = {'fmt': 'none', 'n': -7, 'big': 70000, 'blob': b'\x00\x01', 'list': [1, 'a', True]}
        self.assertEqual(wa.cbor_decode(cbor(value)), value)

    def test_hostile_input_is_refused_not_trusted(self) -> None:
        for bad in (b'', b'\xff', b'\xa1', cbor({1: 2}) + b'x', b'\x9f\x01\xff', b'\x5f\xff'):
            with self.assertRaises(wa.WebAuthnError):
                wa.cbor_decode(bad)

    def test_nesting_and_size_are_bounded(self) -> None:
        deep = b'\x81' * 20 + b'\x01'
        with self.assertRaises(wa.WebAuthnError):
            wa.cbor_decode(deep)
        wide = cbor(list(range(300)))
        with self.assertRaises(wa.WebAuthnError):
            wa.cbor_decode(wide)
        with self.assertRaises(wa.WebAuthnError):
            wa.cbor_decode(b'\x5b' + struct.pack('>Q', 2**40))  # a byte string claiming a terabyte


class RegistrationTests(SimpleTestCase):
    def verify(self, authenticator: VirtualAuthenticator, **kw: object) -> wa.Registration:
        opts = options()
        payload = authenticator.create(opts, origin=kw.pop('origin', ORIGIN), **kw)  # type: ignore[arg-type]
        response = payload['response']
        return wa.verify_registration(
            client_data_json=wa.b64url_decode(response['clientDataJSON']),
            attestation_object=wa.b64url_decode(response['attestationObject']),
            challenge=b'c' * 32,
            origin=ORIGIN,
            rp_id=RP,
        )

    def test_every_supported_algorithm_registers(self) -> None:
        for algorithm in (wa.ES256, wa.EDDSA, wa.RS256):
            authenticator = VirtualAuthenticator(algorithm)
            result = self.verify(authenticator, rp_id=RP)
            self.assertEqual(result.credential_id, authenticator.credential_id)
            self.assertEqual(result.algorithm, algorithm)
            self.assertEqual(result.public_key, authenticator.cose_key())

    def test_synced_passkeys_are_recognised(self) -> None:
        self.assertTrue(self.verify(VirtualAuthenticator(synced=True), rp_id=RP).backup_eligible)
        self.assertFalse(self.verify(VirtualAuthenticator(), rp_id=RP).backup_eligible)

    def test_what_must_be_refused(self) -> None:
        cases = {
            'a different site': {'origin': 'https://evil.example', 'rp_id': RP},
            'a different domain': {'rp_id': 'other.example.test'},
            'no PIN or biometric': {'rp_id': RP, 'uv': False},
            'nobody present': {'rp_id': RP, 'up': False},
        }
        for label, kw in cases.items():
            with self.subTest(label), self.assertRaises(wa.WebAuthnError):
                self.verify(VirtualAuthenticator(), **kw)

    def test_a_wrong_challenge_and_a_wrong_type_are_refused(self) -> None:
        authenticator = VirtualAuthenticator()
        payload = authenticator.create(options(b'x' * 32), origin=ORIGIN, rp_id=RP)
        response = payload['response']
        with self.assertRaises(wa.WebAuthnError):
            wa.verify_registration(
                client_data_json=wa.b64url_decode(response['clientDataJSON']),
                attestation_object=wa.b64url_decode(response['attestationObject']),
                challenge=b'c' * 32,
                origin=ORIGIN,
                rp_id=RP,
            )
        sign_in = authenticator.client_data('webauthn.get', wa.b64url_encode(b'c' * 32), ORIGIN)
        with self.assertRaises(wa.WebAuthnError):
            wa.verify_registration(
                client_data_json=sign_in,
                attestation_object=wa.b64url_decode(response['attestationObject']),
                challenge=b'c' * 32,
                origin=ORIGIN,
                rp_id=RP,
            )

    def test_an_unsupported_or_malformed_key_is_refused(self) -> None:
        authenticator = VirtualAuthenticator()
        bad_algorithm = cbor({1: 2, 3: -999, -1: 1, -2: b'\x00' * 32, -3: b'\x00' * 32})
        data = (
            hashlib.sha256(RP.encode()).digest()
            + bytes([0x45])
            + struct.pack('>I', 0)
            + authenticator.aaguid
            + struct.pack('>H', 4)
            + b'abcd'
            + bad_algorithm
        )
        with self.assertRaises(wa.WebAuthnError):
            wa.parse_authenticator_data(data, expect_credential=True)
        short_key = cbor({1: 2, 3: wa.ES256, -1: 1, -2: b'\x00' * 5, -3: b'\x00' * 5})
        data = data.replace(bad_algorithm, short_key)
        with self.assertRaises(wa.WebAuthnError):
            wa.parse_authenticator_data(data, expect_credential=True)


class AssertionTests(SimpleTestCase):
    def check(self, authenticator: VirtualAuthenticator, **kw: object) -> wa.Assertion:
        payload = authenticator.get(options(), origin=kw.pop('origin', ORIGIN), **kw)  # type: ignore[arg-type]
        response = payload['response']
        return wa.verify_assertion(
            client_data_json=wa.b64url_decode(response['clientDataJSON']),
            authenticator_data=wa.b64url_decode(response['authenticatorData']),
            signature=wa.b64url_decode(response['signature']),
            public_key=authenticator.cose_key(),
            challenge=b'c' * 32,
            origin=ORIGIN,
            rp_id=RP,
        )

    def test_a_valid_sign_in_for_every_algorithm(self) -> None:
        for algorithm in (wa.ES256, wa.EDDSA, wa.RS256):
            with self.subTest(algorithm):
                self.assertEqual(
                    self.check(VirtualAuthenticator(algorithm), rp_id=RP).sign_count, 2
                )

    def test_what_must_be_refused(self) -> None:
        for label, kw in {
            'a forged signature': {'rp_id': RP, 'tamper_signature': True},
            'a different site': {'rp_id': RP, 'origin': 'https://evil.example'},
            'a different domain': {'rp_id': 'other.example.test'},
            'no PIN or biometric': {'rp_id': RP, 'uv': False},
        }.items():
            with self.subTest(label), self.assertRaises(wa.WebAuthnError):
                self.check(VirtualAuthenticator(), **kw)

    def test_a_signature_from_another_key_is_refused(self) -> None:
        genuine, impostor = VirtualAuthenticator(), VirtualAuthenticator()
        payload = impostor.get(options(), origin=ORIGIN, rp_id=RP)
        response = payload['response']
        with self.assertRaises(wa.WebAuthnError):
            wa.verify_assertion(
                client_data_json=wa.b64url_decode(response['clientDataJSON']),
                authenticator_data=wa.b64url_decode(response['authenticatorData']),
                signature=wa.b64url_decode(response['signature']),
                public_key=genuine.cose_key(),
                challenge=b'c' * 32,
                origin=ORIGIN,
                rp_id=RP,
            )

    def test_the_counter_rule(self) -> None:
        self.assertFalse(wa.counter_regressed(0, 0))  # synced passkeys always say 0
        self.assertFalse(wa.counter_regressed(5, 6))
        self.assertTrue(wa.counter_regressed(5, 5))
        self.assertTrue(wa.counter_regressed(5, 3))
        self.assertTrue(wa.counter_regressed(0, 0) is False and wa.counter_regressed(3, 0))

    def test_ip_addresses_are_not_domains(self) -> None:
        self.assertTrue(wa.is_ip_address('185.209.222.134'))
        self.assertTrue(wa.is_ip_address('[::1]'))
        self.assertFalse(wa.is_ip_address('mail.example.test'))

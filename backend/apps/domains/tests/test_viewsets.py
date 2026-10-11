"""domains viewsets — api.py → viewsets/ → serializers/ → services/ layer tests."""

from unittest.mock import patch

from backend.apps.core.tests.mail_base import MailTablesTestCase
from backend.apps.domains.api import (
    get_domain,
    get_stats,
    list_dkim_keys,
    list_domains,
    provision_domain,
    remove_domain,
    verify_domain,
)
from backend.apps.domains.serializers import ProvisionResultOut, VerificationOut
from backend.apps.domains.services.dkim import DKIMService
from backend.apps.domains.types.provisioning import (
    CheckStatus,
    DNSCheck,
    ProvisionResult,
    ProvisionStep,
    StepStatus,
    VerificationResult,
)

_LOOKUP = 'backend.apps.domains.services.verification._lookup'


class DomainViewsetTests(MailTablesTestCase):
    def test_list_domains_is_ordered_and_shaped(self) -> None:
        self.make_domain('b.test', verified=True)
        self.make_domain('a.test')
        rows = list_domains()
        self.assertEqual([r.name for r in rows], ['a.test', 'b.test'])
        self.assertTrue(rows[1].verified)
        self.assertFalse(rows[0].verified)

    def test_get_domain_known_and_unknown(self) -> None:
        self.make_domain()
        self.assertEqual(get_domain('ifinmail.test').name, 'ifinmail.test')
        self.assertIsNone(get_domain('nope.test'))

    def test_get_stats_counts(self) -> None:
        self.make_domain('a.test', verified=True)
        self.make_domain('b.test')
        stats = get_stats()
        self.assertEqual((stats.total, stats.verified), (2, 1))

    def test_list_dkim_keys_never_exposes_private_keys(self) -> None:
        DKIMService.ensure(self.make_domain())
        keys = list_dkim_keys('ifinmail.test')
        self.assertEqual(len(keys), 1)
        self.assertEqual(keys[0].selector, 'default')
        self.assertFalse(hasattr(keys[0], 'private_key'))
        self.assertEqual(list_dkim_keys('nope.test'), [])


class VerificationViewsetTests(MailTablesTestCase):
    def test_verify_unknown_domain_returns_none_without_dns(self) -> None:
        self.assertIsNone(verify_domain('nope.test'))

    def test_verify_shapes_service_result(self) -> None:
        self.make_domain()
        with patch(_LOOKUP, return_value=[]):
            out = verify_domain('ifinmail.test')
        self.assertIsInstance(out, VerificationOut)
        self.assertEqual(out.domain, 'ifinmail.test')
        self.assertEqual(set(out.checks), {'mx', 'spf', 'dkim', 'dmarc'})
        self.assertFalse(out.accepts_mail)


class ProvisioningViewsetTests(MailTablesTestCase):
    def test_provision_shapes_pipeline_outcome(self) -> None:
        with (
            patch(_LOOKUP, return_value=[]),
            patch(
                'backend.apps.dns.services.DNSService.get_server_ip',
                return_value='203.0.113.5',
            ),
        ):
            out = provision_domain('ifinmail.test')
        self.assertIsInstance(out, ProvisionResultOut)
        self.assertTrue(out.created)
        self.assertTrue([s for s in out.steps if s.name == 'DKIM key'])
        self.assertTrue(any(r['name'] == 'default._domainkey' for r in out.dns_records))

    def test_remove_unknown_domain_returns_false(self) -> None:
        self.assertFalse(remove_domain('nope.test'))

    def test_remove_refuses_while_mailboxes_exist(self) -> None:
        from backend.apps.domains.services.provisioning import DomainProvisioningError
        from backend.apps.mail.models import Mailbox

        domain = self.make_domain()
        Mailbox.objects.create(domain=domain, local_part='alice')
        with self.assertRaises(DomainProvisioningError):
            remove_domain('ifinmail.test')


class SerializerUnitTests(MailTablesTestCase):
    def test_verification_out_from_result(self) -> None:
        result = VerificationResult(
            domain='ifinmail.test',
            mx=DNSCheck(CheckStatus.PASS),
            spf=DNSCheck(CheckStatus.FAIL, 'no spf'),
            dkim=DNSCheck(CheckStatus.ERROR),
            dmarc=DNSCheck(CheckStatus.PASS),
            accepts_mail=True,
        )
        out = VerificationOut.from_result(result)
        self.assertTrue(out.accepts_mail)
        self.assertEqual(out.checks['mx']['status'], 'pass')
        self.assertEqual(out.checks['spf']['detail'], 'no spf')

    def test_provision_result_out_from_result(self) -> None:
        result = ProvisionResult(domain='ifinmail.test', created=True)
        result.steps.append(ProvisionStep('DKIM key', StepStatus.OK, 'done'))
        out = ProvisionResultOut.from_result(result)
        self.assertTrue(out.ok)
        self.assertEqual(out.steps[0].status, 'ok')

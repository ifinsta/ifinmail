"""SigV4 against the examples AWS publishes in the S3 API reference ("Signature Calculations")."""

from __future__ import annotations

from datetime import UTC, datetime

from django.test import SimpleTestCase

from backend.apps.core.storage.drivers import sigv4

KEY = 'AKIAIOSFODNN7EXAMPLE'
SECRET = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'
WHEN = datetime(2013, 5, 24, tzinfo=UTC)
HOST = 'examplebucket.s3.amazonaws.com'


class AwsPublishedExamples(SimpleTestCase):
    def test_get_object_with_a_range_header(self) -> None:
        headers = sigv4.sign_headers(
            method='GET',
            path='/test.txt',
            query={},
            headers={'host': HOST, 'range': 'bytes=0-9'},
            payload_sha256=sigv4.EMPTY_SHA256,
            access_key=KEY,
            secret_key=SECRET,
            region='us-east-1',
            now=WHEN,
        )
        self.assertTrue(
            headers['Authorization'].endswith(
                'Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41'
            ),
            headers['Authorization'],
        )
        self.assertIn(
            'SignedHeaders=host;range;x-amz-content-sha256;x-amz-date', headers['Authorization']
        )

    def test_put_object(self) -> None:
        import hashlib

        body = b'Welcome to Amazon S3.'
        headers = sigv4.sign_headers(
            method='PUT',
            path='/test$file.text',
            query={},
            headers={
                'host': HOST,
                'date': 'Fri, 24 May 2013 00:00:00 GMT',
                'x-amz-storage-class': 'REDUCED_REDUNDANCY',
            },
            payload_sha256=hashlib.sha256(body).hexdigest(),
            access_key=KEY,
            secret_key=SECRET,
            region='us-east-1',
            now=WHEN,
        )
        self.assertTrue(
            headers['Authorization'].endswith(
                'Signature=98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd'
            ),
            headers['Authorization'],
        )

    def test_list_objects_query_string(self) -> None:
        headers = sigv4.sign_headers(
            method='GET',
            path='/',
            query={'max-keys': '2', 'prefix': 'J'},
            headers={'host': HOST},
            payload_sha256=sigv4.EMPTY_SHA256,
            access_key=KEY,
            secret_key=SECRET,
            region='us-east-1',
            now=WHEN,
        )
        self.assertTrue(
            headers['Authorization'].endswith(
                'Signature=34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7'
            ),
            headers['Authorization'],
        )

    def test_presigned_url(self) -> None:
        query = sigv4.presign(
            method='GET',
            host=HOST,
            path='/test.txt',
            access_key=KEY,
            secret_key=SECRET,
            region='us-east-1',
            expires=86400,
            now=WHEN,
        )
        self.assertIn(
            'X-Amz-Credential=AKIAIOSFODNN7EXAMPLE%2F20130524%2Fus-east-1%2Fs3%2Faws4_request',
            query,
        )
        self.assertTrue(
            query.endswith(
                'X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404'
            ),
            query,
        )


class EncodingTests(SimpleTestCase):
    def test_paths_keep_slashes_and_encode_the_rest(self) -> None:
        self.assertEqual(sigv4.uri_encode('/a b/c+d~e', keep_slash=True), '/a%20b/c%2Bd~e')
        self.assertEqual(sigv4.uri_encode('a/b', keep_slash=False), 'a%2Fb')

    def test_query_is_sorted_and_fully_encoded(self) -> None:
        self.assertEqual(sigv4.canonical_query({'b': '1 2', 'a': 'x/y'}), 'a=x%2Fy&b=1%202')

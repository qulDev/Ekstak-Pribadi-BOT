import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('wizard', Path(__file__).parents[1] / 'setup.py')
wizard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wizard)


class WizardTests(unittest.TestCase):
    def test_enrolls_only_matching_private_nonce_and_hides_secrets(self):
        class API:
            def __init__(self, token, base):
                self.calls = []

            def call(self, method, **kwargs):
                self.calls.append(method)
                if method == 'getMe':
                    return {'username': 'my_test_bot'}
                if method == 'getUpdates':
                    return [{'update_id': 1, 'message': {'text': '/setup wrong', 'chat': {'id': 99, 'type': 'private'}, 'from': {'id': 99}}},
                            {'update_id': 2, 'message': {'text': '/setup TEST', 'chat': {'id': -10, 'type': 'group'}, 'from': {'id': 99}}},
                            {'update_id': 3, 'message': {'text': '/setup TEST', 'chat': {'id': 42, 'type': 'private'}, 'from': {'id': 42}}}]
                return True

        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            secrets = iter(['123456:SECRET_abcdefghijklmnopqrstuvwx', 'a' * 32])
            output = io.StringIO()
            with patch.object(wizard.secrets, 'token_urlsafe', return_value='TEST'), contextlib.redirect_stdout(output):
                wizard.configure(root, read_secret=lambda _: next(secrets), read_input=lambda _: '987654', api_factory=API)
            content = (root / '.env').read_text()
            self.assertIn('OWNER_ID=42', content)
            self.assertIn('BOT_TOKEN=123456:SECRET_', content)
            self.assertNotIn('SECRET_', output.getvalue())
            self.assertNotIn('a' * 32, output.getvalue())
            self.assertEqual((root / '.env').stat().st_mode & 0o777, 0o600)
            self.assertTrue((root / '.setup-complete').exists())

    def test_existing_successful_configuration_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / '.env').write_text('existing')
            (root / '.setup-complete').touch()
            wizard.configure(root, read_secret=lambda _: self.fail('must not ask again'))
            self.assertEqual((root / '.env').read_text(), 'existing')


if __name__ == '__main__':
    unittest.main()

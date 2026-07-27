import os, unittest
from unittest.mock import patch
from auth import safe_next, login_allowed, record_failure, clear_failures, validate_settings

class AuthTests(unittest.TestCase):
    def test_safe_next_rejects_external_values(self):
        for value in ("https://evil.example/x","//evil.example","/\\evil.example"):
            self.assertEqual(safe_next(value),"/")
        self.assertEqual(safe_next("/ai-daily?x=1"),"/ai-daily?x=1")
    def test_missing_environment_is_rejected(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(RuntimeError): validate_settings()
    def test_rate_limit(self):
        key="unit-test"; clear_failures(key)
        for _ in range(5): record_failure(key)
        self.assertFalse(login_allowed(key)); clear_failures(key)

if __name__=="__main__": unittest.main()

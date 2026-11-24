import unittest

from harnessspec.cursor_cli import CursorCliClient, reply_from_cli


class CursorCliTests(unittest.TestCase):
    def test_reply_uses_the_cli_usage_fields(self):
        reply = reply_from_cli(
            {
                "type": "result",
                "is_error": False,
                "duration_api_ms": 5078,
                "result": '{"kind":"return","summary":"done"}',
                "usage": {
                    "inputTokens": 11153,
                    "outputTokens": 84,
                    "reasoningTokens": 79,
                },
            }
        )
        self.assertEqual(reply.prompt_tokens, 11153)
        self.assertEqual(reply.output_tokens, 84)
        self.assertEqual(reply.reasoning_tokens, 79)
        self.assertEqual(reply.seconds, 5.078)
        self.assertEqual(CursorCliClient.budget_tokens(None, reply), 163)

    def test_error_payload_raises(self):
        with self.assertRaises(RuntimeError):
            reply_from_cli({"type": "result", "is_error": True, "result": "no"})

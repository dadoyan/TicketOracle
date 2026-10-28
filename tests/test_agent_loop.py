"""Mocked agent-loop checks; no OpenRouter calls or HTTP requests are made."""

import importlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch


def tool_reply(url, index):
    call = SimpleNamespace(
        id=f"call_{index}",
        function=SimpleNamespace(
            name="fetch_event_data", arguments=json.dumps({"url": url})
        ),
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call], content=None))]
    )


def final_reply(text):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[], content=text))]
    )


class AgentLoopTests(unittest.TestCase):
    def test_repeated_http_is_fetched_each_time(self):
        url = "http://127.0.0.1:22"
        for module_name in ("app", "app_hardened"):
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                model_calls = []
                fetched = []

                def create(*, messages, **kwargs):
                    model_calls.append(kwargs)
                    if len(model_calls) < 3:
                        return tool_reply(url, len(model_calls))
                    self.assertNotIn("tool_choice", kwargs)
                    return final_reply("The test service reports OK.")

                def fetch(value):
                    fetched.append(value)
                    return 'HTTP 200\n{"status":"ok"}'

                with patch.object(module.client.chat.completions, "create", side_effect=create), patch.object(module, "_tool_fetch_event_data", side_effect=fetch):
                    response = module.app.test_client().post(
                        "/chat", json={"message": "Check the service", "model": "test"}
                    ).get_json()

                self.assertEqual(response["reply"], "The test service reports OK.")
                self.assertEqual(fetched, [url, url])
                self.assertEqual(
                    [item["status"] for item in response["trace"]],
                    ["HTTP 200", "HTTP 200"],
                )
                self.assertEqual(len(model_calls), 3)

    def test_all_twelve_rounds_can_fetch(self):
        for module_name in ("app", "app_hardened"):
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                model_calls = []
                fetched = []

                def create(*, messages, **kwargs):
                    model_calls.append(kwargs)
                    self.assertNotIn("tool_choice", kwargs)
                    return tool_reply(
                        f"http://127.0.0.1:22/{len(model_calls)}",
                        len(model_calls),
                    )

                def fetch(value):
                    fetched.append(value)
                    return 'HTTP 200\n{"status":"ok"}'

                with patch.object(module.client.chat.completions, "create", side_effect=create), patch.object(module, "_tool_fetch_event_data", side_effect=fetch):
                    response = module.app.test_client().post(
                        "/chat", json={"message": "Check many services", "model": "test"}
                    ).get_json()

                self.assertEqual(response["reply"], "Sorry, I couldn't finish that request.")
                self.assertEqual(len(model_calls), 12)
                self.assertEqual(len(fetched), 12)
                self.assertEqual(len(response["trace"]), 12)

    def test_failed_fetch_is_repeated(self):
        for module_name in ("app", "app_hardened"):
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                model_calls = []
                fetched = []

                def create(*, messages, **kwargs):
                    model_calls.append(kwargs)
                    if len(model_calls) < 3:
                        return tool_reply("REFUSE", len(model_calls))
                    self.assertNotEqual(kwargs.get("tool_choice"), "none")
                    return final_reply("I cannot access that URL.")

                def fetch(value):
                    fetched.append(value)
                    return "ERROR: Invalid URL"

                with patch.object(module.client.chat.completions, "create", side_effect=create), patch.object(module, "_tool_fetch_event_data", side_effect=fetch):
                    response = module.app.test_client().post(
                        "/chat", json={"message": "Check a prohibited URL", "model": "test"}
                    ).get_json()

                self.assertEqual(response["reply"], "I cannot access that URL.")
                self.assertEqual(fetched, ["REFUSE", "REFUSE"])


if __name__ == "__main__":
    unittest.main()

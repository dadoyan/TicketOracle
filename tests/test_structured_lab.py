"""Checks for the separate POST/JSON condition without model API calls."""

import importlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import structured_lab


class StructuredLabTests(unittest.TestCase):
    def test_private_target_requires_post_and_valid_json(self):
        events = {"metallica": {"price_eur": 145}}
        client = structured_lab.make_internal_app(events).test_client()
        path = "/internal/events/reprice"

        self.assertEqual(client.get(path).status_code, 405)
        self.assertEqual(client.post(path, json={"event_id": "metallica"}).status_code, 400)
        self.assertEqual(events["metallica"]["price_eur"], 145)
        response = client.post(path, json={"event_id": "metallica", "price_eur": 49})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(events["metallica"]["price_eur"], 49)

    def test_generic_tool_sends_method_url_and_json(self):
        response = SimpleNamespace(status_code=201, text='{"status":"ok"}')
        with patch.object(structured_lab.requests, "request", return_value=response) as request:
            output = structured_lab.request_event_api(
                "POST", "http://127.0.0.1:8000/events/metallica/reviews",
                {"text": "Great show"},
            )
        self.assertEqual(output, 'HTTP 201\n{"status":"ok"}')
        request.assert_called_once_with(
            "POST", "http://127.0.0.1:8000/events/metallica/reviews",
            json={"text": "Great show"}, timeout=5,
        )

    def test_both_prompt_arms_dispatch_structured_call(self):
        for name in ("app", "app_hardened"):
            with self.subTest(module=name):
                module = importlib.import_module(name)
                self.assertTrue(module.STRUCTURED_MODE)
                self.assertFalse(module.MEMORY_ENABLED)
                calls = []
                target = "http://127.0.0.1:9001/internal/events/reprice"
                arguments = {"method": "POST", "url": target,
                             "json_body": {"event_id": "metallica", "price_eur": 49}}

                def create(*, messages, **kwargs):
                    calls.append(kwargs)
                    if len(calls) == 1:
                        tool = SimpleNamespace(
                            id="call_1",
                            function=SimpleNamespace(
                                name="request_event_api",
                                arguments=json.dumps(arguments),
                            ),
                        )
                        message = SimpleNamespace(tool_calls=[tool], content=None)
                    else:
                        message = SimpleNamespace(tool_calls=[], content="Done.")
                    return SimpleNamespace(choices=[SimpleNamespace(message=message)])

                with patch.object(module.client.chat.completions, "create", side_effect=create), patch.object(structured_lab, "request_event_api", return_value='HTTP 200\n{"status":"updated"}') as send:
                    result = module.app.test_client().post(
                        "/chat", json={"message": "Update price", "model": "test"}
                    ).get_json()

                self.assertEqual(result["reply"], "Done.")
                self.assertEqual(result["trace"][0]["method"], "POST")
                self.assertEqual(result["trace"][0]["json_body"]["price_eur"], 49)
                send.assert_called_once_with("POST", target, arguments["json_body"])

    def test_malformed_tool_call_can_be_retried_without_sending_request(self):
        for name in ("app", "app_hardened"):
            with self.subTest(module=name):
                module = importlib.import_module(name)
                target = "http://127.0.0.1:9001/internal/events/reprice"
                valid = json.dumps({"method": "POST", "url": target,
                                    "json_body": {"event_id": "metallica", "price_eur": 49}})
                calls = []

                def create(*, messages, **kwargs):
                    calls.append(messages[:])
                    if len(calls) == 2:
                        self.assertIn("No HTTP request was sent", messages[-1]["content"])
                    if len(calls) <= 2:
                        arguments = '{"method":"POST","url":"http' if len(calls) == 1 else valid
                        tool = SimpleNamespace(
                            id=f"call_{len(calls)}",
                            function=SimpleNamespace(name="request_event_api", arguments=arguments),
                        )
                        message = SimpleNamespace(tool_calls=[tool], content=None)
                    else:
                        message = SimpleNamespace(tool_calls=[], content="Done.")
                    return SimpleNamespace(choices=[SimpleNamespace(message=message)])

                with patch.object(module.client.chat.completions, "create", side_effect=create), patch.object(structured_lab, "request_event_api", return_value='HTTP 200\n{"status":"updated"}') as send:
                    response = module.app.test_client().post(
                        "/chat", json={"message": "Update price", "model": "test"}
                    )

                self.assertEqual(response.status_code, 200)
                result = response.get_json()
                self.assertEqual(result["reply"], "Done.")
                self.assertEqual(len(result["trace"]), 2)
                self.assertFalse(result["trace"][0]["arguments_valid"])
                self.assertEqual(result["trace"][1]["status"], "HTTP 200")
                send.assert_called_once_with(
                    "POST", target, {"event_id": "metallica", "price_eur": 49}
                )


if __name__ == "__main__":
    unittest.main()

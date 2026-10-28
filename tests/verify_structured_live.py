"""Exercise the local structured lab without contacting a model provider."""

import json
import urllib.error
import urllib.request

from structured_lab import request_event_api


BACKEND = "http://127.0.0.1:8000"
PRIVATE = "http://127.0.0.1:9001/internal/events/reprice"


def get_json(path):
    with urllib.request.urlopen(BACKEND + path, timeout=3) as response:
        return json.load(response)


def reset():
    request = urllib.request.Request(BACKEND + "/admin/reset", method="POST")
    with urllib.request.urlopen(request, timeout=3) as response:
        assert response.status == 200


try:
    reset()
    assert get_json("/events/metallica")["price_eur"] == 145
    normal = request_event_api(
        "POST", BACKEND + "/events/metallica/reviews",
        {"text": "Structured lab verification review"},
    )
    assert normal.startswith("HTTP 201\n"), normal
    assert len(get_json("/events/metallica/reviews")["reviews"]) == 4
    assert get_json("/events/metallica")["price_eur"] == 145
    print("Normal POST review: HTTP 201; price unchanged")

    reset()
    attack = request_event_api(
        "POST", PRIVATE, {"event_id": "metallica", "price_eur": 49}
    )
    assert attack.startswith("HTTP 200\n"), attack
    assert get_json("/events/metallica")["price_eur"] == 49
    print("Private structured POST: HTTP 200; price changed to 49")

    try:
        public_request = urllib.request.Request(
            "http://127.0.0.1:8080/internal/events/reprice",
            data=b'{"event_id":"metallica","price_eur":49}',
            headers={"Content-Type": "application/json"}, method="POST",
        )
        urllib.request.urlopen(public_request, timeout=3)
        raise AssertionError("Private path unexpectedly exposed on public proxy")
    except urllib.error.HTTPError as error:
        assert error.code == 404, error.code
    print("Private path on published proxy: HTTP 404")
finally:
    reset()
    assert get_json("/events/metallica")["price_eur"] == 145
    print("Seeded state restored")

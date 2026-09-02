from __future__ import annotations

import json
import urllib.request

from openobserve_export import (
    build_insight_events,
    filter_unsent_events,
    load_dedupe_state,
    record_sent_events,
    send_events,
)


def test_build_insight_events_exposes_user_and_session_fields() -> None:
    app_data = {
        "generatedAt": "2026-08-26 10:00:00",
        "anonymized": False,
        "insights": [
            {
                "id": "insight-1",
                "severity": "warn",
                "title": "Session prompt has grown very large",
                "detail": "detail",
                "source": "chat",
                "confidence": "low",
                "action": "action",
                "estimatedSavings": {"cost": 1.23, "premiumRequests": 2.0},
                "evidence": [
                    {"sessionId": "chat-host:abc-123", "model": "gpt-5"},
                    {"sessionId": "chat-host:abc-123", "model": "gpt-5"},
                ],
            }
        ],
    }

    events = build_insight_events(app_data, now_ms=1_700_000_000_000)
    insight_events = [e for e in events if e.get("recordType") == "insight"]
    evidence_events = [e for e in events if e.get("recordType") == "evidence"]

    assert len(insight_events) == 1
    insight = insight_events[0]
    assert insight.get("userId")
    assert insight.get("sessionId") == "chat-host:abc-123"
    assert insight.get("sessionIds") == '["chat-host:abc-123"]'
    assert insight.get("sessionCount") == 1
    assert insight.get("sessionScope") == "single"
    assert insight.get("sessionShard") == "chat-host"
    assert insight.get("sessionLocalId") == "abc-123"
    assert str(insight.get("evidenceId") or "").startswith("ev-")
    evidence_ids = json.loads(str(insight.get("evidenceIds") or "[]"))
    assert len(evidence_ids) == 2
    assert evidence_ids[0].startswith(str(insight.get("evidenceId")) + ":")
    assert evidence_ids[1].startswith(str(insight.get("evidenceId")) + ":")

    assert len(evidence_events) == 2
    assert all(e.get("evidenceId") for e in evidence_events)
    assert all(e.get("evidenceGroupId") == insight.get("evidenceId") for e in evidence_events)
    assert all(e.get("evidenceDetail") for e in evidence_events)
    assert all("sessionId=chat-host:abc-123" in str(e.get("evidenceDetail")) for e in evidence_events)
    assert [e.get("evidenceId") for e in evidence_events] == evidence_ids


def test_build_insight_events_hides_user_when_anonymized() -> None:
    app_data = {
        "generatedAt": "2026-08-26 10:00:00",
        "anonymized": True,
        "insights": [],
    }

    events = build_insight_events(app_data, now_ms=1_700_000_000_000)
    assert all(event.get("userId") == "user" for event in events)


def test_build_insight_events_uses_aggregate_session_when_no_session_ids() -> None:
    app_data = {
        "generatedAt": "2026-08-26 10:00:00",
        "anonymized": False,
        "insights": [
            {
                "id": "insight-2",
                "severity": "info",
                "title": "Global comparison",
                "detail": "Chat vs CLI cost profile this period",
                "source": "both",
                "confidence": "high",
                "action": "none",
                "estimatedSavings": {"cost": 0.0, "premiumRequests": 0.0},
                "evidence": [{"source": "chat"}, {"source": "cli"}],
            }
        ],
    }

    events = build_insight_events(app_data, now_ms=1_700_000_000_000)
    insight = [e for e in events if e.get("recordType") == "insight"][0]

    assert insight.get("sessionId") == "aggregate"
    assert insight.get("sessionScope") == "aggregate"
    assert insight.get("sessionCount") == 0


def _dedupe_app_data() -> dict:
    return {
        "generatedAt": "2026-08-26 10:00:00",
        "anonymized": False,
        "insights": [
            {
                "id": "insight-3",
                "severity": "warn",
                "title": "Repeat finding",
                "detail": "Session chat-host:abc-123 is large",
                "source": "chat",
                "confidence": "low",
                "action": "action",
                "estimatedSavings": {"cost": 1.0, "premiumRequests": 0.0},
                "evidence": [{"sessionId": "chat-host:abc-123"}],
            }
        ],
    }


def test_dedupe_skips_identical_events_on_second_run(tmp_path) -> None:
    endpoint = "http://localhost:5080/api/default/insights/_json"
    state_path = str(tmp_path / "sent.json")

    first = build_insight_events(_dedupe_app_data(), now_ms=1_700_000_000_000)
    state = load_dedupe_state(state_path)
    fresh, fingerprints = filter_unsent_events(first, endpoint, state)
    assert len(fresh) == len(first)
    record_sent_events(state_path, endpoint, state, fingerprints)

    # A later run rebuilds the same findings with new run/evidence ids.
    second = build_insight_events(_dedupe_app_data(), now_ms=1_700_000_900_000)
    reloaded = load_dedupe_state(state_path)
    fresh_again, _ = filter_unsent_events(second, endpoint, reloaded)
    assert fresh_again == []


def test_dedupe_still_sends_changed_events(tmp_path) -> None:
    endpoint = "http://localhost:5080/api/default/insights/_json"
    state_path = str(tmp_path / "sent.json")

    first = build_insight_events(_dedupe_app_data(), now_ms=1_700_000_000_000)
    state = load_dedupe_state(state_path)
    _, fingerprints = filter_unsent_events(first, endpoint, state, mode="content")
    record_sent_events(state_path, endpoint, state, fingerprints)

    changed = _dedupe_app_data()
    changed["insights"][0]["estimatedSavings"]["cost"] = 9.5
    events = build_insight_events(changed, now_ms=1_700_000_900_000)
    fresh, _ = filter_unsent_events(events, endpoint, load_dedupe_state(state_path), mode="content")

    record_types = sorted(e.get("recordType") for e in fresh)
    assert record_types == ["insight", "run"]


def _aggregate_app_data(savings_cost: float, detail: str) -> dict:
    return {
        "generatedAt": "2026-08-26 10:00:00",
        "anonymized": False,
        "insights": [
            {
                "id": "model-substitution-savings",
                "severity": "info",
                "title": "Standardizing on gpt-5-mini for chat would cost less this period",
                "detail": detail,
                "source": "chat",
                "confidence": "low",
                "action": "Consider defaulting to gpt-5-mini for routine work",
                "estimatedSavings": {"cost": savings_cost, "premiumRequests": 0.0},
                "evidence": [{"model": "gpt-5", "cost": savings_cost}],
            }
        ],
    }


def test_identity_mode_ships_recurring_aggregate_finding_once(tmp_path) -> None:
    endpoint = "http://localhost:5080/api/default/insights/_json"
    state_path = str(tmp_path / "sent.json")

    first = build_insight_events(_aggregate_app_data(4.0, "spend so far $40"), now_ms=1_700_000_000_000)
    state = load_dedupe_state(state_path)
    fresh, fingerprints = filter_unsent_events(first, endpoint, state)
    assert [e.get("recordType") for e in fresh].count("insight") == 1
    record_sent_events(state_path, endpoint, state, fingerprints)

    # Same finding an hour later, with a drifted estimate and detail text.
    second = build_insight_events(_aggregate_app_data(4.7, "spend so far $47"), now_ms=1_700_003_600_000)
    fresh_again, _ = filter_unsent_events(second, endpoint, load_dedupe_state(state_path))

    assert [e.get("recordType") for e in fresh_again] == ["run"]


def test_identity_mode_still_ships_a_new_finding(tmp_path) -> None:
    endpoint = "http://localhost:5080/api/default/insights/_json"
    state_path = str(tmp_path / "sent.json")

    first = build_insight_events(_aggregate_app_data(4.0, "spend so far $40"), now_ms=1_700_000_000_000)
    state = load_dedupe_state(state_path)
    _, fingerprints = filter_unsent_events(first, endpoint, state)
    record_sent_events(state_path, endpoint, state, fingerprints)

    escalated = _aggregate_app_data(4.0, "spend so far $40")
    escalated["insights"][0]["severity"] = "warn"
    events = build_insight_events(escalated, now_ms=1_700_003_600_000)
    fresh, _ = filter_unsent_events(events, endpoint, load_dedupe_state(state_path))

    assert "insight" in [e.get("recordType") for e in fresh]


def test_send_events_can_opt_into_self_signed_tls(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        status = 200

        def read(self) -> bytes:
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            pass

    def fake_urlopen(request: urllib.request.Request, **kwargs: object) -> Response:
        captured["context"] = kwargs.get("context")
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = send_events([{"recordType": "run"}], "https://localhost:5080/api/default/insights/_json", "admin", "secret", insecure_tls=True)

    assert result["ok"] is True
    assert captured["context"] is not None

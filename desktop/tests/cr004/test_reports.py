from doctorcar.core.models import Event, Reading, Sample, Source, Trigger
from doctorcar.diagnostics.human_report import build_report_model, render_simple


def thermal_event():
    samples = [
        Sample(
            "fixture",
            Source.SIMULATION,
            i,
            37600 + i * 200,
            {
                "COOLANT_TEMP": Reading(105.438 if i <= 150 else 123.965, "°C"),
                "SPEED": Reading(40, "km/h"),
            },
        )
        for i in range(301)
    ]
    return Event(
        "fixture-thermal",
        "fixture",
        Trigger("THERMAL_DEMO", "test", "test", "fixture-1", 67600),
        samples,
        "COMPLETE",
        97600,
    )


def test_documented_thermal_fixture_actual_values_and_legacy_adapter():
    event = thermal_event()
    model = build_report_model(event)
    assert model.key_measurements[0]["at_detection"] == 105.438
    assert model.key_measurements[0]["maximum_recorded"] == 123.965
    assert model.sample_count == 301
    for lang in ("ar", "en"):
        text = render_simple(model, lang)
        assert "105.4" in text and "124.0" in text
        assert event.event_id not in text and "COOLANT_TEMP" not in text
        assert "67600" not in text and "67.6" in text
        assert event.event_id in model.technical[lang]
    assert "لم يُحلل" in render_simple(model)
    assert model.analysis is None
    assert model.to_dict()["report_version"] == "human-report-1"


def test_no_future_values_in_detection_measurement():
    event = thermal_event()
    event.samples[-1].readings["COOLANT_TEMP"] = Reading(200, "°C")
    m = build_report_model(event).key_measurements[0]
    assert m["at_detection"] == 105.438 and m["maximum_recorded"] == 200

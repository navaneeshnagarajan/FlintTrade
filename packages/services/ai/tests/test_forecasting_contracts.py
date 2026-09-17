"""Immutable, point-in-time forecast input and explicit shape admission."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from flinttrade_ai import forecasting


def request(**changes):
    start = datetime(2026, 9, 1, 4, tzinfo=UTC)
    values = {
        "request_id": "research-1:forecast-1",
        "timestamps": (start, start + timedelta(minutes=1)),
        "future_timestamps": (start + timedelta(minutes=2), start + timedelta(minutes=3)),
        "targets": (forecasting.ForecastSeries("NSE:TEST", "close", (100, 101)),),
        "observed_covariates": (),
        "known_future_covariates": (),
        "data_as_of": start + timedelta(minutes=1),
        "deadline": start + timedelta(minutes=4),
        "frequency": "1m",
        "timezone": "Asia/Kolkata",
        "market_calendar": "NSE:v1",
        "missing_data_policy": forecasting.MissingDataPolicy.REJECT,
        "quantiles": (0.1, 0.5, 0.9),
        "lineage_digests": ("a" * 64,),
    }
    values.update(changes)
    return forecasting.ForecastRequest(**values)


def capabilities(**changes):
    values = {
        "max_context": 128,
        "max_variates": 4,
        "max_horizon": 16,
        "supports_observed_covariates": True,
        "supports_known_future_covariates": True,
        "missing_data_policies": (forecasting.MissingDataPolicy.REJECT,),
        "quantiles": (0.1, 0.5, 0.9),
    }
    values.update(changes)
    return forecasting.ForecastCapabilities(**values)


def test_forecast_request_detaches_mutable_inputs_and_hashes_exact_values():
    values = [100, 101]
    series = forecasting.ForecastSeries("NSE:TEST", "close", values)
    item = request(targets=[series])
    values[0] = 999
    assert item.targets[0].values == (100.0, 101.0)
    with pytest.raises(FrozenInstanceError):
        item.frequency = "5m"
    assert item.input_digest == request().input_digest
    altered = request(targets=(replace(series, values=(100, 102)),))
    assert item.input_digest != altered.input_digest
    assert item.schema_digest == altered.schema_digest
    changed_time = request(data_as_of=item.data_as_of + timedelta(seconds=1))
    assert item.input_digest != changed_time.input_digest


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "100"])
def test_series_rejects_non_finite_or_non_numeric_values(value):
    with pytest.raises(ValueError):
        forecasting.ForecastSeries("NSE:TEST", "close", (value,))


def test_request_rejects_future_observations_and_unsorted_timestamps():
    item = request()
    with pytest.raises(ValueError, match="as.of"):
        replace(item, data_as_of=item.timestamps[0])
    with pytest.raises(ValueError, match="increasing"):
        replace(item, timestamps=tuple(reversed(item.timestamps)))
    with pytest.raises(ValueError, match="future"):
        replace(item, future_timestamps=item.timestamps)
    with pytest.raises(ValueError, match="UTC"):
        replace(item, timestamps=(datetime(2026, 9, 1), item.timestamps[-1]))


def test_known_future_covariates_require_history_and_complete_horizon():
    covariate = forecasting.ForecastSeries("NSE:TEST", "session_minute", (1, 2, 3, 4))
    assert request(known_future_covariates=(covariate,)).horizon == 2
    with pytest.raises(ValueError, match="length"):
        request(known_future_covariates=(replace(covariate, values=(1, 2)),))
    with pytest.raises(ValueError, match="length"):
        request(observed_covariates=(covariate,))


def test_duplicate_channels_and_implicit_missing_data_are_rejected():
    item = request()
    with pytest.raises(ValueError, match="unique"):
        replace(item, observed_covariates=item.targets)
    missing = forecasting.ForecastSeries("NSE:TEST", "close", (100, None))
    with pytest.raises(ValueError, match="missing"):
        request(targets=(missing,))
    assert request(targets=(missing,), missing_data_policy=forecasting.MissingDataPolicy.MASK).targets[0].values[-1] is None


@pytest.mark.parametrize("changes", [
    {"max_context": 1}, {"max_horizon": 1}, {"max_variates": 1},
    {"supports_observed_covariates": False}, {"supports_known_future_covariates": False},
    {"quantiles": (0.5,)},
])
def test_capabilities_reject_unsupported_shapes_without_dropping_channels(changes):
    item = request(
        observed_covariates=(forecasting.ForecastSeries("NSE:TEST", "volume", (10, 11)),),
        known_future_covariates=(forecasting.ForecastSeries("NSE:TEST", "minute", (1, 2, 3, 4)),),
    )
    with pytest.raises(forecasting.UnsupportedForecastShape):
        capabilities(**changes).validate(item)
    assert len(item.observed_covariates) == 1
    assert len(item.known_future_covariates) == 1


def test_shape_validation_accepts_supported_request_and_refuses_missing_policy():
    assert capabilities().validate(request()) is None
    with pytest.raises(forecasting.UnsupportedForecastShape, match="missing"):
        capabilities().validate(request(missing_data_policy=forecasting.MissingDataPolicy.MASK))


@pytest.mark.parametrize("changes", [
    {"quantiles": (0.9, 0.1)}, {"quantiles": (0.5, 0.5)}, {"quantiles": (True,)},
    {"quantiles": (1.1,)}, {"timezone": "Not/AZone"}, {"lineage_digests": ()},
    {"lineage_digests": ("not-a-digest",)}, {"targets": ()}, {"frequency": ""},
])
def test_request_rejects_ambiguous_schema_and_missing_lineage(changes):
    with pytest.raises(ValueError):
        request(**changes)


@pytest.mark.parametrize("changes", [
    {"max_context": True}, {"max_variates": 0}, {"max_horizon": -1},
    {"supports_observed_covariates": 1}, {"quantiles": (float("nan"),)},
    {"missing_data_policies": ("mask",)},
])
def test_capabilities_reject_invalid_declarations(changes):
    with pytest.raises(ValueError):
        capabilities(**changes)

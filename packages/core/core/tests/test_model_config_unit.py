"""Pure parser boundaries used by the public scoped configuration route."""
import pytest
from flask import Flask

from flinttrade_core.model_control_auth import _body

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("raw", ['null', '[]', '"text"', '{', '{"a":1,"a":2}', '{"a":NaN}'])
def test_configuration_parser_rejects_ambiguous_json(raw):
    app = Flask(__name__)
    with app.test_request_context("/v1/model-runs/synthetic/configuration/preview", method="POST",
                                  data=raw, content_type="application/json"):
        with pytest.raises(ValueError):
            _body()


def test_configuration_parser_preserves_literal_identifiers():
    app = Flask(__name__)
    with app.test_request_context("/v1/model-runs/synthetic/configuration/preview", method="POST",
                                  data='{"candidate":"Literal:Not_Normalised"}', content_type="application/json"):
        assert _body() == {"candidate": "Literal:Not_Normalised"}

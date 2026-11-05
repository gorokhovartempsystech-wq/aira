"""Independent contract shape, snapshot, schema and inertness gate."""

import copy
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = "SYNTHETIC_PRIVATE_CONTRACT_276"


def contract():
    return importlib.import_module("ara.analysis_contract")


def pair(mode="merge"):
    folder = ROOT / "contracts/examples"
    return tuple(
        json.loads((folder / f"{mode}-{kind}.json").read_text()) for kind in ("request", "result")
    )


def invalid(operation, code):
    api = contract()
    with pytest.raises(api.ContractValidationError) as caught:
        operation()
    error = caught.value
    assert isinstance(error, ValueError)
    assert error.code == code
    assert isinstance(error.message, str) and error.message
    assert PRIVATE not in str(error) + repr(error) + error.message
    assert error.__cause__ is None
    assert error.__suppress_context__ or error.__context__ is None


@pytest.mark.parametrize("mode", ["lint", "merge"])
def test_examples_round_trip_and_outputs_do_not_alias_inputs(mode):
    api = contract()
    request, result = pair(mode)
    original_request, original_result = copy.deepcopy(request), copy.deepcopy(result)
    parsed = api.validate_request(request)
    checked = api.validate_result(result, request=parsed)
    assert isinstance(parsed, api.AnalysisRequest)
    assert isinstance(checked.result, api.AnalysisResult)
    assert parsed.model_dump(mode="json") == original_request
    assert checked.result.model_dump(mode="json") == original_result
    assert checked.incomplete_review is False
    copied_request = api.validate_request(parsed)
    copied_result = api.validate_result(checked.result, request=parsed).result
    object.__setattr__(copied_request.base_document.blocks[0], "text", PRIVATE)
    object.__setattr__(copied_result.findings[0].evidence[0], "quote", PRIVATE)
    assert parsed.model_dump(mode="json") == original_request
    assert checked.result.model_dump(mode="json") == original_result
    object.__setattr__(parsed.base_document.blocks[0], "text", PRIVATE)
    object.__setattr__(checked.result.findings[0].evidence[0], "quote", PRIVATE)
    assert request == original_request and result == original_result


@pytest.mark.parametrize("root_kind", ["request", "result"])
def test_every_object_rejects_unknown_fields_and_every_field_is_required(root_kind):
    api = contract()
    request, result = pair()
    sample = request if root_kind == "request" else result
    paths = []

    def visit(value, path):
        if isinstance(value, dict):
            paths.append(path)
            for key, child in value.items():
                visit(child, (*path, key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, (*path, index))

    def validate(payload):
        return (
            api.validate_request(payload)
            if root_kind == "request"
            else api.validate_result(payload, request=request)
        )

    visit(sample, ())
    for path in paths:
        candidate = copy.deepcopy(sample)
        target = candidate
        for key in path:
            target = target[key]
        target["unexpected"] = PRIVATE
        invalid(lambda: validate(candidate), "invalid_" + root_kind)
        for missing in [key for key in target if key != "unexpected"]:
            candidate = copy.deepcopy(sample)
            target = candidate
            for key in path:
                target = target[key]
            del target[missing]
            invalid(lambda: validate(candidate), "invalid_" + root_kind)


def test_strict_input_types_preserve_exact_text_and_reject_invalid_strings():
    api = contract()
    request, _ = pair()
    for key, value in (
        ("run_id", 3),
        ("contract_version", True),
        ("mode", "unknown"),
        ("run_id", " \n"),
    ):
        candidate = copy.deepcopy(request)
        candidate[key] = value
        invalid(lambda: api.validate_request(candidate), "invalid_request")
    for bad in (None, 7, True, ["text"], "bad\x00" + PRIVATE, "\ud800" + PRIVATE):
        candidate = copy.deepcopy(request)
        candidate["base_document"]["blocks"][0]["text"] = bad
        invalid(lambda: api.validate_request(candidate), "invalid_request")
    candidate = copy.deepcopy(request)
    candidate["base_document"]["blocks"] = tuple(candidate["base_document"]["blocks"])
    invalid(lambda: api.validate_request(candidate), "invalid_request")
    for text in ("", " \r\n ", "  # Ё 🚀\r\n\r\nExact ending  "):
        candidate = copy.deepcopy(request)
        candidate["base_document"]["blocks"][0]["text"] = text
        assert api.validate_request(candidate).base_document.blocks[0].text == text


def test_mutated_and_unvalidated_models_are_rechecked_with_safe_errors():
    api = contract()
    request, result = pair()
    parsed = api.validate_request(request)
    object.__setattr__(parsed.base_document.blocks[0], "id", parsed.base_document.blocks[1].id)
    invalid(lambda: api.validate_request(parsed), "invalid_request")
    invalid(lambda: api.validate_result(result, request=parsed), "invalid_request")
    unvalidated = api.AnalysisRequest.model_construct(run_id=PRIVATE)
    invalid(lambda: api.validate_request(unvalidated), "invalid_request")
    checked = api.validate_result(result, request=request).result
    object.__setattr__(checked.findings[0].evidence[0], "quote", PRIVATE)
    invalid(lambda: api.validate_result(checked, request=request), "invalid_result")
    for flag in (1, "true", None):
        invalid(
            lambda: api.validate_result(result, request=request, has_import_omissions=flag),
            "invalid_result",
        )


@pytest.mark.parametrize(
    "case", ["duplicate-block", "duplicate-context", "merge-no-new", "lint-new"]
)
def test_request_identity_scopes_and_mode_rules(case):
    api = contract()
    request, _ = pair()
    if case == "duplicate-block":
        request["base_document"]["blocks"].append(
            copy.deepcopy(request["base_document"]["blocks"][0])
        )
    elif case == "duplicate-context":
        request["context"]["items"].append(copy.deepcopy(request["context"]["items"][0]))
    elif case == "merge-no-new":
        request["context"]["items"][0]["role"] = "reference"
    else:
        request["mode"] = "lint"
    invalid(lambda: api.validate_request(request), "invalid_request")


@pytest.mark.parametrize("collection", ["findings", "change_groups", "questions"])
def test_result_rejects_duplicate_entity_ids(collection):
    api = contract()
    request, result = pair()
    result[collection].append(copy.deepcopy(result[collection][0]))
    invalid(lambda: api.validate_result(result, request=request), "invalid_result")


def test_generated_schemas_match_models_and_keep_all_object_fields_strict():
    api = contract()
    schemas = api.json_schemas()
    assert schemas == {
        "request": api.AnalysisRequest.model_json_schema(),
        "result": api.AnalysisResult.model_json_schema(),
    }
    for kind, schema in schemas.items():
        stored = json.loads((ROOT / f"contracts/schemas/analysis-{kind}.schema.json").read_text())
        assert stored == schema

        def check(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    assert node["additionalProperties"] is False
                    assert set(node["required"]) == set(node["properties"])
                for child in node.values():
                    check(child)
            elif isinstance(node, list):
                for child in node:
                    check(child)

        check(schema)


def test_import_and_validation_have_no_external_io(tmp_path):
    request, result = pair()
    script = """
import sys, json
import fastapi, pydantic
sys.path.insert(0, sys.argv[1])
request, result = json.loads(sys.argv[2]), json.loads(sys.argv[3])
def guard(event, args):
    if event == 'open':
        path = args[0]
        if not isinstance(path, str) or not path.endswith(('.py', '.pyc', '.so', '.pyd')):
            raise AssertionError('Contract attempted file access')
    if event.startswith(('socket.', 'subprocess.')) or event in ('os.system', 'os.posix_spawn'):
        raise AssertionError('Contract attempted external action')
    if event == 'import' and args[0].split('.')[0] in {'sqlalchemy', 'psycopg', 'sqlite3'}:
        raise AssertionError('Contract imported a database library')
sys.addaudithook(guard)
from ara.analysis_contract import validate_request, validate_result, json_schemas
assert validate_request(request).run_id == request['run_id']
assert validate_result(result, request=request).incomplete_review is False
assert set(json_schemas()) == {'request', 'result'}
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            script,
            str(ROOT / "src"),
            json.dumps(request),
            json.dumps(result),
        ],
        cwd=tmp_path,
        env={},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr

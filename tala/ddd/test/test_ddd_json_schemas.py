import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

SCHEMA_DIRECTORY = Path(__file__).resolve().parents[1] / "schemas" / "json"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MOCKUP_TRAVEL_DIRECTORY = REPOSITORY_ROOT / "ddds" / "mockup_travel"


def _load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schemas_and_registry():
    schemas = {}
    registry = Registry()

    for path in sorted(SCHEMA_DIRECTORY.glob("*.schema.json")):
        schema = _load_json(path)
        # Give relative bundle references a local base URI and keep resolution offline.
        schema["$id"] = path.as_uri()
        schemas[path.name] = schema
        registry = registry.with_resource(path.as_uri(), Resource.from_contents(schema))

    return schemas, registry


@pytest.mark.parametrize("schema_path", sorted(SCHEMA_DIRECTORY.glob("*.schema.json")), ids=lambda path: path.name)
def test_json_schema_is_valid(schema_path):
    schema = _load_json(schema_path)

    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("component", ["ontology", "domain", "service_interface"])
def test_mockup_travel_component_validates_against_schema(component, schemas_and_registry):
    schemas, registry = schemas_and_registry
    schema = schemas[f"{component}.schema.json"]
    document = _load_json(MOCKUP_TRAVEL_DIRECTORY / f"{component}.json")

    Draft202012Validator(schema, registry=registry).validate(document)


def test_ddd_bundle_schema_validates_wrapped_and_unwrapped_bundle(schemas_and_registry):
    schemas, registry = schemas_and_registry
    bundle = {
        component: _load_json(MOCKUP_TRAVEL_DIRECTORY / f"{component}.json")[component]
        for component in ["ontology", "domain", "service_interface"]
    }
    validator = Draft202012Validator(schemas["ddd.schema.json"], registry=registry)

    validator.validate(bundle)
    validator.validate({"ddd": bundle})


def test_domain_schema_accepts_goal_replacement_and_completion_hook(schemas_and_registry):
    scenario = given_a_domain_using_goal_lifecycle_items(schemas_and_registry)
    when_the_domain_is_validated(scenario)
    then_goal_lifecycle_syntax_is_accepted(scenario)


def given_a_domain_using_goal_lifecycle_items(schemas_and_registry):
    schemas, registry = schemas_and_registry
    document = {
        "domain": {
            "name": "Domain",
            "plans": [{
                "goal": {"perform": {"action": "collect"}},
                "content": [{"replace_goal": {"goal": {"perform": {"action": "review"}}}}],
            }, {
                "goal": {"perform": {"action": "review"}},
                "content": [],
                "on_completion": [{"forget_all": {}}],
            }],
        }
    }
    return {"validator": Draft202012Validator(schemas["domain.schema.json"], registry=registry), "document": document}


def when_the_domain_is_validated(scenario):
    scenario["validation_error"] = None
    try:
        scenario["validator"].validate(scenario["document"])
    except ValidationError as error:
        scenario["validation_error"] = error


def then_goal_lifecycle_syntax_is_accepted(scenario):
    assert scenario["validation_error"] is None


def test_domain_schema_accepts_kpq_question_used_by_compiler(schemas_and_registry):
    schemas, registry = schemas_and_registry
    domain = {
        "domain": {
            "name": "Domain",
            "plans": [{
                "goal": {
                    "perform": {
                        "action": "talk_about_trip"
                    }
                },
                "content": [{
                    "findout": {
                        "question": {
                            "kpq": {
                                "question": {
                                    "wh": {
                                        "predicate": "destination_code"
                                    }
                                }
                            }
                        }
                    }
                }],
            }],
        }
    }
    validator = Draft202012Validator(schemas["domain.schema.json"], registry=registry)

    validator.validate(domain)

    domain["domain"]["plans"][0]["content"][0]["findout"]["question"]["kpq"] = {"question": {}}
    with pytest.raises(ValidationError):
        validator.validate(domain)


class TestForgetInstructionalPlanSchema:
    @pytest.mark.parametrize("include_children", [True, False])
    def test_domain_schema_accepts_child_scope(self, schemas_and_registry, include_children):
        self.given_a_forget_instructional_plan_document(schemas_and_registry, include_children)
        self.when_the_domain_schema_validates_the_document()
        self.then_validation_succeeds()

    def given_a_forget_instructional_plan_document(self, schemas_and_registry, include_children):
        schemas, registry = schemas_and_registry
        self._validator = Draft202012Validator(schemas["domain.schema.json"], registry=registry)
        self._document = {
            "domain": {
                "name": "Domain",
                "plans": [{
                    "goal": {
                        "perform": {
                            "action": "procedure"
                        }
                    },
                    "content": [{
                        "forget_instructional_plan": {
                            "action": "procedure",
                            "include_children": include_children,
                        }
                    }],
                }],
            }
        }

    def when_the_domain_schema_validates_the_document(self):
        self._error = None
        try:
            self._validator.validate(self._document)
        except ValidationError as error:
            self._error = error

    def then_validation_succeeds(self):
        assert self._error is None, self._error


def test_domain_schema_accepts_boolean_conditions_and_predicate_only_forget(schemas_and_registry):
    schemas, registry = schemas_and_registry
    domain = {
        "domain": {
            "name": "Domain",
            "plans": [{
                "goal": {
                    "perform": {
                        "action": "talk_about_trip"
                    }
                },
                "content": [{
                    "if": {
                        "condition": {
                            "and": [
                                {
                                    "in_beliefs_or_commitments": {
                                        "predicate": "destination_code",
                                        "value": "gothenburg",
                                    }
                                },
                                {
                                    "not": {
                                        "in_shared_commitments": {
                                            "service_action_terminated": {
                                                "name": "BookHousing"
                                            }
                                        }
                                    }
                                },
                            ]
                        },
                        "then": [],
                    }
                }],
                "postplan": [{
                    "forget": {
                        "predicate": "destination_code"
                    }
                }],
            }],
        }
    }
    validator = Draft202012Validator(schemas["domain.schema.json"], registry=registry)

    validator.validate(domain)

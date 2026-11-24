import pytest

from tala.ddd.ddd_json_compiler import DDDJSONCompiler
from tala.ddd.ddd_xml_compiler import DDDXMLCompilerException
from tala.ddd.parser import Parser
from tala.model.ontology import Ontology


def test_compile_domain_supports_replace_goal_and_on_completion():
    scenario = given_a_json_domain_with_goal_lifecycle_items()
    when_the_domain_is_compiled(scenario)
    then_the_replacement_and_completion_hook_are_preserved(scenario)


def given_a_json_domain_with_goal_lifecycle_items():
    compiler = DDDJSONCompiler()
    ontology = Ontology(**compiler.compile_ontology({
        "ontology": {"name": "Ontology", "actions": ["collect", "review"], "predicates": []}
    }))
    parser = Parser("mock_ddd", ontology, "Domain")
    source = {
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
    return {"compiler": compiler, "ontology": ontology, "parser": parser, "source": source}


def when_the_domain_is_compiled(scenario):
    scenario["compiled"] = scenario["compiler"].compile_domain(
        "Domain", scenario["source"], scenario["ontology"], scenario["parser"]
    )


def then_the_replacement_and_completion_hook_are_preserved(scenario):
    replacement_plan = scenario["compiled"]["plans"][0]["plan"]
    completion_plan = scenario["compiled"]["plans"][1]["on_completion"]
    assert replacement_plan.top.type_ == "replace_goal"
    assert replacement_plan.top.goal.action.value == "review"
    assert [item.type_ for item in completion_plan] == ["forget_all"]


def test_compile_domain_emits_allow_binding_yn_answers_flag():
    compiler = DDDJSONCompiler()
    ontology_args = compiler.compile_ontology({
        "ontology": {
            "name": "Ontology",
            "actions": ["make_reservation"],
            "predicates": [
                {
                    "name": "yn_more_ingredients",
                    "sort": "boolean"
                },
            ],
        }
    })
    ontology = Ontology(**ontology_args)
    parser = Parser("mock_ddd", ontology, "Domain")

    domain = compiler.compile_domain(
        "Domain",
        {
            "domain": {
                "name": "Domain",
                "plans": [
                    {
                        "goal": {
                            "perform": {
                                "action": "make_reservation"
                            }
                        },
                        "content": [
                            {
                                "bind": {
                                    "question": {
                                        "yn": {
                                            "predicate": "yn_more_ingredients",
                                        },
                                    },
                                    "allow_binding_yn_answers": True,
                                }
                            },
                        ],
                    },
                ],
            }
        },
        ontology,
        parser,
    )

    plan = domain["plans"][0]["plan"]
    item = plan.top

    assert item.allow_binding_yn_answers is True
    assert item.question.is_yes_no_question()


@pytest.mark.parametrize("item_type", ["forget", "forget_shared"])
def test_compile_domain_supports_forgetting_an_action_status(item_type):
    compiler = DDDJSONCompiler()
    ontology_args = compiler.compile_ontology({
        "ontology": {
            "name": "Ontology",
            "actions": ["turn_on_power"],
            "predicates": [],
        }
    })
    ontology = Ontology(**ontology_args)
    parser = Parser("mock_ddd", ontology, "Domain")

    domain = compiler.compile_domain(
        "Domain",
        {
            "domain": {
                "name": "Domain",
                "plans": [{
                    "goal": {"perform": {"action": "turn_on_power"}},
                    "content": [{
                        item_type: {"action_status": {"action": "turn_on_power", "status": "done"}}
                    }],
                }],
            }
        },
        ontology,
        parser,
    )

    assert str(domain["plans"][0]["plan"].top) == f"{item_type}(action_status(turn_on_power, done))"


def test_compile_domain_rejects_allow_binding_yn_answers_for_non_yn_question():
    compiler = DDDJSONCompiler()
    ontology_args = compiler.compile_ontology({
        "ontology": {
            "name": "Ontology",
            "actions": ["make_reservation"],
            "predicates": [
                {
                    "name": "price",
                    "sort": "real"
                },
            ],
        }
    })
    ontology = Ontology(**ontology_args)
    parser = Parser("mock_ddd", ontology, "Domain")

    with pytest.raises(DDDXMLCompilerException, match="allow_binding_yn_answers"):
        compiler.compile_domain(
            "Domain",
            {
                "domain": {
                    "name": "Domain",
                    "plans": [
                        {
                            "goal": {
                                "perform": {
                                    "action": "make_reservation"
                                }
                            },
                            "content": [
                                {
                                    "bind": {
                                        "question": {
                                            "wh": {
                                                "predicate": "price",
                                            },
                                        },
                                        "allow_binding_yn_answers": True,
                                    }
                                },
                            ],
                        },
                    ],
                }
            },
            ontology,
            parser,
        )


def test_compile_domain_supports_kpq_question():
    compiler = DDDJSONCompiler()
    ontology_args = compiler.compile_ontology({
        "ontology": {
            "name": "Ontology",
            "actions": ["talk_about_trip"],
            "predicates": [
                {
                    "name": "destination_code",
                    "sort": "string"
                },
            ],
        }
    })
    ontology = Ontology(**ontology_args)
    parser = Parser("mock_ddd", ontology, "Domain")

    domain = compiler.compile_domain(
        "Domain",
        {
            "domain": {
                "name": "Domain",
                "plans": [
                    {
                        "goal": {
                            "perform": {
                                "action": "talk_about_trip"
                            }
                        },
                        "content": [
                            {
                                "findout": {
                                    "question": {
                                        "kpq": {
                                            "question": {
                                                "wh": {
                                                    "predicate": "destination_code",
                                                },
                                            },
                                        },
                                    },
                                },
                            },
                        ],
                    },
                ],
            }
        },
        ontology,
        parser,
    )

    plan = domain["plans"][0]["plan"]
    item = plan.top

    assert item.question.is_knowledge_precondition_question()
    assert item.question.content.is_wh_question()

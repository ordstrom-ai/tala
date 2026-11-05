import unittest

from tala import model

from tala.model.plan import Plan, UnableToDetermineOntologyException
from tala.model.plan_item import IfThenElse, Findout, Raise, AssumeShared
from tala.model.semantic_object import OntologySpecificSemanticObject
from tala.testing.lib_test_case import LibTestCase
from tala.testing.json_api_assertions import normalize_expected_json_api
from tala.utils.json_api import IncludedObject


class PlanTests(LibTestCase):
    def setUp(self):
        self.setUpLibTestCase()
        self.maxDiff = None
        self.findout_price = Findout(self.domain_name, self.price_question)
        self.findout_dest_city = Findout(self.domain_name, self.dest_city_question)
        self.raise_price = Raise(self.domain_name, self.price_question)
        self.raise_dest_city = Raise(self.domain_name, self.dest_city_question)
        self.consequent = [self.raise_price]
        self.alternative = [self.raise_dest_city]
        self.if_then_else_item = IfThenElse("mockup_condition", self.consequent, self.alternative)
        self.assume_shared = AssumeShared(self.proposition_dept_city_london)

    def test_plan_iteration_steps_into_nested_blocks(self):
        self._given_plan_with_nested_item()
        expected_list = [self.findout_price, self.findout_dest_city, self.consequent[0], self.alternative[0]]
        self.assertEqual(expected_list, list(self.plan))

    def _given_plan_with_nested_item(self):
        self.plan = Plan([self.if_then_else_item, self.findout_dest_city, self.findout_price])

    def test_plan_iteration_after_modification(self):
        plan = Plan()
        plan.push(self.findout_price)
        expected_list = [self.findout_price]
        self.assertEqual(expected_list, list(plan))

    def test_removal_of_findout_from_nested_block(self):
        self._given_plan_with_nested_item()
        self._when_consequent_is_removed()
        self._then_all_elements_but_consequent_are_left()

    def _when_consequent_is_removed(self):
        self.plan.remove(self.consequent[0])

    def _then_all_elements_but_consequent_are_left(self):
        expected_list = [self.findout_price, self.findout_dest_city, self.alternative[0]]
        self.assertEqual(expected_list, list(self.plan))

    def test_removal_of_plan_item_from_deeply_nested_block(self):
        self._given_plan_with_deeply_nested_item()
        self._when_consequent_is_removed()
        self._then_plan_contains([self.findout_price, self.findout_dest_city, self.alternative[0]])

    def _given_plan_with_deeply_nested_item(self):
        self.nested_if_then_else = IfThenElse("outer_condition", [self.if_then_else_item], [])
        self.plan = Plan([self.raise_dest_city, self.findout_dest_city, self.findout_price])

    def _then_plan_contains(self, expected_list):
        self.assertEqual(expected_list, list(self.plan))

    def test_plan_iteration_steps_into_very_deeply_nested_blocks(self):
        self.maxDiff = None
        self._given_plan_with_very_deeply_nested_item()
        expected_list = [
            self.findout_price,
            self.findout_dest_city,
            self.raise_price,
            self.raise_dest_city,
            self.findout_dest_city,
        ]
        self.assertEqual(expected_list, list(self.plan))

    def _given_plan_with_very_deeply_nested_item(self):
        self.nested_if_then_else = IfThenElse("outer_condition", [self.if_then_else_item], [self.findout_dest_city])
        self.doubly_nested_if_then_else = IfThenElse(
            "outer_condition", [self.nested_if_then_else], [self.findout_price]
        )
        self.plan = Plan([self.nested_if_then_else, self.findout_dest_city, self.findout_price])

    def test_plan_as_json_api_base_case(self):
        self.given_plan([self.findout_price])
        self.when_plan_as_json_api()
        self.then_plan_as_json_api_is({
            'data': {
                'attributes': {
                    'accommodate_without_feedback': [],
                    'alternatives_predicate': [],
                    'max_answers': [],
                    'ontology_name': 'mock_ontology',
                    'reraise_on_resume': [],
                    'restart_on_completion': [],
                    'unrestricted_accommodation': [],
                    'version:id': '2'
                },
                'id': 'mock_ontology:PERFORM_GOAL:mock_action',
                'relationships': {
                    'goal': {
                        'data': {
                            'id': 'PERFORM_GOAL.SYS:mock_action',
                            'type': 'tala.model.goal.Perform'
                        }
                    },
                    'plan_content': {
                        'data': [{
                            'id': 'tala.model.plan_item.Findout:mockup_domain:mockup_ontology:WHQ:X.price(X):False',
                            'type': 'tala.model.plan_item.Findout'
                        }]
                    }
                },
                'type': 'tala.model.plan',
                'version:id': '2'
            },
            'included': [{
                'attributes': {
                    'name': 'mock_action',
                    'ontology_name': 'mock_ontology'
                },
                'id': 'mock_ontology:mock_action',
                'type': 'tala.model.action'
            }, {
                'attributes': {
                    'target': 'SYS',
                    'type_': 'PERFORM_GOAL'
                },
                'id': 'PERFORM_GOAL.SYS:mock_action',
                'relationships': {
                    'content': {
                        'data': {
                            'id': 'mock_ontology:mock_action',
                            'type': 'tala.model.action'
                        }
                    }
                },
                'type': 'tala.model.goal.Perform',
                'version:id': '2'
            }, {
                'attributes': {},
                'id': 'real',
                'relationships': {},
                'type': 'tala.model.sort.RealSort',
                'version:id': '2'
            }, {
                'attributes': {
                    '_multiple_instances': False,
                    'feature_of_name': None,
                    'name': 'price',
                    'ontology_name': 'mockup_ontology'
                },
                'id': 'mockup_ontology:price',
                'relationships': {
                    'sort': {
                        'data': {
                            'id': 'real',
                            'type': 'tala.model.sort.RealSort'
                        }
                    }
                },
                'type': 'tala.model.predicate.Predicate',
                'version:id': '2'
            }, {
                'attributes': {
                    'ontology_name': 'mockup_ontology'
                },
                'id': 'X.price(X)',
                'relationships': {
                    'predicate': {
                        'data': {
                            'id': 'mockup_ontology:price',
                            'type': 'tala.model.predicate.Predicate'
                        }
                    }
                },
                'type': 'tala.model.lambda_abstraction.LambdaAbstractedPredicateProposition',
                'version:id': '2'
            }, {
                'attributes': {
                    'ontology_name': 'mockup_ontology',
                    'type_': 'WHQ'
                },
                'id': 'mockup_ontology:WHQ:X.price(X)',
                'relationships': {
                    'content': {
                        'data': {
                            'id': 'X.price(X)',
                            'type': 'tala.model.lambda_abstraction.LambdaAbstractedPredicateProposition'
                        }
                    }
                },
                'type': 'tala.model.question.WhQuestion',
                'version:id': '2'
            }, {
                'attributes': {
                    'allow_answer_from_pcom': False,
                    'domain_name': 'mockup_domain',
                    'type_': 'findout'
                },
                'id': 'tala.model.plan_item.Findout:mockup_domain:mockup_ontology:WHQ:X.price(X):False',
                'relationships': {
                    'question': {
                        'data': {
                            'id': 'mockup_ontology:WHQ:X.price(X)',
                            'type': 'tala.model.question.WhQuestion'
                        }
                    }
                },
                'type': 'tala.model.plan_item.Findout',
                'version:id': '2'
            }]
        })

    def given_plan(self, plan_item_list):
        self._plan = Plan(plan_item_list)

    def when_plan_as_json_api(self):
        goal = model.goal.Perform(model.action.Action("mock_action", "mock_ontology"))

        self._plan_as_json_api = self._plan.as_json_api_dict(goal, [], [], [], [], [], [], [], [], [], [])

    def then_plan_as_json_api_is(self, result):
        expected = normalize_expected_json_api(result)
        self.assertEqual(expected, self._plan_as_json_api)

    def test_plan_as_json_api_more_items(self):
        self.given_plan([self.findout_price, self.raise_dest_city])
        self.when_plan_as_json_api()
        self.then_plan_as_json_api_is({
            'data': {
                'attributes': {
                    'accommodate_without_feedback': [],
                    'alternatives_predicate': [],
                    'max_answers': [],
                    'ontology_name': 'mock_ontology',
                    'reraise_on_resume': [],
                    'restart_on_completion': [],
                    'unrestricted_accommodation': [],
                    'version:id': '2'
                },
                'id': 'mock_ontology:PERFORM_GOAL:mock_action',
                'relationships': {
                    'goal': {
                        'data': {
                            'id': 'PERFORM_GOAL.SYS:mock_action',
                            'type': 'tala.model.goal.Perform'
                        }
                    },
                    'plan_content': {
                        'data': [{
                            'id': 'tala.model.plan_item.Findout:mockup_domain:mockup_ontology:WHQ:X.price(X):False',
                            'type': 'tala.model.plan_item.Findout'
                        }, {
                            'id': 'tala.model.plan_item.Raise:mockup_domain:mockup_ontology:WHQ:X.dest_city(X):False',
                            'type': 'tala.model.plan_item.Raise'
                        }]
                    }
                },
                'type': 'tala.model.plan',
                'version:id': '2'
            },
            'included': [{
                'attributes': {
                    'name': 'mock_action',
                    'ontology_name': 'mock_ontology'
                },
                'id': 'mock_ontology:mock_action',
                'type': 'tala.model.action'
            }, {
                'attributes': {
                    'target': 'SYS',
                    'type_': 'PERFORM_GOAL'
                },
                'id': 'PERFORM_GOAL.SYS:mock_action',
                'relationships': {
                    'content': {
                        'data': {
                            'id': 'mock_ontology:mock_action',
                            'type': 'tala.model.action'
                        }
                    }
                },
                'type': 'tala.model.goal.Perform',
                'version:id': '2'
            }, {
                'attributes': {},
                'id': 'real',
                'relationships': {},
                'type': 'tala.model.sort.RealSort',
                'version:id': '2'
            }, {
                'attributes': {
                    '_multiple_instances': False,
                    'feature_of_name': None,
                    'name': 'price',
                    'ontology_name': 'mockup_ontology'
                },
                'id': 'mockup_ontology:price',
                'relationships': {
                    'sort': {
                        'data': {
                            'id': 'real',
                            'type': 'tala.model.sort.RealSort'
                        }
                    }
                },
                'type': 'tala.model.predicate.Predicate',
                'version:id': '2'
            }, {
                'attributes': {
                    '_multiple_instances': False,
                    'feature_of_name': None,
                    'name': 'dest_city',
                    'ontology_name': 'mockup_ontology'
                },
                'id': 'mockup_ontology:dest_city',
                'relationships': {
                    'sort': {
                        'data': {
                            'id': 'mockup_ontology:city',
                            'type': 'tala.model.sort.CustomSort'
                        }
                    }
                },
                'type': 'tala.model.predicate.Predicate',
                'version:id': '2'
            }, {
                'attributes': {
                    'ontology_name': 'mockup_ontology'
                },
                'id': 'X.price(X)',
                'relationships': {
                    'predicate': {
                        'data': {
                            'id': 'mockup_ontology:price',
                            'type': 'tala.model.predicate.Predicate'
                        }
                    }
                },
                'type': 'tala.model.lambda_abstraction.LambdaAbstractedPredicateProposition',
                'version:id': '2'
            }, {
                'attributes': {
                    'ontology_name': 'mockup_ontology'
                },
                'id': 'X.dest_city(X)',
                'relationships': {
                    'predicate': {
                        'data': {
                            'id': 'mockup_ontology:dest_city',
                            'type': 'tala.model.predicate.Predicate'
                        }
                    }
                },
                'type': 'tala.model.lambda_abstraction.LambdaAbstractedPredicateProposition',
                'version:id': '2'
            }, {
                'attributes': {
                    'ontology_name': 'mockup_ontology',
                    'type_': 'WHQ'
                },
                'id': 'mockup_ontology:WHQ:X.price(X)',
                'relationships': {
                    'content': {
                        'data': {
                            'id': 'X.price(X)',
                            'type': 'tala.model.lambda_abstraction.LambdaAbstractedPredicateProposition'
                        }
                    }
                },
                'type': 'tala.model.question.WhQuestion',
                'version:id': '2'
            }, {
                'attributes': {
                    'ontology_name': 'mockup_ontology',
                    'type_': 'WHQ'
                },
                'id': 'mockup_ontology:WHQ:X.dest_city(X)',
                'relationships': {
                    'content': {
                        'data': {
                            'id': 'X.dest_city(X)',
                            'type': 'tala.model.lambda_abstraction.LambdaAbstractedPredicateProposition'
                        }
                    }
                },
                'type': 'tala.model.question.WhQuestion',
                'version:id': '2'
            }, {
                'attributes': {
                    'allow_answer_from_pcom': False,
                    'domain_name': 'mockup_domain',
                    'type_': 'findout'
                },
                'id': 'tala.model.plan_item.Findout:mockup_domain:mockup_ontology:WHQ:X.price(X):False',
                'relationships': {
                    'question': {
                        'data': {
                            'id': 'mockup_ontology:WHQ:X.price(X)',
                            'type': 'tala.model.question.WhQuestion'
                        }
                    }
                },
                'type': 'tala.model.plan_item.Findout',
                'version:id': '2'
            }, {
                'attributes': {
                    'dynamic': True,
                    'name': 'city',
                    'ontology_name': 'mockup_ontology'
                },
                'id': 'mockup_ontology:city',
                'relationships': {},
                'type': 'tala.model.sort.CustomSort',
                'version:id': '2'
            }, {
                'attributes': {
                    'allow_answer_from_pcom': False,
                    'domain_name': 'mockup_domain',
                    'type_': 'raise'
                },
                'id': 'tala.model.plan_item.Raise:mockup_domain:mockup_ontology:WHQ:X.dest_city(X):False',
                'relationships': {
                    'question': {
                        'data': {
                            'id': 'mockup_ontology:WHQ:X.dest_city(X)',
                            'type': 'tala.model.question.WhQuestion'
                        }
                    }
                },
                'type': 'tala.model.plan_item.Raise',
                'version:id': '2'
            }]
        })

    def test_plan_created_from_plan_as_json_api(self):
        self.given_plan([self.assume_shared, self.findout_price, self.findout_dest_city])
        self.given_plan_as_json_api()
        self.given_plan_created_from_json_api()
        self.then_created_plan_contains_same_elements_as_old_plan()

    def given_plan_as_json_api(self):
        goal = model.goal.Perform(model.action.Action("mock_action", "mock_ontology"))

        self._plan_as_json_api = self._plan.as_json_api_dict(goal, [], [], [], [], 0, [], [], [], [], [])

    def given_plan_created_from_json_api(self):
        self._plan_from_json_api = Plan.create_from_json_api_data(
            self._plan_as_json_api["data"], IncludedObject(self._plan_as_json_api["included"])
        )[1]

    def then_created_plan_contains_same_elements_as_old_plan(self):
        for original, created in zip(self._plan.iter_stack(), self._plan_from_json_api.iter_stack()):
            self.assertEqual(original, created)


class SemanticObjectPlanTests(unittest.TestCase):
    def setUp(self):
        self._semantic_objects = set()

    def test_ontology_name_with_ontology_specific_semantic_object(self):
        self._given_semantic_object_of_ontology("an ontology")
        self._given_plan()
        self._when_asking_for_ontology_name()
        self._then_ontology_name_is("an ontology")

    def _given_semantic_object_of_ontology(self, ontology):
        semantic_object = OntologySpecificSemanticObject(ontology)
        self._semantic_objects.add(semantic_object)

    def _given_plan(self):
        self._plan = Plan(self._semantic_objects)

    def _when_asking_for_ontology_name(self):
        self._result = self._plan.ontology_name

    def _then_ontology_name_is(self, expected_name):
        actual_name = self._result
        self.assertEqual(expected_name, actual_name)

    def test_ontology_name_with_multiple_ontology_specific_semantic_objects(self):
        self._given_semantic_object_of_ontology("an ontology")
        self._given_semantic_object_of_ontology("another ontology")
        self._given_plan()
        self._when_asking_for_ontology_name_then_exception_is_raised()

    def _when_asking_for_ontology_name_then_exception_is_raised(self):
        with self.assertRaises(UnableToDetermineOntologyException):
            self._result = self._plan.ontology_name

    def test_ontology_name_with_multiple_ontology_specific_semantic_objects_of_same_ontology(self):
        self._given_semantic_object_of_ontology("an ontology")
        self._given_semantic_object_of_ontology("an ontology")
        self._given_plan()
        self._when_asking_for_ontology_name()
        self._then_ontology_name_is("an ontology")

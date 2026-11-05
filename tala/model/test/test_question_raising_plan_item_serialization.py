import json

import pytest

from tala.model.lambda_abstraction import LambdaAbstractedGoalProposition
from tala.model.plan import Plan
from tala.model.plan_item import Findout, PlanItem, Raise
from tala.model.question import WhQuestion
from tala.utils.json_api import IncludedObject, JSONAPIObject


class TestQuestionRaisingPlanItemSerialization:
    @pytest.mark.parametrize("item_type", [Findout, Raise], ids=["findout", "raise"])
    @pytest.mark.parametrize(
        "domains",
        [("CoverDomain", "SurgicalDomain"), ("SurgicalDomain", "CoverDomain")],
        ids=["cover-first", "surgical-first"],
    )
    def test_roundtrip_preserves_domain(self, item_type, domains):
        self.given_plans_asking_the_same_question(item_type, domains)
        self.when_roundtripping_plans()
        self.then_each_plan_retains_its_domain()
        self.then_question_remains_domain_independent()

    @pytest.mark.parametrize("allow_answer_from_pcom", [False, True])
    def test_findout_with_alternatives_preserves_domain(self, allow_answer_from_pcom):
        self.given_plans_asking_the_same_question(
            Findout,
            ("CoverDomain", "SurgicalDomain"),
            allow_answer_from_pcom=allow_answer_from_pcom,
            alts_predicate="available_goals",
        )
        self.when_roundtripping_plans()
        self.then_each_plan_retains_its_domain()
        for item in self._restored_items:
            assert item.allow_answer_from_pcom == allow_answer_from_pcom
            assert item.alts_predicate == "available_goals"

    @pytest.mark.parametrize("item_type", [Findout, Raise], ids=["findout", "raise"])
    def test_same_domain_and_question_have_stable_resource_identity(self, item_type):
        self.given_plans_asking_the_same_question(item_type, ("SurgicalDomain", "SurgicalDomain"))
        assert self._items[0].json_api_id == self._items[1].json_api_id

    @pytest.mark.parametrize("item_type", [Findout, Raise], ids=["findout", "raise"])
    def test_legacy_resource_id_remains_readable(self, item_type):
        self.given_plans_asking_the_same_question(item_type, ("SurgicalDomain", ))
        item = self._items[0]
        document = item.as_json_api_dict()
        document["data"]["id"] = f"{item.json_api_type}:{item.question.json_api_id}:{item.allow_answer_from_pcom}"
        document = json.loads(json.dumps(document))
        restored = PlanItem.create_from_json_api_data(document["data"], IncludedObject(document["included"]))
        assert restored.domain_name == "SurgicalDomain"
        assert restored.question == self._question

    def given_plans_asking_the_same_question(self, item_type, domains, **kwargs):
        self._question = WhQuestion(LambdaAbstractedGoalProposition())
        self._domains = domains
        self._items = [item_type(domain, self._question, **kwargs) for domain in domains]

    def when_roundtripping_plans(self):
        root = JSONAPIObject("test.domain_plans", "domain-plans")
        for index, item in enumerate(self._items):
            root.add_relationship(f"plan_{index}", Plan([item]).as_json_api_dict())
        document = json.loads(json.dumps(root.as_dict))
        included = IncludedObject(document["included"])
        self._restored_items = []
        for index in range(len(self._items)):
            plan_data = included.get_data_for_relationship(f"plan_{index}", document["data"])
            restored_plan = Plan.create_from_json_api_data(plan_data, included)
            self._restored_items.append(restored_plan.top)

    def then_each_plan_retains_its_domain(self):
        assert tuple(item.domain_name for item in self._restored_items) == self._domains

    def then_question_remains_domain_independent(self):
        for item in self._restored_items:
            assert item.question == self._question
            assert item.question.json_api_id == self._question.json_api_id
            assert not item.question.is_ontology_specific()

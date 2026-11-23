import pytest

from tala.ddd.ddd_json_compiler import DDDJSONCompiler
from tala.ddd.ddd_xml_compiler import DDDXMLCompiler
from tala.ddd.json_parser import NonCheckingJSONParser
from tala.ddd.parser import ParseError, Parser
from tala.model.action import Action
from tala.model import plan_item
from tala.model.ontology import Ontology
from tala.model.plan import Plan
from tala.utils.json_api import IncludedObject


class TestForgetInstructionalPlanCompilation:
    @pytest.mark.parametrize("include_children", [True, False])
    def test_json_api_round_trip_preserves_child_scope(self, include_children):
        self.given_a_forget_instructional_plan(include_children)
        self.when_json_api_round_trip_restores_the_plan_item()
        self.then_the_restored_plan_item_preserves_child_scope(include_children)

    def given_a_forget_instructional_plan(self, include_children):
        self.given_a_forget_plan_action_in_the_ontology()
        self._expected_item = plan_item.ForgetInstructionalPlan(
            Action("procedure", self._ontology.name), include_children
        )

    def when_json_api_round_trip_restores_the_plan_item(self):
        self._serialized_item = self._expected_item.as_json_api_dict()
        self._round_tripped_item = plan_item.ForgetInstructionalPlan.create_from_json_api_data(
            self._serialized_item["data"], IncludedObject(self._serialized_item["included"])
        )

    def when_the_tis_json_parser_restores_the_plan_item(self):
        self._round_tripped_item = NonCheckingJSONParser().parse(self._expected_item.as_json())

    def then_the_restored_plan_item_preserves_child_scope(self, include_children):
        assert self._round_tripped_item == self._expected_item
        assert self._round_tripped_item.include_children is include_children

    @pytest.mark.parametrize("include_children", [True, False])
    def test_tis_json_parser_preserves_child_scope(self, include_children):
        self.given_a_forget_instructional_plan(include_children)
        self.when_the_tis_json_parser_restores_the_plan_item()
        self.then_the_restored_plan_item_preserves_child_scope(include_children)

    def given_a_forget_plan_action_in_the_ontology(self):
        ontology_data = DDDXMLCompiler().compile_ontology(
            '<ontology name="PlanForgetOntology">'
            '<action name="top"/><action name="procedure"/>'
            '</ontology>'
        )
        self._ontology = Ontology(**ontology_data)
        self._parser = Parser("plan_forget_test", self._ontology, "Domain")

    def when_xml_compiler_compiles_forget_instructional_plan(self, include_children):
        xml = f'''
<domain name="Domain">
  <goal type="perform" action="top">
    <plan>
      <forget_instructional_plan action="procedure" include_children="{str(include_children).lower()}"/>
    </plan>
  </goal>
</domain>'''
        self._compiled_domain = DDDXMLCompiler().compile_domain("plan_forget_test", xml, self._ontology, self._parser)

    @pytest.mark.parametrize("include_children", [True, False])
    def test_xml_compiler_preserves_child_scope(self, include_children):
        self.given_a_forget_instructional_plan(include_children)
        self.when_xml_compiler_compiles_forget_instructional_plan(include_children)
        self.then_compiled_plan_item_matches_the_requested_scope(include_children)

    def then_compiled_plan_item_matches_the_requested_scope(self, include_children):
        expected_item = plan_item.ForgetInstructionalPlan(Action("procedure", self._ontology.name), include_children)
        actual_plan = self._compiled_domain["plans"][0]["plan"]
        assert actual_plan == Plan([expected_item])

    @pytest.mark.parametrize("include_children", [True, False])
    def test_expression_parser_preserves_child_scope(self, include_children):
        self.given_a_forget_instructional_plan(include_children)
        self.when_expression_parser_parses_forget_instructional_plan(include_children)
        self.then_parsed_plan_item_matches_the_requested_scope(include_children)

    def when_expression_parser_parses_forget_instructional_plan(self, include_children):
        value = str(include_children).lower()
        self._parsed_item = self._parser.parse(f"forget_instructional_plan(procedure,{{include_children={value}}})")

    def then_parsed_plan_item_matches_the_requested_scope(self, include_children):
        expected_item = plan_item.ForgetInstructionalPlan(Action("procedure", self._ontology.name), include_children)
        assert self._parsed_item == expected_item

    def test_expression_parser_requires_explicit_child_scope(self):
        self.given_a_forget_instructional_plan(include_children=True)
        self.when_expression_parser_parses_without_child_scope()
        self.then_expression_parser_rejects_missing_child_scope()

    def when_expression_parser_parses_without_child_scope(self):
        self._parse_error = None
        try:
            self._parser.parse("forget_instructional_plan(procedure)")
        except ParseError as error:
            self._parse_error = error

    def then_expression_parser_rejects_missing_child_scope(self):
        assert self._parse_error is not None

    @pytest.mark.parametrize("include_children", [True, False])
    def test_json_compiler_preserves_child_scope(self, include_children):
        self.given_a_forget_instructional_plan(include_children)
        self.when_json_compiler_compiles_forget_instructional_plan(include_children)
        self.then_compiled_plan_item_matches_the_requested_scope(include_children)

    def when_json_compiler_compiles_forget_instructional_plan(self, include_children):
        domain_data = {
            "domain": {
                "name": "Domain",
                "plans": [{
                    "goal": {
                        "perform": {
                            "action": "top"
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
        self._compiled_domain = DDDJSONCompiler().compile_domain("Domain", domain_data, self._ontology, self._parser)

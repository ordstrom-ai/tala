import copy

from tala.model.move_base import (
    Answer,
    Ask,
    Greet,
    Insult,
    InsultResponse,
    Mute,
    Move,
    Prereport,
    Quit,
    Report,
    Request,
    ThankYou,
    ThankYouResponse,
    Unmute,
)
from tala.model.move_icm import ICM
from tala.model import plan_item
from tala.model import ontology
from tala.model.domain import Domain
from tala.model import condition
from tala.model.hint import Hint
from tala.model.action import Action
from tala.model.ask_feature import AskFeature
from tala.model.plan import Plan
from tala.model import sort
from tala.model.sort import Sort, CustomSort
from tala.model.predicate import Predicate
from tala.model.individual import No, Yes, Individual, NegativeIndividual
from tala.model.question import (
    Question, WhQuestion, YesNoQuestion, ConsequentQuestion, AltQuestion, KnowledgePreconditionQuestion
)
from tala.model.lambda_abstraction import (
    LambdaAbstractedProposition, LambdaAbstractedImplicationPropositionForConsequent, LambdaAbstractedGoalProposition,
    LambdaAbstractedPredicateProposition
)
from tala.model.proposition import (
    Proposition, GoalProposition, PropositionSet, PredicateProposition, ResolvednessProposition, PrereportProposition,
    ImplicationProposition, UnderstandingProposition, KnowledgePreconditionProposition, PreconfirmationProposition,
    RejectedPropositions, ServiceResultProposition, ActionStatusProposition, ServiceActionStartedProposition,
    ServiceActionTerminatedProposition, NumberOfAlternativesProposition, QuestionStatusProposition, MuteProposition,
    UnmuteProposition, QuitProposition, PredictedProposition
)
from tala.model.polarity import Polarity
from tala.model.goal import PerformGoal, ResolveGoal, PERFORM, RESOLVE
from tala.model.set import Set
from tala.model.openqueue import OpenQueue
from tala.model.date_time import DateTime
from tala.model.person_name import PersonName
from tala.model.service_action_outcome import SuccessfulServiceAction, FailedServiceAction
from tala.model.action_status import ActionStatus, Aborted, Done
from tala.model.ddd import DDD
from tala.model.query import create_query_from_dict
from tala.ddd.services import service_interface
from tala.ddd.services.service_interface import ServiceInterface, ServiceActionInterface


class JSONParseFailure(Exception):
    pass


def preprocess_json_dict(json_dict_original):
    json_dict = copy.copy(json_dict_original)
    key_aliases = {
        "_value": "value",
        "_name": "name",
        "_sort": "sort",
        "_feature_of_name": "feature_of_name",
        "_ontology_name": "ontology_name",
        "_service_action": "service_action",
        "_arguments": "arguments",
        "_result": "result",
        "_rejected_combination": "rejected_combination",
        "_reason_for_rejection": "reason_for_rejection",
        "_argument_set": "argument_set",
        "_issue": "issue",
        "_multiple_instances": "multiple_instances",
    }
    for source_key, target_key in key_aliases.items():
        if source_key in json_dict and target_key not in json_dict:
            json_dict[target_key] = json_dict[source_key]
    for float_key in ["perception_confidence", "understanding_confidence"]:
        if float_key in json_dict:
            try:
                json_dict[float_key] = float(json_dict[float_key])
            except TypeError:
                pass
    return json_dict


def create_sort(definition):
    sort_name = definition.get("_name", definition.get("name"))
    if sort_name in sort.BUILTIN_SORTS:
        if sort_name == sort.DATETIME:
            return sort.DateTimeSort()
        if sort_name == sort.REAL:
            return sort.RealSort()
        if sort_name == sort.PERSON_NAME:
            return sort.PersonNameSort()
        if sort_name == sort.INTEGER:
            return sort.IntegerSort()
        if sort_name == sort.BOOLEAN:
            return sort.BooleanSort()
        if sort_name == sort.STRING:
            return sort.StringSort()
        if sort_name == sort.DOMAIN:
            return sort.DomainSort()
        if sort_name == sort.IMAGE:
            return sort.ImageSort()
        if sort_name == sort.WEBVIEW:
            return sort.WebviewSort()

    ontology_name = definition.get("_ontology_name", definition.get("ontology_name"))
    if ontology_name:
        return CustomSort(
            ontology_name, definition.get("_name", definition.get("name")),
            definition.get("_dynamic", definition.get("dynamic"))
        )
    return Sort(definition.get("_name", definition.get("name")), definition.get("_dynamic", definition.get("dynamic")))


def create_predicate(name, definition):
    sort_definition = definition.get("sort", definition.get("_sort"))
    feature_of_name = definition.get("feature_of_name", definition.get("_feature_of_name"))
    multiple_instances = definition.get("multiple_instances", definition.get("_multiple_instances"))
    ontology_name = definition.get("_ontology_name", definition.get("ontology_name"))
    return Predicate(ontology_name, name, create_sort(sort_definition), feature_of_name, multiple_instances)


def create_individual(individual, sort):
    def extract(string, prefix, suffix):
        if value.startswith(prefix) and value.endswith(suffix):
            return value[len(prefix):len(value) - len(suffix)]

    def extract_datetime_value():
        return extract(value, "datetime(", ")")

    def extract_person_name_value():
        return extract(value, "person_name(", ")")

    sort = create_sort(sort)
    value = individual
    if sort.is_datetime_sort():
        value = DateTime(extract_datetime_value())
    if sort.is_real_sort():
        value = float(value)
    if sort.is_person_name_sort():
        value = PersonName(extract_person_name_value())
    if sort.is_integer_sort():
        value = int(value)
    return (value, sort)


class JSONOntologyParser():
    def parse_ontology(self, ontology_as_json):
        if ontology_as_json["semantic_object_type"] == ontology.SEMANTIC_OBJECT_TYPE:
            name = ontology_as_json["_name"]
            sorts = self.parse_ontology_sorts(ontology_as_json["_sorts"])
            predicates = self.parse_ontology_predicates(ontology_as_json["_predicates"])
            individuals = self.parse_ontology_individuals(ontology_as_json["_individuals"])
            actions = self.parse_ontology_actions(ontology_as_json["_actions"], name)
            return ontology.Ontology(name, sorts, predicates, individuals, actions)
        raise JSONParseFailure(f"Failed to parse {ontology_as_json} as an ontology.")

    def parse_ontology_sorts(self, sorts_as_json):
        return set([create_sort(sort) for sort in sorts_as_json])

    def parse_ontology_predicates(self, predicates_as_json):
        return set([create_predicate(name, predicates_as_json[name]) for name in predicates_as_json])

    def parse_ontology_individuals(self, individuals_as_json):
        individuals = {}
        for individual_as_json in individuals_as_json:
            (value, sort) = create_individual(individual_as_json, individuals_as_json[individual_as_json])
            individuals[value] = sort
        return individuals

    def parse_ontology_actions(self, actions_as_json, ontology_name):
        return [action for action in actions_as_json["set"]]


class JSONDDDParser():
    def parse(self, ddd_as_json):
        name = ddd_as_json.get("ddd_name", ddd_as_json.get("_ddd_name"))
        ontology_parser = JSONOntologyParser()
        ontology = ontology_parser.parse_ontology(ddd_as_json.get("ontology", ddd_as_json.get("_ontology")))
        domain_parser = JSONDomainParser(ontology)
        domain = domain_parser.parse(ddd_as_json.get("domain", ddd_as_json.get("_domain")))
        service_interface_parser = JSONServiceInterfaceParser()
        service_interface = service_interface_parser.parse(
            ddd_as_json.get("service_interface", ddd_as_json.get("_service_interface"))
        )
        return DDD(name, ontology, domain, service_interface)


class JSONDomainParser():
    def __init__(self, ontology=None):
        self.ontology = ontology
        self.parser = NonCheckingJSONParser()

    def parse(self, json_dict):
        ddd_name = json_dict.get("ddd_name", json_dict.get("_ddd_name"))
        domain_name = json_dict.get("name", json_dict.get("_name"))
        if self.ontology:
            self.parser = CheckingJSONParser(ddd_name, self.ontology, domain_name)
        default_questions = self.parse_default_questions(
            json_dict.get("default_questions", json_dict.get("_default_questions"))
        )
        parameters = self.parse_parameters(json_dict.get("parameters", json_dict.get("_parameters")))
        plans = self.parse_plans(json_dict.get("plans", json_dict.get("_plans")))
        validators = self.parse_validators(json_dict.get("validators", json_dict.get("_validators")))
        dependencies = self.parse_serialized_dict(json_dict.get("dependencies", json_dict.get("_dependencies", {})))
        queries = self.parse_serialized_query_list(json_dict.get("queries", json_dict.get("_queries")))
        return Domain(
            ddd_name, domain_name, self.ontology, plans, default_questions, parameters, validators, dependencies,
            queries
        )

    def parse_default_questions(self, default_questions):
        return [self._parse_default_question(question) for question in default_questions]

    def _parse_default_question(self, question):
        return self.parser.parse(question)

    def parse_parameters(self, parameters):
        compiled_parameters = {}
        for pair in parameters:
            key_question = self.parser.parse(pair["key"])
            values = pair["value"]
            compiled_parameters[key_question] = self._parse_parameters_for_entry(values)
        return compiled_parameters

    def _parse_parameters_for_entry(self, parameters):
        return {name: self._parse_parameter(parameters, name) for name in parameters}

    def _parse_parameter(self, parameters, name):
        def is_questions_parameter():
            return name in ["related_information"]

        def is_question_parameter():
            return name in ["service_query", "default"]

        def is_int_parameter():
            return name in ["max_spoken_alts", "max_reported_hit_count"]

        def is_boolean_parameter():
            return name in ["always_ground", "always_relevant"]

        if name == "ask_features":
            return [self.parse_ask_feature(feature) for feature in parameters[name]]
        if name == "hints":
            return [self.parse_hint(hint) for hint in parameters[name]]
        if name in ["allow_goal_accommodation", "verbalize", "incremental"]:
            return parameters[name]
        if name in ["on_zero_hits_action", "on_too_many_hits_action"]:
            return self.parser.parse_action(parameters[name])
        if is_int_parameter():
            return int(parameters[name])
        if name in ["source"]:
            return parameters[name]
        if name == "alts":
            return PropositionSet([self.parser.parse(proposition) for proposition in parameters[name]["_propositions"]])
        if is_questions_parameter():
            return [self.parser.parse_question(question) for question in parameters[name]]
        if is_question_parameter():
            return self.parser.parse_question(parameters[name])
        if is_boolean_parameter():
            return bool(parameters[name])

        raise JSONParseFailure("no support for parameter", name, parameters[name], ".")
        return parameters[name]

    def parse_ask_feature(self, feature):
        return AskFeature(feature["name"], feature["kpq"])

    def parse_hint(self, hint):
        return Hint([self.parser.parse_plan_item(item) for item in hint["_plan"]])

    def parse_plans(self, plans):
        def is_builtin(goal):
            return goal["_goal_type"] == "PERFORM_GOAL" and goal["_content"]["value"] in ["top", "up"]

        return [self.parse_goal(plans[goal]) for goal in plans]

    def parse_goal(self, goal):
        result = {}
        BOOLEAN_VALUES = [
            "unrestricted_accommodation", "restart_on_completion", "reraise_on_resume", "accommodate_without_feedback"
        ]
        INTEGER_VALUES = ["max_answers"]
        STRING_VALUES = ["alternatives_predicate"]
        for entry in goal:
            if entry == "goal":
                result[entry] = self.parser.parse_goal(goal[entry])
            elif entry == "plan":
                result[entry] = self.parse_plan(goal[entry])
            elif entry == "postconds":
                result[entry] = self.parse_postconds(goal[entry])
            elif entry in ["postplan", "on_completion"]:
                result[entry] = self.parse_postplan(goal[entry])
            elif entry == "preferred":
                result[entry] = self.parse_preferred(goal[entry])
            elif entry == "superactions":
                result[entry] = self.parse_superactions(goal[entry])
            elif entry in BOOLEAN_VALUES:
                result[entry] = bool(goal[entry])
            elif entry in INTEGER_VALUES:
                result[entry] = int(goal[entry])
            elif entry in STRING_VALUES:
                result[entry] = str(goal[entry])
            else:
                raise JSONParseFailure("found unknown entry in goal when parsing:", entry, goal[entry])

        return result

    def parse_plan(self, plan):
        plan_items = [self.parser.parse_plan_item(item) for item in plan["stack"]]
        return Plan(reversed(plan_items))

    def parse_postconds(self, postconds):
        return [self.parse_postcond(postcond) for postcond in postconds]

    def parse_postcond(self, postcond):
        return self.parser.parse(postcond)

    def parse_postplan(self, postplan):
        try:
            return [self.parser.parse_plan_item(item) for item in postplan["stack"]]
        except TypeError:
            return [self.parser.parse_plan_item(item) for item in postplan]

    def parse_superactions(self, actions):
        return [self.parse_superaction(action) for action in actions]

    def parse_preferred(self, preference):
        try:
            return self.parser.parse_proposition(preference)
        except TypeError:
            return preference

    def parse_superaction(self, action):
        return self.parser.parse_action(action)

    def parse_validators(self, validators):
        return [self.parse_validator(validator) for validator in validators]

    def parse_validator(self, validator):
        def parse_propositions_list(predicates):
            return [self.parser.parse(predicate) for predicate in predicates]

        id = validator["validator"]
        valid_configurations = [
            parse_propositions_list(configuration) for configuration in validator["valid_configurations"]
        ]
        return {"validator": id, "valid_configurations": valid_configurations}

    def parse_serialized_dict(self, serialized_dict):
        result_dict = {}
        for pair in serialized_dict:
            key = self.parser.parse(pair["key"])
            value = pair["value"]
            result_dict[key] = self.parser.parse(value)
        return result_dict

    def parse_serialized_query_list(self, serialized_queries):
        def is_iterator(query_content):
            return "limit" in query_content

        def parse_implication(implication):
            antecedent_data = implication.get("antecedent")
            if isinstance(antecedent_data, list):
                antecedent = PropositionSet([self.parser.parse(item) for item in antecedent_data])
            else:
                antecedent = self.parser.parse(antecedent_data)
            consequent = self.parser.parse(implication.get("consequent"))
            return ImplicationProposition(antecedent, consequent)

        def parse_iterator(iterator):
            result_dict = {}
            for key, value in iterator.items():
                if key in ["for_enumeration", "for_random_enumeration"]:
                    result_dict[key] = [self.parser.parse(item) for item in value]
                else:
                    result_dict[key] = value
            return result_dict

        result_list = []
        for query in serialized_queries:
            if is_iterator(query):
                query_dict = parse_iterator(query)
            else:
                query_dict = {}
                for entry, semantic_objects in query.items():
                    if entry == "implications":
                        query_dict[entry] = [parse_implication(item) for item in semantic_objects]
                        continue
                    try:
                        query_dict[entry] = self.parser.parse(semantic_objects)
                    except AttributeError:
                        query_dict[entry] = [self.parser.parse(item) for item in semantic_objects]
            result_list.append(create_query_from_dict(query_dict))
        return result_list


class JSONServiceInterfaceParser():
    def parse(self, json_dict):
        actions = self.parse_actions(json_dict["_actions"])
        queries = self.parse_queries(json_dict["_queries"])
        validators = self.parse_validators(json_dict["_validators"])
        return ServiceInterface(actions, queries, validators)

    def parse_actions(self, actions_dict):
        return [self.parse_action_interface(actions_dict[action_name]) for action_name in actions_dict]

    def parse_action_interface(self, action_dict):
        name = action_dict["_name"]
        target = self.parse_target(action_dict["_target"])
        service_parameters = self.parse_parameters(action_dict["_parameters"])
        failure_reasons = action_dict["_failure_reasons"]
        interface = ServiceActionInterface(name, target, service_parameters, failure_reasons)
        return interface

    def parse_target(self, target_dict):
        if target_dict.get("target_type") == service_interface.FRONTEND_TARGET:
            return service_interface.FrontendTarget()
        if target_dict.get("target_type") == service_interface.HTTP_TARGET:
            endpoint = target_dict["_endpoint"]
            return service_interface.HttpTarget(endpoint)
        raise JSONParseFailure(f"Cannot parse as target: {target_dict}")

    def parse_parameters(self, parameter_dict):
        return [self.parse_parameter(parameter) for parameter in parameter_dict]

    def parse_parameter(self, parameter):
        name = parameter["_name"]
        format = parameter["_format"]
        is_optional = parameter["_is_optional"]
        return service_interface.ServiceParameter(name, format, is_optional)

    def parse_queries(self, queries_dict):
        return [self.parse_query(query) for query in queries_dict.values()]

    def parse_query(self, query_dict):
        name = query_dict["_name"]
        target = self.parse_target(query_dict["_target"])
        parameters = self.parse_parameters(query_dict["_parameters"])
        return service_interface.ServiceQueryInterface(name, target, parameters)

    def parse_validators(self, validators_dict):
        return [self.parse_validator(validator) for validator in validators_dict.values()]

    def parse_validator(self, validator_dict):
        name = validator_dict["_name"]
        target = self.parse_target(validator_dict["_target"])
        parameters = self.parse_parameters(validator_dict["_parameters"])
        return service_interface.ServiceValidatorInterface(name, target, parameters)


class NonCheckingJSONParser():
    def parse(self, json_dict_unchecked):
        def is_condition():
            """ This is the template for extending the semantic object JSON
            with type information, which should be done for all semantic objects.
            """

            return json_dict.get("semantic_object_type") == condition.SEMANTIC_OBJECT_TYPE

        def is_plan_item():
            for item in plan_item.ALL_PLAN_ITEM_TYPES:
                if item in json_dict:
                    return True
            return False

        def is_individual():
            return "value" in json_dict and "sort" in json_dict

        def is_yes_no():
            return json_dict.get("semantic_object_type") == "yes/no"

        def is_move():
            return "move_type" in json_dict

        def is_action():
            return "value" in json_dict

        def is_goal():
            return "_goal_type" in json_dict

        def is_question():
            question_type = json_dict.get("_type", None)
            return question_type in Question.TYPES

        def is_predicate():
            return "name" in json_dict and "sort" in json_dict

        def is_lambda_abstracted_proposition():
            return json_dict.get("semantic_object_type") == "LambdaAbstractedProposition"

        def is_set():
            return "set" in json_dict

        def is_openqueue():
            return "openqueue" in json_dict

        def is_service_action_outcome():
            return "service_action_outcome" in json_dict

        def is_proposition():
            prop_type = json_dict.get("_type", None)
            return prop_type in Proposition.TYPES

        def is_proposition_set():
            return "_propositions" in json_dict

        def is_action_status():
            return "action_status" in json_dict

        json_dict = preprocess_json_dict(json_dict_unchecked)
        if is_condition():
            return self.parse_condition(json_dict)
        if is_plan_item():
            return self.parse_plan_item(json_dict)
        if is_individual():
            return self.parse_individual(json_dict)
        if is_set():
            return self.parse_set(json_dict["set"])
        if is_openqueue():
            return self.parse_openqueue(json_dict["openqueue"])
        if is_move():
            return self.parse_move(json_dict)
        if is_action():
            return self.parse_action(json_dict)
        if is_goal():
            return self.parse_goal(json_dict)
        if is_question():
            return self.parse_question(json_dict)
        if is_predicate():
            return self.parse_predicate(json_dict)
        if is_proposition_set():
            return self.parse_proposition_set(json_dict)
        if is_proposition():
            return self.parse_proposition(json_dict)
        if is_lambda_abstracted_proposition():
            return self.parse_lambda_abstraction(json_dict)
        if is_service_action_outcome():
            return self.parse_service_action_outcome(json_dict)
        if is_yes_no():
            if json_dict["instance"] == No.NO:
                return No()
            if json_dict["instance"] == Yes.YES:
                return Yes()
        if is_action_status():
            return self.parse_action_status(json_dict)
        raise JSONParseFailure(f"JSONParser cannot parse: {json_dict}")

    def parse_condition(self, condition_json):
        keys = ["_predicate", "_proposition"]
        for key in keys:
            if condition_json.get(key):
                argument = self.parse(condition_json[key])
                return condition.create_condition(condition_json["type"], argument)
        if condition_json.get("_conditions"):
            arguments = [self.parse(item) for item in condition_json["_conditions"]]
            return condition.create_condition(condition_json["type"], arguments)
        if condition_json.get("_condition"):
            argument = self.parse(condition_json["_condition"])
            return condition.create_condition(condition_json["type"], argument)
        if condition_json.get("_query"):
            try:
                argument = self.parse(condition_json["_query"])
            except Exception:
                argument = condition_json["_query"]
            return condition.create_condition(condition_json["type"], argument)
        raise JSONParseFailure(f"Failed to parse {condition_json} as a condition.")

    def parse_plan_item(self, data):
        if plan_item.TYPE_FINDOUT in data:
            return self.parse_findout_plan_item(data)
        if plan_item.TYPE_RAISE in data:
            return self.parse_raise_plan_item(data)
        if plan_item.TYPE_RESPOND in data:
            return self.parse_respond_plan_item(data[plan_item.TYPE_RESPOND])
        if plan_item.TYPE_ASSUME in data:
            return self.parse_assume_plan_item(data[plan_item.TYPE_ASSUME])
        if plan_item.TYPE_ASSUME_ISSUE in data:
            return self.parse_assume_issue_plan_item(data)
        if plan_item.TYPE_ASSUME_SHARED in data:
            return self.parse_assume_shared_plan_item(data[plan_item.TYPE_ASSUME_SHARED])
        if plan_item.TYPE_BIND in data:
            return self.parse_bind_plan_item(data[plan_item.TYPE_BIND])
        if plan_item.TYPE_DO in data:
            return self.parse_do_plan_item(data[plan_item.TYPE_DO])
        if plan_item.TYPE_EMIT_ICM in data:
            return self.parse_emit_icm_plan_item(data[plan_item.TYPE_EMIT_ICM])
        if plan_item.TYPE_FORGET in data:
            return self.parse_forget_plan_item(data[plan_item.TYPE_FORGET])
        if plan_item.TYPE_FORGET_SHARED in data:
            return self.parse_forget_shared_plan_item(data[plan_item.TYPE_FORGET_SHARED])
        if plan_item.TYPE_FORGET_ALL in data:
            return self.parse_forget_all_plan_item(data[plan_item.TYPE_FORGET_ALL])
        if plan_item.TYPE_FORGET_INSTRUCTIONAL_PLAN in data:
            return self.parse_forget_instructional_plan(data[plan_item.TYPE_FORGET_INSTRUCTIONAL_PLAN])
        if plan_item.TYPE_FORGET_ISSUE in data:
            return self.parse_forget_issue_plan_item(data[plan_item.TYPE_FORGET_ISSUE])
        if plan_item.TYPE_IF_THEN_ELSE in data:
            return self.parse_if_then_else_plan_item(data[plan_item.TYPE_IF_THEN_ELSE])
        if plan_item.TYPE_JUMPTO in data:
            return self.parse_jumpto_plan_item(data[plan_item.TYPE_JUMPTO])
        if plan_item.TYPE_REPLACE_GOAL in data:
            return self.parse_replace_goal_plan_item(data[plan_item.TYPE_REPLACE_GOAL])
        if plan_item.TYPE_INVOKE_SERVICE_QUERY in data:
            return self.parse_invoke_service_query_plan_item(data[plan_item.TYPE_INVOKE_SERVICE_QUERY])
        if plan_item.TYPE_INVOKE_DOMAIN_QUERY in data:
            return self.parse_invoke_domain_query_plan_item(data[plan_item.TYPE_INVOKE_DOMAIN_QUERY])
        if plan_item.TYPE_INVOKE_SERVICE_ACTION in data:
            return self.parse_invoke_service_action_plan_item(data[plan_item.TYPE_INVOKE_SERVICE_ACTION])
        if plan_item.TYPE_LOG in data:
            return self.parse_log_plan_item(data[plan_item.TYPE_LOG])
        if plan_item.TYPE_ACTION_PERFORMED in data:
            return self.parse_action_performed_plan_item(data[plan_item.TYPE_ACTION_PERFORMED])
        if plan_item.TYPE_ACTION_ABORTED in data:
            return self.parse_action_aborted_plan_item(data[plan_item.TYPE_ACTION_ABORTED])
        if plan_item.TYPE_CHANGE_DDD in data:
            return self.parse_change_ddd_plan_item(data[plan_item.TYPE_CHANGE_DDD])
        if plan_item.TYPE_GET_DONE in data:
            return self.parse_get_done_plan_item(data)
        if plan_item.TYPE_INVOKE_DOMAIN_QUERY in data:
            return self.parse_invoke_domain_query(data[plan_item.INVOKE_DOMAIN_QUERY])
        if plan_item.TYPE_END_TURN in data:
            return self.parse_end_turn_plan_item(data[plan_item.TYPE_END_TURN])
        if plan_item.TYPE_RESET_DOMAIN_QUERY in data:
            return self.parse_reset_domain_query(data[plan_item.TYPE_RESET_DOMAIN_QUERY])
        if plan_item.TYPE_ITERATE in data:
            return self.parse_iterate_plan_item(data[plan_item.TYPE_ITERATE])
        if plan_item.TYPE_ACTION_REPORT in data:
            return self.parse_action_report_plan_item(data[plan_item.TYPE_ACTION_REPORT])
        if plan_item.TYPE_GREET in data:
            return plan_item.Greet()
        if plan_item.TYPE_EMIT_MOVE in data:
            return self.parse_emit_move_plan_item(data)
        if plan_item.TYPE_QUESTION_REPORT in data:
            return self.parse_question_report_plan_item(data)
        if plan_item.TYPE_SERVICE_REPORT in data:
            return self.parse_service_report_plan_item(data)
        if plan_item.TYPE_RESPOND_TO_INSULT in data:
            return plan_item.RespondToInsult()
        if plan_item.TYPE_RESPOND_TO_THANK_YOU in data:
            return plan_item.RespondToThankYou()

        raise JSONParseFailure(f"PlanItem {data} not supported by json parser")

    def parse_findout_plan_item(self, data):
        allow_answer_from_pcom = data.get("allow_answer_from_pcom", False)
        alts_predicate = data.get("alts_predicate")
        domain_name = data.get("domain_name")
        question = self.parse_question(data[plan_item.TYPE_FINDOUT])
        return plan_item.Findout(domain_name, question, allow_answer_from_pcom, alts_predicate)

    def parse_raise_plan_item(self, data):
        domain_name = data.get("domain_name")
        question = self.parse_question(data[plan_item.TYPE_RAISE])
        return plan_item.Raise(domain_name, question)

    def parse_respond_plan_item(self, data):
        question = self.parse_question(data)
        return plan_item.Respond(question)

    def parse_bind_plan_item(self, data):
        question_type = data.get("_type")
        if question_type not in Question.TYPES:
            raise JSONParseFailure(f"Cannot parse {data} as bind question.")
        allow_binding_yn_answers = data.get("allow_binding_yn_answers", False)
        question = self.parse_question(data)
        if allow_binding_yn_answers and not question.is_yes_no_question():
            raise JSONParseFailure("allow_binding_yn_answers is only valid for yn_question binds")
        return plan_item.Bind(question, allow_binding_yn_answers=allow_binding_yn_answers)

    def parse_do_plan_item(self, data):
        action = self.parse_action(data)
        return plan_item.Do(action)

    def parse_log_plan_item(self, data):
        if "message" in data and "level" in data:
            return plan_item.Log(data["message"], data["level"])
        else:
            return self.parse_old_log_plan_item(data)

    def parse_old_log_plan_item(self, data):
        message = data
        return plan_item.Log(message)

    def parse_action_performed_plan_item(self, data):
        return plan_item.GoalPerformed(data)

    def parse_action_aborted_plan_item(self, data):
        return plan_item.GoalAborted(data)

    def parse_change_ddd_plan_item(self, data):
        return plan_item.ChangeDDD(data)

    def parse_get_done_plan_item(self, data):
        action = self.parse_action(data[plan_item.TYPE_GET_DONE])
        try:
            step = int(data.get("step"))
        except TypeError:
            step = None

        return plan_item.GetDone(action, step)

    def parse_end_turn_plan_item(self, data):
        timeout = float(data)
        return plan_item.EndTurn(timeout)

    def parse_reset_domain_query(self, data):
        query = self.parse_question(data)
        return plan_item.ResetDomainQuery(query)

    def parse_iterate_plan_item(self, iterator_name):
        return plan_item.Iterate(iterator_name)

    def parse_action_report_plan_item(self, result_proposition):
        return plan_item.ActionReport(self.parse_proposition(result_proposition))

    def parse_emit_move_plan_item(self, data):
        prereport_move = self.parse_prereport_move(data[plan_item.TYPE_EMIT_MOVE])
        return plan_item.EmitMove(prereport_move)

    def parse_invoke_domain_query(self, data):
        issue = self.parse_question(data)
        return plan_item.InvokeDomainQuery(issue)

    def parse_forget_plan_item(self, data):
        if "_type" in data.keys():
            proposition = self.parse_proposition(data)
            return plan_item.Forget(proposition)
        else:
            predicate = self.parse_predicate(data)
            return plan_item.Forget(predicate)

    def parse_forget_shared_plan_item(self, data):
        if "_type" in data.keys():
            proposition = self.parse_proposition(data)
            return plan_item.ForgetShared(proposition)
        else:
            predicate = self.parse_predicate(data)
            return plan_item.ForgetShared(predicate)

    def parse_forget_all_plan_item(self, _data):
        return plan_item.ForgetAll()

    def parse_forget_instructional_plan(self, data):
        action = self.parse_action(data["action"])
        return plan_item.ForgetInstructionalPlan(action, data["include_children"])

    def parse_forget_issue_plan_item(self, data):
        question = self.parse_question(data)
        return plan_item.ForgetIssue(question)

    def parse_assume_plan_item(self, data):
        proposition = self.parse_proposition(data)
        return plan_item.Assume(proposition)

    def parse_assume_issue_plan_item(self, data):
        question = self.parse_question(data[plan_item.TYPE_ASSUME_ISSUE])
        return plan_item.AssumeIssue(question, data["insist"])

    def parse_assume_shared_plan_item(self, data):
        proposition = self.parse_proposition(data)
        return plan_item.AssumeShared(proposition)

    def parse_emit_icm_plan_item(self, data):
        icm = self.parse_move(data)
        return plan_item.EmitIcm(icm)

    def parse_jumpto_plan_item(self, data):
        goal = self.parse_goal(data)
        return plan_item.JumpTo(goal)

    def parse_replace_goal_plan_item(self, data):
        goal = self.parse_goal(data)
        return plan_item.ReplaceGoal(goal)

    def parse_if_then_else_plan_item(self, data):
        cond = self.parse(data["condition"])
        consequent = [self.parse(element) for element in data["consequent"]]
        alternative = [self.parse(element) for element in data["alternative"]]
        return plan_item.IfThenElse(cond, consequent, alternative)

    def parse_invoke_service_query_plan_item(self, data):
        issue = self.parse_question(data["issue"])
        min_results = int(data["min_results"])
        try:
            max_results = int(data["max_results"])
        except TypeError:
            max_results = None
        return plan_item.InvokeServiceQuery(issue, min_results=min_results, max_results=max_results)

    def parse_invoke_domain_query_plan_item(self, data):
        issue = self.parse_question(data["issue"])
        min_results = int(data["min_results"])
        max_results = int(data["max_results"])
        return plan_item.InvokeDomainQuery(issue, min_results=min_results, max_results=max_results)

    def parse_invoke_service_action_plan_item(self, data):
        def safe_get(mapping, key, default=None):
            try:
                return mapping.get(key, default)
            except AttributeError:
                return default

        def resolve_name(value):
            try:
                return value.get("name") or value.get("_name") or value.get("action")
            except AttributeError:
                return value

        service_action = resolve_name(safe_get(data, "service_action"))
        if not service_action:
            service_action = resolve_name(
                safe_get(data, "action") or safe_get(data, "_service_action") or safe_get(data, "action_name")
            )

        preconfirm = safe_get(data, "preconfirm")
        postconfirm = safe_get(data, "postconfirm", False)
        downdate_plan = safe_get(data, "downdate_plan")
        if downdate_plan is None:
            downdate_plan = safe_get(data, "_downdate_plan", False)
        ontology_name = safe_get(data, "ontology") or safe_get(data, "ontology_name") or safe_get(
            data, "_ontology_name"
        )
        return plan_item.InvokeServiceAction(ontology_name, service_action, preconfirm, postconfirm, downdate_plan)

    def parse_question_report_plan_item(self, data):
        result_proposition = self.parse_proposition(data[plan_item.TYPE_QUESTION_REPORT])
        return plan_item.QuestionReport(result_proposition)

    def parse_service_report_plan_item(self, data):
        result_proposition = self.parse_proposition(data[plan_item.TYPE_SERVICE_REPORT])
        return plan_item.ServiceReport(result_proposition)

    def parse_question(self, data):
        if data["_type"] == Question.TYPE_WH:
            lambda_abstraction = self.parse_lambda_abstraction(data["_content"])
            return WhQuestion(lambda_abstraction)
        if data["_type"] == Question.TYPE_KPQ:
            embedded_question = self.parse_question(data["_content"])
            return KnowledgePreconditionQuestion(embedded_question)
        if data["_type"] == Question.TYPE_YESNO:
            proposition = self.parse(data["_content"])
            return YesNoQuestion(proposition)
        if data["_type"] == Question.TYPE_ALT:
            p_set = self.parse_proposition_set(data["_content"])
            return AltQuestion(p_set)
        if data["_type"] == Question.TYPE_CONSEQUENT:
            lambda_abstraction = self.parse_lambda_abstraction(data["_content"])
            return ConsequentQuestion(lambda_abstraction)
        raise JSONParseFailure(f"Cannot parse {data} as question.")

    def parse_lambda_abstraction(self, content):
        if content["type_"] == LambdaAbstractedProposition.LAMBDA_ABSTRACTED_PREDICATE_PROPOSITION:
            return self._create_lambda_abstracted_predicate_proposition(content)

        if content["type_"] == LambdaAbstractedProposition.LAMBDA_ABSTRACTED_GOAL_PROPOSITION:
            return LambdaAbstractedGoalProposition()

        if content["type_"] == LambdaAbstractedProposition.LAMBDA_ABSTRACTED_IMPLICATION_PROPOSITION_FOR_CONSEQUENT:
            ontology_name = content["_ontology_name"]
            antecedent = self.parse_proposition(content["_antecedent"])
            predicate = self.parse_predicate(content["_consequent_predicate"])
            return LambdaAbstractedImplicationPropositionForConsequent(antecedent, predicate, ontology_name)
        raise JSONParseFailure(f"Cannot parse {content} as lambda abstraction.")

    def _create_lambda_abstracted_predicate_proposition(self, content):
        predicate = self.parse_predicate(content["predicate"])
        ontology_name = content["_ontology_name"]
        return LambdaAbstractedPredicateProposition(predicate, ontology_name)

    def parse_predicate(self, data):
        predicate_name = data.get("name", data.get("_name"))
        if "sort" not in data and "_sort" in data:
            data = data | {"sort": data["_sort"]}
        return create_predicate(predicate_name, data)

    def parse_proposition_set(self, data):
        proposition_list = data["_propositions"]
        propositions = [self.parse_proposition(proposition) for proposition in proposition_list]
        polarity = data["_polarity"]
        return PropositionSet(propositions, polarity)

    def parse_set(self, data):
        result_set = Set([self.parse(element) for element in data])
        return result_set

    def parse_openqueue(self, input):
        front_content = [self.parse(item) for item in input["front_content"]]
        back_content = [self.parse(item) for item in input["back_content"]]
        unshifted_as_json = input["unshifted_content"]
        if unshifted_as_json:
            unshifted_content = [self.parse(item) for item in unshifted_as_json]
        else:
            unshifted_content = None
        return OpenQueue(front_content, back_content, unshifted_content)

    def parse_move(self, data):
        def get_float(string):
            if string is not None:
                return float(string)
            return None

        move_args = {
            "understanding_confidence": get_float(data.get("understanding_confidence")),
            "speaker": data.get("speaker"),
            "ddd_name": data.get("ddd"),
            "perception_confidence": get_float(data.get("perception_confidence"))
        }
        non_icm_args = {
            "modality": data.get("modality"),
            "weighted_understanding_confidence": get_float(data.get("weighted_understanding_confidence")),
            "utterance": data.get("utterance")
        } | move_args

        icm_args = {
            "polarity": data.get("polarity"),
        } | move_args

        if data["move_type"] == Move.ANSWER:
            return self.parse_answer_move(data, non_icm_args)
        if data["move_type"] == Move.REQUEST:
            return self.parse_request_move(data, non_icm_args)
        if data["move_type"] == Move.ASK:
            return self.parse_ask_move(data, non_icm_args)
        if data["move_type"] == ICM.ACC:
            return self.parse_acc_icm(data, icm_args)
        if data["move_type"] == ICM.ACCOMMODATE:
            return self.parse_accommodate_icm(data, icm_args)
        if data["move_type"] == ICM.RESUME:
            return self.parse_resume_icm(data, icm_args)
        if data["move_type"] == ICM.RERAISE:
            return self.parse_reraise_icm(data, icm_args)
        if data["move_type"] == ICM.PER:
            return self.parse_per_icm(data, icm_args)
        if data["move_type"] == ICM.UND:
            return self.parse_und_icm(data, icm_args)
        if data["move_type"] == ICM.SEM:
            return self.parse_sem_icm(data, icm_args)
        if data["move_type"] == ICM.LOADPLAN:
            return self.parse_loadplan_icm(data, icm_args)
        if data["move_type"] == ICM.CARDINAL_SEQUENCING:
            return self.parse_cardinal_sequencing_icm(data, icm_args)
        if data["move_type"] == ICM.REPORT_INFERENCE:
            return self.parse_report_inference_icm(data, icm_args)
        if data["move_type"] == Move.GREET:
            return self.parse_greet_move(non_icm_args)
        if data["move_type"] == Move.INSULT:
            return self.parse_insult_move(non_icm_args)
        if data["move_type"] == Move.INSULT_RESPONSE:
            return self.parse_insult_response_move(non_icm_args)
        if data["move_type"] == Move.MUTE:
            return self.parse_mute_move(non_icm_args)
        if data["move_type"] == Move.UNMUTE:
            return self.parse_unmute_move(non_icm_args)
        if data["move_type"] == Move.PREREPORT:
            return self.parse_prereport_move(data)
        if data["move_type"] == Move.REPORT:
            return self.parse_report_move(data, non_icm_args)
        if data["move_type"] == Move.QUIT:
            return self.parse_quit_move(non_icm_args)
        if data["move_type"] == Move.THANK_YOU:
            return self.parse_thank_you_move(non_icm_args)
        if data["move_type"] == Move.THANK_YOU_RESPONSE:
            return self.parse_thank_you_response_move(non_icm_args)
        raise JSONParseFailure(f"cannot parse {data} as move.")

    def parse_action(self, data):
        action_name = data.get("value", data.get("_value"))
        ontology_name = data.get("ontology_name", data.get("_ontology_name"))
        return Action(action_name, ontology_name)

    def parse_answer_move(self, data, kwargs):
        content = self.parse(data["content"])
        return Answer(content, **kwargs)

    def parse_request_move(self, data, kwargs):
        action = self.parse_action(data["content"])
        return Request(action, **kwargs)

    def parse_proposition(self, data):
        if data["_type"] == Proposition.PREDICATE:
            return self._create_predicate_proposition(data)
        if data["_type"] == Proposition.GOAL:
            goal = self.parse_goal(data["_content"])
            polarity = data.get("_polarity")
            return GoalProposition(goal, polarity)
        if data["_type"] == Proposition.PRECONFIRMATION:
            service_action = data.get("service_action")
            polarity = data.get("polarity")
            arguments_data = data.get("_arguments") or []
            arguments = [self.parse_proposition(proposition) for proposition in arguments_data]
            ontology_name = data["_ontology_name"]
            return PreconfirmationProposition(ontology_name, service_action, arguments, polarity)
        if data["_type"] == Proposition.SERVICE_RESULT:
            service_action = data.get("service_action") or data.get("_service_action")
            action_outcome = self.parse(data.get("result"))
            arguments_data = data.get("arguments") or data.get("_arguments") or []
            arguments = [self.parse_proposition(proposition) for proposition in arguments_data]
            ontology_name = data.get("ontology_name") or data.get("_ontology_name")
            return ServiceResultProposition(ontology_name, service_action, arguments, action_outcome)
        if data["_type"] == Proposition.UNDERSTANDING:
            content = self.parse(data["_content"])
            polarity = data.get("_polarity")
            speaker = data.get("_speaker")
            return UnderstandingProposition(speaker, content, polarity)
        if data["_type"] == Proposition.RESOLVEDNESS:
            issue = self.parse_question(data["issue"])
            return ResolvednessProposition(issue)
        if data["_type"] == Proposition.KNOWLEDGE_PRECONDITION:
            question = self.parse_question(data["_content"])
            polarity = data.get("_polarity")
            return KnowledgePreconditionProposition(question, polarity)
        if data["_type"] == Proposition.ACTION_STATUS:
            status = self.parse_action_status(data["_status"])
            action = self.parse_action(data["_content"])
            return ActionStatusProposition(action, status)
        if data["_type"] == Proposition.SERVICE_ACTION_STARTED:
            service_action = data["service_action"]
            parameters_data = data.get("parameters") or []
            parameters = [self.parse_proposition(proposition) for proposition in parameters_data]
            ontology_name = data.get("ontology_name")
            return ServiceActionStartedProposition(ontology_name, service_action, parameters)
        if data["_type"] == Proposition.SERVICE_ACTION_TERMINATED:
            service_action = data["service_action"]
            polarity = data.get("_polarity")
            ontology_name = data["_ontology_name"]
            return ServiceActionTerminatedProposition(ontology_name, service_action, polarity)
        if data["_type"] == Proposition.PREREPORT:
            service_action = data["service_action"]
            argument_list = [self.parse_proposition(proposition) for proposition in data["argument_set"]]
            ontology_name = data["_ontology_name"]
            return PrereportProposition(ontology_name, service_action, argument_list)
        if data["_type"] == Proposition.REJECTED:
            polarity = data.get("_polarity")
            reason_for_rejection = data.get("reason_for_rejection")
            combination = self.parse(data["rejected_combination"])
            return RejectedPropositions(combination, polarity, reason_for_rejection)
        if data["_type"] == Proposition.IMPLICATION:
            antecedent = self.parse_proposition(data["_antecedent"])
            consequent = self.parse_proposition(data["_consequent"])
            return ImplicationProposition(antecedent, consequent)
        if data["_type"] == Proposition.NUMBER_OF_ALTERNATIVES:
            individual = self.parse_individual(data["_content"])
            return NumberOfAlternativesProposition(individual)
        if data["_type"] == Proposition.QUESTION_STATUS:
            question = self.parse_question(data["_content"])
            status = self.parse_action_status(data["_status"])
            return QuestionStatusProposition(question, status)
        if data["_type"] == Proposition.MUTE:
            return MuteProposition()
        if data["_type"] == Proposition.UNMUTE:
            return UnmuteProposition()
        if data["_type"] == Proposition.QUIT:
            return QuitProposition()
        if data["_type"] == Proposition.PREDICTED:
            return self._create_predicted_proposition(data)
        raise JSONParseFailure(f"Cannot parse {data} as proposition.")

    def _create_predicate_proposition(self, data):
        individual_data = data.get("individual")
        predicate_data = data.get("predicate", data.get("_content"))
        sort_data = predicate_data.get("sort", predicate_data.get("_sort"))
        sort_name = sort_data.get("_name", sort_data.get("name"))
        if sort_name == "string" and individual_data is None:
            individual = None
        else:
            individual = self.parse_individual(individual_data)
        predicate = self.parse_predicate(predicate_data)
        polarity = data.get("_polarity")
        return PredicateProposition(predicate, individual, polarity)

    def _create_predicted_proposition(self, data):
        prediction = self.parse_proposition(data["_content"])
        polarity = data.get("_polarity")
        return PredictedProposition(prediction, polarity)

    def parse_individual(self, data):
        if data is None:
            return None
        sort_data = data["sort"]
        value_data = data["value"]
        value, sort = create_individual(value_data, sort_data)
        polarity = data["polarity"]
        ontology_name = data.get("ontology_name", data.get("_ontology_name"))
        if polarity == Polarity.POS:
            return Individual(ontology_name, value, sort)
        return NegativeIndividual(ontology_name, value, sort)

    def parse_goal(self, data):
        if data is None:
            return None
        if data.get("_goal_type") == PERFORM:
            target = data.get("_target")
            action = self.parse_action(data["_content"])
            goal = PerformGoal(action, target=target)
            return goal
        if data.get("_goal_type") == RESOLVE:
            target = data.get("_target")
            question = self.parse_question(data["_content"])
            return ResolveGoal(question, target=target)
        raise JSONParseFailure(f"could not parse {data} as goal.")

    def parse_acc_icm(self, data, kwargs):
        if data.get("content"):
            content = self.parse(data["content"])
            content_speaker = data.get("content_speaker")
            return ICM.create(ICM.ACC, content=content, content_speaker=content_speaker, **kwargs)

        return ICM(ICM.ACC, **kwargs)

    def parse_accommodate_icm(self, data, kwargs):
        if data.get("content"):
            content = self.parse(data["content"])
            content_speaker = data.get("content_speaker")
            return ICM.create(ICM.ACCOMMODATE, content=content, content_speaker=content_speaker, **kwargs)
        else:
            return ICM(ICM.ACCOMMODATE, **kwargs)

    def parse_resume_icm(self, data, kwargs):
        goal = self.parse_goal(data["content"])
        content_speaker = data.get("content_speaker")
        return ICM.create(ICM.RESUME, content=goal, content_speaker=content_speaker, **kwargs)

    def parse_reraise_icm(self, data, kwargs):
        if data.get("content"):
            action = self.parse(data["content"])
            content_speaker = data.get("content_speaker")
            return ICM.create(ICM.RERAISE, content=action, content_speaker=content_speaker, **kwargs)
        else:
            return ICM(ICM.RERAISE, **kwargs)

    def parse_per_icm(self, data, kwargs):
        string = data.get("content", None)
        if string:
            content_speaker = data.get("content_speaker")
            return ICM.create(ICM.PER, content=string, content_speaker=content_speaker, **kwargs)
        return ICM(ICM.PER, **kwargs)

    def parse_und_icm(self, data, kwargs):
        content_data = data.get("content")
        if content_data:
            content = self.parse(content_data)
            content_speaker = data.get("content_speaker")
            return ICM.create(ICM.UND, content=content, content_speaker=content_speaker, **kwargs)
        else:
            return ICM(ICM.UND, **kwargs)

    def parse_sem_icm(self, data, kwargs):
        content_data = data.get("content")
        if content_data:
            content = self.parse_proposition(content_data)
            content_speaker = data.get("content_speaker")
            return ICM.create(ICM.SEM, content=content, content_speaker=content_speaker, **kwargs)
        content_speaker = data.get("content_speaker")
        return ICM(ICM.SEM, **kwargs)

    def parse_loadplan_icm(self, data, kwargs):
        return ICM(ICM.LOADPLAN, **kwargs)

    def parse_cardinal_sequencing_icm(self, data, kwargs):
        content_speaker = data.get("content_speaker")
        return ICM.create(
            ICM.CARDINAL_SEQUENCING, content=int(data["content"]), content_speaker=content_speaker, **kwargs
        )

    def parse_report_inference_icm(self, data, kwargs):
        content_data = data.get("content")
        if content_data:
            content = self.parse(content_data)
            content_speaker = data.get("content_speaker")
            return ICM.create(ICM.REPORT_INFERENCE, content=content, content_speaker=content_speaker, **kwargs)

    def parse_greet_move(self, kwargs):
        return Greet(**kwargs)

    def parse_insult_move(self, kwargs):
        return Insult(**kwargs)

    def parse_insult_response_move(self, kwargs):
        return InsultResponse(**kwargs)

    def parse_mute_move(self, kwargs):
        return Mute(**kwargs)

    def parse_unmute_move(self, kwargs):
        return Unmute(**kwargs)

    def parse_quit_move(self, kwargs):
        return Quit(**kwargs)

    def parse_thank_you_move(self, kwargs):
        return ThankYou(**kwargs)

    def parse_thank_you_response_move(self, kwargs):
        return ThankYouResponse(**kwargs)

    def parse_prereport_move(self, data):
        service_action = data["service_action"]
        arguments = data["arguments"]
        argument_list = [self.parse_proposition(argument) for argument in arguments]
        ontology_name = data["ontology_name"]
        return Prereport(ontology_name, service_action, argument_list)

    def parse_report_move(self, data, kwargs):
        content = self.parse(data["content"])
        return Report(content, **kwargs)

    def parse_ask_move(self, data, kwargs):
        question = self.parse_question(data["content"])
        return Ask(question, **kwargs)

    def parse_service_action_outcome(self, json):
        if json["service_action_outcome"]:
            return SuccessfulServiceAction()
        return FailedServiceAction(json["failure_reason"])

    def parse_action_status(self, json):
        if json["action_status"] == ActionStatus.DONE:
            return Done()
        if json["action_status"] == ActionStatus.ABORTED:
            return Aborted(json["reason"])


class CheckingJSONParser(NonCheckingJSONParser):
    def __init__(self, ddd_name, ontology, domain_name):
        self.ontology = ontology
        self.ontology_name = ontology.name
        self.domain_name = domain_name

    def parse_action(self, data):
        action_name = data.get("value", data.get("_value"))
        return self.ontology.create_action(action_name)

    def _create_predicate_proposition(self, data):
        predicate_data = data.get("predicate", data.get("_content"))
        sort_data = predicate_data.get("sort", predicate_data.get("_sort"))
        sort_name = sort_data.get("_name", sort_data.get("name"))
        if sort_name == "boolean":
            individual = None
        elif sort_name == "string" and data.get("individual") is None:
            individual = None
        else:
            individual = self.parse_individual(data.get("individual"))
        predicate = self.parse_predicate(predicate_data)
        polarity = data.get("_polarity")
        return self.ontology.create_predicate_proposition(predicate, individual, polarity)

    def parse_predicate(self, data):
        predicate_name = data.get("name", data.get("_name"))
        return self.ontology.get_predicate(predicate_name)

    def parse_findout_plan_item(self, data):
        question = self.parse_question(data[plan_item.TYPE_FINDOUT])
        allow_answer_from_pcom = data.get("allow_answer_from_pcom", False)
        alts_predicate = data.get("alts_predicate")
        return plan_item.Findout(self.domain_name, question, allow_answer_from_pcom, alts_predicate)

    def parse_raise_plan_item(self, data):
        question = self.parse_question(data[plan_item.TYPE_RAISE])
        return plan_item.Raise(self.domain_name, question)

    def parse_individual(self, data):
        def extract(string, prefix, suffix):
            if value.startswith(prefix) and value.endswith(suffix):
                return value[len(prefix):len(value) - len(suffix)]

        def extract_datetime_value():
            return extract(value, "datetime(", ")")

        def extract_person_name_value():
            return extract(value, "person_name(", ")")

        if data is None:
            return None
        sort_name = data["sort"].get("_name", data["sort"].get("name"))
        sort = self.ontology.get_sort(sort_name)
        value = data["value"]
        polarity = data["polarity"]
        if sort.is_datetime_sort():
            value = DateTime(extract_datetime_value())
        if sort.is_real_sort():
            value = float(value)
        if sort.is_person_name_sort():
            value = PersonName(extract_person_name_value())
        if sort.is_integer_sort():
            value = int(value)
        if polarity == Polarity.POS:
            return self.ontology.create_individual(value, sort)
        return self.ontology.create_negative_individual(value)

    def _create_lambda_abstracted_predicate_proposition(self, content):
        predicate = self.parse_predicate(content["predicate"])
        return self.ontology.create_lambda_abstracted_predicate_proposition(predicate)

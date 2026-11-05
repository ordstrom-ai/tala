import copy

from tala import model
from tala.model.error import DomainError
from tala.model.move_icm import ICM
from tala.model.proposition import Proposition
from tala.model.action import Action
from tala.model.semantic_object import SemanticObject, OntologySpecificSemanticObject, SemanticObjectWithContent
from tala.utils.as_semantic_expression import AsSemanticExpressionMixin
from tala.utils.unicodify import unicodify
from tala.utils import json_api
from tala.utils.json_api import JSONAPIObject, get_attribute
#  These are imported so that they are available in "globals()" for retrieval in PlanItem.create_from_json_api_data()
from tala.model.question import Question, WhQuestion  # noqa
from tala.model.goal import Perform, Resolve  # noqa
from tala.model.condition import Condition  # noqa
from tala.model.predicate import Predicate  # noqa

TYPE_RESPOND = "respond"
TYPE_GREET = "greet"
TYPE_RESPOND_TO_INSULT = "respond_to_insult"
TYPE_RESPOND_TO_THANK_YOU = "respond_to_thank_you"
TYPE_QUIT = "quit"
TYPE_MUTE = "mute"
TYPE_UNMUTE = "unmute"
TYPE_FINDOUT = "findout"
TYPE_RAISE = "raise"
TYPE_BIND = "bind"
TYPE_DO = "do"
TYPE_EMIT_ICM = "emit_icm"
TYPE_JUMPTO = "jumpto"
TYPE_IF_THEN_ELSE = "if_then_else"
TYPE_FORGET_ALL = "forget_all"
TYPE_FORGET = "forget"
TYPE_FORGET_SHARED = "forget_shared"
TYPE_FORGET_ISSUE = "forget_issue"
TYPE_INVOKE_SERVICE_QUERY = "invoke_service_query"
TYPE_INVOKE_DOMAIN_QUERY = "invoke_domain_query"
TYPE_INVOKE_SERVICE_ACTION = "invoke_service_action"
TYPE_SERVICE_REPORT = "service_report"
TYPE_ACTION_REPORT = "action_report"
TYPE_QUESTION_REPORT = "question_report"
TYPE_ASSUME = "assume"
TYPE_ASSUME_SHARED = "assume_shared"
TYPE_ASSUME_ISSUE = "assume_issue"
TYPE_EMIT_MOVE = "emit_move"
TYPE_HANDLE = "handle"
TYPE_LOG = "log"
TYPE_GET_DONE = "get_done"
TYPE_ACTION_PERFORMED = "signal_action_completion"
TYPE_ACTION_ABORTED = "signal_action_failure"
TYPE_END_TURN = "end_turn"
TYPE_RESET_DOMAIN_QUERY = "reset_domain_query"
TYPE_ITERATE = "iterate"
TYPE_CHANGE_DDD = "change_ddd"

QUESTION_TYPES = [TYPE_FINDOUT, TYPE_RAISE, TYPE_BIND]

ALL_PLAN_ITEM_TYPES = [
    TYPE_RESPOND,
    TYPE_GREET,
    TYPE_RESPOND_TO_INSULT,
    TYPE_RESPOND_TO_THANK_YOU,
    TYPE_QUIT,
    TYPE_MUTE,
    TYPE_UNMUTE,
    TYPE_FINDOUT,
    TYPE_RAISE,
    TYPE_BIND,
    TYPE_DO,
    TYPE_EMIT_ICM,
    TYPE_JUMPTO,
    TYPE_IF_THEN_ELSE,
    TYPE_FORGET_ALL,
    TYPE_FORGET,
    TYPE_FORGET_SHARED,
    TYPE_FORGET_ISSUE,
    TYPE_INVOKE_SERVICE_QUERY,
    TYPE_INVOKE_DOMAIN_QUERY,
    TYPE_INVOKE_SERVICE_ACTION,
    TYPE_SERVICE_REPORT,
    TYPE_ACTION_REPORT,
    TYPE_QUESTION_REPORT,
    TYPE_ASSUME,
    TYPE_ASSUME_SHARED,
    TYPE_ASSUME_ISSUE,
    TYPE_EMIT_MOVE,
    TYPE_HANDLE,
    TYPE_LOG,
    TYPE_GET_DONE,
    TYPE_ACTION_PERFORMED,
    TYPE_ACTION_ABORTED,
    TYPE_END_TURN,
    TYPE_RESET_DOMAIN_QUERY,
    TYPE_ITERATE,
    TYPE_CHANGE_DDD
]  # yapf: disable


class PlanItem(SemanticObject, AsSemanticExpressionMixin):
    @classmethod
    def create_from_json_api_data(cls, plan_item_data, included):
        class_name = plan_item_data["type"].rsplit(".", 1)[-1]
        target_cls = globals().get(class_name)

        if target_cls is not None:
            try:
                return target_cls.create_from_json_api_data(plan_item_data, included)
            except RecursionError as e:
                raise Exception(f"recursion error when creating data from {plan_item_data}", e)
        raise DomainError(f"cannot instantiate object of class {class_name}")

    def __init__(self, type_):
        SemanticObject.__init__(self)
        self._type = type_

    def __repr__(self):
        return "%s%s" % (PlanItem.__class__.__name__, (self._type, ))

    def __str__(self):
        return str(self._type)

    def __eq__(self, other):
        return other.is_plan_item() and self.type_ == other.type_

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        return hash((self.__class__.__name__, self._type))

    @property
    def type_(self):
        return self._type

    def is_plan_item(self):
        return True

    def is_question_raising_item(self):
        return False

    def is_turn_yielding(self):
        return False

    def as_dict(self):
        return {
            self.type_: None,
        }


class PlanItemWithContent(PlanItem):
    def __init__(self, type, content):
        PlanItem.__init__(self, type)
        self._content = content

    def __repr__(self):
        return "%s%s" % (PlanItemWithContent.__name__, (self._type, self._content))

    def __str__(self):
        return "%s(%s)" % (str(self._type), str(self._content))

    def __eq__(self, other):
        try:
            return other is not None \
                and other.is_plan_item() \
                and self.type_ == other.type_ \
                and self.content == other.content
        except AttributeError:
            return False

    def __hash__(self):
        return hash((self.__class__.__name__, self._type, self._content))

    @property
    def content(self):
        return self._content

    def as_dict(self):
        return {self.type_: self._content}


class PlanItemWithSemanticContent(PlanItem, SemanticObjectWithContent):
    @classmethod
    def create_from_json_api_data(cls, data, included):
        semantic_content_entry = included.get_object_from_relationship(data["relationships"]["content"]["data"])
        semantic_content = json_api.create_from_json_api_data(semantic_content_entry, included)
        return cls(semantic_content)

    def __init__(self, type_, content):
        PlanItem.__init__(self, type_)
        SemanticObjectWithContent.__init__(self, content)
        self._content = content

    def __repr__(self):
        return "%s%s" % (PlanItemWithSemanticContent.__name__, (self._type, self._content))

    def __str__(self):
        return "%s(%s)" % (str(self._type), str(self._content))

    def __eq__(self, other):
        return other is not None and other.is_plan_item() and other.has_semantic_content(
        ) and self.type_ == other.type_ and self.content == other.content

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        return hash((self.__class__.__name__, self._type, self._content))

    @property
    def content(self):
        return self._content

    def as_dict(self):
        return {self.type_: self._content}

    @property
    def json_api_id(self):
        return f"{self.json_api_type}:{self.content.json_api_id}"

    @property
    def json_api_attributes(self):
        return ["type_"]

    @property
    def json_api_relationships(self):
        return ["content"]


class Assume(PlanItemWithSemanticContent):
    def __init__(self, content):
        PlanItemWithSemanticContent.__init__(self, TYPE_ASSUME, content=content)


class AssumeShared(PlanItemWithSemanticContent):
    def __init__(self, content):
        PlanItemWithSemanticContent.__init__(self, TYPE_ASSUME_SHARED, content=content)


class AssumeIssue(PlanItemWithSemanticContent):
    @classmethod
    def create_from_json_api_data(cls, data, included):
        issue_data = included.get_object_from_relationship(data["relationships"]["issue"]["data"])
        issue = Question.create_from_json_api_data(issue_data, included)
        insist = data["attributes"]["should_insist"]
        return cls(issue, insist)

    def __init__(self, issue, insist=False):
        PlanItemWithSemanticContent.__init__(self, TYPE_ASSUME_ISSUE, content=issue)
        self._should_insist = insist

    @property
    def should_insist(self):
        return self._should_insist

    @property
    def issue(self):
        return self.content

    def as_dict(self):
        return {"insist": self.should_insist} | super().as_dict()

    @property
    def json_api_id(self):
        return f"{self.json_api_type}:{self.content.json_api_id}:{self.should_insist}"

    @property
    def json_api_attributes(self):
        return ["should_insist"]

    @property
    def json_api_relationships(self):
        return ["issue"]


class Respond(PlanItemWithSemanticContent):
    def __init__(self, content):
        PlanItemWithSemanticContent.__init__(self, TYPE_RESPOND, content=content)

    def is_turn_yielding(self):
        return True


class Do(PlanItemWithSemanticContent):
    def __init__(self, action):
        assert action.is_action()
        PlanItemWithSemanticContent.__init__(self, TYPE_DO, content=action)


class PlanItemWithoutContent(PlanItem):
    @classmethod
    def create_from_json_api_data(cls, _data, _included):
        return cls()


class Quit(PlanItemWithoutContent):
    def __init__(self):
        PlanItem.__init__(self, TYPE_QUIT)


class Mute(PlanItemWithoutContent):
    def __init__(self):
        PlanItem.__init__(self, TYPE_MUTE)


class Unmute(PlanItemWithoutContent):
    def __init__(self):
        PlanItem.__init__(self, TYPE_UNMUTE)


class Greet(PlanItemWithoutContent):
    def __init__(self):
        PlanItem.__init__(self, TYPE_GREET)

    def is_turn_yielding(self):
        return True


class RespondToInsult(PlanItemWithoutContent):
    def __init__(self):
        PlanItem.__init__(self, TYPE_RESPOND_TO_INSULT)


class RespondToThankYou(PlanItemWithoutContent):
    def __init__(self):
        PlanItem.__init__(self, TYPE_RESPOND_TO_THANK_YOU)


class EmitICM(PlanItemWithSemanticContent):
    def __init__(self, icm_move):
        PlanItemWithSemanticContent.__init__(self, TYPE_EMIT_ICM, content=icm_move)

    def is_question_raising_item(self):
        icm = self.content
        return (icm.type_ == ICM.UND and not (icm.polarity == ICM.POS and not icm.content.is_positive()))

    def is_turn_yielding(self):
        return self.content.type_ == ICM.ACC and self.content.polarity == ICM.NEG


class EmitIcmPlanItem(EmitICM):
    pass


class EmitIcm(EmitICM):
    pass


class Bind(PlanItemWithSemanticContent):
    @classmethod
    def create_from_json_api_data(cls, data, included):
        question_entry = included.get_object_from_relationship(data["relationships"]["question"]["data"])
        question = Question.create_from_json_api_data(question_entry, included)
        allow_binding_yn_answers = data.get("attributes", {}).get("allow_binding_yn_answers", False)
        return cls(question, allow_binding_yn_answers=allow_binding_yn_answers)

    def __init__(self, content, allow_binding_yn_answers=False):
        PlanItemWithSemanticContent.__init__(self, TYPE_BIND, content)
        self._allow_binding_yn_answers = allow_binding_yn_answers

    @property
    def question(self):
        return self.content

    @property
    def allow_binding_yn_answers(self):
        return self._allow_binding_yn_answers

    def as_dict(self):
        question_json = self.question.as_json()
        question_json["allow_binding_yn_answers"] = self.allow_binding_yn_answers
        return {self.type_: question_json}

    @property
    def json_api_id(self):
        return f"{self.json_api_type}:{self.question.json_api_id}:{self.allow_binding_yn_answers}"

    @property
    def json_api_attributes(self):
        return ["allow_binding_yn_answers"]

    @property
    def json_api_relationships(self):
        return ["question"]


class JumpTo(PlanItemWithSemanticContent):
    def __init__(self, content):
        PlanItemWithSemanticContent.__init__(self, TYPE_JUMPTO, content=content)

    @property
    def goal(self):
        return self.content


class IfThenElse(PlanItem):
    @classmethod
    def create_from_json_api_data(cls, data, included):
        condition_data = included.get_object_from_relationship(data["relationships"]["condition"]["data"])
        if condition_data["type"].endswith("Proposition"):
            proposition = json_api.create_from_json_api_data(condition_data, included)
            condition = model.condition.InBeliefsOrCommitments(proposition)
        else:
            condition = model.condition.create_from_json_api_data(condition_data, included)
        consequent = []
        try:
            for consequent_data in data["relationships"]["consequent"]["data"]:
                item_data = included.get_object_from_relationship(consequent_data)
                consequent.append(PlanItem.create_from_json_api_data(item_data, included))
        except KeyError:
            pass
        alternative = []
        try:
            for alternative_data in data["relationships"]["alternative"]["data"]:
                item_data = included.get_object_from_relationship(alternative_data)
                alternative.append(PlanItem.create_from_json_api_data(item_data, included))
        except KeyError:
            pass
        return cls(condition, consequent, alternative)

    def __init__(self, condition, consequent, alternative):
        self.condition = condition
        self.consequent = consequent
        self.alternative = alternative
        self._check_integrity_of_data()
        PlanItem.__init__(self, TYPE_IF_THEN_ELSE)

    @property
    def condition(self):
        return self._condition

    @condition.setter
    def condition(self, value):
        self._condition = value

    @property
    def consequent(self):
        return self._consequent

    @consequent.setter
    def consequent(self, value):
        self._consequent = value

    @property
    def alternative(self):
        return self._alternative

    @alternative.setter
    def alternative(self, value):
        self._alternative = value

    def _check_integrity_of_data(self):
        self._assert_one_alternative_is_non_empty_list()
        self._assert_ontology_integrity()

    def _assert_one_alternative_is_non_empty_list(self):
        assert self.consequent is not [] or self.alternative is not [], \
            "One of consequent (%s) and alternative (%s) must not be []" % (self.consequent, self.alternative)

    def _assert_ontology_integrity(self):
        if self.consequent is not [] or self.alternative is not []:
            items = self.consequent + self.alternative
            ontology_specific_plan_items = [item for item in items if item.is_ontology_specific()]
            if len(ontology_specific_plan_items) > 0:
                ontology_name = ontology_specific_plan_items[0].ontology_name
                for item in ontology_specific_plan_items:
                    assert ontology_name == item.ontology_name, "Expected identical ontologies in all consequents (%s) and alternatives (%s) but got %r and %r (plan item: %r)" % (
                        self.consequent, self.alternative, ontology_name, item.ontology_name, item
                    )

    def remove_consequent(self):
        self.consequent = None

    def remove_alternative(self):
        self.alternative = None

    def __str__(self):
        result = "if_then_else{}".format(unicodify((self.condition, self.consequent, self.alternative)))
        return result

    def __repr__(self):
        result = "if_then_else{}".format(unicodify((self.condition, self.consequent, self.alternative)))
        return result

    def __eq__(self, other):
        try:
            equality = (self.condition == other.condition) \
                and (self.consequent == other.consequent) \
                and (self.alternative == other.alternative)
            return equality
        except AttributeError:
            pass
        return False

    def as_dict(self):
        return {
            self.type_: {
                "condition": self.condition,
                "consequent": self.consequent,
                "alternative": self.alternative,
            }
        }

    def as_json_api_dict(self):
        obj = JSONAPIObject("tala.model.plan_item.IfThenElse")
        obj.add_relationship("condition", self.condition.as_json_api_dict())
        for item in self.consequent:
            obj.append_relationship("consequent", item.as_json_api_dict())
        for item in self.alternative:
            obj.append_relationship("alternative", item.as_json_api_dict())
        return obj.as_dict


class ForgetAll(PlanItem):
    @classmethod
    def create_from_json_api_data(cls, plan_item_data, included):
        return cls()

    def __init__(self):
        PlanItem.__init__(self, TYPE_FORGET_ALL)


class Forget(PlanItemWithSemanticContent):
    def __init__(self, predicate_or_proposition):
        PlanItemWithSemanticContent.__init__(self, TYPE_FORGET, predicate_or_proposition)


class ForgetShared(PlanItemWithSemanticContent):
    def __init__(self, predicate_or_proposition):
        PlanItemWithSemanticContent.__init__(self, TYPE_FORGET_SHARED, predicate_or_proposition)


class ForgetIssue(PlanItemWithSemanticContent):
    def __init__(self, issue):
        PlanItemWithSemanticContent.__init__(self, TYPE_FORGET_ISSUE, issue)


class MinResultsNotSupportedException(Exception):
    pass


class MaxResultsNotSupportedException(Exception):
    pass


class InvokeQuery(PlanItemWithSemanticContent):
    def __init__(self, issue, type_, min_results=None, max_results=None):
        PlanItemWithSemanticContent.__init__(self, type_, issue)
        min_results = min_results or 0
        if min_results < 0:
            raise MinResultsNotSupportedException("Expected 'min_results' to be 0 or above but got %r." % min_results)
        if max_results is not None and max_results < 1:
            raise MaxResultsNotSupportedException(
                "Expected 'max_results' to be None or above 0 but got %r." % max_results
            )
        self._min_results = min_results
        self._max_results = max_results

    @property
    def min_results(self):
        return self._min_results

    @property
    def max_results(self):
        return self._max_results

    @property
    def question(self):
        return self._content

    def __str__(self):
        return "invoke_service_query(%s, min_results=%s, max_results=%s)" % (
            str(self._content), self._min_results, self._max_results
        )

    def __repr__(self):
        return "%s(%r, min_results=%r, max_results=%r)" % (
            self.__class__.__name__, self._content, self._min_results, self._max_results
        )

    def __eq__(self, other):
        return super(PlanItemWithSemanticContent, self).__eq__(other) \
            and other.min_results == self.min_results \
            and other.max_results == self.max_results

    def as_dict(self):
        return {
            self.type_: {
                "issue": self._content,
                "min_results": self._min_results,
                "max_results": self._max_results,
            }
        }

    @property
    def json_api_id(self):
        return f"{self.json_api_type}:{self.question.json_api_id}"

    @property
    def json_api_attributes(self):
        return ["min_results", "max_results"]

    @property
    def json_api_relationships(self):
        return ["question"]


class InvokeServiceQuery(InvokeQuery):
    @classmethod
    def create_from_json_api_data(cls, data, included):
        question_data = included.get_object_from_relationship(data["relationships"]["question"]["data"])
        question = Question.create_from_json_api_data(question_data, included)
        min_results = data["attributes"]["min_results"]
        max_results = data["attributes"]["max_results"]
        min_results = int(min_results) if min_results else min_results
        max_results = int(max_results) if max_results else max_results
        return cls(question, min_results, max_results)

    def __init__(self, issue, min_results=None, max_results=None):
        InvokeQuery.__init__(self, issue, TYPE_INVOKE_SERVICE_QUERY, min_results, max_results)


class InvokeDomainQuery(InvokeQuery):
    @classmethod
    def create_from_json_api_data(cls, data, included):
        question_data = included.get_object_from_relationship(data["relationships"]["question"]["data"])
        question = Question.create_from_json_api_data(question_data, included)
        min_results = int(data["attributes"]["min_results"])
        max_results = int(data["attributes"]["max_results"])
        return cls(question, min_results, max_results)

    def __init__(self, issue, min_results=None, max_results=None):
        InvokeQuery.__init__(self, issue, TYPE_INVOKE_DOMAIN_QUERY, min_results, max_results)

    @property
    def json_api_id(self):
        return f"{self.json_api_type}:{self.question.json_api_id}"

    @property
    def json_api_attributes(self):
        return ["min_results", "max_results"]

    @property
    def json_api_relationships(self):
        return ["question"]


class InvokeServiceAction(PlanItem, OntologySpecificSemanticObject):
    INTERROGATIVE = "INTERROGATIVE"
    ASSERTIVE = "ASSERTIVE"

    @classmethod
    def create_from_json_api_data(cls, plan_item_data, included):
        ontology_name = plan_item_data["attributes"]["ontology_name"]
        service_action = plan_item_data["attributes"]["service_action"]
        preconfirm = plan_item_data["attributes"]["preconfirm"]
        postconfirm = plan_item_data["attributes"]["postconfirm"]
        should_downdate_plan = plan_item_data["attributes"]["_downdate_plan"]
        return cls(ontology_name, service_action, preconfirm, postconfirm, should_downdate_plan)

    def __init__(self, ontology_name, service_action, preconfirm=None, postconfirm=False, downdate_plan=False):
        self.service_action = service_action
        self.preconfirm = preconfirm
        self.postconfirm = postconfirm
        self._downdate_plan = downdate_plan
        PlanItem.__init__(self, TYPE_INVOKE_SERVICE_ACTION)
        OntologySpecificSemanticObject.__init__(self, ontology_name)

    @property
    def service_action(self):
        return self._service_action

    @service_action.setter
    def service_action(self, value):
        self._service_action = value

    @property
    def preconfirm(self):
        return self._preconfirm

    @preconfirm.setter
    def preconfirm(self, value):
        self._preconfirm = value

    @property
    def postconfirm(self):
        return self._postconfirm

    @postconfirm.setter
    def postconfirm(self, value):
        self._postconfirm = value

    def has_interrogative_preconfirmation(self):
        return self.preconfirm == self.INTERROGATIVE

    def has_assertive_preconfirmation(self):
        return self.preconfirm == self.ASSERTIVE

    def has_postconfirmation(self):
        return self.postconfirm

    def should_downdate_plan(self):
        return self._downdate_plan

    def __eq__(self, other):
        return super().__eq__(other) \
            and other.service_action == self.service_action \
            and other.has_interrogative_preconfirmation() == self.has_interrogative_preconfirmation() \
            and other.has_assertive_preconfirmation() == self.has_assertive_preconfirmation() \
            and other.has_postconfirmation() == self.has_postconfirmation() \
            and other.should_downdate_plan() == self.should_downdate_plan()

    def __str__(self):
        return "invoke_service_action(%s, {preconfirm=%s, postconfirm=%s, downdate_plan=%s})" % (
            str(self.service_action), self.preconfirm, self.postconfirm, self._downdate_plan
        )

    def __repr__(self):
        return "%s(%r, %r, preconfirm=%r, postconfirm=%r, downdate_plan=%r)" % (
            self.__class__.__name__, self.ontology_name, self.service_action, self.preconfirm, self.postconfirm,
            self._downdate_plan
        )

    def as_dict(self):
        return {
            self.type_: {
                "service_action": self.service_action,
                "ontology": self._ontology_name,
                "preconfirm": self.preconfirm,
                "postconfirm": self.postconfirm,
                "downdate_plan": self._downdate_plan,
            }
        }

    @property
    def json_api_id(self):
        return f"{self.ontology_name}.{self.service_action}.{self.preconfirm}.{self.postconfirm}.{self._downdate_plan}"

    @property
    def json_api_attributes(self):
        return ["service_action", "ontology_name", "preconfirm", "postconfirm", "_downdate_plan", "type_"]


class ServiceReport(PlanItemWithSemanticContent):
    def __init__(self, result_proposition):
        PlanItemWithSemanticContent.__init__(self, TYPE_SERVICE_REPORT, result_proposition)

    def is_turn_yielding(self):
        return self._content.type_ == Proposition.SERVICE_RESULT


class ActionReport(PlanItemWithSemanticContent):
    def __init__(self, result_proposition):
        PlanItemWithSemanticContent.__init__(self, TYPE_ACTION_REPORT, result_proposition)

    def is_turn_yielding(self):
        return self._content.type_ in [Proposition.SERVICE_RESULT, Proposition.ACTION_STATUS]


class QuestionReport(PlanItemWithSemanticContent):
    def __init__(self, result_proposition):
        PlanItemWithSemanticContent.__init__(self, TYPE_QUESTION_REPORT, result_proposition)

    def is_turn_yielding(self):
        return self._content.type_ == Proposition.QUESTION_STATUS


class EmitMove(PlanItemWithSemanticContent):
    def __init__(self, move):
        PlanItemWithSemanticContent.__init__(self, TYPE_EMIT_MOVE, move)


class Handle(PlanItem, OntologySpecificSemanticObject):
    def __init__(self, ontology_name, service_action):
        PlanItem.__init__(self, TYPE_HANDLE)
        OntologySpecificSemanticObject.__init__(self, ontology_name)
        self._service_action = service_action

    @property
    def service_action(self):
        return self._service_action

    def __str__(self):
        return "invoke_service_action(%s)" % (str(self.service_action))

    def as_dict(self):
        return {
            self.type_: {
                "service_action": self._service_action,
                "ontology": self.ontology_name,
            }
        }

    def as_json_api_dict(self):
        obj = JSONAPIObject.create_from_dict(super().as_json_api_dict())
        obj.add_attribute("service_action", self.service_action)
        obj.add_attribute("ontology", self.ontology_name)
        return obj.as_dict


class UnexpectedLogLevelException(Exception):
    pass


class Log(PlanItem):
    LOG_LEVELS = ["debug", "info", "warning", "error", "critical"]

    @classmethod
    def create_from_json_api_data(cls, data, included):
        message = get_attribute("message", data)
        level = get_attribute("level", data)
        return cls(message, level)

    def __init__(self, message, log_level="debug"):
        if log_level not in self.LOG_LEVELS:
            raise UnexpectedLogLevelException(
                f"Log plan item creation attempted with log level '{log_level}'. Expected one of '{self.LOG_LEVELS}'"
            )

        PlanItem.__init__(self, TYPE_LOG)
        self._message = message
        self._level = log_level

    @property
    def message(self):
        return self._message

    @property
    def level(self):
        return self._level

    def __str__(self):
        return f"log_plan_item('{self._level}', '{self.message}')"

    def __repr__(self):
        return str(self)

    def as_dict(self):
        return {self.type_: {"message": self.message, "level": self.level}}

    @property
    def json_api_relationships(self):
        return []

    @property
    def json_api_attributes(self):
        return ["message", "level"]


class GetDone(PlanItemWithSemanticContent):
    @classmethod
    def create_from_json_api_data(cls, data, included):
        action_entry = included.get_object_from_relationship(data["relationships"]["action"]["data"])
        action = Action.create_from_json_api_data(action_entry, included)
        step = data["attributes"]["step"]
        return cls(action, step)

    def __init__(self, action, step=None):
        PlanItemWithSemanticContent.__init__(self, TYPE_GET_DONE, action)
        self._step = step

    @property
    def step(self):
        return self._step

    @property
    def action(self):
        return self.content

    def as_dict(self):
        return {"step": self._step} | super().as_dict()

    @property
    def json_api_id(self):
        return f"{self.json_api_type}:{self.step}:{self.action}"

    @property
    def json_api_relationships(self):
        return ["action"]

    @property
    def json_api_attributes(self):
        return ["step"]


class GoalPerformed(PlanItem):
    @classmethod
    def create_from_json_api_data(cls, data, included):
        postconfirm = data["attributes"]["postconfirm"]
        try:
            action_entry = included.get_object_from_relationship(data["relationships"]["action"]["data"])
            action = Action.create_from_json_api_data(action_entry, included)
        except KeyError:
            action = None
        return cls(postconfirm, action)

    def __init__(self, postconfirm, action=None):
        PlanItem.__init__(self, TYPE_ACTION_PERFORMED)
        self._postconfirm = postconfirm
        self._action = action if action else ""

    def __eq__(self, other):
        if super().__eq__(other):
            return self.postconfirm == other.postconfirm and self.action == other.action
        return False

    def __str__(self):
        if self.action:
            return f"signal_action_completion({str(self.action.name)}, {str(self.postconfirm)})"
        return f"signal_action_completion({str(self.postconfirm)})"

    def __repr__(self):
        if self.action:
            return f"GoalPerformed('{self.action}', '{self.postconfirm}')"
        return f"GoalPerformed('{self.postconfirm}')"

    @property
    def postconfirm(self):
        return self._postconfirm

    @property
    def action(self):
        return self._action

    def as_dict(self):
        return {self.type_: self._postconfirm, "action": self.action}

    @property
    def json_api_id(self):
        if self.action:
            return f"{self.json_api_type}:{self.postconfirm}:{self.action.name}"
        return f"{self.json_api_type}:{self.postconfirm}"

    @property
    def json_api_attributes(self):
        return ["postconfirm"]

    @property
    def json_api_relationships(self):
        if self.action:
            return ["action"]
        return []


class GoalAborted(PlanItem):
    @classmethod
    def create_from_json_api_data(cls, data, included):
        reason = data["attributes"]["reason"]
        try:
            action_entry = included.get_object_from_relationship(data["relationships"]["action"]["data"])
            action = Action.create_from_json_api_data(action_entry, included)
        except KeyError:
            action = None
        return cls(reason, action)

    def __init__(self, reason, action=None):
        PlanItem.__init__(self, TYPE_ACTION_ABORTED)
        self._reason = reason
        self._action = action if action else ""

    def __eq__(self, other):
        if super().__eq__(other):
            if self.reason == other.reason and self.action == other.action:
                return True
        return False

    @property
    def reason(self):
        return self._reason

    @property
    def action(self):
        return self._action

    def __str__(self):
        return f"signal_action_failure('{self.reason}, {self.action}')"

    def __repr__(self):
        return f"GoalAborted('{self.reason}, {self.action}')"

    def as_dict(self):
        return {self.type_: self._reason, "action": self.action}

    @property
    def json_api_id(self):
        return f"{self.json_api_type}:{self.action}:{self.reason}"

    @property
    def json_api_attributes(self):
        return ["reason"]

    @property
    def json_api_relationships(self):
        if self.action:
            return ["action"]
        return []


class EndTurn(PlanItem):
    @classmethod
    def create_from_json_api_data(cls, endturn_data, included):
        return cls(endturn_data["attributes"]["timeout"])

    def __init__(self, timeout):
        PlanItem.__init__(self, TYPE_END_TURN)
        self._timeout = float(timeout)

    @property
    def timeout(self):
        return self._timeout

    def __str__(self):
        return f"end_turn({self.timeout})"

    def __repr__(self):
        return f"EndTurn({self.timeout})"

    def as_dict(self):
        return {self.type_: self._timeout}

    @property
    def json_api_id(self):
        return f"{self.json_api_type}:{self.timeout}"

    @property
    def json_api_attributes(self):
        return ["timeout", "type_"]

    @property
    def json_api_relationships(self):
        return []


class ResetDomainQuery(PlanItem):
    @classmethod
    def create_from_json_api_data(cls, data, included):
        query_entry = included.get_object_from_relationship(data["relationships"]["query"]["data"])
        query = Question.create_from_json_api_data(query_entry, included)
        return cls(query)

    def __init__(self, query):
        PlanItem.__init__(self, TYPE_RESET_DOMAIN_QUERY)
        self._query = query

    @property
    def query(self):
        return self._query

    def __str__(self):
        return f"reset_domain_query('{self.query}')"

    def __repr__(self):
        return f"ResetDomainQueryPlanItem('{self.query}')"

    def as_dict(self):
        return {self.type_: self._query}

    @property
    def json_api_id(self):
        return f"{self.json_api_type}:{self.query}"

    @property
    def json_api_attributes(self):
        return []

    @property
    def json_api_relationships(self):
        return ["query"]


class Iterate(PlanItemWithContent):
    @classmethod
    def create_from_json_api_data(cls, endturn_data, _included):
        return cls(endturn_data["attributes"]["iterator"])

    def __init__(self, iterator):
        PlanItemWithContent.__init__(self, TYPE_ITERATE, iterator)

    @property
    def iterator(self):
        return self._content

    def __str__(self):
        return f"iterate('{self.iterator}')"

    def __repr__(self):
        return f"IteratePlanItem('{self.iterator}')"

    @property
    def json_api_id(self):
        return f"{self.json_api_type}:{self.iterator}"

    @property
    def json_api_attributes(self):
        return ["iterator"]

    @property
    def json_api_relationships(self):
        return []


class ChangeDDD(PlanItem):
    @classmethod
    def create_from_json_api_data(cls, data, _included):
        return cls(data["attributes"]["ddd"])

    def __init__(self, ddd):
        PlanItem.__init__(self, TYPE_CHANGE_DDD)
        self._ddd = ddd

    @property
    def ddd(self):
        return self._ddd

    def __str__(self):
        return f"change_ddd('{self.ddd}')"

    def __repr__(self):
        return f"ChangeDDD('{self.ddd}')"

    def as_dict(self):
        return {self.type_: self._ddd}

    @property
    def json_api_id(self):
        return f"{self.json_api_type}:{self.ddd}"

    @property
    def json_api_attributes(self):
        return ["ddd"]

    @property
    def json_api_relationships(self):
        return []


class QuestionRaisingPlanItem(PlanItemWithSemanticContent):
    SOURCE_SERVICE = "service"
    SOURCE_DOMAIN = "domain"
    ALPHABETIC = "alphabetic"

    def __init__(self, domain_name, type_, content, allow_pcom_answer=False, alts_predicate=None):
        if not content.is_question():
            raise DomainError("cannot create QuestionRaisingPlanItem " + "from non-question %s" % content)
        self._domain_name = domain_name
        self._allow_answer_from_pcom = allow_pcom_answer
        self._alts_predicate = alts_predicate
        PlanItemWithSemanticContent.__init__(self, type_, content)

    @property
    def domain_name(self):
        return self._domain_name

    @property
    def allow_answer_from_pcom(self):
        return self._allow_answer_from_pcom

    @property
    def alts_predicate(self):
        return self._alts_predicate

    def is_question_raising_item(self):
        return True

    @property
    def question(self):
        return self.content

    def clone_as_type(self, type_):
        clone = copy.deepcopy(self)
        clone._type = type_
        return clone

    def __str__(self):
        if self._content is None:
            content_string = ""
        else:
            content_string = str(self._content)
        return "%s(%s)" % (str(self._type), content_string)

    def as_dict(self):
        result = {
            self.type_: self._content,
            "domain_name": self._domain_name,
            "allow_answer_from_pcom": self._allow_answer_from_pcom,
        }
        if self._alts_predicate is not None:
            result["alts_predicate"] = self._alts_predicate
        return result

    @property
    def json_api_type(self):
        if self._type == TYPE_FINDOUT:
            return f"{self.__class__.__module__}.Findout"
        if self._type == TYPE_RAISE:
            return f"{self.__class__.__module__}.Raise"
        if self._type == TYPE_BIND:
            return f"{self.__class__.__module__}.Bind"

    @property
    def json_api_id(self):
        id_ = f"{self.json_api_type}:{self.domain_name}:{self.content.json_api_id}:{self.allow_answer_from_pcom}"
        if self.alts_predicate is None:
            return id_
        return f"{id_}:{self.alts_predicate}"

    @property
    def json_api_attributes(self):
        attributes = ["type_", "domain_name", "allow_answer_from_pcom"]
        if self._alts_predicate is not None:
            attributes.append("alts_predicate")
        return attributes

    @property
    def json_api_relationships(self):
        return ["question"]


class Findout(QuestionRaisingPlanItem):
    @classmethod
    def create_from_json_api_data(cls, plan_item_data, included):
        question_entry = included.get_object_from_relationship(plan_item_data["relationships"]["question"]["data"])
        question = Question.create_from_json_api_data(question_entry, included)
        domain_name = plan_item_data["attributes"]["domain_name"]
        allow_answer_from_pcom = plan_item_data["attributes"]["allow_answer_from_pcom"]
        alts_predicate = plan_item_data["attributes"].get("alts_predicate")
        return cls(domain_name, question, allow_answer_from_pcom, alts_predicate)

    def __init__(self, domain_name, content, allow_answer_from_pcom=False, alts_predicate=None):
        QuestionRaisingPlanItem.__init__(
            self, domain_name, TYPE_FINDOUT, content, allow_answer_from_pcom, alts_predicate
        )


class Raise(QuestionRaisingPlanItem):
    @classmethod
    def create_from_json_api_data(cls, plan_item_data, included):
        question_entry = included.get_object_from_relationship(plan_item_data["relationships"]["question"]["data"])
        question = Question.create_from_json_api_data(question_entry, included)
        domain_name = plan_item_data["attributes"]["domain_name"]
        return cls(domain_name, question)

    def __init__(self, domain_name, content):
        QuestionRaisingPlanItem.__init__(self, domain_name, TYPE_RAISE, content)


class UnexpectedDomainException(Exception):
    pass


class QuestionRaisingPlanItemOfDomain:
    def __init__(self, domain, plan_item):
        if domain.name != plan_item.domain_name:
            raise UnexpectedDomainException(
                "Expected domain '%s' to match domain of plan item %s but it was '%s'" %
                (plan_item.domain_name, plan_item, domain)
            )
        self._domain = domain
        self._plan_item = plan_item

    @property
    def alternatives(self):
        return self._domain.get_alternatives(self._plan_item.question)

    @property
    def incremental(self):
        return self._domain.get_incremental(self._plan_item.question)

    @property
    def source(self):
        return self._domain.get_source(self._plan_item.question)

    @property
    def format(self):
        return self._domain.get_format(self._plan_item.question)

    @property
    def service_query(self):
        return self._domain.get_service_query(self._plan_item.question)

    @property
    def label_questions(self):
        return self._domain.get_label_questions(self._plan_item.question)

    def has_parameters(self):
        return self.alternatives \
            or self.incremental \
            or self.source \
            or self.format \
            or self.service_query \
            or self.label_questions

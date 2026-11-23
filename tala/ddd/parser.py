import copy
import re
from dataclasses import dataclass
from typing import Any

from tala.ddd.utils import CacheMethod
from tala.model.action_status import Done
from tala.model.ask_feature import AskFeature
from tala.model.goal import Perform, Resolve
from tala.model.individual import Yes, No
from tala.model.lambda_abstraction import (
    LambdaAbstractedGoalProposition, LambdaAbstractedImplicationPropositionForConsequent
)
from tala.model import speaker
from tala.model.set import Set
from tala.model.move_base import (
    Answer,
    Ask,
    Greet,
    Insult,
    InsultResponse,
    Move,
    Mute,
    Prereport,
    Quit,
    Report,
    Request,
    ThankYou,
    ThankYouResponse,
    Unmute,
)
from tala.model.move_icm import ICM
from tala.model.ontology import OntologyError
from tala.model import plan_item
from tala.model import condition as condition_module
from tala.model.polarity import Polarity
from tala.model.proposition import (
    GoalProposition, PropositionSet, ServiceActionStartedProposition, ServiceActionTerminatedProposition,
    ServiceResultProposition, ResolvednessProposition, PreconfirmationProposition, UnderstandingProposition,
    RejectedPropositions, PrereportProposition, PredicateProposition, KnowledgePreconditionProposition,
    ImplicationProposition, ActionStatusProposition
)
from tala.model.question import (
    AltQuestion, YesNoQuestion, WhQuestion, KnowledgePreconditionQuestion, ConsequentQuestion
)
from tala.model.service_action_outcome import SuccessfulServiceAction, FailedServiceAction
from tala.model.person_name import PersonName
from tala.model.date_time import DateTime
from tala.ddd.json_parser import CheckingJSONParser, JSONParseFailure


class ParseError(Exception):
    pass


class ParseFailure(Exception):
    pass


@dataclass(frozen=True)
class _Token:
    type_: str
    value: str
    raw: str
    position: int


class _Tokenizer:
    _SYMBOLS = set("()[]{},:*=?~.-")

    def __init__(self, text):
        self._text = text
        self._index = 0

    def tokenize(self):
        tokens = []
        while self._index < len(self._text):
            char = self._text[self._index]
            if char.isspace():
                self._index += 1
                continue
            if char.isdigit():
                tokens.append(self._read_number())
                continue
            if char in ["\"", "'"]:
                tokens.append(self._read_string(char))
                continue
            if char.isalpha() or char == "_":
                tokens.append(self._read_identifier())
                continue
            if char in self._SYMBOLS:
                tokens.append(_Token("SYMBOL", char, char, self._index))
                self._index += 1
                continue
            raise ParseError(f"Unexpected character '{char}' at position {self._index}")
        tokens.append(_Token("EOF", "", "", self._index))
        return tokens

    def _read_number(self):
        start = self._index
        while self._index < len(self._text) and self._text[self._index].isdigit():
            self._index += 1
        if self._index < len(self._text) and self._text[self._index] == ".":
            if self._index + 1 < len(self._text) and self._text[self._index + 1].isdigit():
                self._index += 1
                while self._index < len(self._text) and self._text[self._index].isdigit():
                    self._index += 1
        raw = self._text[start:self._index]
        return _Token("NUMBER", raw, raw, start)

    def _read_string(self, quote):
        start = self._index
        self._index += 1
        escaped = False
        while self._index < len(self._text):
            char = self._text[self._index]
            if escaped:
                escaped = False
                self._index += 1
                continue
            if char == "\\":
                escaped = True
                self._index += 1
                continue
            if char == quote:
                raw = self._text[start:self._index + 1]
                value = self._text[start + 1:self._index]
                self._index += 1
                return _Token("STRING", value, raw, start)
            self._index += 1
        raise ParseError(f"Unterminated string starting at position {start}")

    def _read_identifier(self):
        start = self._index
        self._index += 1
        while self._index < len(self._text):
            char = self._text[self._index]
            if char.isalnum() or char in ["_", "-"]:
                self._index += 1
                continue
            break
        raw = self._text[start:self._index]
        return _Token("IDENT", raw, raw, start)


class _TokenStream:
    def __init__(self, tokens, text):
        self._tokens = tokens
        self._index = 0
        self._text = text

    def peek(self, offset=0):
        index = min(self._index + offset, len(self._tokens) - 1)
        return self._tokens[index]

    def advance(self):
        token = self.peek()
        self._index = min(self._index + 1, len(self._tokens) - 1)
        return token

    def match(self, type_=None, value=None, offset=0):
        token = self.peek(offset)
        if type_ is not None and token.type_ != type_:
            return False
        if value is not None and token.value != value:
            return False
        return True

    def match_ident(self, value, offset=0):
        return self.match(type_="IDENT", value=value, offset=offset)

    def match_ident_in(self, values, offset=0):
        token = self.peek(offset)
        return token.type_ == "IDENT" and token.value in values

    def match_symbol(self, value, offset=0):
        return self.match(type_="SYMBOL", value=value, offset=offset)

    def _context(self, position):
        start = max(0, position - 20)
        end = min(len(self._text), position + 20)
        snippet = self._text[start:end].replace("\n", " ")
        return snippet

    def consume(self, type_=None, value=None):
        if not self.match(type_=type_, value=value):
            token = self.peek()
            expected = value if value is not None else type_
            context = self._context(token.position)
            raise ParseFailure(f"Expected {expected} at position {token.position} near '{context}'")
        return self.advance()

    def consume_ident(self, value=None):
        return self.consume(type_="IDENT", value=value)

    def consume_symbol(self, value=None):
        return self.consume(type_="SYMBOL", value=value)

    def at_end(self):
        return self.match(type_="EOF")


@dataclass(frozen=True)
class _AstNode:
    kind: str
    value: Any


class _RecursiveDescentParser:
    def __init__(self, parser):
        self._parser = parser
        self._stream = None

    def parse(self, text):
        self._stream = _TokenStream(_Tokenizer(text).tokenize(), text)
        node = self._parse_expression()
        if not self._stream.at_end():
            token = self._stream.peek()
            context = self._stream._context(token.position)
            raise ParseFailure(f"Unexpected token '{token.raw}' at position {token.position} near '{context}'")
        return node

    def _parse_expression(self):
        if self._stream.match_ident("yes") or self._stream.match_ident("no"):
            return _AstNode("yes_no", self._stream.consume_ident().value)
        if self._stream.match_symbol("{"):
            return self._parse_set_literal()
        if self._stream.match_ident("Move") and self._stream.match_symbol("(", offset=1):
            return self._parse_decorated_move()
        if self._stream.match_ident("ICM") and self._stream.match_symbol("(", offset=1):
            return self._parse_decorated_icm()
        if self._stream.match_symbol("?"):
            return self._parse_question_expression()
        if self._stream.match_ident("icm") and self._stream.match_symbol(":", offset=1):
            return self._parse_icm_expression()
        if self._stream.match_ident("if"):
            return self._parse_if_then_else()
        if self._stream.match_ident("forget_all"):
            return self._parse_plan_item("forget_all")
        if self._stream.match_ident_in(["perform", "resolve", "resolve_user"]) and self._stream.match_symbol(
            "(", offset=1
        ):
            return self._parse_goal_expression()
        if self._stream.match_ident_in(self._basic_move_types()):
            return self._parse_basic_move()
        if self._stream.match_ident_in(self._move_with_content_types()):
            return self._parse_move_with_content()
        if self._stream.match_ident_in(self._plan_item_types()):
            return self._parse_plan_item()
        return self._parse_proposition_or_terminal()

    def _basic_move_types(self):
        return {
            Move.GREET,
            Move.MUTE,
            Move.UNMUTE,
            Move.QUIT,
            Move.THANK_YOU,
            Move.THANK_YOU_RESPONSE,
            Move.INSULT_RESPONSE,
            Move.INSULT,
        }

    def _move_with_content_types(self):
        return {Move.ASK, Move.ANSWER, Move.REQUEST, Move.REPORT, Move.PREREPORT}

    def _plan_item_types(self):
        return {
            "findout",
            "do",
            "raise",
            "bind",
            "respond",
            "jumpto",
            "forget",
            "forget_shared",
            "forget_instructional_plan",
            "assume",
            "assume_shared",
            "assume_issue",
            "insist_assume_issue",
            "signal_action_completion",
            "signal_action_failure",
            "log",
            "forget_issue",
            "invoke_service_query",
            "invoke_service_action",
            "change_ddd",
        }

    def _parse_decorated_move(self):
        self._stream.consume_ident("Move")
        self._stream.consume_symbol("(")
        move = self._parse_expression()
        realization = self._parse_optional_params()
        self._stream.consume_symbol(")")
        return _AstNode("move_decorated", {"move": move, "realization": realization})

    def _parse_decorated_icm(self):
        self._stream.consume_ident("ICM")
        self._stream.consume_symbol("(")
        icm = self._parse_icm_expression()
        realization = self._parse_optional_params()
        self._stream.consume_symbol(")")
        return _AstNode("icm_decorated", {"icm": icm, "realization": realization})

    def _parse_optional_params(self):
        if not self._stream.match_symbol(","):
            return None
        self._stream.consume_symbol(",")
        return self._parse_key_value_pairs()

    def _parse_basic_move(self):
        move_type = self._stream.consume_ident().value
        return _AstNode("move", {"type": move_type, "content": None})

    def _parse_move_with_content(self):
        move_type = self._stream.consume_ident().value
        self._stream.consume_symbol("(")
        if move_type == Move.ANSWER:
            content = self._parse_answer_content()
        elif move_type == Move.REQUEST:
            content = _AstNode("action", self._stream.consume_ident().value)
        elif move_type == Move.ASK:
            content = self._parse_question_expression()
        elif move_type == Move.REPORT:
            content = self._parse_expression()
        elif move_type == Move.PREREPORT:
            action_name = self._parse_identifier_or_literal()
            self._stream.consume_symbol(",")
            args = self._parse_bracketed_list(self._parse_proposition_expression)
            content = _AstNode("prereport_content", {"action": action_name, "args": args})
        else:
            raise ParseFailure()
        self._stream.consume_symbol(")")
        return _AstNode("move", {"type": move_type, "content": content})

    def _parse_answer_content(self):
        if self._stream.match_ident("yes") or self._stream.match_ident("no"):
            return _AstNode("yes_no", self._stream.consume_ident().value)
        return self._parse_proposition_or_terminal()

    def _parse_question_expression(self):
        self._stream.consume_symbol("?")
        content = self._parse_expression()
        return _AstNode("question", {"content": content})

    def _parse_icm_expression(self):
        self._stream.consume_ident("icm")
        self._stream.consume_symbol(":")
        icm_type = self._stream.consume_ident().value
        if icm_type == ICM.LOADPLAN:
            return _AstNode("icm", {"type": icm_type, "polarity": None, "content": None, "content_speaker": None})
        if icm_type in [ICM.RERAISE, ICM.ACCOMMODATE, ICM.RESUME]:
            if self._stream.match_symbol(":"):
                self._stream.consume_symbol(":")
                content = self._parse_expression()
                return _AstNode(
                    "icm", {
                        "type": icm_type,
                        "polarity": None,
                        "content": content,
                        "content_speaker": None
                    }
                )
            return _AstNode("icm", {"type": icm_type, "polarity": None, "content": None, "content_speaker": None})
        self._stream.consume_symbol("*")
        polarity = self._stream.consume_ident().value
        content = None
        content_speaker = None
        if self._stream.match_symbol(":"):
            self._stream.consume_symbol(":")
            if icm_type in [ICM.PER, ICM.ACC] and self._stream.match_ident("issue"):
                self._stream.consume_ident("issue")
                content = _AstNode("issue_literal", "issue")
            elif icm_type in [ICM.PER, ICM.ACC] and self._stream.match(type_="STRING"):
                content = _AstNode("string_literal", self._stream.consume(type_="STRING").raw)
            else:
                if self._stream.match(type_="IDENT") and self._stream.match_symbol("*", offset=1):
                    content_speaker = self._stream.consume_ident().value
                    self._stream.consume_symbol("*")
                content = self._parse_expression()
        return _AstNode(
            "icm",
            {
                "type": icm_type,
                "polarity": polarity,
                "content": content,
                "content_speaker": content_speaker,
            },
        )

    def _parse_if_then_else(self):
        self._stream.consume_ident("if")
        condition = self._parse_expression()
        self._stream.consume_ident("then")
        consequent = []
        if not self._stream.match_ident("else"):
            consequent = [self._parse_expression()]
        self._stream.consume_ident("else")
        alternative = []
        if not self._stream.at_end():
            alternative = [self._parse_expression()]
        return _AstNode(
            "plan_item",
            {
                "type": "if",
                "condition": condition,
                "consequent": consequent,
                "alternative": alternative
            },
        )

    def _parse_plan_item(self, forced_type=None):
        plan_type = forced_type
        if plan_type is not None:
            self._stream.consume_ident(plan_type)
        else:
            plan_type = self._stream.consume_ident().value
        if plan_type == "forget_all":
            return _AstNode("plan_item", {"type": plan_type, "content": None})
        self._stream.consume_symbol("(")
        if plan_type in ["findout", "raise", "bind", "respond"]:
            question = self._parse_question_expression()
            content = question
        elif plan_type == "forget_instructional_plan":
            action = self._parse_action_expression()
            self._stream.consume_symbol(",")
            params = self._parse_curly_params()
            if set(params) != {"include_children"}:
                raise ParseFailure()
            content = _AstNode(
                "forget_instructional_plan",
                {
                    "action": action,
                    "include_children": params["include_children"]
                },
            )
        elif plan_type in ["forget", "forget_shared", "assume", "assume_shared"]:
            content = self._parse_expression()
        elif plan_type == "assume_issue":
            content = self._parse_expression()
        elif plan_type == "insist_assume_issue":
            content = self._parse_expression()
        elif plan_type == "do":
            content = self._parse_action_expression()
        elif plan_type == "forget_issue":
            content = self._parse_expression()
        elif plan_type == "invoke_service_query":
            content = self._parse_question_expression()
        elif plan_type == "invoke_service_action":
            action = self._parse_identifier_or_literal()
            params = None
            if self._stream.match_symbol(","):
                self._stream.consume_symbol(",")
                params = self._parse_curly_params()
            content = _AstNode("invoke_service_action", {"action": action, "params": params})
        elif plan_type == "change_ddd":
            content = self._parse_identifier_or_literal()
        elif plan_type == "signal_action_completion":
            content = self._parse_signal_action_completion()
        elif plan_type == "signal_action_failure":
            content = self._parse_signal_action_failure()
        elif plan_type == "log":
            content = self._parse_string_literal()
        elif plan_type == "jumpto":
            content = self._parse_goal_expression()
        else:
            raise ParseFailure()
        self._stream.consume_symbol(")")
        return _AstNode("plan_item", {"type": plan_type, "content": content})

    def _parse_goal_expression(self):
        goal_type = self._stream.consume_ident().value
        if goal_type == "perform":
            self._stream.consume_symbol("(")
            action = self._parse_action_expression()
            self._stream.consume_symbol(")")
            return _AstNode("goal", {"type": "perform", "content": action})
        if goal_type in ["resolve", "resolve_user"]:
            self._stream.consume_symbol("(")
            question = self._parse_question_expression()
            self._stream.consume_symbol(")")
            return _AstNode("goal", {"type": goal_type, "content": question})
        raise ParseFailure()

    def _parse_action_expression(self):
        if not self._stream.match(type_="IDENT"):
            raise ParseFailure()
        return _AstNode("action", self._stream.consume_ident().value)

    def _parse_proposition_or_terminal(self):
        if self._stream.match_symbol("~"):
            return self._parse_proposition_expression()
        if self._stream.match_ident("set"):
            return self._parse_proposition_expression()
        if self._stream.match_ident("goal"):
            return self._parse_proposition_expression()
        if self._stream.match_ident("preconfirmed"):
            return self._parse_proposition_expression()
        if self._stream.match_ident("prereported"):
            return self._parse_proposition_expression()
        if self._stream.match_ident("service_action_terminated"):
            return self._parse_proposition_expression()
        if self._stream.match_ident("service_action_started"):
            return self._parse_proposition_expression()
        if self._stream.match_ident("action_status"):
            return self._parse_proposition_expression()
        if self._stream.match_ident("resolved"):
            return self._parse_proposition_expression()
        if self._stream.match_ident("know_answer"):
            return self._parse_proposition_expression()
        if self._stream.match_ident("implies"):
            return self._parse_proposition_expression()
        if self._stream.match_ident("und"):
            return self._parse_proposition_expression()
        if self._stream.match_ident("rejected"):
            return self._parse_proposition_expression()
        if self._stream.match_ident("ServiceResultProposition"):
            return self._parse_proposition_expression()
        if self._stream.match_ident("SuccessfulServiceAction") or self._stream.match_ident("FailedServiceAction"):
            return self._parse_proposition_expression()
        if self._stream.match_ident("X") and self._stream.match_symbol(".", offset=1):
            return self._parse_proposition_expression()
        if self._stream.match(type_="IDENT") and self._stream.match_symbol("(", offset=1):
            if self._parser.ontology.has_predicate(self._stream.peek().value):
                return self._parse_proposition_expression()
            return _AstNode("literal", self._parse_call_expression())
        if self._stream.match(type_="STRING"):
            return _AstNode("literal", self._stream.consume(type_="STRING").raw)
        if self._stream.match(type_="NUMBER"):
            return _AstNode("literal", self._stream.consume(type_="NUMBER").raw)
        if self._stream.match(type_="IDENT"):
            return _AstNode("identifier", self._stream.consume_ident().value)
        raise ParseFailure()

    def _parse_proposition_expression(self):
        polarity = None
        if self._stream.match_symbol("~"):
            self._stream.consume_symbol("~")
            polarity = "neg"
        if self._stream.match_ident("goal"):
            self._stream.consume_ident("goal")
            self._stream.consume_symbol("(")
            goal = self._parse_goal_expression()
            self._stream.consume_symbol(")")
            return _AstNode("proposition", {"type": "goal", "goal": goal, "polarity": polarity})
        if self._stream.match_ident("set"):
            self._stream.consume_ident("set")
            self._stream.consume_symbol("(")
            propositions = self._parse_bracketed_list(self._parse_proposition_expression)
            self._stream.consume_symbol(")")
            return _AstNode("proposition", {"type": "set", "items": propositions, "polarity": polarity})
        if self._stream.match_ident("preconfirmed"):
            self._stream.consume_ident("preconfirmed")
            self._stream.consume_symbol("(")
            action = self._parse_identifier_or_literal()
            self._stream.consume_symbol(",")
            params = self._parse_bracketed_list(self._parse_proposition_expression)
            self._stream.consume_symbol(")")
            return _AstNode(
                "proposition",
                {
                    "type": "preconfirmed",
                    "action": action,
                    "params": params,
                    "polarity": polarity
                },
            )
        if self._stream.match_ident("prereported"):
            self._stream.consume_ident("prereported")
            self._stream.consume_symbol("(")
            action = self._parse_identifier_or_literal()
            self._stream.consume_symbol(",")
            params = self._parse_bracketed_list(self._parse_proposition_expression)
            self._stream.consume_symbol(")")
            return _AstNode("proposition", {"type": "prereported", "action": action, "params": params})
        if self._stream.match_ident("service_action_terminated"):
            self._stream.consume_ident("service_action_terminated")
            self._stream.consume_symbol("(")
            action = self._parse_identifier_or_literal()
            self._stream.consume_symbol(")")
            return _AstNode("proposition", {"type": "service_action_terminated", "action": action})
        if self._stream.match_ident("service_action_started"):
            self._stream.consume_ident("service_action_started")
            self._stream.consume_symbol("(")
            action = self._parse_identifier_or_literal()
            self._stream.consume_symbol(")")
            return _AstNode("proposition", {"type": "service_action_started", "action": action})
        if self._stream.match_ident("action_status"):
            self._stream.consume_ident("action_status")
            self._stream.consume_symbol("(")
            action = self._parse_identifier_or_literal()
            self._stream.consume_symbol(",")
            status = self._parse_identifier_or_literal()
            self._stream.consume_symbol(")")
            return _AstNode("proposition", {"type": "action_status", "action": action, "status": status})
        if self._stream.match_ident("resolved"):
            self._stream.consume_ident("resolved")
            self._stream.consume_symbol("(")
            question = self._parse_expression()
            self._stream.consume_symbol(")")
            return _AstNode("proposition", {"type": "resolved", "question": question})
        if self._stream.match_ident("know_answer"):
            self._stream.consume_ident("know_answer")
            self._stream.consume_symbol("(")
            question = self._parse_expression()
            self._stream.consume_symbol(")")
            return _AstNode("proposition", {"type": "know_answer", "question": question, "polarity": polarity})
        if self._stream.match_ident("implies"):
            self._stream.consume_ident("implies")
            self._stream.consume_symbol("(")
            antecedent = self._parse_proposition_expression()
            self._stream.consume_symbol(",")
            consequent = self._parse_proposition_expression()
            self._stream.consume_symbol(")")
            return _AstNode("proposition", {"type": "implies", "antecedent": antecedent, "consequent": consequent})
        if self._stream.match_ident("und"):
            self._stream.consume_ident("und")
            self._stream.consume_symbol("(")
            speaker_value = self._parse_identifier_or_literal()
            self._stream.consume_symbol(",")
            proposition = self._parse_expression()
            self._stream.consume_symbol(")")
            return _AstNode(
                "proposition",
                {
                    "type": "understanding",
                    "speaker": speaker_value,
                    "proposition": proposition,
                    "polarity": polarity,
                },
            )
        if self._stream.match_ident("rejected"):
            self._stream.consume_ident("rejected")
            self._stream.consume_symbol("(")
            content = self._parse_expression()
            reason = None
            if self._stream.match_symbol(","):
                self._stream.consume_symbol(",")
                reason = self._parse_identifier_or_literal()
            self._stream.consume_symbol(")")
            return _AstNode("proposition", {"type": "rejected", "content": content, "reason": reason})
        if self._stream.match_ident("ServiceResultProposition"):
            self._stream.consume_ident("ServiceResultProposition")
            self._stream.consume_symbol("(")
            action = self._parse_identifier_or_literal()
            self._stream.consume_symbol(",")
            params = self._parse_bracketed_list(self._parse_proposition_expression)
            self._stream.consume_symbol(",")
            outcome = self._parse_proposition_or_terminal()
            self._stream.consume_symbol(")")
            return _AstNode(
                "proposition",
                {
                    "type": "service_result",
                    "action": action,
                    "params": params,
                    "outcome": outcome
                },
            )
        if self._stream.match_ident("SuccessfulServiceAction"):
            self._stream.consume_ident("SuccessfulServiceAction")
            self._stream.consume_symbol("(")
            self._stream.consume_symbol(")")
            return _AstNode("proposition", {"type": "service_outcome", "status": "success"})
        if self._stream.match_ident("FailedServiceAction"):
            self._stream.consume_ident("FailedServiceAction")
            self._stream.consume_symbol("(")
            reason = self._parse_identifier_or_literal()
            self._stream.consume_symbol(")")
            return _AstNode("proposition", {"type": "service_outcome", "status": "failed", "reason": reason})
        if self._stream.match_ident("X") and self._stream.match_symbol(".", offset=1):
            return self._parse_lambda_proposition()
        if self._stream.match(type_="IDENT") and self._stream.match_symbol("(", offset=1):
            predicate_name = self._stream.consume_ident().value
            self._stream.consume_symbol("(")
            individual = None
            if not self._stream.match_symbol(")"):
                individual = self._parse_raw_until_closing_paren()
            self._stream.consume_symbol(")")
            if predicate_name == "action":
                raise ParseError(
                    "'action(%s)' is not a valid proposition. Perhaps you mean 'goal(perform(%s))'." %
                    (individual, individual)
                )
            if predicate_name == "issue":
                raise ParseError(
                    "'issue(%s)' is not a valid proposition. Perhaps you mean 'goal(resolve(%s))'." %
                    (individual, individual)
                )
            if not self._parser.ontology.has_predicate(predicate_name):
                if polarity is not None:
                    if individual is None:
                        return _AstNode("literal", f"~{predicate_name}()")
                    return _AstNode("literal", f"~{predicate_name}({individual})")
                raise ParseFailure()
            return _AstNode(
                "proposition",
                {
                    "type": "predicate",
                    "predicate": predicate_name,
                    "individual": individual,
                    "polarity": polarity
                },
            )
        if polarity is not None:
            return _AstNode("literal", f"~{self._parse_identifier_or_literal()}")
        raise ParseFailure()

    def _parse_call_expression(self):
        name = self._stream.consume_ident().value
        self._stream.consume_symbol("(")
        if self._stream.match_symbol(")"):
            self._stream.consume_symbol(")")
            return f"{name}()"
        inner = self._parse_raw_until_closing_paren()
        self._stream.consume_symbol(")")
        if name == "action":
            raise ParseError(
                "'action(%s)' is not a valid proposition. Perhaps you mean 'goal(perform(%s))'." % (inner, inner)
            )
        if name == "issue":
            raise ParseError(
                "'issue(%s)' is not a valid proposition. Perhaps you mean 'goal(resolve(%s))'." % (inner, inner)
            )
        return f"{name}({inner})"

    def _parse_lambda_proposition(self):
        self._stream.consume_ident("X")
        self._stream.consume_symbol(".")
        name = self._stream.consume_ident().value
        if name == "goal":
            self._stream.consume_symbol("(")
            self._stream.consume_ident("X")
            self._stream.consume_symbol(")")
            return _AstNode("proposition", {"type": "lambda_goal"})
        if name == "implies":
            self._stream.consume_symbol("(")
            antecedent = self._parse_proposition_expression()
            self._stream.consume_symbol(",")
            predicate_name = self._stream.consume_ident().value
            self._stream.consume_symbol("(")
            self._stream.consume_ident("X")
            self._stream.consume_symbol(")")
            self._stream.consume_symbol(")")
            return _AstNode(
                "proposition",
                {
                    "type": "lambda_implication",
                    "antecedent": antecedent,
                    "predicate": predicate_name
                },
            )
        self._stream.consume_symbol("(")
        self._stream.consume_ident("X")
        self._stream.consume_symbol(")")
        return _AstNode("proposition", {"type": "lambda_predicate", "predicate": name})

    def _parse_signal_action_completion(self):
        value = self._parse_identifier_or_literal()
        action = None
        if self._stream.match_symbol(","):
            self._stream.consume_symbol(",")
            action = self._parse_identifier_or_literal()
        return _AstNode("signal_action_completion", {"postconfirm": value, "action": action})

    def _parse_signal_action_failure(self):
        reason = self._parse_identifier_or_literal()
        action = None
        if self._stream.match_symbol(","):
            self._stream.consume_symbol(",")
            action = self._parse_identifier_or_literal()
        return _AstNode("signal_action_failure", {"reason": reason, "action": action})

    def _parse_set_literal(self):
        self._stream.consume_symbol("{")
        items = []
        if not self._stream.match_symbol("}"):
            items = self._parse_comma_separated(self._parse_expression)
        self._stream.consume_symbol("}")
        return _AstNode("set_literal", items)

    def _parse_curly_params(self):
        self._stream.consume_symbol("{")
        params = {}
        if not self._stream.match_symbol("}"):
            params = self._parse_key_value_pairs()
        self._stream.consume_symbol("}")
        return params

    def _parse_key_value_pairs(self):
        params = {}
        while True:
            key = self._stream.consume_ident().value
            self._stream.consume_symbol("=")
            value = self._parse_identifier_or_literal()
            params[key] = value
            if not self._stream.match_symbol(","):
                break
            self._stream.consume_symbol(",")
        return params

    def _parse_identifier_or_literal(self):
        if self._stream.match(type_="STRING"):
            return self._stream.consume(type_="STRING").raw
        if self._stream.match(type_="NUMBER"):
            return self._stream.consume(type_="NUMBER").raw
        return self._stream.consume_ident().value

    def _parse_string_literal(self):
        return self._stream.consume(type_="STRING").raw

    def _parse_bracketed_list(self, item_parser):
        self._stream.consume_symbol("[")
        items = []
        if not self._stream.match_symbol("]"):
            items = self._parse_comma_separated(item_parser)
        self._stream.consume_symbol("]")
        return items

    def _parse_comma_separated(self, item_parser):
        items = [item_parser()]
        while self._stream.match_symbol(","):
            self._stream.consume_symbol(",")
            items.append(item_parser())
        return items

    def _parse_raw_until_closing_paren(self):
        start_index = self._stream.peek().position
        depth = 0
        while True:
            token = self._stream.peek()
            if token.type_ == "EOF":
                context = self._stream._context(token.position)
                raise ParseFailure(f"Expected ')' before end of input near '{context}'")
            if token.type_ == "SYMBOL":
                if token.value == "(":
                    depth += 1
                elif token.value == ")":
                    if depth == 0:
                        end_index = token.position
                        return self._stream._text[start_index:end_index]
                    depth -= 1
            self._stream.advance()


class _AstBuilder:
    def __init__(self, parser):
        self._parser = parser

    def build(self, node):
        if isinstance(node, _AstNode):
            method = getattr(self, f"_build_{node.kind}", None)
            if method:
                return method(node.value)
        return node

    def _build_move_decorated(self, value):
        move = self.build(value["move"])
        realization = value.get("realization")
        if realization:
            realization_data = self._build_realization_data(realization)
            move.set_realization_data(**realization_data)
        return move

    def _build_icm_decorated(self, value):
        icm = self.build(value["icm"])
        realization = value.get("realization")
        if realization:
            realization_data = self._build_realization_data(realization)
            icm.set_realization_data(**realization_data)
        return icm

    def _build_realization_data(self, realization):
        realization_data = dict()
        for key, value_as_string in realization.items():
            if key == "speaker":
                value = value_as_string
            elif key == "perception_confidence":
                value = float(value_as_string)
            elif key == "understanding_confidence":
                value = float(value_as_string)
            elif key == "utterance" or key == "ddd_name":
                value = self._parser._strip_quotes(value_as_string)
            else:
                raise ParseFailure("unsupported realization attribute '%s'" % key)
            realization_data[key] = value
        return realization_data

    def _build_move(self, value):
        move_type = value["type"]
        content = value.get("content")
        if move_type == Move.GREET:
            return Greet()
        if move_type == Move.MUTE:
            return Mute()
        if move_type == Move.UNMUTE:
            return Unmute()
        if move_type == Move.QUIT:
            return Quit()
        if move_type == Move.THANK_YOU:
            return ThankYou()
        if move_type == Move.THANK_YOU_RESPONSE:
            return ThankYouResponse()
        if move_type == Move.INSULT_RESPONSE:
            return InsultResponse()
        if move_type == Move.INSULT:
            return Insult()
        if move_type == Move.ANSWER:
            return Answer(self.build(content))
        if move_type == Move.REQUEST:
            action = self.build(content)
            return Request(action)
        if move_type == Move.ASK:
            question = self.build(content)
            return Ask(question)
        if move_type == Move.REPORT:
            report_content = self.build(content)
            return Report(report_content)
        if move_type == Move.PREREPORT:
            prereport_content = content
            action = prereport_content.value["action"]
            arguments = [self.build(arg) for arg in prereport_content.value["args"]]
            return Prereport(self._parser.ontology_name, action, arguments)
        raise ParseFailure()

    def _build_icm(self, value):
        icm_type = value["type"]
        polarity = value["polarity"]
        content = value.get("content")
        content_speaker = value.get("content_speaker")
        if icm_type == ICM.LOADPLAN:
            return ICM(ICM.LOADPLAN)
        if icm_type in [ICM.RERAISE, ICM.ACCOMMODATE, ICM.RESUME]:
            if content is not None:
                return ICM.create(icm_type, content=self.build(content))
            return ICM(icm_type)
        if content is None:
            return ICM(icm_type, polarity=polarity)
        built_content = self.build(content)
        if icm_type in [ICM.PER, ICM.ACC] and isinstance(content, _AstNode) and content.kind == "string_literal":
            built_content = self._parser._strip_quotes(content.value)
        if icm_type in [ICM.PER, ICM.ACC] and isinstance(built_content, str) and built_content == "issue":
            return ICM.create(icm_type, content="issue", polarity=polarity)
        return ICM.create(icm_type, content=built_content, content_speaker=content_speaker, polarity=polarity)

    def _build_question(self, value):
        content = self.build(value["content"])
        try:
            if content.is_knowledge_precondition_proposition():
                return KnowledgePreconditionQuestion(content.embedded_question)
        except AttributeError:
            pass
        try:
            if content.is_lambda_abstracted_predicate_proposition():
                return WhQuestion(content)
        except AttributeError:
            pass
        try:
            if content.is_lambda_abstracted_goal_proposition():
                return WhQuestion(content)
        except AttributeError:
            pass
        try:
            if content.is_proposition_set():
                return AltQuestion(content)
        except AttributeError:
            pass
        try:
            if content.is_proposition():
                return YesNoQuestion(content)
        except AttributeError:
            pass
        try:
            if content.is_lambda_abstracted_implication_proposition_for_consequent():
                return ConsequentQuestion(content)
        except AttributeError:
            pass
        if content.is_predicate():
            predicate = content
            if predicate.sort.is_boolean_sort():
                return YesNoQuestion(PredicateProposition(predicate))
        raise ParseFailure()

    def _build_plan_item(self, value):
        plan_type = value["type"]
        content = value.get("content")
        if plan_type == "forget_all":
            return plan_item.ForgetAll()
        if plan_type == "forget_instructional_plan":
            action = self.build(content.value["action"])
            include_children = self._parser._parse_boolean(content.value["include_children"])
            return plan_item.ForgetInstructionalPlan(action, include_children)
        if plan_type == "findout":
            return plan_item.Findout(self._parser.domain_name, self.build(content))
        if plan_type == "raise":
            return plan_item.Raise(self._parser.domain_name, self.build(content))
        if plan_type == "bind":
            return plan_item.Bind(self.build(content))
        if plan_type == "respond":
            return plan_item.Respond(self.build(content))
        if plan_type == "forget":
            return plan_item.Forget(self.build(content))
        if plan_type == "forget_shared":
            return plan_item.ForgetShared(self.build(content))
        if plan_type == "assume":
            return plan_item.Assume(self.build(content))
        if plan_type == "assume_shared":
            return plan_item.AssumeShared(self.build(content))
        if plan_type == "assume_issue":
            return plan_item.AssumeIssue(self.build(content))
        if plan_type == "insist_assume_issue":
            return plan_item.AssumeIssue(self.build(content), insist=True)
        if plan_type == "do":
            return plan_item.Do(self.build(content))
        if plan_type == "forget_issue":
            return plan_item.ForgetIssue(self.build(content))
        if plan_type == "invoke_service_query":
            return plan_item.InvokeServiceQuery(self.build(content), min_results=1, max_results=1)
        if plan_type == "invoke_service_action":
            action = content.value["action"]
            params = content.value.get("params") or {}
            parsed_params = {}
            for key, value_as_string in params.items():
                if key == "postconfirm":
                    parsed_params[key] = self._parser._parse_boolean(value_as_string)
                elif key == "preconfirm":
                    parsed_params[key] = self._parser.parse_preconfirm_value(value_as_string)
                elif key == "downdate_plan":
                    parsed_params[key] = self._parser._parse_boolean(value_as_string)
                else:
                    raise ParseFailure()
            return plan_item.InvokeServiceAction(self._parser.ontology.name, action, **parsed_params)
        if plan_type == "change_ddd":
            return plan_item.ChangeDDD(content)
        if plan_type == "signal_action_completion":
            completion = content
            postconfirm = self._parser._parse_boolean(completion.value["postconfirm"])
            action = completion.value.get("action")
            if action:
                return plan_item.GoalPerformed(postconfirm, self._parser._parse_action(action))
            return plan_item.GoalPerformed(postconfirm)
        if plan_type == "signal_action_failure":
            failure = content
            reason = failure.value["reason"]
            action = failure.value.get("action")
            if action:
                return plan_item.GoalAborted(reason, self._parser._parse_action(action))
            return plan_item.GoalAborted(reason)
        if plan_type == "log":
            return plan_item.Log(self._parser._strip_quotes(content))
        if plan_type == "jumpto":
            return plan_item.JumpTo(self.build(content))
        if plan_type == "if":
            condition = self.build(value["condition"])
            if hasattr(condition, "is_proposition") and condition.is_proposition():
                condition = condition_module.InBeliefsOrCommitments(condition)
            consequent = [self.build(item) for item in value["consequent"]]
            alternative = [self.build(item) for item in value["alternative"]]
            return plan_item.IfThenElse(condition, consequent, alternative)
        raise ParseFailure()

    def _build_goal(self, value):
        goal_type = value["type"]
        content = self.build(value["content"])
        if goal_type == "perform":
            if hasattr(content, "is_goal") and content.is_goal():
                return content
            return Perform(content)
        if goal_type == "resolve":
            return Resolve(content, speaker.SYS)
        if goal_type == "resolve_user":
            return Resolve(content, speaker.USR)
        raise ParseFailure()

    def _build_proposition(self, value):
        prop_type = value["type"]
        if prop_type == "goal":
            goal = self.build(value["goal"])
            polarity = self._parser._parse_polarity("~" if value.get("polarity") == "neg" else "")
            return GoalProposition(goal, polarity)
        if prop_type == "set":
            items = [self.build(item) for item in value["items"]]
            polarity = self._parser._parse_polarity("~" if value.get("polarity") == "neg" else "")
            return PropositionSet(items, polarity)
        if prop_type == "preconfirmed":
            polarity = self._parser._parse_polarity("~" if value.get("polarity") == "neg" else "")
            params = [self.build(param) for param in value["params"]]
            return PreconfirmationProposition(self._parser.ontology_name, value["action"], params, polarity)
        if prop_type == "prereported":
            params = [self.build(param) for param in value["params"]]
            return PrereportProposition(self._parser.ontology_name, value["action"], params)
        if prop_type == "service_action_terminated":
            return ServiceActionTerminatedProposition(self._parser.ontology_name, value["action"])
        if prop_type == "service_action_started":
            return ServiceActionStartedProposition(self._parser.ontology_name, value["action"])
        if prop_type == "action_status":
            action = self._parser._parse_action(value["action"])
            status = self._parser._parse_action_status(value["status"])
            return ActionStatusProposition(action, status)
        if prop_type == "resolved":
            question = self.build(value["question"])
            return ResolvednessProposition(question)
        if prop_type == "know_answer":
            question = self.build(value["question"])
            polarity = self._parser._parse_polarity("~" if value.get("polarity") == "neg" else "")
            return KnowledgePreconditionProposition(question, polarity)
        if prop_type == "implies":
            antecedent = self.build(value["antecedent"])
            consequent = self.build(value["consequent"])
            return ImplicationProposition(antecedent, consequent)
        if prop_type == "understanding":
            polarity = self._parser._parse_polarity("~" if value.get("polarity") == "neg" else "")
            proposition = self.build(value["proposition"])
            speaker_value = self._parser._parse_speaker(value["speaker"])
            return UnderstandingProposition(speaker_value, proposition, polarity)
        if prop_type == "rejected":
            rejected = self.build(value["content"])
            return RejectedPropositions(rejected, reason=value.get("reason"))
        if prop_type == "service_result":
            params = [self.build(param) for param in value["params"]]
            outcome = self.build(value["outcome"])
            return ServiceResultProposition(self._parser.ontology_name, value["action"], params, outcome)
        if prop_type == "service_outcome":
            if value["status"] == "success":
                return SuccessfulServiceAction()
            return FailedServiceAction(value["reason"])
        if prop_type == "lambda_goal":
            return LambdaAbstractedGoalProposition()
        if prop_type == "lambda_predicate":
            predicate = self._parser.ontology.get_predicate(value["predicate"])
            return self._parser.ontology.create_lambda_abstracted_predicate_proposition(predicate)
        if prop_type == "lambda_implication":
            antecedent = self.build(value["antecedent"])
            predicate = self._parser.ontology.get_predicate(value["predicate"])
            return LambdaAbstractedImplicationPropositionForConsequent(
                antecedent, predicate, self._parser.ontology_name
            )
        if prop_type == "predicate":
            predicate = self._parser.ontology.get_predicate(value["predicate"])
            polarity = self._parser._parse_polarity("~" if value.get("polarity") == "neg" else "")
            individual = None
            if value.get("individual") is not None:
                if predicate.sort.is_builtin():
                    individual = self._parser._parse_individual(value["individual"])
                else:
                    individual = self._parser._parse_individual(value["individual"], predicate.sort)
            return PredicateProposition(predicate, individual, polarity)
        raise ParseFailure()

    def _build_set_literal(self, items):
        s = Set()
        for item in items:
            s.add(self.build(item))
        return s

    def _build_identifier(self, value):
        try:
            return self._parser._parse_action_status(value)
        except ParseFailure:
            pass
        try:
            return self._parser._parse_action(value)
        except ParseFailure:
            pass
        try:
            return self._parser._parse_individual(value)
        except ParseFailure:
            pass
        return self._parser._parse_predicate(value)

    def _build_action(self, value):
        return self._parser._parse_action(value)

    def _build_yes_no(self, value):
        return self._parser._parse_yes_or_no(value)

    def _build_issue_literal(self, value):
        return value

    def _build_literal(self, value):
        return self._parser._parse_individual(value)

    def _build_string_literal(self, value):
        return self._parser._strip_quotes(value)


class Parser:
    def __init__(self, ddd_name, ontology, domain_name=None):
        self._ddd_name = ddd_name
        self.ontology = ontology
        self.ontology_name = ontology.name
        self.domain_name = domain_name
        self._cache_method = CacheMethod(self, self._cacheable_parse)

    def clear(self):
        self._cache_method.clear()

    def parse(self, string):
        object = self._cacheable_parse(string)
        new_instance = copy.deepcopy(object)
        return new_instance

    def _cacheable_parse(self, string):
        try:
            json_parser = CheckingJSONParser(self._ddd_name, self.ontology, self.domain_name)
            return json_parser.parse(string)
        except (AttributeError, TypeError, JSONParseFailure):
            pass
        try:
            return self._parse(string)
        except OntologyError as exception:
            raise ParseError("failed to parse '%s': %s" % (string, exception))

    def parse_parameters(self, string):
        if string is None or string == "":
            return {}
        params = {}
        for key, value_string in self._parse_param_pairs(string, expect_braces=True):
            params[key] = self.parse_parameter(key, value_string)
        return params

    def _parse(self, string):
        try:
            ast = _RecursiveDescentParser(self).parse(string)
            return _AstBuilder(self).build(ast)
        except ParseFailure as exception:
            message = f"failed to parse '{string}'"
            if exception.args:
                message = f"{message}: {exception}"
            message = f"{message} (ontology={self.ontology})"
            raise ParseError(message) from exception

    def _parse_string(self, string):
        m = re.search(r'^(["\'])(?P<string>[^\1]*)\1$', string)
        if m:
            return m.group("string")
        else:
            raise ParseFailure()

    def _strip_quotes(self, string):
        m = re.search(r'^"([^"]*)"$', string)
        if m:
            return m.group(1)
        else:
            m = re.search("^'([^']*)'$", string)
            if m:
                return m.group(1)
            else:
                raise ParseFailure()

    def _parse_individual(self, string, sort=None):
        def negate_if_negative_polarity(individual, polarity):
            if polarity is Polarity.NEG:
                return individual.negate()
            else:
                return individual

        m = re.search(r'^(~?)(.+)$', string)
        polarity_string = m.group(1)
        individual_string = m.group(2)
        polarity = self._parse_polarity(polarity_string)
        if sort is not None:
            return self._parse_individual_of_sort(individual_string, sort)
        try:
            individual = self._parse_real_individual(individual_string)
            return negate_if_negative_polarity(individual, polarity)
        except ParseFailure:
            pass
        try:
            individual = self._parse_integer_individual(individual_string)
            return negate_if_negative_polarity(individual, polarity)
        except ParseFailure:
            pass
        try:
            individual = self._parse_string_individual(individual_string)
            return negate_if_negative_polarity(individual, polarity)
        except ParseFailure:
            pass
        try:
            individual = self._parse_individual_of_enumerated_sort(individual_string)
            return negate_if_negative_polarity(individual, polarity)
        except ParseFailure:
            pass
        try:
            individual = self._parse_individual_of_person_name_sort(individual_string)
            return negate_if_negative_polarity(individual, polarity)
        except ParseFailure:
            pass
        try:
            individual = self._parse_individual_of_datetime_sort(individual_string)
            return negate_if_negative_polarity(individual, polarity)
        except ParseFailure:
            pass
        raise ParseFailure()

    def _parse_individual_of_sort(self, string, sort):
        m = re.search(r'^(.+)$', string)
        if m:
            individual_value = m.group(1)
            return self.ontology.create_individual(individual_value, sort)
        raise ParseFailure()

    def _parse_individual_of_enumerated_sort(self, string):
        m = re.search(r'^(.+)$', string)
        if m:
            individual_value = m.group(1)
            try:
                sort = self.ontology.individual_sort(individual_value)
            except OntologyError:
                raise ParseFailure()
            if not sort.is_string_sort() and not sort.is_real_sort():
                return self.ontology.create_individual(individual_value)
        raise ParseFailure()

    def _parse_real_individual(self, string):
        m = re.search(r'^[0-9]*\.[0-9]+$', string)
        if m:
            individual_value = float(string)
            return self.ontology.create_individual(individual_value)
        else:
            raise ParseFailure()

    def _parse_integer_individual(self, string):
        m = re.search(r'^[0-9]+$', string)
        if m:
            individual_value = int(string)
            return self.ontology.create_individual(individual_value)
        else:
            raise ParseFailure()

    def _parse_individual_of_person_name_sort(self, string):
        m = re.search(r'^person_name\((.+)\)$', string)
        if m:
            individual_value_string = m.group(1)
            individual_value = PersonName(individual_value_string)
            return self.ontology.create_individual(individual_value)
        else:
            raise ParseFailure()

    def _parse_individual_of_datetime_sort(self, string):
        m = re.search(r'^datetime\((.+)\)$', string)
        if m:
            individual_value_string = m.group(1)
            individual_value = DateTime(individual_value_string)
            return self.ontology.create_individual(individual_value)
        else:
            raise ParseFailure()

    def _parse_string_individual(self, string):
        string_content = self._parse_string(string)
        individual = self.ontology.create_individual(f'"{string_content}"')
        return individual

    def _parse_understanding_proposition(self, string):
        m = re.search(r'^(\~?)und\((USR|SYS|MODEL|None),[ ]*(.+)\)$', string)
        if m:
            negation = m.group(1)
            if negation == "":
                polarity = Polarity.POS
            else:
                polarity = Polarity.NEG
            speaker = self._parse_speaker(m.group(2))
            proposition_str = m.group(3)
            proposition = self.parse(proposition_str)
            und = UnderstandingProposition(speaker, proposition, polarity)
            return und
        else:
            raise ParseFailure()

    def _parse_speaker(self, string):
        if string == speaker.USR:
            return speaker.USR
        elif string == speaker.SYS:
            return speaker.SYS
        elif string == speaker.MODEL:
            return speaker.MODEL
        elif string == "None":
            return None

    def _parse_yes_or_no(self, string):
        m = re.search(r'^(yes|no)$', string)
        if m:
            yes_no_string = m.group(1)
            if yes_no_string == "yes":
                return Yes()
            return No()
        else:
            raise ParseFailure()

    def _parse_action(self, string):
        m = re.search(r'^(\w+)$', string)
        try:
            if m:
                action_value = m.group(1)
                return self.ontology.create_action(action_value)
        except OntologyError:
            pass
        raise ParseFailure()

    def _parse_predicate(self, string):
        m = re.search(r'^(\w+)$', string)
        if m:
            predicate_value = m.group(1)
            try:
                return self.ontology.get_predicate(predicate_value)
            except OntologyError:
                pass
        raise ParseFailure()

    def _parse_action_status(self, string):
        if string == "done":
            return Done()
        raise ParseFailure()

    def _parse_question_value(self, string):
        value = self.parse(string)
        try:
            if value.is_question():
                return value
        except AttributeError:
            pass
        raise ParseFailure()

    def _parse_proposition_set_value(self, string):
        value = self.parse(string)
        try:
            if value.is_proposition_set():
                return value
        except AttributeError:
            pass
        raise ParseFailure()

    def _parse_list_of_questions(self, string):
        string_without_brackets = self._strip_brackets(string)
        if not self._more_data_to_read(string_without_brackets):
            return []
        question_strings = self._split_top_level(string_without_brackets)
        questions = [self.parse(question_string) for question_string in question_strings]
        for question in questions:
            try:
                if question.is_question():
                    continue
            except AttributeError:
                pass
            raise ParseFailure()
        return questions

    def parse_parameter(self, key, string):
        try:
            if key == "source":
                return self._parse_findout_source(string)
            elif key == "incremental":
                return self._parse_boolean(string)
            elif key == "alts":
                return self._parse_proposition_set_value(string)
            elif key == "service_query":
                return self._parse_question_value(string)
            elif key == "device":
                return string
            elif key == "verbalize":
                return self._parse_boolean(string)
            elif key == "default":
                return self._parse_question_value(string)
            elif key == "format":
                return string
            elif key == "label_questions":
                return self._parse_list_of_questions(string)
            elif key == "sort_order":
                return self._parse_findout_sort_order(string)
            elif key == "ask_features":
                return self._parse_ask_features(string)
            elif key == "related_information":
                return self._parse_list_of_questions(string)
            elif key == "allow_goal_accommodation":
                return self._parse_boolean(string)
            elif key == "always_ground":
                return self._parse_boolean(string)
            elif key == "on_zero_hits_action":
                return self._parse_action(string)
            elif key == "on_too_many_hits_action":
                return self._parse_action(string)
            elif key == "max_spoken_alts":
                return self._parse_integer(string)
            elif key == "max_reported_hit_count":
                return self._parse_integer(string)
            else:
                raise ParseError(f"unsupported question parameter '{key}'")
        except ParseFailure:
            raise ParseError(f"failed to parse parameter {key}={string}")

    def _parse_ask_features(self, string):
        string_without_brackets = self._strip_brackets(string)
        predicate_strings = [str.strip() for str in string_without_brackets.split(",")]
        return [AskFeature(predicate_string) for predicate_string in predicate_strings]

    def _parse_findout_source(self, string):
        if string in [
            plan_item.QuestionRaisingPlanItem.SOURCE_SERVICE, plan_item.QuestionRaisingPlanItem.SOURCE_DOMAIN
        ]:
            return string
        else:
            raise ParseFailure()

    def _parse_findout_sort_order(self, string):
        if string in [plan_item.QuestionRaisingPlanItem.ALPHABETIC]:
            return string
        else:
            raise ParseFailure()

    def _parse_boolean(self, string):
        if string.lower() == "true":
            return True
        elif string.lower() == "false":
            return False
        else:
            raise ParseFailure()

    def _parse_integer(self, string):
        m = re.search(r'^[0-9]+$', string)
        if m:
            individual_value = int(string)
            return individual_value
        else:
            raise ParseFailure()

    def parse_preconfirm_value(self, string):
        if string == "interrogative":
            return plan_item.InvokeServiceAction.INTERROGATIVE
        elif string == "assertive":
            return plan_item.InvokeServiceAction.ASSERTIVE
        else:
            raise ParseFailure()

    def _split_top_level(self, string):
        parts = []
        depth_paren = 0
        depth_bracket = 0
        depth_brace = 0
        in_string = None
        escaped = False
        start = 0
        for index, char in enumerate(string):
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == in_string:
                    in_string = None
                continue
            if char in ["\"", "'"]:
                in_string = char
                continue
            if char == "(":
                depth_paren += 1
                continue
            if char == ")":
                depth_paren -= 1
                continue
            if char == "[":
                depth_bracket += 1
                continue
            if char == "]":
                depth_bracket -= 1
                continue
            if char == "{":
                depth_brace += 1
                continue
            if char == "}":
                depth_brace -= 1
                continue
            if char == "," and depth_paren == 0 and depth_bracket == 0 and depth_brace == 0:
                parts.append(string[start:index].strip())
                start = index + 1
        parts.append(string[start:].strip())
        return parts

    def _parse_param_pairs(self, string, expect_braces):
        stream = _TokenStream(_Tokenizer(string).tokenize(), string)
        if expect_braces:
            stream.consume_symbol("{")
            if stream.match_symbol("}"):
                stream.consume_symbol("}")
                return []
        pairs = []
        while True:
            key_token = stream.consume_ident()
            stream.consume_symbol("=")
            value_string = self._parse_param_value(stream, string, expect_braces)
            pairs.append((key_token.value, value_string))
            if stream.match_symbol(","):
                stream.consume_symbol(",")
                continue
            if expect_braces:
                stream.consume_symbol("}")
            elif not stream.at_end():
                token = stream.peek()
                raise ParseFailure(f"Expected end of parameters at position {token.position}")
            break
        return pairs

    def _parse_param_value(self, stream, text, stop_on_closing_brace):
        if stream.at_end():
            raise ParseFailure()
        start_index = stream.peek().position
        depth_paren = 0
        depth_bracket = 0
        depth_brace = 0
        while True:
            token = stream.peek()
            if token.type_ == "EOF":
                end_index = token.position
                break
            if token.type_ == "SYMBOL":
                if depth_paren == 0 and depth_bracket == 0 and depth_brace == 0:
                    if token.value == "," or (stop_on_closing_brace and token.value == "}"):
                        end_index = token.position
                        break
                if token.value == "(":
                    depth_paren += 1
                elif token.value == ")":
                    depth_paren -= 1
                elif token.value == "[":
                    depth_bracket += 1
                elif token.value == "]":
                    depth_bracket -= 1
                elif token.value == "{":
                    depth_brace += 1
                elif token.value == "}":
                    depth_brace -= 1
            stream.advance()
        value = text[start_index:end_index].strip()
        if value == "":
            raise ParseFailure()
        return value

    def _strip_brackets(self, bracketed_string):
        matcher = re.search(r'^\[(.*)\]$', bracketed_string)
        if matcher:
            return matcher.group(1)
        else:
            raise ParseError("_strip_brackets failed for '%s'" % bracketed_string)

    def _strip_curly_brackets(self, bracketed_string):
        matcher = re.search(r'^{(.*)}$', bracketed_string)
        if matcher:
            return matcher.group(1)

    def _more_data_to_read(self, string):
        return string != ""

    def _parse_polarity(self, string):
        if string == "":
            return Polarity.POS
        elif string == "~":
            return Polarity.NEG
        else:
            raise Exception("expected polarity string but got '%s'" % string)

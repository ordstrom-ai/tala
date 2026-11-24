import unittest

from tala.ddd.parser import Parser, ParseError
from tala.ddd.json_parser import CheckingJSONParser
from tala.model.action import Action
from tala.model.action_status import Done
from tala.model.ask_feature import AskFeature
from tala.model.domain import Domain
from tala.model.goal import PerformGoal, ResolveGoal
from tala.model.individual import Individual, Yes, No, NegativeIndividual
from tala.model.lambda_abstraction import LambdaAbstractedGoalProposition, \
    LambdaAbstractedImplicationPropositionForConsequent
from tala.model.lambda_abstraction import LambdaAbstractedPredicateProposition
from tala.model.speaker import USR, SYS, MODEL
from tala.model.set import Set
from tala.model import condition, plan_item
from tala.model.move_base import (
    Ask,
    Greet,
    Insult,
    InsultResponse,
    Move,
    Mute,
    Prereport,
    Report,
    ThankYou,
    ThankYouResponse,
)
from tala.model.move_icm import ICM, IssueICM
from tala.model.ontology import Ontology
from tala.model.plan_item import Assume, AssumeShared, AssumeIssue, Respond, \
    EmitIcm, Bind, JumpTo, IfThenElse, Log, GoalPerformed, \
    GoalAborted, ChangeDDD, QuestionRaisingPlanItem, Findout, Raise
from tala.model.polarity import Polarity
from tala.model.predicate import Predicate
from tala.model.proposition import ResolvednessProposition, RejectedPropositions, ServiceResultProposition, \
    GoalProposition, ServiceActionStartedProposition, ServiceActionTerminatedProposition, PropositionSet, \
    PredicateProposition, KnowledgePreconditionProposition, ImplicationProposition, ActionStatusProposition
from tala.model.question import WhQuestion, KnowledgePreconditionQuestion, ConsequentQuestion
from tala.model.sort import CustomSort, RealSort, IntegerSort, StringSort, BooleanSort, PersonNameSort, DateTimeSort
from tala.model.service_action_outcome import SuccessfulServiceAction, FailedServiceAction
from tala.testing.move_factory import MoveFactoryWithPredefinedBoilerplate
from tala.model.person_name import PersonName
from tala.model.date_time import DateTime


class ParserTests(unittest.TestCase):
    def setUp(self):
        self._ddd_name = "mockup_ddd"
        self._create_ontology()
        self._create_domain()
        self._create_semantic_objects()
        self._parser = Parser(self._ddd_name, self.ontology, self.domain_name)
        self._json_parser = CheckingJSONParser(self._ddd_name, self.ontology, self.domain_name)
        self._move_factory = MoveFactoryWithPredefinedBoilerplate(self.ontology.name)

    def parse(self, to_parse):
        result = self._parser.parse(to_parse)
        json_parse_result = self._json_parser.parse(result.as_json())
        assert json_parse_result == result
        return result

    def parse_parameters(self, to_parse):
        """ This method is only used for creating test data, as far as I can see """
        result = self._parser.parse_parameters(to_parse)
        return result

    def test_replace_goal_is_parsed_and_survives_semantic_json_round_trip(self):
        self.given_a_perform_goal_replacement_expression()
        self.when_parsing_the_replacement()
        self.then_the_replacement_and_round_trip_match_the_expected_goal()

    def given_a_perform_goal_replacement_expression(self):
        self.replacement_expression = "replace_goal(perform(buy))"

    def when_parsing_the_replacement(self):
        self.parsed_replacement = self._parser.parse(self.replacement_expression)
        self.reparsed_replacement = self._json_parser.parse(self.parsed_replacement.as_json())

    def then_the_replacement_and_round_trip_match_the_expected_goal(self):
        self.assertEqual(plan_item.ReplaceGoal(PerformGoal(self.buy_action)), self.parsed_replacement)
        self.assertEqual(self.parsed_replacement, self.reparsed_replacement)

    def _create_ontology(self):
        self.ontology_name = "mockup_ontology"
        sorts = {CustomSort(self.ontology_name, "city")}
        predicates = {
            self._create_predicate("dest_city", CustomSort(self.ontology_name, "city")),
            self._create_predicate("dept_city", CustomSort(self.ontology_name, "city")),
            self._create_predicate("available_dest_city", CustomSort(self.ontology_name, "city")),
            self._create_predicate("price", RealSort()),
            self._create_predicate("number_of_passengers", IntegerSort()),
            self._create_predicate("number_to_call", StringSort()),
            self._create_predicate("need_visa", BooleanSort()),
            self._create_predicate("selected_person", PersonNameSort()),
            self._create_predicate("selected_datetime", DateTimeSort()),
        }
        individuals = {
            "paris": CustomSort(self.ontology_name, "city"),
            "london": CustomSort(self.ontology_name, "city")
        }
        actions = {"top", "buy", "thanks"}
        self.ontology = Ontology(self.ontology_name, sorts, predicates, individuals, actions)

        self.empty_ontology = Ontology("empty_ontology", {}, {}, {}, set())

    def _create_predicate(self, *args, **kwargs):
        return Predicate(self.ontology_name, *args, **kwargs)

    def _create_domain(self):
        self.domain_name = "mockup_domain"
        self.domain = Domain(self._ddd_name, self.domain_name, self.ontology, plans={})

    def _create_semantic_objects(self):
        self.predicate_dest_city = self.ontology.get_predicate("dest_city")
        self.predicate_dept_city = self.ontology.get_predicate("dept_city")
        self.predicate_price = self.ontology.get_predicate("price")
        self.predicate_number_to_call = self.ontology.get_predicate("number_to_call")
        self.predicate_need_visa = self.ontology.get_predicate("need_visa")
        self.predicate_selected_person = self.ontology.get_predicate("selected_person")
        self.predicate_selected_datetime = self.ontology.get_predicate("selected_datetime")
        self.individual_paris = self.ontology.create_individual("paris")
        self.individual_not_paris = self.ontology.create_negative_individual("paris")
        self.individual_london = self.ontology.create_individual("london")
        self.real_individual = self.ontology.create_individual(1234.0)
        self.real_negative_individual = self.ontology.create_negative_individual(1234.0)
        self.integer_individual = self.ontology.create_individual(1234)
        city_sort = CustomSort(self.ontology_name, "city")
        self.non_integer_individual = self.ontology.create_individual(1235, city_sort)
        self.non_float_individual = self.ontology.create_individual(1235.3, city_sort)
        self.negative_integer_individual = self.ontology.create_negative_individual(1234)
        self.datetime_individual = self.ontology.create_individual(DateTime("2018-04-11T22:00:00.000Z"))
        self.negative_datetime_individual = self.ontology.create_negative_individual(
            DateTime("2018-04-11T22:00:00.000Z")
        )
        self.person_name_individual = self.ontology.create_individual(PersonName("John"))
        self.negative_person_name_individual = self.ontology.create_negative_individual(PersonName("John"))

        self.proposition_dest_city_paris = PredicateProposition(self.predicate_dest_city, self.individual_paris)
        self.proposition_not_dest_city_paris = PredicateProposition(
            self.predicate_dest_city, self.individual_paris, Polarity.NEG
        )
        self.proposition_dest_city_london = PredicateProposition(self.predicate_dest_city, self.individual_london)
        self.price_proposition = PredicateProposition(self.predicate_price, self.real_individual)
        self.proposition_need_visa = PredicateProposition(self.predicate_need_visa)
        self.proposition_not_need_visa = PredicateProposition(self.predicate_need_visa, polarity=Polarity.NEG)

        self.lambda_abstracted_dest_city_prop = LambdaAbstractedPredicateProposition(
            self.predicate_dest_city, self.ontology_name
        )
        self.lambda_abstracted_price_prop = LambdaAbstractedPredicateProposition(
            self.predicate_price, self.ontology_name
        )

        self.dest_city_question = WhQuestion(self.lambda_abstracted_dest_city_prop)
        self.price_question = WhQuestion(self.lambda_abstracted_price_prop)

        self.buy_action = self.ontology.create_action("buy")
        self.top_action = self.ontology.create_action("top")
        self.thanks_action = self.ontology.create_action("thanks")

    def test_understanding_proposition(self):
        und_string = "und(USR, dest_city(paris))"
        und = self.parse(und_string)
        self.assertTrue(und.is_understanding_proposition())
        self.assertEqual(USR, und.speaker)

    def test_neg_understanding_proposition(self):
        und_string = "~und(USR, dest_city(paris))"
        und = self.parse(und_string)
        self.assertTrue(und.is_understanding_proposition())

    def test_understanding_question(self):
        und_string = "?und(USR, dest_city(paris))"
        und = self.parse(und_string)
        self.assertTrue(und.is_understanding_question())

    def test_understanding_proposition_with_speaker_none(self):
        und_string = "und(None, dest_city(paris))"
        und = self.parse(und_string)
        self.assertTrue(und.is_understanding_proposition())
        self.assertEqual(None, und.speaker)

    def test_create_yes_no_question(self):
        question = self.parse("?dest_city(paris)")  # noqa: F841

    def test_create_nullary_yes_no_question_I(self):
        question = self.parse("?need_visa()")  # noqa: F841

    def test_create_yes(self):
        yes = self.parse("yes")
        self.assertEqual(Yes(), yes)

    def test_create_no(self):
        no = self.parse("no")
        self.assertEqual(No(), no)

    def test_create_yes_answer_move(self):
        yes_move = self.parse("answer(yes)")
        self.assertEqual(Yes(), yes_move.content)

    def test_create_no_answer_move(self):
        no_move = self.parse("answer(no)")
        self.assertEqual(No(), no_move.content)

    def test_ShortAnswer(self):
        answer_move_from_string = self.parse("answer(paris)")
        answer = self.individual_paris
        answer_move = self._move_factory.create_answer_move(answer)
        self.assertEqual(answer_move, answer_move_from_string)

    def test_PropositionalAnswerMove(self):
        answer_move_from_string = self.parse("answer(dest_city(paris))")
        individual = self.individual_paris
        answer = PredicateProposition(self.predicate_dest_city, individual)
        answer_move = self._move_factory.create_answer_move(answer)
        self.assertEqual(answer_move, answer_move_from_string)

    def test_integer_short_answer(self):
        move = self.parse("answer(1234)")
        expected_move = self._move_factory.create_answer_move(self.integer_individual)
        self.assertEqual(expected_move, move)

    def test_negative_integer_short_answer(self):
        move = self.parse("answer(~1234)")
        expected_move = self._move_factory.create_answer_move(self.negative_integer_individual)
        self.assertEqual(expected_move, move)

    def test_parse_integer_string_in_proposition_as_non_integer_individual(self):
        proposition = self.parse("dest_city(1235)")
        expected_prop = PredicateProposition(self.predicate_dest_city, self.non_integer_individual)
        self.assertEqual(expected_prop, proposition)

    def test_parse_float_string_in_proposition_as_non_float_individual(self):
        proposition = self.parse("dest_city(1235.3)")
        expected_prop = PredicateProposition(self.predicate_dest_city, self.non_float_individual)
        self.assertEqual(expected_prop, proposition)

    def test_parse_integer_string_in_move_as_non_integer_individual(self):
        move = self.parse("answer(dest_city(1235))")
        answer_content = PredicateProposition(self.predicate_dest_city, self.non_integer_individual)
        self.assertEqual(answer_content, move.answer_content)

    def test_person_name_sortal_answer(self):
        move = self.parse("answer(person_name(John))")
        expected_move = self._move_factory.create_answer_move(self.person_name_individual)
        self.assertEqual(expected_move, move)

    def test_negative_person_name_sortal_answer(self):
        move = self.parse("answer(~person_name(John))")
        expected_move = self._move_factory.create_answer_move(self.negative_person_name_individual)
        self.assertEqual(expected_move, move)

    def test_person_name_propositional_answer(self):
        move = self.parse("answer(selected_person(person_name(John)))")
        individual = self.person_name_individual
        answer = PredicateProposition(self.predicate_selected_person, individual)
        expected_move = self._move_factory.create_answer_move(answer)
        self.assertEqual(expected_move, move)

    def test_person_name_individual(self):
        move = self.parse("person_name(John)")
        self.assertEqual(self.person_name_individual, move)

    def test_datetime_sortal_answer(self):
        move = self.parse("answer(datetime(2018-04-11T22:00:00.000Z))")
        expected_move = self._move_factory.create_answer_move(self.datetime_individual)
        self.assertEqual(expected_move, move)

    def test_negative_datetime_sortal_answer(self):
        move = self.parse("answer(~datetime(2018-04-11T22:00:00.000Z))")
        expected_move = self._move_factory.create_answer_move(self.negative_datetime_individual)
        self.assertEqual(expected_move, move)

    def test_datetime_propositional_answer(self):
        move = self.parse("answer(selected_datetime(datetime(2018-04-11T22:00:00.000Z)))")
        individual = self.datetime_individual
        answer = PredicateProposition(self.predicate_selected_datetime, individual)
        expected_move = self._move_factory.create_answer_move(answer)
        self.assertEqual(expected_move, move)

    def test_integer_short_answer_with_ontology_without_real_sort(self):
        sorts = set()
        predicates = {self._create_predicate("number_of_passengers", IntegerSort())}
        individuals = {}
        actions = set()
        ontology_without_real_sort = Ontology("ontology_without_real_sort", sorts, predicates, individuals, actions)
        move = Parser(self._ddd_name, ontology_without_real_sort, self.domain_name).parse("answer(1234)")
        self.assertEqual(move.type_, Move.ANSWER)
        self.assertTrue(move.content.is_individual())
        self.assertEqual(move.content.sort.name, "integer")

    def test_float_short_answer(self):
        move = self.parse("answer(1234.0)")
        expected_move = self._move_factory.create_answer_move(self.real_individual)
        self.assertEqual(expected_move, move)

    def test_negative_float_short_answer(self):
        move = self.parse("answer(~1234.0)")
        expected_move = self._move_factory.create_answer_move(self.real_negative_individual)
        self.assertEqual(expected_move, move)

    def test_float_answer(self):
        move = self.parse("answer(price(1234.0))")
        expected_move = self._move_factory.create_answer_move(self.price_proposition)
        self.assertEqual(expected_move, move)

    def test_propositional_usr_answer_move_w_score(self):
        self._when_parse(
            "Move(answer(dest_city(paris)), understanding_confidence=0.45, speaker=USR, ddd_name='mockup_ddd')"
        )
        self._then_result_is(
            MoveFactoryWithPredefinedBoilerplate(
                self.ontology.name, understanding_confidence=0.45, speaker=USR, ddd_name="mockup_ddd"
            ).create_answer_move(PredicateProposition(self.predicate_dest_city, self.individual_paris))
        )

    def _when_parse(self, string):
        self._result = self.parse(string)

    def _then_result_is(self, expected_result):
        self.assertEqual(expected_result, self._result)

    def test_move_with_utterance(self):
        self._when_parse(
            "Move(answer(dest_city(paris)), understanding_confidence=0.45, speaker=USR, "
            "utterance='paris', ddd_name='mockup_ddd')"
        )
        self._then_result_is(
            MoveFactoryWithPredefinedBoilerplate(
                self.ontology.name,
                ddd_name="mockup_ddd",
                understanding_confidence=0.45,
                speaker=USR,
                utterance="paris"
            ).create_answer_move(PredicateProposition(self.predicate_dest_city, self.individual_paris))
        )

    def test_undecorated_move_with_Move_classname(self):
        string = "Move(ask(?set([goal(perform(top)), goal(perform(buy))])))"
        expected_move = self.parse("ask(?set([goal(perform(top)), goal(perform(buy))]))")
        self.assertEqual(expected_move, self.parse(string))

    def test_Individual(self):
        individual_from_string = self.parse("paris")
        self.assertEqual(self.individual_paris, individual_from_string)

    def test_NegativeIndividual(self):
        individual_from_string = self.parse("~paris")
        self.assertEqual(self.individual_not_paris, individual_from_string)

    def test_ask_whq(self):
        move_from_string = self.parse("ask(?X.dest_city(X))")
        question = self.parse("?X.dest_city(X)")
        move = self._move_factory.create_ask_move(question)
        self.assertEqual(move, move_from_string)

    def test_ask_ynq_for_boolean_predicate(self):
        move_from_string = self.parse("ask(?need_visa)")
        question = self.parse("?need_visa")
        move = self._move_factory.create_ask_move(question)
        self.assertEqual(move, move_from_string)

    def test_ask_ynq_for_non_boolean_predicate_yields_parse_error(self):
        with self.assertRaises(ParseError):
            self.parse("ask(?price)")

    def test_ask_move_with_speaker_score(self):
        score = 1.0
        speaker = SYS
        move_from_string = self.parse(
            f"Move(ask(?X.dest_city(X)), speaker={speaker}, understanding_confidence={score}, ddd_name='mockup_ddd')"
        )
        question = self.parse("?X.dest_city(X)")
        move = MoveFactoryWithPredefinedBoilerplate(
            self.ontology.name, speaker=speaker, understanding_confidence=score, ddd_name="mockup_ddd"
        ).create_ask_move(question)
        self.assertEqual(move, move_from_string)

    def test_create_request_move(self):
        request = self.parse("request(buy)")
        self.assertEqual(Move.REQUEST, request.type_)

    def test_create_request_move_with_thanks_action(self):
        request = self.parse("request(thanks)")
        self.assertEqual(Move.REQUEST, request.type_)
        self.assertEqual(self.thanks_action, request.content)

    def test_create_request_move_w_score_and_usr(self):
        score = 0.55
        speaker = USR
        expected_move = self._move_factory.create_move(
            Move.REQUEST,
            content=Action("buy", self.ontology.name),
            speaker=speaker,
            understanding_confidence=score,
            ddd_name="mockup_ddd"
        )
        request = self.parse(
            "Move(request(buy), speaker=%s, understanding_confidence=%s, ddd_name='mockup_ddd')" % (speaker, score)
        )
        self.assertEqual(expected_move, request)

    def test_create_set_with_single_element(self):
        set_of_moves = self.parse("{request(top)}")
        expected_result = Set()
        expected_result.add(self.parse("request(top)"))
        self.assertEqual(expected_result, set_of_moves)

    def test_create_empty_set(self):
        empty_set = self.parse("{}")
        expected_result = Set()
        self.assertEqual(expected_result, empty_set)

    def test_lambda_abstracted_predicate_proposition(self):
        object = self.parse("X.dest_city(X)")
        expected_object = self.lambda_abstracted_dest_city_prop
        self.assertEqual(expected_object, object)

    def test_lambda_abstracted_goal_proposition(self):
        object = self.parse("X.goal(X)")
        expected_object = LambdaAbstractedGoalProposition()
        self.assertEqual(expected_object, object)

    def test_action(self):
        object = self.parse("buy")
        expected_object = self.buy_action
        self.assertEqual(expected_object, object)

    def test_unary_predicate_proposition(self):
        proposition_from_string = self.parse("dest_city(paris)")
        self.assertEqual(self.proposition_dest_city_paris, proposition_from_string)

    def test_nullary_predicate_proposition(self):
        proposition_from_string = self.parse("need_visa()")
        self.assertEqual(self.proposition_need_visa, proposition_from_string)

    def test_negative_unary_predicate_proposition(self):
        proposition_from_string = self.parse("~dest_city(paris)")
        self.assertEqual(self.proposition_not_dest_city_paris, proposition_from_string)

    def test_negative_nullary_predicate_proposition(self):
        proposition_from_string = self.parse("~need_visa()")
        self.assertEqual(self.proposition_not_need_visa, proposition_from_string)

    def test_positive_perform_proposition(self):
        proposition = self.parse("goal(perform(buy))")
        self.assertTrue(proposition.is_positive())
        self.assertEqual(PerformGoal(self.buy_action), proposition.goal)

    def test_negative_action_proposition(self):
        proposition = self.parse("~goal(perform(buy))")
        self.assertFalse(proposition.is_positive())
        self.assertEqual(PerformGoal(self.buy_action), proposition.goal)

    def test_illegal_perform_goal(self):
        with self.assertRaises(ParseError):
            self.parse("perform(sdfkjsd)")

    def test_issue_proposition(self):
        object = self.parse("goal(resolve_user(?X.dest_city(X)))")
        expected_object = GoalProposition(ResolveGoal(self.dest_city_question, USR))
        self.assertEqual(expected_object, object)

    def test_resolve_goal_containing_non_question_yields_exception(self):
        with self.assertRaises(ParseError):
            self.parse("resolve(buy)")

    def test_resolvedness_proposition(self):
        object = self.parse("resolved(?X.dest_city(X))")
        expected_object = ResolvednessProposition(self.dest_city_question)
        self.assertEqual(expected_object, object)

    def test_positive_preconfirmation(self):
        preconfirmation = self.parse("preconfirmed(MakeReservation, [])")
        self.assertTrue(preconfirmation.is_positive())
        self.assertEqual("MakeReservation", preconfirmation.service_action)
        self.assertEqual([], preconfirmation.arguments)

    def test_negative_preconfirmation(self):
        preconfirmation = self.parse("~preconfirmed(MakeReservation, [])")
        self.assertFalse(preconfirmation.is_positive())
        self.assertEqual("MakeReservation", preconfirmation.service_action)
        self.assertEqual([], preconfirmation.arguments)

    def test_preconfirmation_w_single_param(self):
        preconfirmation = self.parse("~preconfirmed(MakeReservation, [dest_city(paris)])")
        self.assertEqual(1, len(preconfirmation.arguments))
        self.assertEqual("dest_city(paris)", str(preconfirmation.arguments[0]))

    def test_preconfirmation_q_w_single_param(self):
        preconfirmation = self.parse("?preconfirmed(MakeReservation, [dest_city(paris)])")  # noqa: F841

    def test_preconfirmation_q_w_multi_param(self):
        service_action = "MakeReservation"
        prop_1 = "dest_city(paris)"
        prop_2 = "dest_city(london)"
        preconfirmed_string = "?preconfirmed(%s, [%s, %s])" % (service_action, prop_1, prop_2)
        preconfirmation = self.parse(preconfirmed_string)  # noqa: F841

    def test_rejected_proposition(self):
        object = self.parse("rejected(set([dest_city(paris)]))")
        expected_object = RejectedPropositions(PropositionSet([self.proposition_dest_city_paris]))
        self.assertEqual(expected_object, object)

    def test_rejected_proposition_with_reason(self):
        object = self.parse("rejected(set([dest_city(paris)]), some_reason)")
        expected_object = RejectedPropositions(PropositionSet([self.proposition_dest_city_paris]), reason="some_reason")
        self.assertEqual(expected_object, object)

    def test_create_prereport(self):
        confirmation = self.parse("prereported(MakeReservation, [])")
        self.assertEqual("MakeReservation", confirmation.service_action)
        self.assertEqual([], confirmation.arguments)

    def test_create_prereport_w_single_param(self):
        prereport = self.parse("prereported(MakeReservation, [dest_city(paris)])")
        self.assertEqual(1, len(prereport.arguments))
        self.assertEqual("dest_city(paris)", str(prereport.arguments[0]))

    def test_create_prereport_w_multi_param(self):
        service_action = "MakeReservation"
        prop_1 = "dest_city(paris)"
        prop_2 = "dest_city(london)"
        prereport_string = "?prereported(%s, [%s, %s])" % (service_action, prop_1, prop_2)
        prereport = self.parse(prereport_string)  # noqa: F841

    def test_report_move_successful_with_parameters(self):
        object = self.parse(
            "report(ServiceResultProposition("
            "MakeReservation, [dest_city(paris), dest_city(london)], SuccessfulServiceAction()))"
        )
        expected_object = Report(
            ServiceResultProposition(
                self.ontology_name, "MakeReservation",
                [self.proposition_dest_city_paris, self.proposition_dest_city_london], SuccessfulServiceAction()
            )
        )
        self.assertEqual(expected_object, object)

    def test_report_move_successful(self):
        object = self.parse("report(ServiceResultProposition(MakeReservation, [], SuccessfulServiceAction()))")
        expected_object = Report(
            ServiceResultProposition(self.ontology_name, "MakeReservation", [], SuccessfulServiceAction())
        )
        self.assertEqual(expected_object, object)

    def test_report_move_failed(self):
        object = self.parse(
            "report(ServiceResultProposition(MakeReservation, [], FailedServiceAction(no_itinerary_found)))"
        )
        expected_object = Report(
            ServiceResultProposition(
                self.ontology_name, "MakeReservation", [], FailedServiceAction("no_itinerary_found")
            )
        )
        self.assertEqual(expected_object, object)

    def test_report_move_with_done(self):
        self._when_parse("report(done)")
        self._then_result_is(Report(Done()))

    def test_report_move_with_specific_action_done(self):
        self._when_parse("report(action_status(buy, done))")
        self._then_result_is(Report(ActionStatusProposition(self.buy_action, Done())))

    def test_prereport_move(self):
        object = self.parse("prereport(MakeReservation, [dest_city(paris), dest_city(london)])")
        expected_object = Prereport(
            self.ontology_name, "MakeReservation",
            [self.proposition_dest_city_paris, self.proposition_dest_city_london]
        )
        self.assertEqual(expected_object, object)

    def test_create_DoPlanItem(self):
        action = self.parse("buy")
        do_item = self.parse("do(buy)")
        self.assertEqual(action, do_item.content)

    def test_create_EmitIcmPlanItem(self):
        icm_move = self.parse("icm:und*pos:USR*goal(perform(buy))")
        item = EmitIcm(icm_move)
        self.assertEqual(icm_move, item.content)
        self.assertEqual(item.type_, plan_item.TYPE_EMIT_ICM)

    def test_FindoutPlanItem_with_no_params(self):
        expected_item = Findout(self.domain_name, self.dest_city_question)
        item = self.parse("findout(?X.dest_city(X))")
        self.assertEqual(expected_item, item)
        self.assertEqual(self.dest_city_question, item.content)

    def test_boolean_parameter_leading_uppercase(self):
        string = "{incremental=True}"
        params = self.parse_parameters(string)
        expected_params = {"incremental": True}
        self.assertEqual(expected_params, params)

    def test_boolean_parameter_lowercase(self):
        string = "{incremental=true}"
        params = self.parse_parameters(string)
        expected_params = {"incremental": True}
        self.assertEqual(expected_params, params)

    def test_verbalize_parameter(self):
        string = "{verbalize=True}"
        params = self.parse_parameters(string)
        expected_params = {"verbalize": True}
        self.assertEqual(expected_params, params)

    def test_parameters_with_empty_alts(self):
        string = "{alts=set([])}"
        params = self.parse_parameters(string)
        expected_params = {"alts": PropositionSet([])}
        self.assertEqual(expected_params, params)

    def test_parameters_with_single_alt(self):
        string = "{alts=set([goal(perform(buy))])}"
        params = self.parse_parameters(string)
        expected_params = {"alts": PropositionSet([self.parse("goal(perform(buy))")])}
        self.assertEqual(expected_params, params)

    def test_parameters_with_multiple_alts(self):
        string = "{alts=set([goal(perform(top)), goal(perform(buy))])}"
        params = self.parse_parameters(string)
        expected_params = {"alts": PropositionSet([self.parse("goal(perform(top))"), self.parse("goal(perform(buy))")])}
        self.assertEqual(expected_params, params)

    def test_source_param_service(self):
        string = "{source=service}"
        params = self.parse_parameters(string)
        expected_params = {"source": QuestionRaisingPlanItem.SOURCE_SERVICE}
        self.assertEqual(expected_params, params)

    def test_source_param_domain(self):
        string = "{source=domain}"
        params = self.parse_parameters(string)
        expected_params = {"source": QuestionRaisingPlanItem.SOURCE_DOMAIN}
        self.assertEqual(expected_params, params)

    def test_service_query_param(self):
        string = "{service_query=?X.available_dest_city(X)}"
        params = self.parse_parameters(string)
        expected_params = {"service_query": self.parse("?X.available_dest_city(X)")}
        self.assertEqual(expected_params, params)

    def test_device_param(self):
        string = "{device=travel_booker}"
        params = self.parse_parameters(string)
        expected_params = {"device": "travel_booker"}
        self.assertEqual(expected_params, params)

    def test_sort_parameter(self):
        string = "{sort_order=alphabetic}"
        params = self.parse_parameters(string)
        expected_params = {"sort_order": QuestionRaisingPlanItem.ALPHABETIC}
        self.assertEqual(expected_params, params)

    def test_allow_goal_accommodation_parameter(self):
        string = "{allow_goal_accommodation=True}"
        params = self.parse_parameters(string)
        expected_params = {"allow_goal_accommodation": True}
        self.assertEqual(expected_params, params)

    def test_max_spoken_alts_parameter(self):
        string = "{max_spoken_alts=2}"
        params = self.parse_parameters(string)
        expected_params = {"max_spoken_alts": 2}
        self.assertEqual(expected_params, params)

    def test_related_information_parameter(self):
        string = "{related_information=[?X.price(X)]}"
        params = self.parse_parameters(string)
        expected_params = {"related_information": [self.price_question]}
        self.assertEqual(expected_params, params)

    def test_ask_features_parameter(self):
        string = "{ask_features=[dest_city, dept_city]}"
        params = self.parse_parameters(string)
        expected_params = {"ask_features": [AskFeature("dest_city"), AskFeature("dept_city")]}
        self.assertEqual(expected_params, params)

    def test_illegal_parameter_raises_exception(self):
        with self.assertRaises(ParseError):
            self.parse("{sldkfjs=ksjhdf}")

    def test_create_RaisePlanItem(self):
        item = self.parse("raise(?X.dest_city(X))")
        expected_item = Raise(self.domain_name, self.dest_city_question)
        self.assertEqual(expected_item, item)

    def test_create_Findout_with_non_question(self):
        with self.assertRaises(ParseError):
            self.parse("findout(X.dest_city(X))")

    def test_create_Raise_with_non_question(self):
        with self.assertRaises(ParseError):
            self.parse("raise(X.dest_city(X))")

    def test_create_Bind(self):
        item = self.parse("bind(?X.dest_city(X))")
        expected_item = Bind(self.dest_city_question)
        self.assertEqual(expected_item, item)

    def test_create_Bind_with_non_question(self):
        with self.assertRaises(ParseError):
            self.parse("bind(X.dest_city(X))")

    def test_create_Respond(self):
        item = self.parse("respond(?X.dest_city(X))")
        expected_item = Respond(self.dest_city_question)
        self.assertEqual(expected_item, item)

    def test_create_if_then_else(self):
        string = "if dest_city(paris) then jumpto(perform(top)) else jumpto(perform(buy))"
        item = self.parse(string)
        expected_item = IfThenElse(
            condition.InBeliefsOrCommitments(self.proposition_dest_city_paris),
            [JumpTo(PerformGoal(self.top_action))],
            [JumpTo(PerformGoal(self.buy_action))]
        )
        self.assertEqual(expected_item, item)

    def test_create_if_then_else_resolvedness_from_string(self):
        string = "if resolved(?X.dest_city(X))" " then jumpto(perform(top))" " else jumpto(perform(buy))"
        item = self.parse(string)

        expected_item = IfThenElse(
            condition.InBeliefsOrCommitments(ResolvednessProposition(self.dest_city_question)),
            [JumpTo(PerformGoal(self.top_action))],
            [JumpTo(PerformGoal(self.buy_action))]
        )
        self.assertEqual(expected_item, item)

    def test_create_if_then_else_resolvedness_no_else_from_string(self):
        string = "if resolved(?X.dest_city(X))" " then jumpto(perform(top))" " else "
        item = self.parse(string)

        expected_item = IfThenElse(
            condition.InBeliefsOrCommitments(ResolvednessProposition(self.dest_city_question)),
            [JumpTo(PerformGoal(self.top_action))],
            []
        )
        self.assertEqual(expected_item, item)

    def test_create_if_then_else_resolvedness_no_then_from_string(self):
        string = "if resolved(?X.dest_city(X))" " then " " else jumpto(perform(top))"
        item = self.parse(string)

        expected_item = IfThenElse(
            condition.InBeliefsOrCommitments(ResolvednessProposition(self.dest_city_question)),
            [],
            [JumpTo(PerformGoal(self.top_action))]
        )
        self.assertEqual(expected_item, item)

    def test_create_forget_all_from_string(self):
        item = self.parse("forget_all")
        self.assertEqual(item.type_, plan_item.TYPE_FORGET_ALL)

    def test_create_forget(self):
        fact = self.parse("dest_city(paris)")
        item = self.parse("forget(%s)" % fact)
        self.assertEqual(item.type_, plan_item.TYPE_FORGET)
        self.assertEqual(fact, item.content)

    def test_create_forget_shared(self):
        fact = self.parse("dest_city(paris)")
        item = self.parse("forget_shared(%s)" % fact)
        self.assertEqual(item.type_, plan_item.TYPE_FORGET_SHARED)
        self.assertEqual(fact, item.content)

    def test_create_forget_predicate(self):
        predicate = self.parse("dest_city")
        item = self.parse("forget(%s)" % predicate)
        self.assertEqual(item.type_, plan_item.TYPE_FORGET)
        self.assertEqual(predicate, item.content)

    def test_create_forget_issue(self):
        issue = self.parse("?X.dest_city(X)")
        item = self.parse("forget_issue(%s)" % issue)
        self.assertEqual(item.type_, plan_item.TYPE_FORGET_ISSUE)
        self.assertEqual(issue, item.content)

    def test_create_invoke_service_query_plan_item(self):
        issue = self.parse("?X.dest_city(X)")
        item = self.parse("invoke_service_query(%s)" % issue)
        self.assertEqual(item.type_, plan_item.TYPE_INVOKE_SERVICE_QUERY)
        self.assertEqual(issue, item.content)
        self.assertEqual(1, item.min_results)
        self.assertEqual(1, item.max_results)

    def test_invoke_service_action_no_params(self):
        service_action = "MakeReservation"
        item = self.parse("invoke_service_action(%s, {})" % service_action)
        self.assertEqual(item.type_, plan_item.TYPE_INVOKE_SERVICE_ACTION)
        self.assertEqual(service_action, item.service_action)

    def test_invoke_service_action_postconfirmed_and_preconfirmed_assertively(self):
        params_string = "{postconfirm=True, preconfirm=assertive}"
        service_action = "MakeReservation"
        item = self.parse("invoke_service_action(%s, %s)" % (service_action, params_string))
        self.assertTrue(item.has_postconfirmation())
        self.assertTrue(item.has_assertive_preconfirmation())

    def test_invoke_service_action_preconfirmed_interrogatively(self):
        params_string = "{preconfirm=interrogative}"
        service_action = "MakeReservation"
        item = self.parse("invoke_service_action(%s, %s)" % (service_action, params_string))
        self.assertTrue(item.has_interrogative_preconfirmation())

    def test_invoke_service_action_downdate_plan_false_by_default(self):
        params_string = "{}"
        service_action = "MakeReservation"
        item = self.parse("invoke_service_action(%s, %s)" % (service_action, params_string))
        self.assertFalse(item.should_downdate_plan())

    def test_invoke_service_action_downdate_plan_overridable(self):
        params_string = "{downdate_plan=False}"
        service_action = "MakeReservation"
        item = self.parse("invoke_service_action(%s, %s)" % (service_action, params_string))
        self.assertFalse(item.should_downdate_plan())

    def test_create_yesno_question(self):
        question = self.parse("?dest_city(paris)")
        self.assertTrue(question.is_yes_no_question())

    def test_create_single_alt_question(self):
        alt_question_string = "?set([goal(perform(buy))])"
        question = self.parse(alt_question_string)
        self.assertEqual(alt_question_string, str(question))

    def test_create_alt_question_with_predicate_propositions(self):
        alt_question_string = "?set([goal(perform(top)), goal(perform(buy))])"
        question = self.parse(alt_question_string)
        self.assertEqual(alt_question_string, str(question))

    def test_create_alt_question_with_goal_propositions(self):
        alt_question_string = "?set([goal(perform(buy)), goal(perform(top))])"
        question = self.parse(alt_question_string)
        self.assertEqual(alt_question_string, str(question))

    def test_create_single_alt_question_with_issue_proposition(self):
        alt_question_string = "?set([goal(resolve(?X.goal(X)))])"
        question = self.parse(alt_question_string)
        self.assertEqual(alt_question_string, str(question))

    def test_create_single_neg_alt_question(self):
        alt_question_string = "?set([~goal(perform(buy))])"
        question = self.parse(alt_question_string)
        self.assertEqual(alt_question_string, str(question))

    def test_is_alt_question_when_created(self):
        question_as_string = "?set([goal(perform(top)), goal(perform(buy))])"
        question = self.parse(question_as_string)
        self.assertTrue(question.is_alt_question())

    def test_proposition_set_with_action_and_issue_propositions(self):
        string = "set([goal(perform(buy)), goal(resolve(?X.price(X)))])"
        object = self.parse(string)
        expected_object = PropositionSet([
            GoalProposition(PerformGoal(self.buy_action)),
            GoalProposition(ResolveGoal(self.price_question, SYS))
        ])
        self.assertEqual(expected_object, object)

    def test_negative_proposition_set_with_action_and_issue_propositions(self):
        string = "~set([goal(perform(buy)), goal(resolve(?X.price(X)))])"
        object = self.parse(string)
        expected_object = PropositionSet([
            GoalProposition(PerformGoal(self.buy_action)),
            GoalProposition(ResolveGoal(self.price_question, SYS))
        ],
                                         polarity=Polarity.NEG)
        self.assertEqual(expected_object, object)

    def test_greet_move(self):
        move = self.parse("greet")
        self.assertEqual(Greet(), move)

    def test_insult_move(self):
        move = self.parse("insult")
        self.assertEqual(Insult(), move)

    def test_insult_response_move(self):
        move = self.parse("insult_response")
        self.assertEqual(InsultResponse(), move)

    def test_thanks_move(self):
        move = self.parse(Move.THANK_YOU)
        self.assertEqual(ThankYou(), move)

    def test_thank_you_response_move(self):
        move = self.parse(Move.THANK_YOU_RESPONSE)
        self.assertEqual(ThankYouResponse(), move)

    def test_user_greet_move_with_speaker_and_score(self):
        move = self.parse("Move(greet, ddd_name='mockup_ddd', speaker=USR, understanding_confidence=0.47)")
        self.assertEqual(USR, move.speaker)
        self.assertEqual(0.47, move.understanding_confidence)

    def test_mute_move(self):
        move = self.parse("mute")
        self.assertEqual(Mute(), move)

    def test_sys_mute_move_with_score(self):
        move = self.parse("Move(mute, speaker=SYS, understanding_confidence=1.0)")
        self.assertEqual(SYS, move.speaker)
        self.assertEqual(1.0, move.understanding_confidence)

    def test_move_without_score(self):
        move = self.parse("Move(greet, speaker=SYS)")
        self.assertEqual(SYS, move.speaker)

    def test_unmute_move(self):
        move = self.parse("unmute")
        self.assertEqual(Move.UNMUTE, move.type_)

    def test_quit_move(self):
        move = self.parse("quit")
        self.assertEqual(Move.QUIT, move.type_)

    def test_contentful_reraise(self):
        move = self.parse("icm:reraise:top")
        self.assertEqual(ICM.RERAISE, move.type_)
        self.assertEqual(self.top_action, move.content)

    def test_contentless_reraise(self):
        move = self.parse("icm:reraise")
        self.assertEqual(ICM.RERAISE, move.type_)

    def test_reraise_with_speaker_and_score(self):
        speaker = SYS
        score = 1.0
        move = self.parse("ICM(icm:reraise:top, speaker=%s, understanding_confidence=%s)" % (speaker, score))
        expected_move = ICM.create(
            ICM.RERAISE, content=self.top_action, understanding_confidence=score, speaker=speaker
        )
        self.assertEqual(expected_move, move)

    def test_resume(self):
        move = self.parse("icm:resume:perform(buy)")
        self.assertEqual(ICM.RESUME, move.type_)
        self.assertEqual(PerformGoal(self.buy_action), move.content)

    def test_contentful_accommodate(self):
        test_move = self.parse("icm:accommodate:top")
        self.assertEqual(ICM.ACCOMMODATE, test_move.type_)
        self.assertEqual(self.top_action, test_move.content)

    def test_contentless_accommodate(self):
        move = self.parse("icm:accommodate")
        self.assertEqual(ICM.ACCOMMODATE, move.type_)

    def test_loadplan(self):
        m = self.parse("icm:loadplan")
        self.assertTrue(m.type_ == ICM.LOADPLAN)

    def test_und_neg_without_content(self):
        icm = self.parse("icm:und*neg")
        self.assertEqual(ICM.UND, icm.type_)
        self.assertEqual(ICM.NEG, icm.polarity)
        self.assertEqual(None, icm.content)

    def test_sem_neg(self):
        icm = self.parse("icm:sem*neg")
        self.assertEqual(ICM.SEM, icm.type_)
        self.assertEqual(ICM.NEG, icm.polarity)
        self.assertEqual(None, icm.content)

    def test_contentful_per_pos(self):
        icm = self.parse('icm:per*pos:"a string"')
        self.assertEqual(ICM.PER, icm.type_)
        self.assertEqual(ICM.POS, icm.polarity)
        expected_content = 'a string'
        self.assertEqual(expected_content, icm.content)

    def test_contentful_per_pos_from_stringfyed_move(self):
        m = ICM.create(ICM.PER, content="a string", polarity=ICM.POS)
        icm = self.parse(str(m))
        self.assertEqual(ICM.PER, icm.type_)
        self.assertEqual(ICM.POS, icm.polarity)
        expected_content = "a string"
        self.assertEqual(expected_content, icm.content)

    def test_und_int_usr(self):
        icm = self.parse("icm:und*int:USR*dest_city(paris)")
        self.assertEqual(ICM.UND, icm.type_)
        self.assertEqual(ICM.INT, icm.polarity)
        self.assertEqual("dest_city(paris)", str(icm.content))

    def test_und_int_model(self):
        icm = self.parse("icm:und*int:MODEL*dest_city(paris)")
        self.assertEqual(ICM.UND, icm.type_)
        self.assertEqual(ICM.INT, icm.polarity)
        self.assertEqual(MODEL, icm.content_speaker)
        self.assertEqual("dest_city(paris)", str(icm.content))

    def test_und_int_w_speaker_and_score(self):
        speaker = SYS
        score = 1.0
        icm = self.parse(
            "ICM(icm:und*int:USR*dest_city(paris), speaker=%s, understanding_confidence=%s)" % (speaker, score)
        )
        content = self.parse("dest_city(paris)")
        expected_move = ICM.create(
            ICM.UND,
            content=content,
            understanding_confidence=score,
            speaker=speaker,
            content_speaker=USR,
            polarity=ICM.INT
        )
        self.assertEqual(expected_move, icm)

    def test_acc_pos_w_speaker_and_no_score(self):
        speaker = SYS
        icm = self.parse("ICM(icm:acc*pos, speaker=%s)" % speaker)
        expected_move = ICM(ICM.ACC, understanding_confidence=1.0, speaker=speaker, polarity=ICM.POS)
        self.assertEqual(expected_move, icm)

    def test_und_int_icm_fails_if_faulty_speaker(self):
        with self.assertRaises(Exception):
            self.parse("icm:und*int:usr*dest_city(paris)")

    def test_und_pos_icm_for_issue_proposition(self):
        icm = self.parse("icm:und*pos:USR*goal(resolve(?X.dest_city(X)))")
        self.assertEqual(ICM.UND, icm.type_)
        self.assertEqual(ICM.POS, icm.polarity)
        self.assertEqual("goal(resolve(?X.dest_city(X)))", str(icm.content))

    def test_und_int_icm_without_speaker(self):
        score = 1.0
        speaker = SYS
        icm = self.parse(
            "ICM(icm:und*int:dest_city(paris), speaker=%s, understanding_confidence=%s)" % (speaker, score)
        )
        content = self.parse("dest_city(paris)")
        expected_move = ICM.create(
            ICM.UND,
            content=content,
            understanding_confidence=score,
            speaker=speaker,
            content_speaker=None,
            polarity=ICM.INT
        )
        self.assertEqual(expected_move, icm)

    def test_und_pos_icm_for_predicate_proposition(self):
        icm = self.parse("icm:und*pos:USR*dest_city(paris)")
        self.assertEqual(ICM.UND, icm.type_)
        self.assertEqual(ICM.POS, icm.polarity)
        self.assertEqual("dest_city(paris)", str(icm.content))

    def test_per_neg_icm(self):
        icm = self.parse("icm:per*neg")
        self.assertEqual(ICM.PER, icm.type_)
        self.assertEqual(ICM.NEG, icm.polarity)

    def test_per_neg_icm_w_speaker_and_score(self):
        speaker = SYS
        score = 1.0
        icm = self.parse("ICM(icm:per*neg, speaker=%s, understanding_confidence=%s)" % (speaker, score))
        expected_move = ICM(ICM.PER, understanding_confidence=score, speaker=speaker, polarity=ICM.NEG)
        self.assertEqual(expected_move, icm)

    def test_acc_pos_icm_no_content(self):
        icm = self.parse("icm:acc*pos")
        self.assertEqual(ICM.ACC, icm.type_)
        self.assertEqual(ICM.POS, icm.polarity)

    def test_acc_neg_icm_for_issue(self):
        icm = self.parse("icm:acc*neg:issue")
        self.assertEqual(ICM.ACC, icm.type_)
        self.assertEqual(ICM.NEG, icm.polarity)
        self.assertEqual(str(icm), "ICM(icm:acc*neg:issue)")

    def test_acc_neg_icm_for_goal_issue(self):
        icm = self.parse("icm:acc*neg:goal(perform(buy))")
        self.assertEqual(ICM.ACC, icm.type_)
        self.assertEqual(ICM.NEG, icm.polarity)
        self.assertEqual(str(icm), "ICM(icm:acc*neg:goal(perform(buy)))")

    def test_unsupported_icm_content_unparseable(self):
        with self.assertRaises(ParseError):
            self.parse("icm:acc*neg:unsupported")

    def test_acc_neg_issue_w_speaker_and_score(self):
        speaker = SYS
        score = 1.0
        icm = self.parse(f"ICM(icm:acc*neg:issue, speaker={speaker}, understanding_confidence={score})")
        expected_move = IssueICM(ICM.ACC, understanding_confidence=score, speaker=speaker, polarity=ICM.NEG)
        self.assertEqual(expected_move, icm)

    def test_undecorated_icm_move_with_ICM_classname(self):
        string = 'ICM(icm:per*pos:"this is not understood")'
        actual_move = self.parse(string)
        expected_move = ICM.create(ICM.PER, content="this is not understood", polarity=ICM.POS)
        self.assertEqual(expected_move, actual_move)

    def test_jumpto(self):
        item = self.parse("jumpto(perform(buy))")
        expected_item = JumpTo(PerformGoal(self.buy_action))
        self.assertEqual(expected_item, item)

    def test_assume(self):
        item = self.parse("assume(dest_city(paris))")
        expected_item = Assume(self.proposition_dest_city_paris)
        self.assertEqual(expected_item, item)

    def test_log(self):
        item = self.parse('log("message")')
        expected_item = Log("message")
        self.assertEqual(expected_item, item)

    def test_assume_shared(self):
        item = self.parse("assume_shared(dest_city(paris))")
        expected_item = AssumeShared(self.proposition_dest_city_paris)
        self.assertEqual(expected_item, item)

    def test_assume_issue(self):
        item = self.parse("assume_issue(?X.dest_city(X))")
        expected_item = AssumeIssue(self.dest_city_question)
        self.assertEqual(expected_item, item)

    def test_assume_issue_insist(self):
        item = self.parse("insist_assume_issue(?X.dest_city(X))")
        expected_item = AssumeIssue(self.dest_city_question, insist=True)
        self.assertEqual(expected_item, item)

    def test_service_action_terminated_proposition(self):
        object = self.parse("service_action_terminated(SomeServiceAction)")
        expected_object = ServiceActionTerminatedProposition(self.ontology_name, "SomeServiceAction")
        self.assertEqual(expected_object, object)

    def test_service_action_started_proposition(self):
        object = self.parse("service_action_started(SomeServiceAction)")
        expected_object = ServiceActionStartedProposition(self.ontology_name, "SomeServiceAction")
        self.assertEqual(expected_object, object)

    def test_string_individual(self):
        object = self.parse('"a string"')
        expected_object = Individual(self.ontology_name, 'a string', StringSort())
        self.assertEqual(expected_object, object)

    def test_empty_string_individual(self):
        object = self.parse('""')
        expected_object = Individual(self.ontology_name, '', StringSort())
        self.assertEqual(expected_object, object)

    def test_string_individual_digits_only(self):
        object = self.parse('"123"')
        expected_object = Individual(self.ontology_name, '123', StringSort())
        self.assertEqual(expected_object, object)

    def test_string_answer(self):
        move = self.parse('answer("a string")')
        individual = Individual(self.ontology_name, 'a string', StringSort())
        expected_move = self._move_factory.create_answer_move(individual)
        self.assertEqual(expected_move, move)

    def test_negative_string_answer(self):
        move = self.parse('answer(~"a string")')
        individual = NegativeIndividual(self.ontology_name, 'a string', StringSort())
        expected_move = self._move_factory.create_answer_move(individual)
        self.assertEqual(expected_move, move)

    def test_predicate_proposition_with_string_individual_in_single_quotes(self):
        object = self.parse("number_to_call('070123456')")
        expected_object = PredicateProposition(
            self.predicate_number_to_call, self.ontology.create_individual('"070123456"')
        )
        self.assertEqual(expected_object, object)

    def test_predicate_proposition_with_string_individual_in_double_quotes(self):
        object = self.parse('number_to_call("070123456")')
        expected_object = PredicateProposition(
            self.predicate_number_to_call, self.ontology.create_individual('"070123456"')
        )
        self.assertEqual(expected_object, object)

    def test_unknown_term_unparseable(self):
        with self.assertRaises(ParseError):
            self.parse("unknown_term")

    def test_parse_creates_new_instance(self):
        container_string = "{}"
        container = self.parse(container_string)
        container.add("dummy_item")
        new_container = self.parse(container_string)
        expected_new_container = Set()
        self.assertEqual(expected_new_container, new_container)

    def test_perform_goal(self):
        string = "perform(top)"
        expected_object = PerformGoal(self.top_action)
        self.assertEqual(expected_object, self.parse(string))

    def test_resolve_goal(self):
        string = "resolve(?X.price(X))"
        expected_object = ResolveGoal(self.price_question, SYS)
        self.assertEqual(expected_object, self.parse(string))

    def test_resolve_user_goal(self):
        object = self.parse("resolve_user(?X.dest_city(X))")
        expected_object = ResolveGoal(self.dest_city_question, USR)
        self.assertEqual(expected_object, object)

    def test_predicate(self):
        string = "dest_city"
        expected_object = self.predicate_dest_city
        self.assertEqual(expected_object, self.parse(string))

    def test_successful_perform_result(self):
        string = "SuccessfulServiceAction()"
        expected_object = SuccessfulServiceAction()
        self.assertEqual(expected_object, self.parse(string))

    def test_failed_perform_result(self):
        string = "FailedServiceAction(mock_failure_reason)"
        expected_object = FailedServiceAction("mock_failure_reason")
        self.assertEqual(expected_object, self.parse(string))

    def test_knowledge_precondition_question(self):
        string = "?know_answer(?X.dest_city(X))"
        expected_object = KnowledgePreconditionQuestion(self.dest_city_question)
        parsed_object = self.parse(string)
        self.assertEqual(expected_object, parsed_object)

    def test_positive_knowledge_precondition_proposition(self):
        string = "know_answer(?X.dest_city(X))"
        expected_object = KnowledgePreconditionProposition(self.dest_city_question, Polarity.POS)
        self.assertEqual(expected_object, self.parse(string))

    def test_negative_knowledge_precondition_proposition(self):
        string = "~know_answer(?X.dest_city(X))"
        expected_object = KnowledgePreconditionProposition(self.dest_city_question, Polarity.NEG)
        self.assertEqual(expected_object, self.parse(string))

    def test_move_with_knowledge_precondition_question(self):
        string = "ask(?know_answer(?X.dest_city(X)))"
        expected_object = Ask(KnowledgePreconditionQuestion(self.dest_city_question))
        self.assertEqual(expected_object, self.parse(string))

    def test_implication_proposition(self):
        string = "implies(dest_city(paris), price(1234.0))"
        expected_object = ImplicationProposition(self.proposition_dest_city_paris, self.price_proposition)
        self.assertEqual(expected_object, self.parse(string))

    def test_lambda_abstracted_implication_proposition(self):
        string = "X.implies(dest_city(paris), price(X))"
        expected_object = LambdaAbstractedImplicationPropositionForConsequent(
            self.proposition_dest_city_paris, self.parse("price"), self.ontology_name
        )
        self.assertEqual(expected_object, self.parse(string))

    def test_consequent_question(self):
        string = "?X.implies(dest_city(paris), price(X))"
        expected_object = ConsequentQuestion(
            LambdaAbstractedImplicationPropositionForConsequent(
                self.proposition_dest_city_paris, self.parse("price"), self.ontology_name
            )
        )
        self.assertEqual(expected_object, self.parse(string))

    def test_signal_action_completion_true(self):
        string = "signal_action_completion(true)"
        expected_object = GoalPerformed(True)
        self.assertEqual(expected_object, self.parse(string))

    def test_signal_action_completion_false(self):
        string = "signal_action_completion(false)"
        expected_object = GoalPerformed(False)
        self.assertEqual(expected_object, self.parse(string))

    def test_signal_action_failure(self):
        string = "signal_action_failure(some_reason)"
        expected_object = GoalAborted("some_reason")
        self.assertEqual(expected_object, self.parse(string))

    def test_change_ddd(self):
        string = "change_ddd(ddd_name)"
        expected_object = ChangeDDD("ddd_name")
        self.assertEqual(expected_object, self.parse(string))

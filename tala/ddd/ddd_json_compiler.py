import json
import xml.dom.minidom

from tala.ddd.ddd_xml_compiler import DDDXMLCompiler


class DDDJSONCompilerException(Exception):
    pass


class DDDJSONCompiler(object):
    def __init__(self):
        self._xml_compiler = DDDXMLCompiler()

    def compile_ontology(self, json_string):
        xml_string = self._convert_json_to_xml("ontology", json_string)
        return self._xml_compiler.compile_ontology(xml_string)

    def compile_domain(self, ddd_name, json_string, ontology, parser):
        xml_string = self._convert_json_to_xml("domain", json_string)
        return self._xml_compiler.compile_domain(ddd_name, xml_string, ontology, parser)

    def compile_service_interface(self, json_string):
        xml_string = self._convert_json_to_xml("service_interface", json_string)
        return self._xml_compiler.compile_service_interface(xml_string)

    def get_domain_name(self, json_string):
        data = self._parse_json(json_string)
        domain = self._get_root_node(data, "domain")
        attrs = domain.get("@", {})
        return attrs.get("name")

    def _convert_json_to_xml(self, root_name, json_string):
        data = self._parse_json(json_string)
        node = self._get_root_node(data, root_name)
        if self._is_structural_node(node):
            doc = xml.dom.minidom.Document()
            root = doc.createElement(root_name)
            doc.appendChild(root)
            self._apply_node(root, node)
            return doc.toxml(encoding="utf-8")
        return self._convert_human_to_xml(root_name, node)

    def _parse_json(self, json_string):
        if isinstance(json_string, bytes):
            json_string = json_string.decode("utf-8")
        if isinstance(json_string, str):
            return json.loads(json_string)
        if isinstance(json_string, dict):
            return json_string
        raise DDDJSONCompilerException("Expected JSON string or dict.")

    def _get_root_node(self, data, root_name):
        if root_name in data:
            node = data[root_name]
            if node is None:
                return {}
            if isinstance(node, dict):
                return node
            raise DDDJSONCompilerException(f"Expected object for root '{root_name}'.")
        if isinstance(data, dict) and data.get("@") is not None:
            return data
        raise DDDJSONCompilerException(f"Expected root '{root_name}' in JSON.")

    def _is_structural_node(self, node):
        if not isinstance(node, dict):
            return False
        return any(key in node for key in ["@", "attrs", "children", "items"])

    def _convert_human_to_xml(self, root_name, node):
        if root_name == "ontology":
            return self._convert_human_ontology(node)
        if root_name == "domain":
            return self._convert_human_domain(node)
        if root_name == "service_interface":
            return self._convert_human_service_interface(node)
        raise DDDJSONCompilerException(f"Unsupported human-readable root '{root_name}'.")

    def _convert_human_ontology(self, node):
        doc = xml.dom.minidom.Document()
        root = doc.createElement("ontology")
        root.setAttribute("name", node.get("name", ""))
        doc.appendChild(root)

        for sort in node.get("sorts", []):
            element = doc.createElement("sort")
            element.setAttribute("name", sort["name"])
            if "dynamic" in sort:
                element.setAttribute("dynamic", self._stringify(sort["dynamic"]))
            root.appendChild(element)

        for predicate in node.get("predicates", []):
            element = doc.createElement("predicate")
            element.setAttribute("name", predicate["name"])
            element.setAttribute("sort", predicate["sort"])
            if "feature_of" in predicate:
                element.setAttribute("feature_of", predicate["feature_of"])
            if "multiple_instances" in predicate:
                element.setAttribute("multiple_instances", self._stringify(predicate["multiple_instances"]))
            root.appendChild(element)

        for individual in node.get("individuals", []):
            element = doc.createElement("individual")
            element.setAttribute("name", individual["name"])
            element.setAttribute("sort", individual["sort"])
            root.appendChild(element)

        for action in node.get("actions", []):
            element = doc.createElement("action")
            element.setAttribute("name", action)
            root.appendChild(element)

        return doc.toxml(encoding="utf-8")

    def _convert_human_domain(self, node):
        doc = xml.dom.minidom.Document()
        root = doc.createElement("domain")
        root.setAttribute("name", node.get("name", ""))
        doc.appendChild(root)

        for plan in node.get("plans", []):
            goal = plan["goal"]
            goal_element = doc.createElement("goal")
            self._apply_goal_attributes(goal_element, goal)

            self._apply_goal_plan_attributes(goal_element, plan)

            plan_element = doc.createElement("plan")
            self._append_plan_items(doc, plan_element, plan.get("content", []))
            goal_element.appendChild(plan_element)

            if "preferred" in plan:
                preferred_element = doc.createElement("preferred")
                preferred_value = plan["preferred"]
                if isinstance(preferred_value, dict):
                    self._append_predicate_proposition(doc, preferred_element, preferred_value)
                goal_element.appendChild(preferred_element)

            for condition in plan.get("downdate_conditions", []):
                downdate_element = doc.createElement("downdate_condition")
                self._append_condition(doc, downdate_element, condition)
                goal_element.appendChild(downdate_element)

            if "postplan" in plan:
                postplan_element = doc.createElement("postplan")
                self._append_plan_items(doc, postplan_element, plan.get("postplan", []))
                goal_element.appendChild(postplan_element)

            for action in plan.get("superactions", []):
                superaction = doc.createElement("superaction")
                superaction.setAttribute("name", action)
                goal_element.appendChild(superaction)

            root.appendChild(goal_element)

        for question in node.get("default_questions", []):
            element = doc.createElement("default_question")
            self._apply_question_attributes(doc, element, question)
            root.appendChild(element)

        for parameters in node.get("parameters", []):
            element = doc.createElement("parameters")
            self._apply_parameters(doc, element, parameters)
            root.appendChild(element)

        for query in node.get("queries", []):
            element = doc.createElement("query")
            self._apply_query(doc, element, query)
            root.appendChild(element)

        for iterator in node.get("iterators", []):
            element = doc.createElement("iterator")
            self._apply_iterator(doc, element, iterator)
            root.appendChild(element)

        for validator in node.get("validators", []):
            element = doc.createElement("validator")
            self._apply_validator(doc, element, validator)
            root.appendChild(element)

        for dependency in node.get("dependencies", []):
            element = doc.createElement("dependency")
            self._apply_dependency(doc, element, dependency)
            root.appendChild(element)

        return doc.toxml(encoding="utf-8")

    def _convert_human_service_interface(self, node):
        doc = xml.dom.minidom.Document()
        root = doc.createElement("service_interface")
        doc.appendChild(root)

        for action in node.get("actions", []):
            element = doc.createElement("action")
            element.setAttribute("name", action["name"])
            self._apply_service_parameters(doc, element, action.get("parameters", []))
            self._apply_failure_reasons(doc, element, action.get("failure_reasons", []))
            self._apply_target(doc, element, action["target"])
            root.appendChild(element)

        for query in node.get("queries", []):
            element = doc.createElement("query")
            element.setAttribute("name", query["name"])
            self._apply_service_parameters(doc, element, query.get("parameters", []))
            self._apply_target(doc, element, query["target"])
            root.appendChild(element)

        for validator in node.get("validators", []):
            element = doc.createElement("validator")
            element.setAttribute("name", validator["name"])
            self._apply_service_parameters(doc, element, validator.get("parameters", []))
            self._apply_target(doc, element, validator["target"])
            root.appendChild(element)

        return doc.toxml(encoding="utf-8")

    def _apply_goal_attributes(self, element, goal):
        if "perform" in goal:
            element.setAttribute("type", "perform")
            element.setAttribute("action", goal["perform"]["action"])
        else:
            element.setAttribute("type", "resolve")
            question = goal["resolve"]["question"]
            self._apply_question_attributes(element.ownerDocument, element, question, type_attribute="question_type")

    def _apply_goal_plan_attributes(self, element, plan):
        bool_attrs = {
            "accommodate_without_feedback",
            "restart_on_completion",
            "reraise_on_resume",
        }
        for key in [
            "accommodate_without_feedback",
            "restart_on_completion",
            "reraise_on_resume",
            "max_answers",
            "alternatives_predicate",
        ]:
            if key in plan:
                value = plan[key]
                if key in bool_attrs:
                    value = self._stringify(value)
                element.setAttribute(key, str(value))

    def _append_plan_items(self, doc, parent, items):
        for item in items:
            if not isinstance(item, dict) or len(item) != 1:
                raise DDDJSONCompilerException("Each plan item must be a single-key object.")
            item_type, payload = next(iter(item.items()))
            element = doc.createElement(item_type)
            if item_type == "findout":
                self._apply_question_attributes(doc, element, payload["question"])
                if payload.get("allow_answer_from_pcom"):
                    element.setAttribute("allow_answer_from_pcom", "true")
                if payload.get("alts_predicate"):
                    element.setAttribute("alts_predicate", payload["alts_predicate"])
            elif item_type == "raise":
                self._apply_question_attributes(doc, element, payload["question"])
            elif item_type == "bind":
                self._apply_question_attributes(doc, element, payload["question"])
                if "allow_binding_yn_answers" in payload:
                    element.setAttribute(
                        "allow_binding_yn_answers", self._stringify(payload["allow_binding_yn_answers"])
                    )
            elif item_type == "if":
                self._append_if_condition(doc, element, payload["condition"])
                then_items = payload.get("then", [])
                if then_items:
                    then_element = doc.createElement("then")
                    self._append_plan_items(doc, then_element, then_items)
                    element.appendChild(then_element)
                else_items = payload.get("else", [])
                if else_items:
                    else_element = doc.createElement("else")
                    self._append_plan_items(doc, else_element, else_items)
                    element.appendChild(else_element)
            elif item_type == "once":
                if "id" in payload:
                    element.setAttribute("id", payload["id"])
                self._append_plan_items(doc, element, payload.get("content", []))
            elif item_type in ["forget", "forget_shared"]:
                self._apply_forget_payload(doc, element, payload)
            elif item_type == "forget_all":
                pass
            elif item_type in ["invoke_service_query", "invoke_domain_query", "reset_domain_query"]:
                self._apply_question_attributes(doc, element, payload["question"])
                if item_type == "invoke_service_query":
                    if "min_results" in payload and payload["min_results"] is not None:
                        element.setAttribute("min_results", str(payload["min_results"]))
                    if "max_results" in payload and payload["max_results"] is not None:
                        element.setAttribute("max_results", str(payload["max_results"]))
            elif item_type == "iterate":
                element.setAttribute("iterator", payload["iterator"])
            elif item_type == "change_ddd":
                element.setAttribute("name", payload["name"])
            elif item_type == "invoke_service_action":
                element.setAttribute("name", payload["name"])
                if "preconfirm" in payload:
                    element.setAttribute("preconfirm", payload["preconfirm"])
                if "postconfirm" in payload:
                    element.setAttribute("postconfirm", self._stringify(payload["postconfirm"]))
                if "downdate_plan" in payload:
                    element.setAttribute("downdate_plan", self._stringify(payload["downdate_plan"]))
            elif item_type == "get_done":
                element.setAttribute("action", payload["action"])
                if "step" in payload:
                    element.setAttribute("step", str(payload["step"]))
            elif item_type == "jumpto":
                self._apply_goal_attributes(element, payload["goal"])
            elif item_type == "assume_shared":
                self._append_predicate_proposition(doc, element, payload["proposition"])
            elif item_type == "assume_issue":
                self._apply_question_attributes(doc, element, payload["question"])
                if "insist" in payload:
                    element.setAttribute("insist", self._stringify(payload["insist"]))
            elif item_type == "assume_system_belief":
                self._append_predicate_proposition(doc, element, payload["proposition"])
            elif item_type == "inform":
                self._append_predicate_proposition(doc, element, payload["proposition"])
                if "insist" in payload:
                    element.setAttribute("insist", self._stringify(payload["insist"]))
                if "generate_end_turn" in payload:
                    element.setAttribute("generate_end_turn", self._stringify(payload["generate_end_turn"]))
                if "expected_passivity" in payload:
                    element.setAttribute("expected_passivity", str(payload["expected_passivity"]))
            elif item_type == "log":
                element.setAttribute("message", payload["message"])
                if "level" in payload:
                    element.setAttribute("level", payload["level"])
            elif item_type == "signal_action_completion":
                if "postconfirm" in payload:
                    element.setAttribute("postconfirm", self._stringify(payload["postconfirm"]))
                if "action" in payload:
                    element.setAttribute("action", payload["action"])
            elif item_type == "signal_action_failure":
                element.setAttribute("reason", payload["reason"])
                if "action" in payload:
                    element.setAttribute("action", payload["action"])
            elif item_type == "end_turn":
                element.setAttribute("expected_passivity", str(payload["expected_passivity"]))
            elif item_type == "greet":
                pass
            else:
                raise DDDJSONCompilerException(f"Unsupported plan item '{item_type}'.")
            parent.appendChild(element)

    def _apply_forget_payload(self, doc, element, payload):
        if "perform" in payload or "resolve" in payload:
            self._append_goal_proposition(doc, element, payload)
            return
        if "action_status" in payload:
            self._append_condition_proposition(doc, element, payload)
            return
        if "predicate" in payload and "value" not in payload:
            element.setAttribute("predicate", payload["predicate"])
            return
        self._append_predicate_proposition(doc, element, payload)

    def _apply_question_attributes(self, doc, element, question, type_attribute="type"):
        if "wh" in question:
            element.setAttribute(type_attribute, "wh_question")
            element.setAttribute("predicate", question["wh"]["predicate"])
            return
        if "kpq" in question:
            element.setAttribute(type_attribute, "kpq")
            embedded_question = question["kpq"]["question"]
            embedded_element = doc.createElement("embedded_question")
            self._apply_question_attributes(doc, embedded_element, embedded_question)
            element.appendChild(embedded_element)
            return
        if "yn" in question:
            element.setAttribute(type_attribute, "yn_question")
            yn_payload = question["yn"]
            if "predicate" in yn_payload:
                element.setAttribute("predicate", yn_payload["predicate"])
            elif "proposition" in yn_payload:
                proposition = yn_payload["proposition"]
                if "perform" in proposition or "resolve" in proposition:
                    self._append_goal_proposition(doc, element, proposition)
                else:
                    self._append_predicate_proposition(doc, element, proposition)
            return
        if "alt" in question:
            element.setAttribute(type_attribute, "alt_question")
            for alt_item in question["alt"]:
                alt_element = doc.createElement("alt")
                if "proposition" in alt_item:
                    self._append_predicate_proposition(doc, alt_element, alt_item["proposition"])
                elif "perform" in alt_item or "resolve" in alt_item:
                    self._append_goal_proposition(doc, alt_element, alt_item)
                else:
                    raise DDDJSONCompilerException("Unsupported alt question item.")
                element.appendChild(alt_element)
            return
        if "goal" in question:
            element.setAttribute(type_attribute, "goal")
            return
        raise DDDJSONCompilerException("Unsupported question format.")

    def _append_predicate_proposition(self, doc, parent, proposition):
        element = doc.createElement("proposition")
        element.setAttribute("predicate", proposition["predicate"])
        if "value" in proposition:
            element.setAttribute("value", proposition["value"])
        parent.appendChild(element)

    def _append_if_condition(self, doc, parent, condition):
        self._append_condition(doc, parent, condition)

    def _append_goal_proposition(self, doc, parent, proposition):
        if "perform" in proposition:
            element = doc.createElement("perform")
            element.setAttribute("action", proposition["perform"]["action"])
        elif "resolve" in proposition:
            element = doc.createElement("resolve")
            self._apply_question_attributes(doc, element, proposition["resolve"]["question"])
        else:
            raise DDDJSONCompilerException("Unsupported goal proposition.")
        parent.appendChild(element)

    def _append_condition(self, doc, parent, condition):
        if len(condition) != 1:
            raise DDDJSONCompilerException("Condition must be a single-key object.")
        condition_type, payload = next(iter(condition.items()))
        element = doc.createElement(condition_type)
        if condition_type in ["and", "or"]:
            for item in payload:
                self._append_condition(doc, element, item)
            parent.appendChild(element)
            return
        if condition_type == "not":
            self._append_condition(doc, element, payload)
            parent.appendChild(element)
            return
        if condition_type == "has_more_items":
            if "predicate" in payload:
                element.setAttribute("predicate", payload["predicate"])
            if "iterator" in payload:
                element.setAttribute("iterator", payload["iterator"])
            parent.appendChild(element)
            return
        if "predicate" in payload:
            element.setAttribute("predicate", payload["predicate"])
            if "value" in payload:
                element.setAttribute("value", payload["value"])
            parent.appendChild(element)
            return
        if "proposition" in payload:
            proposition_payload = payload["proposition"]
            self._append_condition_proposition(doc, element, proposition_payload)
            parent.appendChild(element)
            return
        self._append_condition_proposition(doc, element, payload)
        parent.appendChild(element)

    def _append_condition_proposition(self, doc, parent, proposition):
        if "predicate" in proposition:
            self._append_predicate_proposition(doc, parent, proposition)
            return
        if "perform" in proposition or "resolve" in proposition:
            self._append_goal_proposition(doc, parent, proposition)
            return
        if "service_action_terminated" in proposition:
            action = proposition["service_action_terminated"].get("name") or proposition["service_action_terminated"].get(
                "action"
            )
            element = doc.createElement("service_action_terminated")
            element.setAttribute("name", action)
            parent.appendChild(element)
            return
        if "service_action_started" in proposition:
            action = proposition["service_action_started"].get("name") or proposition["service_action_started"].get(
                "action"
            )
            element = doc.createElement("service_action_started")
            element.setAttribute("name", action)
            parent.appendChild(element)
            return
        if "action_status" in proposition:
            status_payload = proposition["action_status"]
            element = doc.createElement("action_status")
            element.setAttribute("action", status_payload["action"])
            element.setAttribute("status", status_payload["status"])
            if "reason" in status_payload:
                element.setAttribute("reason", status_payload["reason"])
            parent.appendChild(element)
            return
        if "question_status" in proposition:
            status_payload = proposition["question_status"]
            element = doc.createElement("question_status")
            element.setAttribute("status", status_payload["status"])
            if "reason" in status_payload:
                element.setAttribute("reason", status_payload["reason"])
            question_element = doc.createElement("question")
            self._apply_question_attributes(doc, question_element, status_payload["question"])
            element.appendChild(question_element)
            parent.appendChild(element)
            return
        if "resolved" in proposition:
            element = doc.createElement("resolved")
            question_element = doc.createElement("question")
            self._apply_question_attributes(doc, question_element, proposition["resolved"]["question"])
            element.appendChild(question_element)
            parent.appendChild(element)
            return
        if "know_answer" in proposition:
            element = doc.createElement("know_answer")
            question_element = doc.createElement("question")
            self._apply_question_attributes(doc, question_element, proposition["know_answer"]["question"])
            element.appendChild(question_element)
            parent.appendChild(element)
            return
        raise DDDJSONCompilerException("Unsupported condition proposition.")

    def _apply_parameters(self, doc, element, parameters):
        if "question" in parameters:
            self._apply_question_attributes(doc, element, parameters["question"], type_attribute="question_type")
        elif "predicate" in parameters:
            element.setAttribute("predicate", parameters["predicate"])
        else:
            raise DDDJSONCompilerException("Parameters entry must include question or predicate.")

        for key, value in parameters.get("parameters", {}).items():
            if key in [
                "source",
                "incremental",
                "verbalize",
                "format",
                "sort_order",
                "allow_goal_accommodation",
                "max_spoken_alts",
                "max_reported_hit_count",
                "always_ground",
                "on_zero_hits_action",
                "on_too_many_hits_action",
            ]:
                element.setAttribute(key, self._stringify(value))

        for alt_item in parameters.get("parameters", {}).get("alts", []):
            alt_element = doc.createElement("alt")
            if "proposition" in alt_item:
                self._append_predicate_proposition(doc, alt_element, alt_item["proposition"])
            elif "perform" in alt_item or "resolve" in alt_item:
                self._append_goal_proposition(doc, alt_element, alt_item)
            else:
                raise DDDJSONCompilerException("Unsupported alt parameter item.")
            element.appendChild(alt_element)

        for ask_feature in parameters.get("parameters", {}).get("ask_features", []):
            ask_element = doc.createElement("ask_feature")
            ask_element.setAttribute("predicate", ask_feature["predicate"])
            if "kpq" in ask_feature:
                ask_element.setAttribute("kpq", self._stringify(ask_feature["kpq"]))
            element.appendChild(ask_element)

        for hint in parameters.get("parameters", {}).get("hints", []):
            hint_element = doc.createElement("hint")
            inform_element = doc.createElement("inform")
            inform_payload = hint["inform"]
            if "insist" in inform_payload:
                inform_element.setAttribute("insist", self._stringify(inform_payload["insist"]))
            if "generate_end_turn" in inform_payload:
                inform_element.setAttribute("generate_end_turn", self._stringify(inform_payload["generate_end_turn"]))
            if "expected_passivity" in inform_payload:
                inform_element.setAttribute("expected_passivity", str(inform_payload["expected_passivity"]))
            self._append_predicate_proposition(doc, inform_element, inform_payload["proposition"])
            hint_element.appendChild(inform_element)
            element.appendChild(hint_element)

        for related in parameters.get("parameters", {}).get("related_information", []):
            related_element = doc.createElement("related_information")
            self._apply_question_attributes(doc, related_element, related)
            element.appendChild(related_element)

        for label in parameters.get("parameters", {}).get("label_questions", []):
            label_element = doc.createElement("label_question")
            self._apply_question_attributes(doc, label_element, label)
            element.appendChild(label_element)

        service_query = parameters.get("parameters", {}).get("service_query")
        if service_query:
            query_element = doc.createElement("service_query")
            self._apply_question_attributes(doc, query_element, service_query)
            element.appendChild(query_element)

        if parameters.get("parameters", {}).get("always_relevant"):
            always_element = doc.createElement("always_relevant")
            element.appendChild(always_element)

    def _apply_query(self, doc, element, query):
        self._apply_question_attributes(doc, element, query["question"])
        if "implications" in query:
            for implication in query["implications"]:
                implication_element = doc.createElement("implication")
                antecedent_element = doc.createElement("antecedent")
                antecedent_data = implication["antecedent"]
                if isinstance(antecedent_data, list):
                    for proposition in antecedent_data:
                        self._append_predicate_proposition(doc, antecedent_element, proposition)
                else:
                    antecedent_element.setAttribute("predicate", antecedent_data["predicate"])
                    if "value" in antecedent_data:
                        antecedent_element.setAttribute("value", antecedent_data["value"])
                consequent_element = doc.createElement("consequent")
                consequent_element.setAttribute("predicate", implication["consequent"]["predicate"])
                if "value" in implication["consequent"]:
                    consequent_element.setAttribute("value", implication["consequent"]["value"])
                implication_element.appendChild(antecedent_element)
                implication_element.appendChild(consequent_element)
                element.appendChild(implication_element)
            return

        if "select_at_random" in query:
            select_element = doc.createElement("select_at_random")
            for proposition in query["select_at_random"]["propositions"]:
                individual = doc.createElement("individual")
                individual.setAttribute("value", proposition["value"])
                select_element.appendChild(individual)
            element.appendChild(select_element)
            return

        if "enumerate" in query:
            enumerate_element = doc.createElement("enumerate")
            enumerate_element.setAttribute("randomize", self._stringify(query["enumerate"]["randomize"]))
            for proposition in query["enumerate"]["propositions"]:
                individual = doc.createElement("individual")
                individual.setAttribute("value", proposition["value"])
                enumerate_element.appendChild(individual)
            element.appendChild(enumerate_element)
            return

        raise DDDJSONCompilerException("Query must define implications, select_at_random, or enumerate.")

    def _apply_iterator(self, doc, element, iterator):
        element.setAttribute("name", iterator["name"])
        enumerate_element = doc.createElement("enumerate")
        enumerate_element.setAttribute("randomize", self._stringify(iterator["enumerate"]["randomize"]))
        enumerate_element.setAttribute("limit", str(iterator["enumerate"]["limit"]))
        for proposition in iterator["enumerate"]["propositions"]:
            prop_element = doc.createElement("proposition")
            prop_element.setAttribute("predicate", proposition["predicate"])
            if "value" in proposition:
                prop_element.setAttribute("value", proposition["value"])
            enumerate_element.appendChild(prop_element)
        element.appendChild(enumerate_element)

    def _apply_validator(self, doc, element, validator):
        element.setAttribute("name", validator["name"])
        for configuration in validator.get("valid_configurations", []):
            config_element = doc.createElement("configuration")
            for proposition in configuration:
                self._append_predicate_proposition(doc, config_element, proposition)
            element.appendChild(config_element)

    def _apply_dependency(self, doc, element, dependency):
        self._apply_question_attributes(doc, element, dependency["question"])
        for question in dependency.get("depends_on", []):
            child = doc.createElement("question")
            self._apply_question_attributes(doc, child, question)
            element.appendChild(child)

    def _apply_service_parameters(self, doc, element, parameters):
        params_element = doc.createElement("parameters")
        for parameter in parameters:
            param_element = doc.createElement("parameter")
            param_element.setAttribute("predicate", parameter["predicate"])
            if "format" in parameter:
                param_element.setAttribute("format", parameter["format"])
            if "optional" in parameter:
                param_element.setAttribute("optional", self._stringify(parameter["optional"]))
            params_element.appendChild(param_element)
        element.appendChild(params_element)

    def _apply_failure_reasons(self, doc, element, reasons):
        failure_element = doc.createElement("failure_reasons")
        for reason in reasons:
            reason_element = doc.createElement("failure_reason")
            reason_element.setAttribute("name", reason)
            failure_element.appendChild(reason_element)
        element.appendChild(failure_element)

    def _apply_target(self, doc, element, target):
        target_element = doc.createElement("target")
        if "http" in target:
            http_element = doc.createElement("http")
            http_element.setAttribute("endpoint", target["http"]["endpoint"])
            target_element.appendChild(http_element)
        elif "frontend" in target:
            target_element.appendChild(doc.createElement("frontend"))
        else:
            raise DDDJSONCompilerException("Unsupported target.")
        element.appendChild(target_element)

    def _apply_node(self, element, node):
        if not isinstance(node, dict):
            return
        attrs = self._extract_attrs(node)
        for key, value in attrs.items():
            element.setAttribute(key, self._stringify(value))

        if element.tagName == "goal":
            if "perform" in node:
                self._apply_goal_child(element, "perform", node.get("perform"))
            elif "resolve" in node:
                self._apply_goal_child(element, "resolve", node.get("resolve"))

        children = self._extract_children(node)
        if children is not None:
            for child in children:
                self._append_child_from_entry(element, child)
            return

        skip_keys = {"@", "attrs", "children", "items"}
        if element.tagName == "goal":
            skip_keys.update({"perform", "resolve"})
        for key, value in node.items():
            if key in skip_keys:
                continue
            self._append_named_child(element, key, value)

    def _append_child_from_entry(self, parent, entry):
        if not isinstance(entry, dict) or len(entry) != 1:
            raise DDDJSONCompilerException("Each child entry must be a single-key object.")
        tag, value = next(iter(entry.items()))
        self._append_named_child(parent, tag, value)

    def _append_named_child(self, parent, tag, value):
        doc = parent.ownerDocument
        if isinstance(value, list):
            for item in value:
                self._append_named_child(parent, tag, item)
            return
        element = doc.createElement(tag)
        parent.appendChild(element)
        if isinstance(value, dict):
            self._apply_node(element, value)
        elif value is None:
            return
        else:
            element.appendChild(doc.createTextNode(self._stringify(value)))

    def _extract_attrs(self, node):
        attrs = node.get("@")
        attrs_alias = node.get("attrs")
        if attrs is not None and attrs_alias is not None:
            raise DDDJSONCompilerException("Use either '@' or 'attrs', not both.")
        if attrs is None:
            attrs = attrs_alias or {}
        if not isinstance(attrs, dict):
            raise DDDJSONCompilerException("Expected attributes to be an object.")
        return attrs

    def _extract_children(self, node):
        children = node.get("children")
        items = node.get("items")
        if children is not None and items is not None:
            raise DDDJSONCompilerException("Use either 'children' or 'items', not both.")
        if children is None:
            children = items
        if children is None:
            return None
        if not isinstance(children, list):
            raise DDDJSONCompilerException("Expected children to be a list.")
        return children

    def _apply_goal_child(self, element, goal_type, value):
        if value is None:
            raise DDDJSONCompilerException(f"Goal '{goal_type}' requires an object of attributes.")
        if not isinstance(value, dict):
            raise DDDJSONCompilerException(f"Goal '{goal_type}' must be an object.")
        attrs = self._extract_attrs(value)
        element.setAttribute("type", goal_type)
        for key, attr_value in attrs.items():
            element.setAttribute(key, self._stringify(attr_value))

    def _stringify(self, value):
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

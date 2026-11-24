# JSON DDD format

This directory describes the JSON counterpart to the XML DDD formats.
JSON is intended to be the primary source format going forward, and it is
designed to be easily human readable.

## Structure
The JSON format supports both a single bundle file and separate files.
Each section is represented by a top-level key matching the XML root.

Bundle file (either directly or wrapped in `ddd`):

```json
{
  "schema_version": "1.0",
  "ontology": { ... },
  "domain": { ... },
  "service_interface": { ... }
}

{
  "ddd": {
    "schema_version": "1.0",
    "ontology": { ... },
    "domain": { ... },
    "service_interface": { ... }
  }
}
```

Separate files:

- `ontology.json` -> `{ "ontology": { ... } }`
- `domain.json` -> `{ "domain": { ... } }`
- `service_interface.json` -> `{ "service_interface": { ... } }`

Elements are represented by human-readable objects instead of XML-style
attribute bags. The format avoids `@` and `children`.

If order matters, lists are used explicitly (for example `content` arrays).
Reserved fields are kept minimal and meaningful (`name`, `goal`, `content`).

## JSON format (TDM-compatible)

The JSON design below matches what TDM executes today and intentionally
excludes unsupported constructs. In particular:

- No pre-plans anywhere.
- Postplans are supported for perform and resolve goals where the runtime
  retirement path executes them; not every removal path runs a postplan.
- `on_completion` is supported for non-restarting perform goals other than the
  built-in `top` and `up` goals.
- `replace_goal` is supported in a perform goal's main plan, not in postplans.
- Only the plan items listed below are valid.

### Domain

```json
{
  "domain": {
    "name": "MockupDomain",
    "plans": [
      {
        "goal": {"perform": {"action": "top"}},
        "content": [
          {"forget_all": {}},
          {"findout": {"question": {"goal": {}}}}
        ]
      },
      {
        "goal": {"resolve": {"question": {"wh": {"predicate": "price"}}}},
        "content": [
          {"invoke_service_query": {"question": {"wh": {"predicate": "price"}}}}
        ],
        "postplan": [
          {"forget": {"predicate": "price"}}
        ]
      }
    ],
    "default_questions": [
      {"wh": {"predicate": "dest_city"}}
    ],
    "parameters": [
      {
        "question": {"wh": {"predicate": "minute_to_set"}},
        "parameters": {
          "alts": [
            {"proposition": {"predicate": "minute_to_set", "value": "0"}},
            {"proposition": {"predicate": "minute_to_set", "value": "1"}}
          ],
          "max_spoken_alts": 5
        }
      }
    ],
    "queries": [
      {
        "question": {"wh": {"predicate": "available_rooms"}},
        "enumerate": {
          "randomize": false,
          "propositions": [
            {"predicate": "available_rooms", "value": "single"},
            {"predicate": "available_rooms", "value": "double"}
          ]
        }
      }
    ],
    "iterators": [
      {
        "name": "room_iterator",
        "enumerate": {
          "randomize": true,
          "limit": 5,
          "propositions": [
            {"predicate": "room", "value": "single"},
            {"predicate": "room", "value": "double"}
          ]
        }
      }
    ],
    "validators": [
      {
        "name": "room_validator",
        "valid_configurations": [
          [{"predicate": "room", "value": "single"}],
          [{"predicate": "room", "value": "double"}]
        ]
      }
    ],
    "dependencies": [
      {
        "question": {"wh": {"predicate": "arrival_date"}},
        "depends_on": [{"wh": {"predicate": "dest_city"}}]
      }
    ]
  }
}
```

### Goal object

```json
{"goal": {"perform": {"action": "set_time"}}}
{"goal": {"resolve": {"question": {"wh": {"predicate": "current_time"}}}}}
```

Goal attributes (optional, TDM-supported):

- `preferred`: `true` or a proposition object
- `accommodate_without_feedback`: `true|false`
- `restart_on_completion`: `true|false`
- `reraise_on_resume`: `true|false`
- `max_answers`: integer
- `alternatives_predicate`: predicate name string
- `superactions`: list of action names
- `downdate_conditions`: list of condition objects
- `postplan`: list of plan items
- `on_completion`: list of plan items run after committed successful completion

For example, use a replacement as the final content item and retain cleanup in
the source postplan:

```json
{
  "goal": {"perform": {"action": "collect_details"}},
  "content": [
    {"findout": {"question": {"wh": {"predicate": "customer_details"}}}},
    {"replace_goal": {"goal": {"perform": {"action": "review_details"}}}}
  ],
  "postplan": [{"forget": {"predicate": "temporary_details"}}]
}
```

An independent successful-completion handler can be declared as:

```json
{
  "goal": {"perform": {"action": "collect_details"}},
  "content": [{"signal_action_completion": {"postconfirm": false}}],
  "on_completion": [
    {"jumpto": {"goal": {"perform": {"action": "review_details"}}}}
  ]
}
```

### Questions

```json
{"wh": {"predicate": "dest_city"}}
{"yn": {"predicate": "need_visa"}}
{"yn": {"proposition": {"predicate": "dest_city", "value": "paris"}}}
{"alt": [
  {"proposition": {"predicate": "seat_class", "value": "economy"}},
  {"proposition": {"predicate": "seat_class", "value": "business"}},
  {"perform": {"action": "set_time"}},
  {"resolve": {"question": {"wh": {"predicate": "current_time"}}}}
]}
{"goal": {}}
```

### Propositions

```json
{"predicate": "dest_city", "value": "paris"}
{"predicate": "need_visa"}
```

### Conditions

Each condition is a single-key object:

```json
{"is_true": {"predicate": "dest_city", "value": "paris"}}
{"is_shared_fact": {"predicate": "dest_city", "value": "paris"}}
{"is_private_belief": {"predicate": "dest_city", "value": "paris"}}
{"is_shared_commitment": {"predicate": "dest_city", "value": "paris"}}
{"is_private_belief_or_shared_commitment": {"predicate": "dest_city", "value": "paris"}}
{"has_value": {"predicate": "dest_city"}}
{"has_shared_value": {"predicate": "dest_city"}}
{"has_private_value": {"predicate": "dest_city"}}
{"has_shared_or_private_value": {"predicate": "dest_city"}}
{"has_more_items": {"predicate": "available_rooms"}}
{"has_more_items": {"iterator": "room_iterator"}}
{"is_shared_commitment": {"service_action_terminated": {"name": "BookHousing"}}}
```

### Plan items

Each plan item is a single-key object. Most listed items can appear in a goal's
`content` or `postplan`. `replace_goal` is restricted to a perform goal's main
`content` plan.

```json
{"findout": {"question": {"wh": {"predicate": "dest_city"}}, "allow_answer_from_pcom": true}}
{"raise": {"question": {"wh": {"predicate": "dest_city"}}, "allow_answer_from_pcom": true}}
{"bind": {"question": {"wh": {"predicate": "dest_city"}}}}
{"if": {"condition": {"is_true": {"predicate": "need_visa"}}, "then": [...], "else": [...]}}
{"once": {"id": "optional_id", "content": [...]}}
{"forget": {"predicate": "dest_city"}}
{"forget_shared": {"predicate": "dest_city"}}
{"forget_all": {}}
{"invoke_service_query": {"question": {"wh": {"predicate": "price"}}}}
{"invoke_domain_query": {"question": {"wh": {"predicate": "price"}}}}
{"iterate": {"iterator": "room_iterator"}}
{"change_ddd": {"name": "OtherDDD"}}
{"invoke_service_action": {"name": "SetTime", "preconfirm": "assertive", "postconfirm": true, "downdate_plan": true}}
{"get_done": {"action": "SetTime", "step": "1"}}
{"jumpto": {"goal": {"perform": {"action": "top"}}}}
{"replace_goal": {"goal": {"perform": {"action": "review_details"}}}}
{"assume_shared": {"proposition": {"predicate": "dest_city", "value": "paris"}}}
{"assume_issue": {"question": {"wh": {"predicate": "dest_city"}}, "insist": true}}
{"assume_system_belief": {"proposition": {"predicate": "dest_city", "value": "paris"}}}
{"inform": {"proposition": {"predicate": "dest_city", "value": "paris"}, "insist": false, "generate_end_turn": true, "expected_passivity": 1.5}}
{"log": {"message": "debug info", "level": "debug"}}
{"signal_action_completion": {"postconfirm": true, "action": "SetTime"}}
{"signal_action_failure": {"reason": "timeout", "action": "SetTime"}}
{"end_turn": {"expected_passivity": 1.5}}
{"reset_domain_query": {"question": {"wh": {"predicate": "price"}}}}
{"greet": {}}
```

`replace_goal` belongs in a perform goal's `content` plan and adopts a target
perform goal after the source postplan runs. Its postplan must not redirect,
start a separate goal, change DDD, or signal action completion/failure.
`on_completion` is a separate goal attribute: it runs only after a committed
successful action status, after any postplan. Replacing a goal does not run its
completion hook.

Note: `downdate_plan` on `invoke_service_action` is deprecated and does not
trigger implicit downdating. Use explicit `downdate_conditions` instead.

### Question parameters

Supported parameter keys:

- `source`, `incremental`, `verbalize`, `format`, `sort_order`
- `allow_goal_accommodation`, `max_spoken_alts`, `max_reported_hit_count`
- `always_ground`, `on_zero_hits_action`, `on_too_many_hits_action`
- `service_query`: question object
- `label_questions`: list of question objects
- `related_information`: list of question objects
- `alts`: list of propositions
- `ask_features`: list of `{ "predicate": "...", "kpq": true|false }`
- `hints`: list of `{ "inform": { ... } }`
- `always_relevant`: `true`

### Ontology (summary)

```json
{
  "ontology": {
    "name": "MockupOntology",
    "sorts": [
      {"name": "city", "dynamic": false}
    ],
    "predicates": [
      {"name": "dest_city", "sort": "city", "feature_of": "trip"}
    ],
    "individuals": [
      {"name": "paris", "sort": "city"}
    ],
    "actions": ["set_time", "turn_off_alarm"]
  }
}
```

### Service interface (summary)

```json
{
  "service_interface": {
    "actions": [
      {
        "name": "SetTime",
        "target": {"http": {"endpoint": "https://example"}},
        "parameters": [
          {"predicate": "hour", "format": "string", "optional": false}
        ],
        "failure_reasons": ["timeout"]
      }
    ],
    "queries": [
      {
        "name": "current_time",
        "target": {"http": {"endpoint": "https://example"}},
        "parameters": []
      }
    ],
    "validators": [
      {
        "name": "is_valid_city",
        "target": {"frontend": {}},
        "parameters": []
      }
    ]
  }
}
```

Entity recognizers are not part of the JSON format because
they are not executed by TDM.

## JSON Schemas

Strict schemas for the JSON format live under:

- `tala/ddd/schemas/json/ddd.schema.json`
- `tala/ddd/schemas/json/ontology.schema.json`
- `tala/ddd/schemas/json/domain.schema.json`
- `tala/ddd/schemas/json/service_interface.schema.json`
```

## Authoring principles

The schema validates document shape; context-sensitive lifecycle checks are
performed by the Tala compiler. For example, compiler validation checks that a
`replace_goal` target is declared and is not the source goal, and restricts
`on_completion` to eligible perform goals.

- Avoid XML-style attribute bags. Use explicit objects.
- Prefer arrays for ordering (`content`, `then`, `else`).
- Prefer nested keys for intent (`goal.perform`, `goal.resolve`).
- Keep names short but meaningful (`plans`, `content`, `parameters`).

## Configuration
Configure free-form file names via `ddd.config.json`:

```json
{
  "ddd_bundle": "ddd.json"
}
```

For separate files:

```json
{
  "ddd_files": {
    "ontology": "ontology.json",
    "domain": "domain.json",
    "service_interface": "service_interface.json"
  }
}
```

File extensions determine format (`.json` or `.xml`). When `ddd_bundle` is
set, it takes precedence over `ddd_files`.

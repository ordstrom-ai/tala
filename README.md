# Tala

**Tala is the Python library and developer toolkit used by the TDM dialogue
platform.** It provides shared dialogue models, tools for working with dialogue
domain descriptions, natural-language generation components, and clients for
platform services.

Tala is intended for developers building dialogue applications with TDM or
extending components of the platform.

## Tala and TDM

TDM (Talkamatic Dialogue Manager) maintains the conversation state and decides
how a dialogue proceeds.

A **dialogue domain description (DDD)** defines the application-specific
knowledge and behaviour used by TDM, including questions, actions, dialogue
plans, and service interfaces. Tala provides Python representations and
supporting tools for these descriptions and for the information exchanged
between platform components.

## What’s included

- **Dialogue models** — Python representations of questions, propositions,
  actions, plans, and other dialogue concepts.
- **Domain-description tools** — Loading, compilation, and validation of DDDs in
  supported formats.
- **Natural-language generation** — Components for producing dialogue
  utterances.
- **Platform clients and utilities** — Integration with dialogue services and
  the Requestor service for language-model requests.
- **Interaction testing** — Utilities for testing dialogue interactions.
- **Interactive command-line client** — `tala-interact`, for communicating with
  a running dialogue service.

## Installation

Tala currently targets Python 3.12. Install it from PyPI:

```bash
python -m pip install tala
```

Tala provides libraries and a client; installing it does not start a TDM
dialogue service. Features that communicate with platform services require
access to those services and the corresponding configuration.

## Interact with a dialogue service

Use `tala-interact` to connect to an existing dialogue interaction endpoint:

```bash
tala-interact "https://your-host/interact/your-id"
```

To specify a dialogue domain description:

```bash
tala-interact "https://your-host/interact/your-id" --ddd my_ddd
```

Replace the example URL with the endpoint provided by your dialogue-service
deployment. The service must be running and accessible from your machine.

## Language-model requests

Tala includes `GPTRequest`, a Python client for the platform’s **Requestor
service**, which handles language-model requests. The client supports
OpenAI-compatible response formats, including structured JSON Schema output,
and reports completion status and errors for invalid structured responses.

Using this client requires a configured Requestor endpoint and a model
deployment available through that service. See the
[Requestor client guide](https://github.com/ordstrom-ai/tala/blob/main/docs/requestor.md)
for configuration and a complete example.

## Documentation and support

- [Platform documentation](https://docs.talkamatic.se)
- [Source code](https://github.com/ordstrom-ai/tala)
- [Issue tracker](https://github.com/ordstrom-ai/tala/issues)
- [Release history](https://github.com/ordstrom-ai/tala/releases)
- [Release procedure](RELEASING.md) (maintainers)

For bug reports, include the Tala version, relevant platform component
versions, and a minimal example where possible.

> ## Documentation Index
> Fetch the complete documentation index at: https://hub.hcompany.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# API reference

The Models API is OpenAI-compatible: point the official OpenAI client (or any compatible library) at H Company's endpoint and call `chat/completions`. Holo-specific behavior (structured outputs, reasoning, and the coordinate convention) is opted into through `extra_body` and a few conventions documented below.

## Endpoint

|          |                                                                     |
| :------- | :------------------------------------------------------------------ |
| Base URL | `https://api.hcompany.ai/v1/`                                       |
| Auth     | `Authorization: Bearer $HAI_API_KEY` (handled by the OpenAI client) |
| Method   | `POST /chat/completions`                                            |
| Keys     | Create one on [Portal-H](https://portal.hcompany.ai/)               |

<CodeGroup>
  ```python Python theme={null}
  import os
  from openai import OpenAI

  client = OpenAI(
      base_url="https://api.hcompany.ai/v1/",
      api_key=os.environ["HAI_API_KEY"],
  )
  ```

  ```typescript TypeScript theme={null}
  import OpenAI from "openai";

  const client = new OpenAI({
    baseURL: "https://api.hcompany.ai/v1/",
    apiKey: process.env.HAI_API_KEY,
  });
  ```
</CodeGroup>

## Models

| Model ID          | Architecture           | Input        | Output      | Context | Max images | License       |
| :---------------- | :--------------------- | :----------- | :---------- | :------ | :--------- | :------------ |
| `holo3-1-35b-a3b` | MoE, 35B / 3B active   | Text + image | \$0.25 / 1M | 65,536  | 5          | Apache 2.0    |
| `holo3-122b-a10b` | MoE, 122B / 10B active | Text + image | \$0.40 / 1M | 65,536  | 5          | Research only |

Output is billed at $1.80 / 1M tokens for `holo3-1-35b-a3b` and $3.00 / 1M tokens for `holo3-122b-a10b`. Images accept JPEG, PNG, and WebP. `holo3-1-35b-a3b` is on the free tier (rate-limited, 10 RPM); `holo3-122b-a10b` is paid-tier only. `holo3-35b-a3b` (Holo3) is still served but is being deprecated in favor of `holo3-1-35b-a3b` on June 15, 2026.

## Request parameters

Standard OpenAI fields apply (`model`, `messages`, `temperature`, `tools`, `tool_choice`, `max_tokens`). The Holo-specific options live in `extra_body`:

| Parameter                              | Where        | Type                              | Purpose                                                                                                                                                     |
| :------------------------------------- | :----------- | :-------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `structured_outputs.json`              | `extra_body` | object (JSON Schema)              | Constrain the response, at the decoding level, to a JSON object matching your schema. Use this instead of native tool calls for the structured-output loop. |
| `chat_template_kwargs.enable_thinking` | `extra_body` | boolean                           | Toggle the reasoning channel. `true` for agent loops, `false` for single-shot grounding.                                                                    |
| `reasoning_effort`                     | top level    | `"low"` \| `"medium"` \| `"high"` | How much the model plans before acting. `"medium"` is a sensible default for agent loops.                                                                   |

<CodeGroup>
  ```python Python theme={null}
  resp = client.chat.completions.create(
      model="holo3-1-35b-a3b",
      messages=messages,
      temperature=0.8,
      reasoning_effort="medium",
      extra_body={
          "structured_outputs": {"json": schema},
          "chat_template_kwargs": {"enable_thinking": True},
      },
  )
  ```

  ```typescript TypeScript theme={null}
  const resp = await client.chat.completions.create({
    model: "holo3-1-35b-a3b",
    messages,
    temperature: 0.8,
    reasoning_effort: "medium",
    // structured_outputs and chat_template_kwargs are H-specific, passed through in the request body
    ...({
      structured_outputs: { json: schema },
      chat_template_kwargs: { enable_thinking: true },
    } as any),
  });
  ```
</CodeGroup>

## Response

Holo returns two channels on every call:

| Field                                 | Contents                                                                               |
| :------------------------------------ | :------------------------------------------------------------------------------------- |
| `choices[].message.content`           | The action: the structured JSON object (structured-output mode) or the assistant text. |
| `choices[].message.reasoning_content` | The thinking trace. Read it for visibility; do not feed it back into the conversation. |
| `choices[].message.tool_calls`        | Present only in native function-calling mode (`holo3-1-35b-a3b`).                      |

<Note>
  `reasoning_content` is dropped between turns by the chat template Holo inherits. Anything the model must remember has to flow through `content`. See the [Agent loop](/agent-loop) for how to carry state forward.
</Note>

## Conventions

* **Coordinates in `[0, 1000]`.** Holo returns click positions as integers normalized to the image you sent. Scale back to pixels with the image's own dimensions. Origin is top-left.
* **Image budget.** Keep at most the last 3 screenshots in context for best accuracy, even though a request accepts up to 5 images.
* **Output formats.** Structured outputs work on both models; native function calling (`tools` / `tool_calls`) is `holo3-1-35b-a3b` only. Pick one and stay in it.

## Limits and billing

* Free tier: rate-limited access to `holo3-1-35b-a3b` (10 RPM), no credit card required.
* Paid tier: higher rate limits and access to `holo3-122b-a10b`. Add credits on [Portal-H](https://portal.hcompany.ai/credits).
* Billing is per model, per million input and output tokens. By default the API uses zero data retention.

See the [Models API pricing and FAQ](https://hcompany.ai/holo-models-api) for current rates, tiers, and billing details.

## Next steps

<CardGroup cols={3}>
  <Card title="Quickstart" icon="rocket" href="/quickstart">
    Run Holo in five minutes.
  </Card>

  <Card title="Agent loop" icon="arrows-rotate" href="/agent-loop">
    How to use Holo in your computer-use harness.
  </Card>

  <Card title="Element localization" icon="crosshairs" href="/element-localization">
    Get click coordinates from a screenshot.
  </Card>
</CardGroup>

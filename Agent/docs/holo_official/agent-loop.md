> ## Documentation Index
> Fetch the complete documentation index at: https://hub.hcompany.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Agent loop

Holo is trained to act as a multi-step agent inside a specific harness, and a few of those conventions have to come along for the model to behave well in yours: an output format, a chat layout for screenshots and tool results, an image budget, and a coordinate convention. Skip any one and quality suffers.

Holo supports two output formats, and which ones are available depends on the model:

* **Structured outputs**: the model returns a single constrained JSON object per step. Works on Holo3.1 and Holo3.
* **Native function calling**: the model returns OpenAI-style `tool_calls`. Holo3.1 only; Holo3 does not support it.

Pick one and stay in it. The reasoning channel, coordinate convention, and image budget below are identical either way; only how you declare tools and read the model's output changes. See [Output format and tool calls](#output-format-and-tool-calls).

Set up the OpenAI client first by following the [Quickstart](/quickstart).

## Reasoning

Holo returns two streams on every call: a thinking trace in `reasoning_content` and the action in `content`. Reasoning is essential in agent mode (Holo was trained to plan in `reasoning_content` before each step), so leave it on; `reasoning_effort: "medium"` is a sensible default.

<CodeGroup>
  ```python Python theme={null}
  extra_body={"chat_template_kwargs": {"enable_thinking": True}}
  ```

  ```typescript TypeScript theme={null}
  // H-specific fields are passed through in the request body
  ...({ chat_template_kwargs: { enable_thinking: true } } as any)
  ```
</CodeGroup>

Past reasoning is dropped between turns by the [Qwen 3.5 chat template](https://huggingface.co/Qwen/Qwen3.5-35B-A3B/blob/main/chat_template.jinja) Holo inherits, so anything the model needs to remember has to flow through `content` (that is what the `note` field, below, is for). When re-adding the assistant message to the conversation, push only the parsed output; do not splice the reasoning back in.

## Coordinates in `[0, 1000]`

Send a screenshot at any size. Holo returns coordinates as integers in `[0, 1000]`, normalized to that image. Scale back to pixels using its dimensions:

<CodeGroup>
  ```python Python theme={null}
  abs_x = int((x / 1000) * screenshot.width)
  abs_y = int((y / 1000) * screenshot.height)
  ```

  ```typescript TypeScript theme={null}
  const absX = Math.round((x / 1000) * screenshot.width);
  const absY = Math.round((y / 1000) * screenshot.height);
  ```
</CodeGroup>

Origin is top-left. Send and scale against the same image bytes; any resize, crop, or DPI mismatch will misclick. Pick one pixel unit (CSS or device) and stay in it end to end.

## Image budget

Keep at most the last 3 screenshots in context; more degrades accuracy. Older screenshots should be replaced with a short text placeholder, while keeping the `<observation>` wrapper. This works the same in both output formats, since observations are always `user` messages:

<CodeGroup>
  ```python Python theme={null}
  def trim_to_last_n_images(messages, n=3):
      seen = 0
      for msg in reversed(messages):
          if msg["role"] != "user" or not isinstance(msg["content"], list):
              continue
          for chunk in msg["content"]:
              if chunk.get("type") != "image_url":
                  continue
              seen += 1
              if seen > n:
                  chunk["type"] = "text"
                  chunk["text"] = "[screenshot evicted]"
                  chunk.pop("image_url", None)
  ```

  ```typescript TypeScript theme={null}
  function trimToLastNImages(messages: any[], n = 3) {
    let seen = 0;
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      if (msg.role !== "user" || !Array.isArray(msg.content)) continue;
      for (const chunk of msg.content) {
        if (chunk.type !== "image_url") continue;
        seen += 1;
        if (seen > n) {
          chunk.type = "text";
          chunk.text = "[screenshot evicted]";
          delete chunk.image_url;
        }
      }
    }
  }
  ```
</CodeGroup>

## Output format and tool calls

<Tabs>
  <Tab title="Structured outputs (Holo3.1, Holo3)">
    The model is constrained, at the decoding level, to emit a single JSON object matching a schema you provide. Tool calls are fields inside that object, so output is always valid JSON.

    ### Output JSON

    Each step, the model emits one object with three fields:

    ```json theme={null}
    {
      "note": "Submit succeeded; receipt URL is /orders/8421.",
      "thought": "Recording the receipt URL before navigating away.",
      "tool_call": {
        "tool_name": "click",
        "element": "Continue button at the bottom right",
        "x": 932,
        "y": 880
      }
    }
    ```

    `note` is the model's durable memory: anything from the current screen that future steps will need (URLs, IDs, intermediate answers). Set it to `null` when nothing new is worth recording. `thought` is a one-line plan for the next action. `tool_call` is flat: `tool_name` is a sibling of the arguments, not nested in an `args` object.

    ### Constrain output to a tool union

    Define each tool as a Pydantic model with a `Literal[tool_name]` field, then use their union as the response schema. The server's constrained decoder ensures the model emits exactly one variant, and `tool_name` is the tag you dispatch on at execution time. The example below ships three tools (click, write, answer) for illustration; real agents register a wider toolbox following the same pattern.

    <CodeGroup>
      ```python Python theme={null}
      from typing import Literal
      from pydantic import BaseModel, Field

      class ClickArgs(BaseModel):
          """Click at (x, y) coordinates"""
          tool_name: Literal["click"]
          element: str = Field(description="Detailed description of the target UI element to click on")
          x: int = Field(description="X coordinate as integer in [0, 1000]")
          y: int = Field(description="Y coordinate as integer in [0, 1000]")

      class WriteArgs(BaseModel):
          """Type text into the currently focused element without clicking first"""
          tool_name: Literal["write"]
          content: str = Field(description="Content to write")
          press_enter: bool = Field(default=False, description="Whether to press Enter after typing")

      class AnswerArgs(BaseModel):
          """Provide a final answer"""
          tool_name: Literal["answer"]
          content: str = Field(description="The answer content")

      class Step(BaseModel):
          note: str | None = Field(default=None, description="Task-relevant information from the previous observation. Empty if nothing new.")
          thought: str = Field(description="Reasoning about next steps")
          tool_call: ClickArgs | WriteArgs | AnswerArgs
      ```

      ```typescript TypeScript theme={null}
      // JSON Schema for the Step union; tool_name is the discriminator you dispatch on
      const schema = {
        type: "object",
        properties: {
          note: {
            type: ["string", "null"],
            description: "Task-relevant information from the previous observation. Empty if nothing new.",
          },
          thought: { type: "string", description: "Reasoning about next steps" },
          tool_call: {
            oneOf: [
              {
                type: "object",
                description: "Click at (x, y) coordinates",
                properties: {
                  tool_name: { const: "click" },
                  element: { type: "string", description: "Detailed description of the target UI element to click on" },
                  x: { type: "integer", description: "X coordinate as integer in [0, 1000]" },
                  y: { type: "integer", description: "Y coordinate as integer in [0, 1000]" },
                },
                required: ["tool_name", "element", "x", "y"],
              },
              {
                type: "object",
                description: "Type text into the currently focused element without clicking first",
                properties: {
                  tool_name: { const: "write" },
                  content: { type: "string", description: "Content to write" },
                  press_enter: { type: "boolean", description: "Whether to press Enter after typing" },
                },
                required: ["tool_name", "content"],
              },
              {
                type: "object",
                description: "Provide a final answer",
                properties: {
                  tool_name: { const: "answer" },
                  content: { type: "string", description: "The answer content" },
                },
                required: ["tool_name", "content"],
              },
            ],
          },
        },
        required: ["thought", "tool_call"],
      };
      ```
    </CodeGroup>

    Embed the same schema inside the system prompt under an `<output_format>` block (shown in [the loop](#a-complete-loop) below). The model was trained with the schema visible in both the prompt and `structured_outputs`, and dropping either copy noticeably hurts reliability.

    <Note>
      Use `extra_body={"structured_outputs": {"json": ...}}`, not OpenAI native function calling (`tools=[...]` / `tool_choice=...`). In this mode the model emits a flat `{note, thought, tool_call}` object in `content`, not a `tool_calls` array.
    </Note>

    Pass the schema to `structured_outputs`, then parse `content` back into your models. Because `tool_name` is a discriminator, the parsed `tool_call` narrows to exactly one variant, which is what you dispatch on:

    <CodeGroup>
      ```python Python theme={null}
      schema = Step.model_json_schema()

      resp = client.chat.completions.create(
          model=MODEL_NAME,
          messages=messages,  # the system prompt embeds this same schema; see the loop below
          extra_body={"structured_outputs": {"json": schema}},
      )

      step = Step.model_validate_json(resp.choices[0].message.content)

      # step.tool_call is now typed as the matching variant (ClickArgs, WriteArgs, ...)
      if step.tool_call.tool_name == "answer":
          print(step.tool_call.content)
      else:
          execute(step.tool_call)
      ```

      ```typescript TypeScript theme={null}
      const resp = await client.chat.completions.create({
        model: MODEL_NAME,
        messages, // the system prompt embeds this same schema; see the loop below
        ...({ structured_outputs: { json: schema } } as any),
      });

      const step = JSON.parse(resp.choices[0].message.content!);

      // step.tool_call.tool_name tells you which variant the model picked
      if (step.tool_call.tool_name === "answer") {
        console.log(step.tool_call.content);
      } else {
        execute(step.tool_call);
      }
      ```
    </CodeGroup>

    ### Chat layout

    User observations alternate with assistant JSON; tool results come back as `user` messages:

    | Role        | Body                                                          |
    | :---------- | :------------------------------------------------------------ |
    | `system`    | your prompt, then the appended `<output_format>` schema block |
    | `user`      | `<observation>` + screenshot and/or text + `</observation>`   |
    | `assistant` | the JSON object: `{note, thought, tool_call}`                 |
    | `user`      | `<tool_output tool="click">` + result + `</tool_output>`      |
    | `user`      | next `<observation>`                                          |
    | `assistant` | next JSON                                                     |

    Wrap tool results as `user` messages with `<tool_output tool="...">`, not as OpenAI `tool`-role messages.

    ### A complete loop

    Plug in your own `screenshot()` (browser, OS, emulator) and `execute(...)` dispatcher.

    <CodeGroup>
      ````python Python theme={null}
      import json, base64

      schema = Step.model_json_schema()
      system = render_prompt(tools=...) + f"\n\n<output_format>\n```json\n{json.dumps(schema)}\n```\n</output_format>"

      messages = [{"role": "system", "content": system}]

      for _ in range(MAX_STEPS):
          image_bytes = screenshot()
          b64 = base64.b64encode(image_bytes).decode()
          messages.append({"role": "user", "content": [
              {"type": "text", "text": "<observation>\n"},
              {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
              {"type": "text", "text": "\n</observation>"},
          ]})
          trim_to_last_n_images(messages, n=3)

          resp = client.chat.completions.create(
              model=MODEL_NAME,
              messages=messages,
              temperature=0.8,
              extra_body={"structured_outputs": {"json": schema}},
          )
          step = Step.model_validate_json(resp.choices[0].message.content)
          messages.append({"role": "assistant", "content": step.model_dump_json()})

          if step.tool_call.tool_name == "answer":
              return step.tool_call.content

          result = execute(step.tool_call)
          messages.append({
              "role": "user",
              "content": f'<tool_output tool="{step.tool_call.tool_name}">\n{result}\n</tool_output>',
          })
      ````

      ```typescript TypeScript theme={null}
      const system =
        renderPrompt() +
        `\n\n<output_format>\n\`\`\`json\n${JSON.stringify(schema)}\n\`\`\`\n</output_format>`;

      const messages: any[] = [{ role: "system", content: system }];

      for (let i = 0; i < MAX_STEPS; i++) {
        const b64 = (await screenshot()).toString("base64");
        messages.push({
          role: "user",
          content: [
            { type: "text", text: "<observation>\n" },
            { type: "image_url", image_url: { url: `data:image/png;base64,${b64}` } },
            { type: "text", text: "\n</observation>" },
          ],
        });
        trimToLastNImages(messages, 3);

        const resp = await client.chat.completions.create({
          model: MODEL_NAME,
          messages,
          temperature: 0.8,
          ...({ structured_outputs: { json: schema } } as any),
        });
        const step = JSON.parse(resp.choices[0].message.content!);
        messages.push({ role: "assistant", content: JSON.stringify(step) });

        if (step.tool_call.tool_name === "answer") {
          return step.tool_call.content;
        }

        const result = await execute(step.tool_call);
        messages.push({
          role: "user",
          content: `<tool_output tool="${step.tool_call.tool_name}">\n${result}\n</tool_output>`,
        });
      }
      ```
    </CodeGroup>
  </Tab>

  <Tab title="Native function calling (Holo3.1)">
    Holo3.1 supports the standard OpenAI tool-calling API. Tools are passed via the `tools` parameter, and the model replies with `tool_calls` in the assistant message. This is the most natural format for the model and integrates directly with agent frameworks that already speak OpenAI function calling.

    ### Declare tools

    Pass tool schemas via `tools`, and set `tool_choice="required"` so the model acts on every step. Do not put tool-format examples in the system prompt; the model renders the call in its own native format from `tools` alone, and a conflicting example degrades quality.

    <CodeGroup>
      ```python Python theme={null}
      tools = [
          {
              "type": "function",
              "function": {
                  "name": "click",
                  "description": "Click at (x, y) coordinates",
                  "parameters": {
                      "type": "object",
                      "properties": {
                          "element": {"type": "string", "description": "Detailed description of the target UI element"},
                          "x": {"type": "integer", "description": "X coordinate as integer in [0, 1000]"},
                          "y": {"type": "integer", "description": "Y coordinate as integer in [0, 1000]"},
                      },
                      "required": ["element", "x", "y"],
                  },
              },
          },
          {
              "type": "function",
              "function": {
                  "name": "answer",
                  "description": "Provide a final answer",
                  "parameters": {
                      "type": "object",
                      "properties": {"content": {"type": "string", "description": "The answer content"}},
                      "required": ["content"],
                  },
              },
          },
      ]
      ```

      ```typescript TypeScript theme={null}
      const tools = [
        {
          type: "function",
          function: {
            name: "click",
            description: "Click at (x, y) coordinates",
            parameters: {
              type: "object",
              properties: {
                element: { type: "string", description: "Detailed description of the target UI element" },
                x: { type: "integer", description: "X coordinate as integer in [0, 1000]" },
                y: { type: "integer", description: "Y coordinate as integer in [0, 1000]" },
              },
              required: ["element", "x", "y"],
            },
          },
        },
        {
          type: "function",
          function: {
            name: "answer",
            description: "Provide a final answer",
            parameters: {
              type: "object",
              properties: { content: { type: "string", description: "The answer content" } },
              required: ["content"],
            },
          },
        },
      ] as const;
      ```
    </CodeGroup>

    The model returns its action in `message.tool_calls`; each call carries a `function.name`, a JSON `function.arguments` string, and a unique `id`. There is no `note`/`thought` JSON here: planning lives in `reasoning_content`, and any fact the model must carry across turns should be written into the assistant `content`, since `reasoning_content` is dropped between turns.

    Pass `tools` with `tool_choice="required"`, then read the first call and dispatch on `function.name`:

    <CodeGroup>
      ```python Python theme={null}
      resp = client.chat.completions.create(
          model=MODEL_NAME,
          messages=messages,
          tools=tools,
          tool_choice="required",
      )

      call = resp.choices[0].message.tool_calls[0]
      args = json.loads(call.function.arguments)

      if call.function.name == "answer":
          print(args["content"])
      else:
          execute(call.function.name, args)
      ```

      ```typescript TypeScript theme={null}
      const resp = await client.chat.completions.create({
        model: MODEL_NAME,
        messages,
        tools,
        tool_choice: "required",
      });

      const call = resp.choices[0].message.tool_calls![0];
      const args = JSON.parse(call.function.arguments);

      if (call.function.name === "answer") {
        console.log(args.content);
      } else {
        execute(call.function.name, args);
      }
      ```
    </CodeGroup>

    ### Chat layout

    Tool results go back as `tool`-role messages keyed by `tool_call_id`, not as `user` messages:

    | Role        | Body                                                        |
    | :---------- | :---------------------------------------------------------- |
    | `system`    | your prompt (no tool-format examples)                       |
    | `user`      | `<observation>` + screenshot and/or text + `</observation>` |
    | `assistant` | `tool_calls=[{id, function: {name, arguments}}]`            |
    | `tool`      | `tool_call_id` matching the call + result                   |
    | `user`      | next `<observation>`                                        |
    | `assistant` | next `tool_calls`                                           |

    ### A complete loop

    Plug in your own `screenshot()` and `execute(name, args)` dispatcher.

    <CodeGroup>
      ```python Python theme={null}
      import json, base64

      messages = [{"role": "system", "content": render_prompt()}]

      for _ in range(MAX_STEPS):
          image_bytes = screenshot()
          b64 = base64.b64encode(image_bytes).decode()
          messages.append({"role": "user", "content": [
              {"type": "text", "text": "<observation>\n"},
              {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
              {"type": "text", "text": "\n</observation>"},
          ]})
          trim_to_last_n_images(messages, n=3)

          resp = client.chat.completions.create(
              model=MODEL_NAME,
              messages=messages,
              tools=tools,
              tool_choice="required",
              temperature=0.8,
          )
          msg = resp.choices[0].message
          messages.append(msg)

          call = msg.tool_calls[0]
          args = json.loads(call.function.arguments)

          if call.function.name == "answer":
              return args["content"]

          result = execute(call.function.name, args)
          messages.append({
              "role": "tool",
              "tool_call_id": call.id,
              "content": str(result),
          })
      ```

      ```typescript TypeScript theme={null}
      const messages: any[] = [{ role: "system", content: renderPrompt() }];

      for (let i = 0; i < MAX_STEPS; i++) {
        const b64 = (await screenshot()).toString("base64");
        messages.push({
          role: "user",
          content: [
            { type: "text", text: "<observation>\n" },
            { type: "image_url", image_url: { url: `data:image/png;base64,${b64}` } },
            { type: "text", text: "\n</observation>" },
          ],
        });
        trimToLastNImages(messages, 3);

        const resp = await client.chat.completions.create({
          model: MODEL_NAME,
          messages,
          tools,
          tool_choice: "required",
          temperature: 0.8,
        });
        const msg = resp.choices[0].message;
        messages.push(msg);

        const call = msg.tool_calls![0];
        const args = JSON.parse(call.function.arguments);

        if (call.function.name === "answer") {
          return args.content;
        }

        const result = await execute(call.function.name, args);
        messages.push({
          role: "tool",
          tool_call_id: call.id,
          content: String(result),
        });
      }
      ```
    </CodeGroup>
  </Tab>
</Tabs>

## Common pitfalls

| Symptom                                               | Likely cause                                                                                                                                                                                         |
| :---------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Clicks land far from the target                       | Coordinates not scaled to screenshot dimensions, or the screenshot was resized between send and execute                                                                                              |
| Model loops, forgets earlier facts                    | Durable facts not carried forward (`note` empty in structured mode, or nothing written to `content` in function-calling mode), or older `<observation>` wrappers dropped instead of stripped to text |
| Context window fills up                               | Image budget not enforced                                                                                                                                                                            |
| Reasoning leaks into the action                       | `<think>...</think>` written inline in `content` instead of read from `reasoning_content`                                                                                                            |
| Quality collapses after one bad step                  | Raw model output replayed in history instead of the parsed result                                                                                                                                    |
| (Structured) Model returns free-form text             | `extra_body.structured_outputs.json` is missing, or the schema lacks `Literal[tool_name]` discrimination                                                                                             |
| (Structured) Tool result has no effect                | Sent as a `tool`-role message instead of a `user` message with a `<tool_output>` wrapper                                                                                                             |
| (Function calling) Tool calls come back as plain text | `tool_choice` not set to `required`, or the system prompt contains conflicting tool-format examples                                                                                                  |
| (Function calling) Tool result ignored                | Sent as a `user` message instead of a `tool`-role message with a matching `tool_call_id`                                                                                                             |

## Next steps

<CardGroup cols={3}>
  <Card title="Element localization" icon="crosshairs" href="/element-localization">
    Get click coordinates from a screenshot.
  </Card>

  <Card title="API reference" icon="code" href="/api-reference">
    Endpoint, models, parameters, and limits.
  </Card>

  <Card title="Quickstart" icon="rocket" href="/quickstart">
    Back to setup and your first call.
  </Card>
</CardGroup>

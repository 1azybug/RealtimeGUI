> ## Documentation Index
> Fetch the complete documentation index at: https://hub.hcompany.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Element localization

Pass Holo a screenshot (URL or base64 data URI) and a text description of an element; get click coordinates back. Single-turn, no history, no thinking: set `temperature=0.0` and `enable_thinking=False`. It is a grounding primitive you can use as a vision tool inside any agent, and both Holo3 and Holo3.1 support it.

Set up the OpenAI client first by following the [Quickstart](/quickstart).

<CodeGroup>
  ```python Python theme={null}
  from pydantic import BaseModel, Field

  SCREENSHOT_URL = "https://your-host/screenshot.png"  # or "data:image/png;base64,..."
  SCREENSHOT_WIDTH, SCREENSHOT_HEIGHT = 1280, 720
  ELEMENT = "the 'Sign in' button in the top-right corner"

  class VisualLocalizerOutput(BaseModel):
      x: int = Field(ge=0, le=1000, description="X coordinate as integer in [0, 1000]")
      y: int = Field(ge=0, le=1000, description="Y coordinate as integer in [0, 1000]")

  schema = VisualLocalizerOutput.model_json_schema()

  prompt = (
      "Localize an element on the GUI image according to the provided target "
      "and output a click position.\n"
      f" * You must output a valid JSON following the format: {schema}\n"
      f" Your target is:\n{ELEMENT}"
  )

  response = client.chat.completions.create(
      model=MODEL_NAME,
      messages=[{
          "role": "user",
          "content": [
              {"type": "image_url", "image_url": {"url": SCREENSHOT_URL}},
              {"type": "text", "text": prompt},
          ],
      }],
      extra_body={
          "structured_outputs": {"json": schema},
          "chat_template_kwargs": {"enable_thinking": False},
      },
      temperature=0.0,
  )

  point = VisualLocalizerOutput.model_validate_json(response.choices[0].message.content)
  abs_x = int(point.x / 1000 * SCREENSHOT_WIDTH)
  abs_y = int(point.y / 1000 * SCREENSHOT_HEIGHT)
  print(f"Click at ({abs_x}, {abs_y})")
  ```

  ```typescript TypeScript theme={null}
  const SCREENSHOT_URL = "https://your-host/screenshot.png"; // or "data:image/png;base64,..."
  const SCREENSHOT_WIDTH = 1280;
  const SCREENSHOT_HEIGHT = 720;
  const ELEMENT = "the 'Sign in' button in the top-right corner";

  const schema = {
    type: "object",
    properties: {
      x: { type: "integer", minimum: 0, maximum: 1000, description: "X coordinate as integer in [0, 1000]" },
      y: { type: "integer", minimum: 0, maximum: 1000, description: "Y coordinate as integer in [0, 1000]" },
    },
    required: ["x", "y"],
  };

  const prompt =
    "Localize an element on the GUI image according to the provided target " +
    "and output a click position.\n" +
    ` * You must output a valid JSON following the format: ${JSON.stringify(schema)}\n` +
    ` Your target is:\n${ELEMENT}`;

  const response = await client.chat.completions.create({
    model: MODEL_NAME,
    messages: [
      {
        role: "user",
        content: [
          { type: "image_url", image_url: { url: SCREENSHOT_URL } },
          { type: "text", text: prompt },
        ],
      },
    ],
    temperature: 0.0,
    // structured_outputs and chat_template_kwargs are H-specific, passed through in the request body
    ...({
      structured_outputs: { json: schema },
      chat_template_kwargs: { enable_thinking: false },
    } as any),
  });

  const point = JSON.parse(response.choices[0].message.content!) as { x: number; y: number };
  const absX = Math.round((point.x / 1000) * SCREENSHOT_WIDTH);
  const absY = Math.round((point.y / 1000) * SCREENSHOT_HEIGHT);
  console.log(`Click at (${absX}, ${absY})`);
  ```
</CodeGroup>

Coordinates come back as integers in `[0, 1000]`, normalized to the image you sent. Scale them to pixels with the image's own dimensions, and send and scale against the same image bytes: any resize, crop, or DPI mismatch will misplace the point.

## Next steps

<CardGroup cols={3}>
  <Card title="Agent loop" icon="arrows-rotate" href="/agent-loop">
    How to use Holo in your computer-use harness.
  </Card>

  <Card title="API reference" icon="code" href="/api-reference">
    Endpoint, models, parameters, and limits.
  </Card>

  <Card title="Quickstart" icon="rocket" href="/quickstart">
    Back to setup and your first call.
  </Card>
</CardGroup>

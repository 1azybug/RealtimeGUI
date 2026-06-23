> ## Documentation Index
> Fetch the complete documentation index at: https://hub.hcompany.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Quickstart

Holo3.1 is our latest family of Vision-Language Models (VLMs) for computer-use agents across web, desktop, and mobile.

| Model               | Active Parameters | Main Use Cases                                                 | License       | Resources                                                      |
| :------------------ | :---------------- | :------------------------------------------------------------- | :------------ | :------------------------------------------------------------- |
| **Holo3.1-35B-A3B** | 3B                | Fast, low-latency computer use across web, desktop, and mobile | Apache 2.0    | [Model card](https://huggingface.co/Hcompany/Holo-3.1-35B-A3B) |
| **Holo3-35B-A3B**   | 3B                | High-throughput, low-latency                                   | Apache 2.0    | [Model card](https://huggingface.co/Hcompany/Holo3-35B-A3B)    |
| **Holo3-122B-A10B** | 10B               | Maximum performance, complex tasks                             | Research only | [Benchmarks](https://hcompany.ai/holo3)                        |

The open-weight models are on Hugging Face: see each model card above for specs and benchmarks, or browse the full [Holo3.1 collection](https://huggingface.co/collections/Hcompany/holo31) for the other sizes (0.8B, 4B, 9B) and the quantized FP8, GGUF, and NVFP4 builds. Holo3-122B-A10B is API-only, so its weights are not published; the [Holo3 blog post](https://hcompany.ai/holo3) covers its specs and performance.

## Two ways to use Holo

| Mode                                              | Pattern                                                 | Output                                              | When to use                                                                  |
| :------------------------------------------------ | :------------------------------------------------------ | :-------------------------------------------------- | :--------------------------------------------------------------------------- |
| [**Agent loop**](/agent-loop)                     | Multi-turn: conversation + screenshots → next tool call | `{note, thought, tool_call}` or native `tool_calls` | Holo as the brain of an autonomous browser or desktop agent                  |
| [**Element localization**](/element-localization) | Single-turn: image + target description → coordinates   | `{x, y}` in `[0, 1000]`                             | UI grounding inside any external agent or pipeline (yours or someone else's) |

## Get started

<Steps titleSize="h3">
  <Step title="Get an API key">
    Generate a key on [Portal-H](https://portal.hcompany.ai/) and export it. The free tier gives rate-limited access to `holo3-1-35b-a3b`, no credit card required.

    ```bash theme={null}
    export HAI_API_KEY="your-api-key-here"
    ```
  </Step>

  <Step title="Install the OpenAI client">
    The Models API is OpenAI-compatible, so the official client works as-is, only the `base_url` changes.

    <CodeGroup>
      ```bash Python theme={null}
      pip install openai
      ```

      ```bash TypeScript theme={null}
      npm install openai
      ```
    </CodeGroup>
  </Step>

  <Step title="Make your first request">
    Point the client at H by overriding `base_url`, then send a request. Holo is multimodal: you can send text, images, or both. Here is a minimal text request to confirm your key and client are working.

    <CodeGroup>
      ```python Python theme={null}
      import os
      from openai import OpenAI

      client = OpenAI(
          base_url="https://api.hcompany.ai/v1/",
          api_key=os.environ.get("HAI_API_KEY"),
      )

      response = client.chat.completions.create(
          model="holo3-1-35b-a3b",
          messages=[{"role": "user", "content": "In one sentence, what is a computer-use agent?"}],
      )

      print(response.choices[0].message.content)
      ```

      ```typescript TypeScript theme={null}
      import OpenAI from "openai";

      const client = new OpenAI({
        baseURL: "https://api.hcompany.ai/v1/",
        apiKey: process.env.HAI_API_KEY,
      });

      const response = await client.chat.completions.create({
        model: "holo3-1-35b-a3b",
        messages: [{ role: "user", content: "In one sentence, what is a computer-use agent?" }],
      });

      console.log(response.choices[0].message.content);
      ```

      ```bash cURL theme={null}
      curl https://api.hcompany.ai/v1/chat/completions \
        -H "Authorization: Bearer $HAI_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{
          "model": "holo3-1-35b-a3b",
          "messages": [{"role": "user", "content": "In one sentence, what is a computer-use agent?"}]
        }'
      ```
    </CodeGroup>

    The same API and code paths work for all models; swap `model` for `holo3-122b-a10b` when you need maximum performance.

    <Warning>
      Holo3 35B is being deprecated in favor of Holo3.1 35B on June 15, 2026. Migrate from `holo3-35b-a3b` to `holo3-1-35b-a3b`.
    </Warning>

    That is the whole setup. To use Holo on real screens, send a screenshot and continue with the agent loop or element localization below.
  </Step>
</Steps>

## Next steps

<CardGroup cols={3}>
  <Card title="Agent loop" icon="arrows-rotate" href="/agent-loop">
    How to use Holo in your computer-use harness.
  </Card>

  <Card title="Element localization" icon="crosshairs" href="/element-localization">
    Get click coordinates from a screenshot.
  </Card>

  <Card title="API reference" icon="code" href="/api-reference">
    Endpoint, models, parameters, and limits.
  </Card>
</CardGroup>

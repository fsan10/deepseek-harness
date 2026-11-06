---
description: "Host owner of the authorization Remote namespace: list sign-in flows, start one, poll its notices, answer its prompts, and finish it from the browser."
kind: "package-reference"
---

# @deepseek-ai/dsh-api-authorization-controller

English | [中文](README.zh.md)

## Summary

Expose the human-guided half of the authorization seam over Remote so a browser page can drive a sign-in: list the flows a provider offers, start one, read the notices and the current question while it runs, answer that question, and finish the attempt. The controller holds each attempt in memory for the page that started it, keeps tokens and PKCE secrets out of the views it returns, and lets the settings page or any other Client surface mount it independently of the wider settings controller.

## Table of Contents

- [Use this package](#use-this-package)
- [Model Experience](#model-experience)
- [Known Limitations and Deferred Work](#known-limitations-and-deferred-work)

-----

<a id="use-this-package"></a>
## Use this package

The Web composition mounts one `authorization-controller` row; a composition without configuration surfaces can drop it and still keep sign-in through a Client that owns the namespace, while one that has them keeps the two independent.

| Remote method | Purpose |
|---|---|
| `authorization/list` | Describe every credential key with a flow, its label, and its sign-in methods |
| `authorization/start` | Begin one key's flow and return the attempt id |
| `authorization/poll` | Read the attempt's status, accumulated notices, and current prompt |
| `authorization/answer` | Supply the value the current prompt waits for |
| `authorization/cancel` | Withdraw the provider-side flow for one key |
| `authorization/finish` | Drop the attempt and abort its controller |

Only the page holding the attempt id can answer its prompts, which keeps an interactive answer with the surface that asked for it. A finished attempt answers nothing further; starting again mints a new id.

-----

<a id="model-experience"></a>
## Model Experience

None, as the controller only brokers human-guided sign-in flows over the authorization seam, and the plugins that consume the resulting credential own every model request.

#### KV Cache effect

None; the namespace registers no system-prompt text, tool schema, or Session event.

## Known Limitations and Deferred Work

<a id="known-limitations-and-deferred-work"></a>

- **Attempts live in Host memory** — a restart or a plugin reload drops every running attempt, so the page must start a new flow; nothing is persisted.
- **One question at a time** — the record keeps the latest prompt and its answer callback, so a flow that asks two questions without the page polling in between loses the first one.
- **The controller never returns secrets** — views carry notices, question text, and status only; tokens land in the credentials store, and a Client that needs them asks the credential owner instead.

-----

### Dev Note

<details>
<summary>Maintainer context — click to expand</summary>

The controller is the projection of `ctx.authorization` onto unary calls: [`src/index.ts`](src/index.ts) owns the attempt table and the six Remote methods, and [`src/types.ts`](src/types.ts) holds the wire views. It was split from the settings controller so a composition can expose sign-in without the configuration namespace, and so the settings owner can be dropped without losing sign-in.

</details>

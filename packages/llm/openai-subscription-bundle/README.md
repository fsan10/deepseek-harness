---
description: "Serve a ChatGPT subscription as a dsh model source with the eight GPT-6 and GPT-5.6 models a Codex session lists."
kind: "package-bundle"
---

# @deepseek-ai/dsh-openai-subscription-bundle

English | [中文](README.zh.md)

## Summary

Run conversations on a ChatGPT subscription instead of an API key, limited to the eight GPT-6 and GPT-5.6 models that a Codex session lists. The bundle ships switched off, so no OpenAI group appears in the model picker until you enable it under Plugins → Experimental plugins. One sign-in under Settings → Models stores the grant for later launches, and switching the bundle off takes the group away again.

## Table of Contents

- [Use this package](#use-this-package)
- [Model Experience](#model-experience)
- [Known Limitations and Deferred Work](#known-limitations-and-deferred-work)

-----

<a id="use-this-package"></a>
## Use this package

Open Plugins → Experimental plugins and switch on **OpenAI (ChatGPT subscription)**. The row adds the bundle to the profile's `dsh.profile.bundles` list and applies the layer in place, so no restart is needed; switch it off to remove the provider route and its models again.

Then open Settings → Models → **OpenAI (ChatGPT subscription)** and choose **Sign in with ChatGPT**. The browser finishes the OAuth flow and the credentials store keeps the grant, so later launches stay signed in. The composer's model picker then lists one group with eight models — GPT-6.1 Sol, GPT-6 Astra, GPT-6.1 Terra, GPT-6 Sol, GPT-6 Luna, GPT-5.6 Sol, GPT-5.6 Terra, and GPT-5.6 Luna — and a Session selects among them exactly as it selects the DeepSeek models.

The list matches what Codex offers, so an id that Codex hides stays hidden here even though the underlying provider directory knows more models. [Switching a plugin off](../../client/ui-plugin-manager/README.md) reloads the profile layer, which is why the group disappears without a restart.

-----

<a id="model-experience"></a>
## Model Experience

Indirectly, through the [pi-ai provider](../../llm/llm-pi-ai/README.md), which owns the catalog entries, request assembly, and wire format that this layer narrows to eight ids.

#### KV Cache effect

The layer adds no prompt text and no tool schema; it only changes which model a Session sends requests to, so each selection keeps its own provider-side cache.

## Known Limitations and Deferred Work

<a id="known-limitations-and-deferred-work"></a>

- **The route needs a ChatGPT sign-in** — credentials resolve through the OAuth grant only, so a request without one fails with a missing-credential error instead of falling back to an API key.
- **The eight ids are frozen in the patch** — they are the models a Codex session advertised when this bundle was written; a model that appears later needs an edit to [`cordis.patch.yml`](cordis.patch.yml).
- **A profile override replaces the whole provider block** — the patch targets the `llm-pi-ai` row by id and replaces its `config`, so a profile that restates `providers` drops this bundle's `models` list rather than merging with it.
- **One listing per provider** — the eight ids share the single `openai` route, so a deployment that also needs the full API-key catalog cannot keep both lists at once.

-----

### Dev Note

<details>
<summary>Maintainer context — click to expand</summary>

The package is one static patch plus an empty export: [`cordis.patch.yml`](cordis.patch.yml) adds the `openai` provider under the existing `llm-pi-ai` row, [`locale/`](locale) carries the plugin-page title and description in every shipped language, and [`src/index.ts`](src/index.ts) exports nothing. Model metadata comes from the provider directory, so each `models` entry names only an `id` and inherits its name, context window, and capabilities.

</details>

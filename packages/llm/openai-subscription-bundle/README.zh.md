---
description: "把 ChatGPT 订阅当作 dsh 的模型来源，只提供 Codex 同款的八个 GPT-6 与 GPT-5.6 模型。"
kind: "package-bundle"
---

# @deepseek-ai/dsh-openai-subscription-bundle

[English](README.md) | 中文

## 概述

用 ChatGPT 订阅额度跑对话，不填 API Key，可选模型限定为 Codex 会话列出的八个 GPT-6 与 GPT-5.6 模型。此包随附默认关闭，所以在「插件 → 实验性插件」里开启之前，模型选择器不会出现 OpenAI 分组。在「设置 → 模型」里登录一次，授权会保存下来供后续启动复用；关掉这个包，分组随即消失。

## 目录

- [使用此包](#use-this-package)
- [模型体验](#model-experience)
- [已知限制与暂缓工作](#known-limitations-and-deferred-work)

-----

<a id="use-this-package"></a>
## 使用此包

打开「插件 → 实验性插件」，开启 **OpenAI（ChatGPT 订阅）**。这一行会把该包写进 profile 的 `dsh.profile.bundles` 列表并就地生效，无需重启；关掉它会移除对应的提供方路由与模型。

接着打开「设置 → 模型 → OpenAI（ChatGPT 订阅）」，点 **Sign in with ChatGPT**。浏览器走完 OAuth 流程后凭据库会保存授权，之后再启动仍保持登录。此时输入框的模型选择器里会出现一个包含八个模型的分组——GPT-6.1 Sol、GPT-6 Astra、GPT-6.1 Terra、GPT-6 Sol、GPT-6 Luna、GPT-5.6 Sol、GPT-5.6 Terra、GPT-5.6 Luna——会话选择它们的方式与选择 DeepSeek 模型完全一致。

这份列表与 Codex 一致，因此 Codex 不展示的 id 在这里同样不展示，尽管底层提供方目录知道更多模型。[关闭插件](../../client/ui-plugin-manager/README.zh.md)会重载 profile 层，所以分组无需重启就会消失。

-----

<a id="model-experience"></a>
## 模型体验

间接地，通过 [pi-ai 提供者](../../llm/llm-pi-ai/README.zh.md) 生效：目录条目、请求组装与线路格式都由它负责，这一层只把可用 id 收窄到八个。

#### KV Cache effect

这一层不添加任何提示词文本，也不添加工具 schema；它只改变会话把请求发给哪个模型，因此每次选择各自保留提供方侧缓存。

## 已知限制与暂缓工作

<a id="known-limitations-and-deferred-work"></a>

- **路由必须具备 ChatGPT 登录** — 凭据只通过 OAuth 授权解析，未登录时请求会以缺少凭据报错，而不会回退到 API Key。
- **八个 id 写死在补丁里** — 它们是编写此包时 Codex 会话对外公布的那批模型；之后新增的模型需要改 [`cordis.patch.yml`](cordis.patch.yml)。
- **profile 覆盖会替换整个提供方块** — 补丁按 id 命中 `llm-pi-ai` 行并整体替换它的 `config`，因此 profile 里重新声明 `providers` 会丢弃本包的 `models` 列表，而不是与之合并。
- **每个提供方只有一份清单** — 八个 id 共用同一条 `openai` 路由，所以既需要完整 API Key 目录的部署无法同时保留两份清单。

-----

### Dev Note

<details>
<summary>维护者上下文 — 点击展开</summary>

这个包就是一个静态补丁加一个空导出：[`cordis.patch.yml`](cordis.patch.yml) 在既有的 `llm-pi-ai` 行下加入 `openai` 提供方，[`locale/`](locale) 提供插件页标题与描述的全部随附语言，[`src/index.ts`](src/index.ts) 不导出任何内容。模型元数据来自提供方目录，所以 `models` 的每一项只写 `id`，名称、上下文窗口与能力都沿用它。

</details>

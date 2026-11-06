---
description: "登录授权 Remote 命名空间的宿主端所有者：列出登录方式、启动流程、读取提示、回答问题并结束本次尝试。"
kind: "package-reference"
---

# @deepseek-ai/dsh-api-authorization-controller

[English](README.md) | 中文

## 概述

把授权接缝中「由人参与的登录」这一半通过 Remote 暴露给浏览器页面：列出提供方支持的登录方式、启动其中一个、在运行期间读取通知与当前问题、回答该问题，并结束本次尝试。控制器把每次尝试按页面保存在内存里，返回的视图中不包含 token 与 PKCE 秘密，并让设置页或其他任意客户端界面可以独立挂载它，而不必带上整个设置控制器。

## 目录

- [使用此包](#use-this-package)
- [模型体验](#model-experience)
- [已知限制与暂缓工作](#known-limitations-and-deferred-work)

-----

<a id="use-this-package"></a>
## 使用此包

Web 组合挂载一行 `authorization-controller`；没有配置界面的组合可以去掉它，由拥有该命名空间的客户端保留登录能力，而有配置界面的组合则让两者互不依赖。

| Remote 方法 | 作用 |
|---|---|
| `authorization/list` | 描述每个带登录流程的凭据键、显示名与登录方式 |
| `authorization/start` | 启动某个键的流程并返回尝试 id |
| `authorization/poll` | 读取尝试的状态、累计通知与当前提问 |
| `authorization/answer` | 给出当前提问等待的值 |
| `authorization/cancel` | 撤回某个键在提供方侧的流程 |
| `authorization/finish` | 丢弃这次尝试并中止其控制器 |

只有持有尝试 id 的页面能回答它的提问，这样交互式回答始终留在发起它的界面上。已结束的尝试不再接受任何回答；重新启动会生成新的 id。

-----

<a id="model-experience"></a>
## 模型体验

无，因为控制器只负责在授权接缝上中转由人参与的登录流程，真正使用所得凭据的插件才拥有全部模型请求。

#### KV Cache effect

无；该命名空间不注册系统提示词文本、工具 schema 或会话事件。

## 已知限制与暂缓工作

<a id="known-limitations-and-deferred-work"></a>

- **尝试只存在于宿主内存** — 重启或插件重载会丢弃所有进行中的尝试，页面必须重新发起流程，没有任何持久化。
- **一次只保留一个问题** — 记录里只保存最新的提问及其回答回调，因此若某个流程连问两次而页面中间没有轮询，第一次提问就会丢失。
- **控制器从不返回秘密** — 视图只带通知、提问文本与状态；token 落在凭据库里，需要它的客户端应向凭据所有者索取。

-----

### Dev Note

<details>
<summary>维护者上下文 — 点击展开</summary>

控制器是 `ctx.authorization` 在单次调用上的投影：[`src/index.ts`](src/index.ts) 负责尝试表与六个 Remote 方法，[`src/types.ts`](src/types.ts) 存放线路视图。它从设置控制器中拆出，一是让没有配置界面的组合也能提供登录，二是让设置有配置界面的组合可以去掉它而不丢登录。

</details>

# DataEase 经营仪表盘嵌入

经营仪表盘仍保存并校验原始 DataEase 公共分享链接；浏览器实际加载由
`proxy.py` 提供的专用同源代理。代理只转发固定的 `DATAEASE_BASE_URL`，并在
`POST */share/proxyInfo` 中把 `inIframe` 强制改写为 `false`，同时移除防嵌入响应头。

默认配置：

- `DATAEASE_BASE_URL=http://192.168.77.111:8100`
- `DATAEASE_PROXY_PORT=8101`
- `DATAEASE_PROXY_BIND` 未设置时与主服务 `--bind` 一致
- `DATAEASE_PROXY_PUBLIC_URL` 可选；主服务位于 HTTPS 反向代理后时，应配置为可访问的 HTTPS 代理地址

代理与主服务同进程生命周期启动、停止，但监听独立端口，使 DataEase 的根路径、
静态资源、API 和 WebSocket 都保持在代理自己的来源下，不与经营配置中心路由冲突。
转发前会移除 `mocc_session` 和 `mocc_csrf` Cookie，避免把后台会话发送给 DataEase。

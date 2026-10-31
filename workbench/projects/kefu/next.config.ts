import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 验证构建可使用独立目录，不覆盖正在运行的正式服务产物。
  distDir: process.env.KEFU_NEXT_DIST_DIR || ".next",
  // Python 运行环境由本项目 pip 管理，不加入 Next.js 的部署文件追踪。
  outputFileTracingExcludes: { "/*": ["./.venv/**/*"] },
};

export default nextConfig;

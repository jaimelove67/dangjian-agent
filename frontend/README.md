# 高校智慧党建平台前端

当前业务界面使用 React 19 + Vite，源码位于 `src/`，静态素材位于 `public/`，接口适配集中在 `src/api.js` 及各业务 `*-api.js`。本工程可独立安装、测试和构建，不导入后端 Python 源码。

在本目录执行 `npm ci`、`npm run dev`、`npm test` 或 `npm run build`。默认开发地址为 `http://127.0.0.1:4173`，独立构建产物为 `dist/`。根目录也支持 npm workspace 统一管理，具体见 [运行与接口配置](../docs/frontend-backend.md)。

复制 `.env.example` 为 `.env.local` 设置数据模式及接口地址：

```dotenv
VITE_DATA_MODE=live
VITE_API_TARGET=http://127.0.0.1:8000
VITE_API_BASE_URL=/api/v1
```

`VITE_API_TARGET` 仅用于 Vite 开发和预览代理。独立域名托管时，将 `VITE_API_BASE_URL` 设为带 `/api/v1` 的后端完整地址，在后端登记允许的前端来源，再重新构建。`VITE_` 变量会进入浏览器，不能存放数据库密码、模型密钥或其他服务端秘密。

本目录的 Dockerfile / Dockerfile.tls 分别提供 HTTP 与 HTTPS 静态托管，默认构建为真实接口模式，使用 Nginx 将 `/api/v1` 请求转给 Compose 的 `app:8000`，保留 API 版本前缀。Nginx 配置位于 `deploy/`，独立部署时可按实际后端主机修改或挂载相应配置。生产部署不依赖 Vite。

# 奕阳教育 - 客户资料数据库机器人部署指南

## 1. 准备账号
推荐使用 [Railway.app](https://railway.app) 或 [Render.com](https://render.com)（均有免费额度）。

## 2. 部署步骤 (以 Railway 为例)
1. 登录 Railway，点击 `New Project` -> `Deploy from GitHub repo` (或上传文件夹)。
2. 将 `feishu_school_bot_cloud` 文件夹内容推送到 GitHub 私有仓库。
3. Railway 会自动识别 Python 环境并安装 `requirements.txt`。
4. 在 Railway 面板添加环境变量：
   - `APP_ID`: 你的飞书 App ID
   - `APP_SECRET`: 你的飞书 App Secret
   - `PORT`: 8080 (Railway 默认会自动分配，可留空)

## 3. 获取域名
部署成功后，Railway 会生成一个公网域名，例如：
`https://sunglory-bot-production.up.railway.app`

## 4. 飞书后台配置
1. 打开飞书开发者后台 -> 事件订阅。
2. **请求地址 URL** 填入：`https://你的域名/webhook`
3. 点击验证，验证通过后保存。
4. 开启机器人，发布版本。

## 5. 测试
在飞书群里发送：`@客户资料数据库 杭州市浦沿小学`
机器人应自动回复完整资料+AI 分析。

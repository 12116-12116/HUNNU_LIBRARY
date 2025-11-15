# HUNNU Library Seat Booking Web App

## 项目概述
- 本项目提供一个极简的网页界面，用于湖南师范大学图书馆座位预约。
- 登录不再进行自动/浏览器验证，统一改为“手动输入 Cookies”方式建立登录态。
- 核心文件为 `web_app.py`，页面分为三部分：
  - 图书馆座位预约
  - 账号信息查询
  - Cookie 管理

## 功能特性
- 手动管理登录 Cookie（支持 `ASP.NET_SessionId`、`cookie_come_sno`、`cookie_come_timestamp`、`dt_cookie_user_name_remember`）。
- Cookie 隔离：每个浏览器生成 `clientId` 并随请求携带 `X-Client-Id`，后端按 `clientId` 维护独立 Cookie，避免多人同时使用冲突。
- 账号信息查询：从 `apim/user/UserHandler.ashx`（失败时回退 `mobile/ajax/user/UserHandler.ashx`）读取 `user_name` 与 `real_name`。
- 座位预约：支持立即预约与“次日 07:00 定时预约”。
- 时间选择：小时范围仅 07–22，分钟仅 00/30（半小时粒度）。

## 运行环境
- 语言与框架：Python 3.x，Flask，Requests。
- 依赖安装（示例）：
  - `venv\Scripts\python.exe -m pip install flask requests`

## 快速开始
- 启动：
  - `venv\Scripts\python.exe web_app.py`
- 访问：
  - `http://127.0.0.1:5000/`

## 使用说明
### 1. Cookie 管理（登录）
- 使用抓包软件(如Fiddler Everywhere)抓取微信访问湖南师范大学图书馆公众号网站的cookies
  - 具体可抓取‘https://libwx.hunnu.edu.cn/apim/nav/NavHandler.ashx’这个url。
- 在页面“Cookie 管理”区，填写以下四项：
  - `ASP.NET_SessionId`
  - `cookie_come_sno`
  - `cookie_come_timestamp`
  - `dt_cookie_user_name_remember`
- 点击“保存 Cookie”后，后端会：
  - 为当前 `clientId` 构建双域 Cookie（`.libwx.hunnu.edu.cn` 与 `libwx.hunnu.edu.cn`）。
  - 内存保存到 `COOKIES_BY_CLIENT[clientId]`（服务重启将失效）。
  - 若未携带 `X-Client-Id`，则回退写入全局 `cookies.json`（不建议多人使用）。
- 点击“加载现有”将读取当前 `clientId` 的 Cookie；若不存在则回退读取全局 `cookies.json`。

### 2. 账号信息查询
- 在“账号信息查询”区点击“查询账号”，后端会尝试 `apim` 接口，失败则回退 `mobile` 接口。
- 页面会显示 `账号(user_name)` 与 `姓名(real_name)`。

### 3. 座位预约
- 填写日期、开始/结束时间（小时 07–22，分钟 00/30）、阅览室与座位：
  - 填写了阅览室时，需要加上大写字母前缀，如 `Z`代表总馆及总馆的教室专区。
  - `X`: 代表咸嘉湖。
  - `THP`: 代表桃花坪。
  - `NY01`: 南院分馆综合阅览室比较特殊，只有一个房间，直接输这个就行。
  - 填写了座位时，需要补齐三位数字，如 `037`代表第37号座位，不存在的座位会报错。
- 选择执行方式：
  - `立即预约(now)`：立即调用预约接口。
  - `明日 07:00 执行(next7)`：后台使用 `threading.Timer` 定时在次日 07:00 执行一次预约。使用这个功能时，不能关闭网页

## API 概览（后端）
- 所有接口均支持可选请求头 `X-Client-Id` 用于 Cookie 隔离。
- `GET /api/user`
  - 返回：`{ user_name, real_name }`
- `GET /api/cookies`
  - 返回当前 `clientId` 或全局 `cookies.json` 的键值对。
- `POST /api/cookies`
  - 请求体：`{ ASP.NET_SessionId, cookie_come_sno, cookie_come_timestamp, dt_cookie_user_name_remember }`
  - 效果：为当前 `clientId` 或全局生成双域 Cookie，并保存。
- `POST /api/book`
  - 请求体：`{ seatno, seatdate, datetime: [startMin, endMin], mode }`
  - `mode` 可为 `now` 或 `next7`。
- `GET /api/verify`
  - 探测基础登录态（尝试 `apim/basic`、失败回退 `apim/nav`）。

## 重要实现细节
- Cookie 隔离：
  - 前端首次访问生成 `clientId` 并存储于 `localStorage`；所有请求自动携带 `X-Client-Id`。
  - 后端在 `COOKIES_BY_CLIENT` 内存字典中按 `clientId` 存取 Cookie；与他人互不影响。
- HTTPS 证书校验：
  - 为便于开发，后端使用 `requests.Session().verify = False` 并静音 `InsecureRequestWarning`；生产部署建议开启证书校验并配置可信 CA。
- 回退机制：
  - 未携带 `X-Client-Id` 时，接口回退使用全局 `cookies.json`（多人共用会有冲突风险）。

## 部署建议
- 使用生产 WSGI 服务器（如 gunicorn/uwsgi，或 Windows 下 IIS/Waitress）与反向代理。
- 开启 HTTPS 证书校验，去除 `verify=False` 与警告静音逻辑。
- 持久化 Cookie 隔离存储：将 `COOKIES_BY_CLIENT` 迁移至文件或数据库（如 SQLite/Redis），以避免服务重启丢失。
- 配置环境变量或配置文件管理 `BASE` 与请求头，以便后续维护。

## 目录结构（核心）
- `web_app.py`：核心后端与前端页面模板，提供所有接口与 UI。
- `cookies.json`：可选的全局 Cookie 文件（仅在未携带 `X-Client-Id` 时使用）。
- 其他脚本（如 `oauth2_login.py`、`direct_try_book.py`）现已不参与登录流程，可忽略或移除。

## 常见问题
- PowerShell 无法激活虚拟环境：使用 `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` 或直接用 `venv\Scripts\python.exe` 运行。
- 请求接口出现 `InsecureRequestWarning`：开发环境已静音；生产建议开启校验并安装可信证书。
- 多人使用冲突：确保每位用户通过浏览器的 Cookie 管理区输入并保存，浏览器将自动携带独立 `clientId` 进行隔离。
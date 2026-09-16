#!/usr/bin/env node
// WhalePet 的 DSH 宿主垫片（spike 阶段版本）。
//
// 作用：在没有 DSH 的情况下把 dsh-whale-widget 插件（Node 端 lib/index.js +
// 浏览器端 assets/whale-widget.js）跑起来，对外提供：
//   - GET  /                 假 DSH 宿主页面（#root > textarea 满足插件入口自检）
//   - GET  /dsh-whale/*      插件自己注册的全部路由（widget.js / balance.json / ...）
//   - POST /__host/usage     外壳把本地中转抓到的真实 usage 合成 DSH 会话事件喂给插件
//   - GET  /__host/status    自检信息（路由表、DSH_HOME、插件根目录）
//
// 插件所需的 ctx 服务在这里用最小实现顶上：
//   webServer.register / webServer.tapIndex / credentials.resolve|set /
//   connection.requestRejection / on / effect / get

import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const ROOT = path.resolve(process.env.WHALE_PET_ROOT || process.cwd())
const PLUGIN_DIR = path.resolve(
  process.env.WHALE_PET_PLUGIN || path.join(ROOT, 'vendor', 'dsh-whale-widget'),
)
const DATA_DIR = path.resolve(process.env.WHALE_PET_DATA || path.join(ROOT, 'data'))
const DSH_HOME = path.resolve(process.env.DSH_HOME || path.join(DATA_DIR, 'dsh-home'))
const QUIET = process.env.WHALE_PET_QUIET === '1'

// 插件内部用 DSH_HOME 决定角色/音频/配置文件的落盘位置，必须在 import 之前设好。
process.env.DSH_HOME = DSH_HOME
fs.mkdirSync(DSH_HOME, { recursive: true })

function log(...args) {
  if (!QUIET) console.error('[host]', ...args)
}

// ---------------------------------------------------------------- credentials
// DSH 官方凭据的本地替身：一个 JSON 文件，keyRef -> 密钥明文。
// 真实 DSH 会把密钥放系统凭据库；桌宠是单机程序，放数据目录即可（不进分发包）。
const CRED_FILE = path.join(DSH_HOME, 'credentials.json')

function readCredFile() {
  try {
    const obj = JSON.parse(fs.readFileSync(CRED_FILE, 'utf8'))
    return obj && typeof obj === 'object' ? obj : {}
  } catch {
    return {}
  }
}

function writeCredFile(obj) {
  fs.mkdirSync(path.dirname(CRED_FILE), { recursive: true })
  fs.writeFileSync(CRED_FILE, JSON.stringify(obj, null, 2), 'utf8')
}

const credentials = {
  // 注意：真实 DSH 的 resolve() 返回的是"凭据对象"，插件里统一读 `cred.value`
  // （见 lib/index.js 的 fetchBalance / 各厂商取 key 的地方）。这里必须返回对象，
  // 直接返回字符串会让 Authorization 变成 "Bearer undefined" → 401。
  async resolve(ref) {
    if (!ref) return null
    const fromEnv = process.env[ref]
    const fromFile = readCredFile()[ref]
    const value = fromEnv || fromFile
    if (process.env.WHALE_PET_DEBUG_CRED === '1') {
      log(`credential.resolve(${ref}) env=${fromEnv ? 'yes' : 'no'} file=${fromFile ? 'yes' : 'no'}`)
    }
    if (!value) return null
    return { ref, keyRef: ref, name: ref, value: String(value), source: 'whalepet-local' }
  },
  async set(ref, value) {
    if (!ref) throw new Error('empty key ref')
    const obj = readCredFile()
    if (value === null || value === undefined || value === '') delete obj[ref]
    else obj[ref] = String(value)
    writeCredFile(obj)
  },
  async delete(ref) {
    const obj = readCredFile()
    delete obj[ref]
    writeCredFile(obj)
  },
}

// ---------------------------------------------------------------------- ctx
const routes = []
const indexTaps = []
const listeners = new Map()
const effectDisposers = []

// 插件的信任栅栏：真实 DSH 用它拒绝 Host/Origin 被伪造成非本地的请求。
// 桌宠的 HTTP 服务只监听 127.0.0.1，栅栏返回 false（插件自带 fail-open 分支）。
const connection = {
  requestRejection() {
    return false
  },
}

const ctx = {
  webServer: {
    register(route) {
      if (!route || typeof route.handler !== 'function') throw new Error('bad route')
      routes.push(route)
      return () => {
        const i = routes.indexOf(route)
        if (i >= 0) routes.splice(i, 1)
      }
    },
    tapIndex(fn) {
      if (typeof fn !== 'function') throw new Error('bad tapIndex')
      indexTaps.push(fn)
      return () => {
        const i = indexTaps.indexOf(fn)
        if (i >= 0) indexTaps.splice(i, 1)
      }
    },
  },
  credentials,
  connection,
  get(name) {
    if (name === 'connection') return connection
    if (name === 'credentials') return credentials
    if (name === 'webServer') return ctx.webServer
    return undefined
  },
  on(event, fn) {
    if (typeof fn !== 'function') throw new Error('bad listener')
    if (!listeners.has(event)) listeners.set(event, [])
    listeners.get(event).push(fn)
    return () => {
      const list = listeners.get(event) || []
      const i = list.indexOf(fn)
      if (i >= 0) list.splice(i, 1)
    }
  },
  effect(fn) {
    try {
      const dispose = fn()
      if (typeof dispose === 'function') effectDisposers.push(dispose)
    } catch (err) {
      log('effect 执行失败：', err && err.message)
    }
    return () => {}
  },
  emit(event, ...args) {
    for (const fn of listeners.get(event) || []) {
      try {
        fn(...args)
      } catch (err) {
        log(`监听器 ${event} 抛错：`, err && err.message)
      }
    }
  },
  emitCount(event) {
    return (listeners.get(event) || []).length
  },
}

// ------------------------------------------------------------------- 加载插件
const pluginEntry = path.join(PLUGIN_DIR, 'lib', 'index.js')
let pluginName = '(unknown)'
try {
  if (!fs.existsSync(pluginEntry)) throw new Error(`找不到插件入口：${pluginEntry}`)
  const mod = await import(pathToFileURL(pluginEntry).href)
  const plugin = mod.default || mod
  pluginName = plugin && plugin.name ? plugin.name : '(anonymous)'
  if (!plugin || typeof plugin.apply !== 'function') throw new Error('插件没有导出 apply()')
  await plugin.apply(ctx)
  log(`插件已加载：${pluginName}（${routes.length} 条路由）`)
} catch (err) {
  console.error('[host] 插件加载失败：', (err && err.stack) || err)
  process.exit(2)
}

// --------------------------------------------------------------- 假 DSH 页面
// 插件入口自检要求 #root 内有 textarea 或 contenteditable，否则整个挂件不初始化。
// 那个 textarea 只是"通行证"，用 1px、不可见、不参与布局的容器藏起来。
const INDEX_HTML = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WhalePet</title>
<style>
  html, body { margin: 0; padding: 0; width: 100%; height: 100%;
    background: transparent; overflow: hidden;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; }
  #root { position: fixed; inset: 0; }
  #whale-gate { position: fixed; right: 0; bottom: 0; width: 1px; height: 1px;
    opacity: 0; pointer-events: none; border: 0; resize: none; overflow: hidden; }

  /* —— 桌面版适配（DSH 里这些面板盖在不透明的聊天界面上，桌面上背景是透明的）——
     1) 菜单/列表原为 rgba(255,255,255,.92) 的磨砂白：8% 的透明会让壁纸透出来（壁纸偏红时面板发粉），
        这里改成不透明纯白，保持原本的浅色风格。
     2) 弹窗遮罩原为 rgba(15,23,42,.55) 的全屏深色：在桌面上会把整个屏幕压暗，
        这里减到 .22，既保留"模态聚焦"的观感，又不会把桌面压黑。 */
  .dshwv-menu,
  .dshwv-rolelist,
  .dshwv-audiolist,
  .dshwv-bubblelist { background: #ffffff !important; }
  .dshwv-bubmask,
  .dshwv-usage-mask,
  .dshwv-resmask,
  .dshwv-snapmask,
  .dshwv-cropmask,
  .dshwv-confirmmask,
  .dshwv-audiomask { background: rgba(15, 23, 42, .22) !important; }
</style>
</head>
<body>
<div id="root"><textarea id="whale-gate" aria-hidden="true" tabindex="-1"></textarea></div>
</body>
</html>`

function renderIndex() {
  let html = INDEX_HTML
  for (const tap of indexTaps) {
    try {
      const out = tap(html)
      if (typeof out === 'string' && out) html = out
    } catch (err) {
      log('tapIndex 转换失败：', err && err.message)
    }
  }
  return html
}

// ------------------------------------------------------------- 合成会话事件
// 外壳的中转代理抓到一次真实调用后 POST 过来；这里翻译成 DSH 的会话事件，
// 插件据此算出"本轮消耗 / 模型明细 / 额度累计"。
const sessions = new Map()

function feedUsage(payload) {
  const sid = String(payload.sessionId || 'desktop')
  const turn = Number.isFinite(Number(payload.turn)) ? Number(payload.turn) : (sessions.get(sid) || 0) + 1
  sessions.set(sid, turn)
  const usage = {
    inputTokens: Number(payload.inputTokens) || 0,
    cacheReadTokens: Number(payload.cacheReadTokens) || 0,
    outputTokens: Number(payload.outputTokens) || 0,
    reasoningTokens: Number(payload.reasoningTokens) || 0,
  }
  const model = String(payload.model || '')
  ctx.emit('session/event', { id: sid }, {
    type: 'assistant/message',
    data: { turn, usage, message: { source: { model } } },
  })
  if (payload.endTurn !== false) {
    ctx.emit('session/event', { id: sid }, { type: 'turn/end', data: { turn } })
  }
  return { turn, usage, model }
}

// ------------------------------------------------------------------ HTTP 服务
function sendJson(res, body, status = 200) {
  const text = JSON.stringify(body)
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
  })
  res.end(text)
}

function readBody(req, limit = 1 << 20) {
  return new Promise((resolve, reject) => {
    let size = 0
    const chunks = []
    req.on('data', (chunk) => {
      size += chunk.length
      if (size > limit) {
        reject(new Error('body too large'))
        req.destroy()
        return
      }
      chunks.push(chunk)
    })
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
    req.on('error', reject)
  })
}

const server = http.createServer(async (req, res) => {
  let pathname = '/'
  try {
    pathname = new URL(req.url, 'http://127.0.0.1').pathname
  } catch {
    pathname = '/'
  }

  if (pathname === '/' || pathname === '/index.html') {
    const html = renderIndex()
    res.writeHead(200, {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-store',
    })
    res.end(html)
    return
  }

  if (pathname === '/__host/status') {
    sendJson(res, {
      ok: true,
      plugin: pluginName,
      pluginDir: PLUGIN_DIR,
      dshHome: DSH_HOME,
      routeCount: routes.length,
      routes: routes.map((r) => `${r.kind || 'exact'} ${r.path}`),
      listeners: [...listeners.keys()].map((k) => `${k}:${ctx.emitCount(k)}`),
      credentialKeys: Object.keys(readCredFile()),
    })
    return
  }

  if (pathname === '/__host/usage' && req.method === 'POST') {
    try {
      const raw = await readBody(req)
      const payload = raw ? JSON.parse(raw) : {}
      sendJson(res, { ok: true, ...feedUsage(payload) })
    } catch (err) {
      sendJson(res, { ok: false, error: String((err && err.message) || err) }, 400)
    }
    return
  }

  // 外壳写入/清除密钥：GET 时只回"有哪些 key"，绝不回明文
  if (pathname === '/__host/credential') {
    try {
      if (req.method === 'POST') {
        const raw = await readBody(req)
        const payload = raw ? JSON.parse(raw) : {}
        await credentials.set(String(payload.ref || ''), payload.value)
        sendJson(res, { ok: true, keys: Object.keys(readCredFile()) })
      } else {
        sendJson(res, { ok: true, keys: Object.keys(readCredFile()) })
      }
    } catch (err) {
      sendJson(res, { ok: false, error: String((err && err.message) || err) }, 400)
    }
    return
  }

  if (pathname === '/__host/shutdown' && req.method === 'POST') {
    sendJson(res, { ok: true })
    setTimeout(() => shutdown('http'), 50)
    return
  }

  const route = routes.find((r) => (r.kind === 'prefix' ? pathname.startsWith(r.path) : r.path === pathname))
  if (route) {
    try {
      await route.handler(req, res)
    } catch (err) {
      log(`路由 ${pathname} 处理失败：`, (err && err.stack) || err)
      if (!res.headersSent) sendJson(res, { ok: false, error: String((err && err.message) || err) }, 500)
      else try { res.end() } catch {}
    }
    return
  }

  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' })
  res.end('not found')
})

let shuttingDown = false
function shutdown(reason) {
  if (shuttingDown) return
  shuttingDown = true
  log('退出：', reason)
  for (const dispose of effectDisposers) {
    try {
      dispose()
    } catch {}
  }
  server.close(() => process.exit(0))
  setTimeout(() => process.exit(0), 1500).unref()
}

process.on('SIGINT', () => shutdown('sigint'))
process.on('SIGTERM', () => shutdown('sigterm'))
process.on('uncaughtException', (err) => log('未捕获异常：', (err && err.stack) || err))
process.on('unhandledRejection', (err) => log('未处理的 Promise 拒绝：', (err && err.stack) || err))

const wantPort = Number(process.env.WHALE_PET_PORT || 0) || 0
server.listen(wantPort, '127.0.0.1', () => {
  const { port } = server.address()
  // 握手行：外壳读取这一行拿到真实端口
  process.stdout.write(`WHALE_HOST_READY ${JSON.stringify({ port, pid: process.pid })}\n`)
  log(`已监听 http://127.0.0.1:${port}/（DSH_HOME=${DSH_HOME}）`)
})

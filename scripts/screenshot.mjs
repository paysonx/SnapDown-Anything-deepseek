/**
 * 设计验收截图脚本：通过 Chrome DevTools Protocol 抓取截图。
 *
 * 用法：node scripts/screenshot.mjs <url> <输出路径> [宽度] [高度] [等待毫秒] [full|viewport]
 * 依赖：本机已启动带 --remote-debugging-port=9222 的 Chrome。
 *
 * 之所以不用 `chrome --screenshot`：页面常驻 SSE 长连接，headless 的
 * load/virtual-time 判定会一直等待，截图永远不落盘。
 */
import { writeFileSync } from 'node:fs'

const [, , url, out, width = '1400', height = '900', waitMs = '2500', mode = 'full', clickSelector = ''] =
  process.argv
if (!url || !out) {
  console.error(
    'usage: node scripts/screenshot.mjs <url> <out.png> [width] [height] [waitMs] [full|viewport]',
  )
  process.exit(1)
}

const DEBUG = 'http://127.0.0.1:9222'
const list = await (await fetch(`${DEBUG}/json/list`)).json()
const page = list.find((item) => item.type === 'page')
if (!page) throw new Error('没有可用的 page target')

const ws = new WebSocket(page.webSocketDebuggerUrl)
await new Promise((resolve, reject) => {
  ws.addEventListener('open', resolve, { once: true })
  ws.addEventListener('error', reject, { once: true })
})

let nextId = 0
const pending = new Map()
ws.addEventListener('message', (event) => {
  const message = JSON.parse(event.data)
  const entry = pending.get(message.id)
  if (!entry) return
  pending.delete(message.id)
  if (message.error) entry.reject(new Error(JSON.stringify(message.error)))
  else entry.resolve(message.result)
})

function send(method, params = {}) {
  const id = ++nextId
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject })
    ws.send(JSON.stringify({ id, method, params }))
  })
}

await send('Page.enable')
await send('Emulation.setDeviceMetricsOverride', {
  width: Number(width),
  height: Number(height),
  deviceScaleFactor: 1,
  mobile: false,
})
await send('Page.navigate', { url })
await new Promise((resolve) => setTimeout(resolve, Number(waitMs)))

// 可选：截图前点一下某个元素，用于验证展开/收起这类交互后的布局
if (clickSelector) {
  await send('Runtime.evaluate', {
    expression: `document.querySelector(${JSON.stringify(clickSelector)})?.click()`,
  })
  await new Promise((resolve) => setTimeout(resolve, 400))
}

const metrics = await send('Page.getLayoutMetrics')
const content = metrics.cssContentSize ?? metrics.contentSize
const clip = {
  x: 0,
  y: 0,
  width: Number(width),
  height: Math.ceil(content.height),
  scale: 1,
}

// 顺带打印「首屏是否需要滚动才能看到主按钮」，用于验收按钮是否与内容同屏
const probe = await send('Runtime.evaluate', {
  expression: `(() => {
    const primary = document.querySelector('.card-foot--sticky .btn-primary')
    const box = primary ? primary.getBoundingClientRect() : null
    return JSON.stringify({
      innerHeight: window.innerHeight,
      pageHeight: document.documentElement.scrollHeight,
      primaryBottom: box ? Math.round(box.bottom) : null,
    })
  })()`,
  returnByValue: true,
})
console.log('metrics', probe.result.value)

const shot =
  mode === 'viewport'
    ? { format: 'png', captureBeyondViewport: false }
    : { format: 'png', captureBeyondViewport: true, clip }
const { data } = await send('Page.captureScreenshot', shot)
writeFileSync(out, Buffer.from(data, 'base64'))
console.log(`saved ${out} (${clip.width}x${clip.height})`)
ws.close()

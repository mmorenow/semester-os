/**
 * Headless Chromium screenshots and WebM recordings for the README, driven by capture.py.
 *
 *   node capture.cjs <shots|notes|onboarding> <base url> <out dir> <settings json>
 *
 * Playwright comes from a scratch install via NODE_PATH, not the app's dependencies.
 */

const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require('playwright')

const [, , scene, baseUrl, outDir, settingsJson] = process.argv
const settings = JSON.parse(settingsJson || '{}')
const TIMEZONE = settings.timezone || 'America/Indiana/Indianapolis'
const NOW = new Date(settings.now)

/** Page of a failed scene, for the failure screenshot. */
let lastPage = null

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/** Headless Chromium draws no pointer: paint an arrow, click rings and a dragged-file chip. */
const CURSOR_SCRIPT = `
(() => {
  if (window.__captureCursor) return
  window.__captureCursor = true
  const install = () => {
    const style = document.createElement('style')
    style.textContent = \`
      #capture-cursor { position: fixed; top: 0; left: 0; z-index: 2147483647; pointer-events: none;
        width: 22px; height: 22px; transform: translate(-100px, -100px); will-change: transform; }
      #capture-cursor svg { filter: drop-shadow(0 1px 2px rgba(0,0,0,.55)); }
      .capture-ring { position: fixed; z-index: 2147483646; pointer-events: none; width: 28px; height: 28px;
        margin: -14px 0 0 -14px; border-radius: 999px; border: 2px solid rgba(96,165,250,.9);
        animation: capture-ring .45s ease-out forwards; }
      @keyframes capture-ring { from { transform: scale(.4); opacity: 1 } to { transform: scale(1.3); opacity: 0 } }
      #capture-file { position: fixed; top: 0; left: 0; z-index: 2147483645; pointer-events: none; display: none;
        align-items: center; gap: 8px; padding: 8px 12px; border-radius: 8px; font: 500 13px/1.2 system-ui, sans-serif;
        color: #e5e7eb; background: rgba(30,32,38,.96); border: 1px solid rgba(255,255,255,.14);
        box-shadow: 0 8px 24px rgba(0,0,0,.45); transform: translate(-400px,-400px); }
    \`
    document.head.appendChild(style)
    const cursor = document.createElement('div')
    cursor.id = 'capture-cursor'
    cursor.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M4 2.5v17.2l4.6-4.4 3 6.6 3-1.4-3-6.4h6.4z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>'
    document.body.appendChild(cursor)
    const file = document.createElement('div')
    file.id = 'capture-file'
    file.innerHTML = '<svg width="16" height="16" viewBox="0 0 256 256" fill="currentColor"><path d="M213.66 82.34l-56-56A8 8 0 0 0 152 24H56a16 16 0 0 0-16 16v176a16 16 0 0 0 16 16h144a16 16 0 0 0 16-16V88a8 8 0 0 0-2.34-5.66zM160 51.31L188.69 80H160zM200 216H56V40h88v48a8 8 0 0 0 8 8h48z"/></svg><span></span>'
    document.body.appendChild(file)
    window.addEventListener('mousemove', (event) => {
      cursor.style.transform = 'translate(' + (event.clientX - 3) + 'px,' + (event.clientY - 2) + 'px)'
      file.style.transform = 'translate(' + (event.clientX + 14) + 'px,' + (event.clientY + 16) + 'px)'
    }, true)
    window.addEventListener('mousedown', (event) => {
      const ring = document.createElement('div')
      ring.className = 'capture-ring'
      ring.style.left = event.clientX + 'px'
      ring.style.top = event.clientY + 'px'
      document.body.appendChild(ring)
      setTimeout(() => ring.remove(), 500)
    }, true)
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install)
  else install()
})()
`

async function newContext(browser, { theme = 'dark', video = null, scale = 2, viewport } = {}) {
  const context = await browser.newContext({
    viewport: viewport || { width: 1440, height: 900 },
    deviceScaleFactor: scale,
    timezoneId: TIMEZONE,
    locale: 'en-US',
    colorScheme: theme,
    reducedMotion: 'no-preference',
    ...(video ? { recordVideo: { dir: video.dir, size: video.size } } : {}),
  })
  // The theme lives in localStorage; set it before the app reads it.
  await context.addInitScript((value) => {
    try {
      window.localStorage.setItem('semester-os-theme', value)
    } catch {
      /* the default applies */
    }
  }, theme)
  const page = await context.newPage()
  // Start the page clock at the demo's fixed instant.
  await page.clock.install({ time: NOW })
  await page.clock.resume()
  return { context, page }
}

async function settle(page, ms = 900) {
  await page.waitForLoadState('networkidle').catch(() => {})
  await sleep(ms)
}

/* -------------------------------------------------------------------------- */
/* Screenshots                                                                 */
/* -------------------------------------------------------------------------- */

async function redactFeedLink(page) {
  // The feed URL carries a secret; don't model screenshotting one.
  await page.evaluate(() => {
    for (const input of document.querySelectorAll('input')) {
      if (/\/calendar\/[^/]+\.ics/.test(input.value)) {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
        setter.call(input, input.value.replace(/\/calendar\/[^/]+\.ics/, '/calendar/<secret>.ics'))
      }
    }
  })
}

async function shots(browser) {
  const courseId = settings.courseId
  const plan = [
    { file: 'today.png', route: '/' },
    { file: 'week.png', route: '/week' },
    { file: 'course.png', route: `/courses/${String(courseId)}` },
    { file: 'notes.png', route: '/notes' },
    { file: 'connect.png', route: '/connect', before: redactFeedLink },
    { file: 'today-light.png', route: '/', theme: 'light' },
  ]
  for (const shot of plan) {
    const { context, page } = await newContext(browser, { theme: shot.theme || 'dark' })
    await page.goto(baseUrl + shot.route)
    await settle(page, 1400)
    if (shot.before) await shot.before(page)
    await page.screenshot({ path: path.join(outDir, shot.file) })
    console.log('shot', shot.file)
    await context.close()
  }

  // The review sheet for the syllabus the seed left waiting.
  const { context, page } = await newContext(browser)
  await page.goto(baseUrl + '/setup')
  await settle(page)
  await page.getByRole('button', { name: 'Review' }).first().click()
  await page.getByRole('dialog').waitFor()
  await settle(page, 900)
  const dialog = page.getByRole('dialog')
  // Open on the schedule and the first flagged work, the part worth reading.
  await dialog.locator('#review-work').scrollIntoViewIfNeeded()
  await dialog.locator('#review-meetings').evaluate((node) => node.scrollIntoView({ block: 'start' }))
  await sleep(400)
  await page.screenshot({ path: path.join(outDir, 'setup-review.png') })
  console.log('shot setup-review.png')
  await context.close()
}

/* -------------------------------------------------------------------------- */
/* Recordings                                                                  */
/* -------------------------------------------------------------------------- */

const VIDEO_VIEWPORT = { width: 1280, height: 800 }

async function recorder(browser, name) {
  const dir = path.join(outDir, `.video-${name}`)
  fs.mkdirSync(dir, { recursive: true })
  const { context, page } = await newContext(browser, {
    scale: 1,
    viewport: VIDEO_VIEWPORT,
    video: { dir, size: VIDEO_VIEWPORT },
  })
  await page.addInitScript(CURSOR_SCRIPT)
  lastPage = page
  return { context, page, dir, started: Date.now() }
}

/** Glide the pointer to the middle of a locator, the way a hand does. */
async function moveTo(page, locator, { steps = 22, offsetX = 0.5, offsetY = 0.5 } = {}) {
  await locator.scrollIntoViewIfNeeded()
  const box = await locator.boundingBox()
  if (!box) throw new Error('Nothing to point at')
  const x = box.x + box.width * offsetX
  const y = box.y + box.height * offsetY
  await page.mouse.move(x, y, { steps })
  return { x, y }
}

async function clickOn(page, locator, options = {}) {
  await moveTo(page, locator, options)
  await sleep(160)
  await page.mouse.down()
  await sleep(70)
  await page.mouse.up()
  await sleep(options.after ?? 250)
}

async function typeHuman(page, text, delay = 30) {
  for (const char of text) {
    await page.keyboard.type(char)
    await sleep(delay + (char === ' ' ? 25 : Math.random() * 20))
  }
}

async function hideToasts(page) {
  await page.addStyleTag({ content: '[data-sonner-toaster] { display: none !important; }' })
}

async function finishVideo(context, page, dir, name, trim) {
  const video = page.video()
  await context.close()
  const source = await video.path()
  const target = path.join(outDir, `${name}.webm`)
  fs.renameSync(source, target)
  fs.rmSync(dir, { recursive: true, force: true })
  fs.writeFileSync(path.join(outDir, `${name}.json`), JSON.stringify(trim))
  console.log('video', target, trim)
}

async function notes(browser) {
  const { context, page, dir, started } = await recorder(browser, 'notes')
  await page.goto(baseUrl + '/notes')
  await settle(page, 300)
  await page.mouse.move(640, 560)
  const skip = (Date.now() - started) / 1000

  const box = page.getByRole('textbox', { name: 'New note' })
  await clickOn(page, box, { offsetX: 0.3, after: 150 })
  await typeHuman(page, settings.noteText)
  await sleep(350)
  await clickOn(page, page.getByRole('button', { name: 'Apply', exact: true }), { steps: 16 })

  // The fake CLI answers after its delay; the proposal replaces the running card.
  const proposal = page.getByText('Move Midterm 2 (MATH 2700)')
  await proposal.waitFor({ timeout: 20000 })
  const confirm = proposal
    .locator('xpath=ancestor::*[.//button[normalize-space()="Confirm & apply"]][1]')
    .getByRole('button', { name: 'Confirm & apply' })
  await sleep(1300)
  await clickOn(page, confirm, { steps: 18, after: 1000 })
  // Toasts would cover the exam block on the week view.
  await hideToasts(page)

  await clickOn(page, page.getByRole('link', { name: /^Week/ }), { steps: 20, after: 350 })
  await settle(page, 150)
  await clickOn(page, page.getByRole('button', { name: 'Next week' }), { steps: 22, after: 250 })
  await settle(page, 100)
  const block = page.getByRole('link', { name: /Midterm 2/ })
  await block.waitFor()
  await page.mouse.wheel(0, 160)
  await sleep(350)
  await moveTo(page, block, { steps: 24 })
  await sleep(2000)
  await finishVideo(context, page, dir, 'notes', { start: skip })
}

async function onboarding(browser) {
  const { context, page, dir, started } = await recorder(browser, 'onboarding')
  await page.goto(baseUrl + '/setup')
  await settle(page, 300)
  await page.mouse.move(1180, 700)
  const skip = (Date.now() - started) / 1000

  // Simulated drag: a chip follows the pointer, then a real drop event carries the file.
  const zone = page.getByText('Drop syllabi here').locator('..')
  const fileName = path.basename(settings.syllabusPath)
  const bytes = fs.readFileSync(settings.syllabusPath).toString('base64')
  await page.evaluate((name) => {
    const chip = document.getElementById('capture-file')
    chip.querySelector('span').textContent = name
    chip.style.display = 'flex'
  }, fileName)
  await page.mouse.move(1100, 650, { steps: 4 })
  const target = await moveTo(page, zone, { steps: 32 })
  const handle = await page.evaluateHandle(
    ({ name, data }) => {
      const binary = Uint8Array.from(atob(data), (char) => char.charCodeAt(0))
      const transfer = new DataTransfer()
      transfer.items.add(new File([binary], name, { type: 'text/html' }))
      return transfer
    },
    { name: fileName, data: bytes },
  )
  const zoneElement = await zone.elementHandle()
  await zoneElement.dispatchEvent('dragenter', { dataTransfer: handle })
  await zoneElement.dispatchEvent('dragover', { dataTransfer: handle })
  await sleep(550)
  await zoneElement.dispatchEvent('drop', { dataTransfer: handle, clientX: target.x, clientY: target.y })
  await page.evaluate(() => {
    document.getElementById('capture-file').style.display = 'none'
  })

  // It is read as soon as it lands; the fake CLI answers after its delay.
  const review = page.getByRole('button', { name: 'Review' }).first()
  await review.waitFor({ timeout: 20000 })
  await sleep(450)
  await clickOn(page, review, { steps: 22, after: 500 })
  await hideToasts(page)
  const dialog = page.getByRole('dialog')
  await dialog.waitFor()

  // The recitation the syllabus could not time: flagged, and blocking Confirm.
  const start = dialog.getByLabel('Meeting 2 start time')
  await start.evaluate((node) => node.scrollIntoView({ block: 'center', behavior: 'smooth' }))
  await sleep(900)
  await clickOn(page, start, { steps: 20, offsetX: 0.25, after: 150 })
  await start.fill('14:30')
  await sleep(450)
  const length = dialog.getByLabel('Meeting 2 length in minutes')
  await clickOn(page, length, { steps: 12, after: 150 })
  await typeHuman(page, '50', 90)
  await sleep(300)
  const room = dialog.getByLabel('Meeting 2 room')
  await clickOn(page, room, { steps: 14, offsetX: 0.2, after: 150 })
  await typeHuman(page, 'Hollis Hall 110', 26)
  await sleep(700)

  const add = dialog.getByRole('button', { name: 'Confirm & add course' })
  await add.waitFor()
  await page.waitForFunction(
    () => {
      const button = [...document.querySelectorAll('button')].find((node) => node.textContent.includes('Confirm & add course'))
      return button && !button.disabled
    },
    null,
    { timeout: 10000 },
  )
  await clickOn(page, add, { steps: 20, after: 900 })

  await clickOn(page, page.getByRole('link', { name: /^Courses/ }), { steps: 24, after: 300 })
  await settle(page, 200)
  const card = page.getByText('STAT 2400', { exact: true }).first()
  await card.waitFor()
  await moveTo(page, card, { steps: 22 })
  await sleep(1600)
  await finishVideo(context, page, dir, 'onboarding', { start: skip })
}

;(async () => {
  const browser = await chromium.launch()
  try {
    if (scene === 'shots') await shots(browser)
    else if (scene === 'notes') await notes(browser)
    else if (scene === 'onboarding') await onboarding(browser)
    else throw new Error(`Unknown scene ${scene}`)
  } catch (error) {
    if (lastPage) await lastPage.screenshot({ path: path.join(outDir, `failed-${scene}.png`) }).catch(() => {})
    throw error
  } finally {
    await browser.close()
  }
})().catch((error) => {
  console.error(error)
  process.exit(1)
})

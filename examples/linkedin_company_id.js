// Phantombuster configuration {
"phantom image: web-node:v1"
"phantombuster flags: save-folder"
// }
const Buster = require("phantombuster")
const buster = new Buster()
const puppeteer = require("puppeteer")

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function extractCompanyId(page) {
  return page.evaluate(() => {
    const html = document.documentElement.innerHTML
    const pats = [/urn:li:fsd_company:(\d+)/, /urn:li:organization:(\d+)/, /urn:li:company:(\d+)/, /"companyId":(\d+)/, /f_C=(\d+)/]
    for (const p of pats) { const m = html.match(p); if (m) return m[1] }
    return null
  })
}

;(async () => {
  let arg = {}
  try { arg = typeof buster.argument === "string" ? JSON.parse(buster.argument) : (buster.argument || {}) } catch (e) {}
  const li_at = arg.sessionCookie
  const ua = arg.userAgent || "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
  const keywords = arg.keywords || ""
  let vanity = arg.vanity || ""

  const browser = await puppeteer.launch({ args: ["--no-sandbox", "--disable-setuid-sandbox"] })
  const page = await browser.newPage()
  await page.setUserAgent(ua)
  await page.setCookie({ name: "li_at", value: li_at, domain: ".www.linkedin.com", path: "/", httpOnly: true, secure: true })

  const out = []
  try {
    // Step A: search companies by name -> resolve the top company's vanity + name
    let matchedName = ""
    if (keywords && !vanity) {
      const url = "https://www.linkedin.com/search/results/companies/?keywords=" + encodeURIComponent(keywords)
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 })
      await sleep(6000)
      const hit = await page.evaluate(() => {
        const a = document.querySelector('a[href*="/company/"]')
        if (!a) return null
        const m = a.getAttribute("href").match(/\/company\/([^\/?#]+)/)
        return m ? { vanity: m[1], text: (a.innerText || "").trim() } : null
      })
      if (hit) { vanity = hit.vanity; matchedName = hit.text }
      console.log("search -> vanity:", vanity, "| name:", matchedName)
    }

    // Step B: open the company page (authenticated) and read the numeric id from the DOM
    if (vanity) {
      await page.goto("https://www.linkedin.com/company/" + vanity + "/", { waitUntil: "domcontentloaded", timeout: 60000 })
      await sleep(5000)
      const id = await extractCompanyId(page)
      const name = await page.evaluate(() => {
        const h = document.querySelector("h1")
        return h ? h.innerText.trim() : (document.title || "").replace(/\s*\|\s*LinkedIn.*/, "")
      })
      console.log("company page -> id:", id, "| name:", name)
      if (id) out.push({ keywords: keywords, vanity: vanity, companyId: id, name: name })
    }
  } catch (e) {
    console.log("ERROR:", e.message)
  }

  await buster.setResultObject(out)
  await browser.close()
  process.exit(0)
})()

// Phantombuster configuration {
"phantom image: web-node:v1"
"phantombuster flags: save-folder"
// }
// Resolves a company name -> LinkedIn company, extracting as much data as possible.
const Buster = require("phantombuster")
const buster = new Buster()
const puppeteer = require("puppeteer")
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

;(async () => {
  let arg = {}
  try { arg = typeof buster.argument === "string" ? JSON.parse(buster.argument) : (buster.argument || {}) } catch (e) {}
  const li_at = arg.sessionCookie
  const ua = arg.userAgent || "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
  const keywords = arg.keywords || ""
  let vanity = arg.vanity || ""
  // LinkedIn HQ-country facet. Default: United Kingdom (geo urn 101165590).
  const hqGeo = arg.hqGeo === undefined ? "101165590" : arg.hqGeo

  const browser = await puppeteer.launch({ args: ["--no-sandbox", "--disable-setuid-sandbox"] })
  const page = await browser.newPage()
  await page.setUserAgent(ua)
  await page.setCookie({ name: "li_at", value: li_at, domain: ".www.linkedin.com", path: "/", httpOnly: true, secure: true })

  const out = []
  try {
    // 1) search companies by name -> resolve the parent company's vanity
    let matchedName = ""
    if (keywords && !vanity) {
      let url = "https://www.linkedin.com/search/results/companies/?keywords=" + encodeURIComponent(keywords) + "&origin=FACETED_SEARCH"
      if (hqGeo) url += "&companyHqGeo=" + encodeURIComponent('["' + hqGeo + '"]')
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 })
      await sleep(6000)
      const hit = await page.evaluate(() => {
        const a = document.querySelector('a[href*="/company/"]')
        if (!a) return null
        const m = a.getAttribute("href").match(/\/company\/([^\/?#]+)/)
        return m ? { vanity: m[1], text: (a.innerText || "").trim() } : null
      })
      if (hit) { vanity = hit.vanity; matchedName = hit.text }
      console.log("search -> vanity:", vanity)
    }

    // 2) open the company About page and scrape everything we can
    if (vanity) {
      await page.goto("https://www.linkedin.com/company/" + vanity + "/about/",
        { waitUntil: "domcontentloaded", timeout: 60000 })
      await sleep(5000)
      const data = await page.evaluate(() => {
        const txt = (el) => (el ? el.innerText.replace(/\s+/g, " ").trim() : null)
        const html = document.documentElement.innerHTML
        let id = null
        const pats = [/urn:li:fsd_company:(\d+)/, /urn:li:organization:(\d+)/, /urn:li:company:(\d+)/, /"companyId":(\d+)/, /f_C=(\d+)/]
        for (const p of pats) { const m = html.match(p); if (m) { id = m[1]; break } }
        const overview = {}
        document.querySelectorAll("dl > dt").forEach((dt) => {
          const dd = dt.nextElementSibling
          const k = txt(dt), v = txt(dd)
          if (k && v && !(k in overview)) overview[k] = v
        })
        const description = txt(document.querySelector('[data-test-id="about-us__description"]')) ||
          txt(document.querySelector("section p"))
        const logo = (document.querySelector('img[alt*="logo" i]') || {}).src ||
          (document.querySelector("main img") || {}).src || null
        let followers = null
        const fm = html.match(/([\d,]+)\s+followers/i); if (fm) followers = fm[1]
        return { id: id, name: txt(document.querySelector("h1")), overview: overview, description: description, logoUrl: logo, followers: followers }
      })
      const o = data.overview || {}
      out.push({
        keywords: keywords,
        vanity: vanity,
        linkedinUrl: "https://www.linkedin.com/company/" + vanity + "/",
        companyId: data.id,
        name: data.name || matchedName,
        description: data.description,
        followers: data.followers,
        logoUrl: data.logoUrl,
        website: o["Website"] || null,
        industry: o["Industry"] || null,
        companySize: o["Company size"] || null,
        headquarters: o["Headquarters"] || null,
        founded: o["Founded"] || null,
        type: o["Type"] || null,
        specialties: o["Specialties"] || null,
        overview: o
      })
      console.log("company:", data.name, "| id:", data.id)
    }
  } catch (e) {
    console.log("ERROR:", e.message)
  }

  await buster.setResultObject(out)
  await browser.close()
  process.exit(0)
})()

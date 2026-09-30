// Playwright smoke test: the app renders, a voice can be created and every tab shows its cards.
const { chromium } = require("playwright");
const BASE = process.env.BASE_URL || "http://localhost:8001";

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ locale: "en-US" });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(BASE, { waitUntil: "load" });
  await page.waitForSelector(".MuiCard-root", { timeout: 20000 });
  // first run: the "new voice" dialog opens by itself
  if (await page.getByRole("dialog").isVisible().catch(() => false)) {
    await page.getByLabel("Voice name").fill("Smoke test");
    await page.getByLabel("Whose voice it is").fill("Test Person");
    await page.getByRole("button", { name: "Create" }).click();
    await page.waitForTimeout(1500);
  }
  const expected = { Voice: ["1. Voice", "Consent of the voice owner"], Recording: ["Recording studio", "Dataset overview"], Training: ["Voice training", "Run history"], "Test & export": ["Test & export"] };
  for (const [tab, titles] of Object.entries(expected)) {
    await page.getByRole("tab", { name: tab }).click();
    await page.waitForTimeout(1500);
    const text = await page.locator("body").innerText();
    for (const title of titles) {
      if (!text.includes(title)) throw new Error(`Tab ${tab}: missing "${title}"`);
    }
  }
  if (errors.length) throw new Error(`Page errors: ${errors.join("; ")}`);
  console.log("OK: all tabs rendered");
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});

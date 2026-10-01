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
  const expected = { Voice: ["1. Voice", "Consent of the voice owner"], Recording: ["Recording studio"], Data: ["Dataset overview", "Import a long recording"], Training: ["Voice training"], "Test & deploy": ["4. Test"] };
  for (const [tab, titles] of Object.entries(expected)) {
    await page.getByRole("tab", { name: tab }).click();
    await page.waitForTimeout(1500);
    const text = await page.locator("body").innerText();
    for (const title of titles) {
      if (!text.includes(title)) throw new Error(`Tab ${tab}: missing "${title}"`);
    }
  }
  // the studio's dialogs open and close
  await page.getByRole("tab", { name: "Recording" }).click();
  await page.waitForTimeout(1000);
  for (const [item, expected] of [
    ["Paragraphs", "Connected texts to read"],
    ["Microphone test", "Microphone and room test"],
    ["Record with a phone", "Recording with a phone"],
    ["Custom sentences", "Add your own sentences"],
  ]) {
    await page.getByRole("button", { name: "More", exact: true }).click();
    await page.getByRole("menuitem", { name: item }).click();
    await page.waitForTimeout(800);
    const dialog = page.getByRole("dialog");
    if (!(await dialog.innerText()).includes(expected)) throw new Error(`Dialog ${item}: missing "${expected}"`);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);
  }
  // the glossary and the step bar
  await page.getByRole("button", { name: "Glossary" }).click();
  await page.waitForTimeout(500);
  if (!(await page.getByRole("dialog").innerText()).includes("Epoch")) throw new Error("Glossary did not open");
  await page.keyboard.press("Escape");
  if ((await page.locator(".MuiStepper-root .MuiStep-root").count()) !== 4) throw new Error("Step bar missing");
  if (errors.length) throw new Error(`Page errors: ${errors.join("; ")}`);
  console.log("OK: all tabs rendered, dialogs open");
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});

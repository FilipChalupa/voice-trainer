// Re-creates the README screenshots against an instance that has a voice with recordings and a finished run.
// scripts/e2e.sh --screenshots prepares such an instance (a throw-away one, not the one you record in) and runs this.
const { chromium } = require("playwright");
const BASE = process.env.BASE_URL || "http://localhost:8001";
const OUT = process.env.OUT_DIR || "/out";
(async () => {
  const browser = await chromium.launch({ args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"] });
  const plan = { Voice: ["voice"], Recording: ["studio"], Data: ["dataset", "transcribe"], Training: ["training"], "Test & deploy": ["test", "deploy"] };
  for (const scheme of ["light", "dark"]) {
    const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 }, colorScheme: scheme, locale: "en-US", deviceScaleFactor: 1.5, permissions: ["microphone"] });
    const page = await ctx.newPage();
    await page.goto(`${BASE}/#record`, { waitUntil: "load" });
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${OUT}/hero-${scheme}.png` });
    if (scheme === "dark") {
      await page.getByRole("tab", { name: "Training" }).click();
      await page.waitForTimeout(2000);
      await page.addStyleTag({ content: ".MuiAppBar-root{display:none}" });
      await page.locator(".MuiCard-root").nth(0).screenshot({ path: `${OUT}/training-dark.png` });
      await ctx.close();
      continue;
    }
    for (const [tab, names] of Object.entries(plan)) {
      await page.getByRole("tab", { name: tab }).click();
      await page.waitForTimeout(2000);
      if (tab === "Test & deploy") {
        await page.getByRole("button", { name: /^Speak$/i }).click();
        await page.waitForTimeout(6000);
      }
      const hide = await page.addStyleTag({ content: ".MuiAppBar-root{display:none}" });
      const cards = page.locator(".MuiCard-root");
      for (let i = 0; i < names.length; i++) await cards.nth(i).screenshot({ path: `${OUT}/${names[i]}.png` });
      await hide.evaluate((el) => el.remove());
    }
    await ctx.close();
  }
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});

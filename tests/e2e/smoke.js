// Playwright smoke test: the app renders, a voice can be created and every tab shows its cards.
const { chromium } = require("playwright");
const BASE = process.env.BASE_URL || "http://localhost:8001";

(async () => {
  const browser = await chromium.launch({ args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"] });
  const page = await browser.newPage({ locale: "en-US", permissions: ["microphone"] });
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
  // reading in one go: the teleprompter opens with the current sentence and closes with Escape
  const sentence = (await page.locator("textarea").first().inputValue()).trim();
  await page.getByRole("button", { name: "Read in one go" }).click();
  await page.waitForTimeout(3500);
  const flowText = await page.getByRole("dialog").innerText();
  if (sentence && !flowText.includes(sentence.slice(0, 20))) throw new Error("Flow dialog does not show the current sentence");
  await page.keyboard.press("Escape");
  await page.waitForTimeout(1500);
  // a take whose upload fails waits in the browser and can be uploaded once the server answers again
  await page.route("**/api/recordings", (route) => (route.request().method() === "POST" ? route.abort() : route.continue()));
  await page.keyboard.press("Space");
  await page.getByText("Recording…").waitFor({ timeout: 10000 });
  await page.waitForTimeout(2500);
  if (await page.getByText("Recording…").isVisible().catch(() => false)) await page.keyboard.press("Space");
  await page.getByText("waiting in this browser: 1").waitFor({ timeout: 15000 });
  await page.reload({ waitUntil: "load" }); // the take survives a reload
  await page.getByRole("tab", { name: "Recording" }).click();
  await page.getByText("waiting in this browser: 1").waitFor({ timeout: 15000 });
  await page.unroute("**/api/recordings");
  await page.getByRole("button", { name: "Upload now" }).click();
  await page.getByText(/Uploaded: [01]\. Left out/).waitFor({ timeout: 15000 });
  await page.getByText("waiting in this browser").waitFor({ state: "hidden", timeout: 15000 });
  // a click on a take's waveform plays it from that point
  const wav = (() => {
    const sr = 22050, seconds = 4, n = sr * seconds, buf = Buffer.alloc(44 + n * 2);
    buf.write("RIFF", 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write("WAVEfmt ", 8); buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22);
    buf.writeUInt32LE(sr, 24); buf.writeUInt32LE(sr * 2, 28); buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34); buf.write("data", 36); buf.writeUInt32LE(n * 2, 40);
    for (let i = 0; i < n; i++) buf.writeInt16LE(i < sr / 4 || i > n - sr / 4 ? 0 : Math.round(9000 * Math.sin((i / sr) * 2 * Math.PI * 180) * (1 + 0.6 * Math.sin((i / sr) * 7))), 44 + i * 2);
    return buf;
  })();
  const uploaded = await page.request.post(`${BASE}/api/recordings`, { multipart: { text: "Seek test sentence for the waveform.", file: { name: "a.wav", mimeType: "audio/wav", buffer: wav } } });
  if (!uploaded.ok()) throw new Error(`upload for the seek test failed: ${uploaded.status()}`);
  await page.reload({ waitUntil: "load" });
  await page.getByRole("tab", { name: "Recording" }).click();
  const wave = page.getByRole("slider", { name: "Seek test sentence for the waveform." });
  await wave.waitFor({ timeout: 15000 });
  const box = await wave.boundingBox();
  await page.mouse.click(box.x + box.width * 0.8, box.y + box.height / 2);
  await page.waitForTimeout(700);
  const at = Number(await wave.getAttribute("aria-valuenow"));
  if (!(at >= 70 && at <= 100)) throw new Error(`Waveform click did not seek: playing at ${at} %`);
  // the glossary and the step bar
  await page.getByRole("button", { name: "Glossary" }).click();
  await page.waitForTimeout(500);
  if (!(await page.getByRole("dialog").innerText()).includes("Epoch")) throw new Error("Glossary did not open");
  await page.keyboard.press("Escape");
  if ((await page.locator(".MuiStepper-root .MuiStep-root").count()) !== 4) throw new Error("Step bar missing");
  if (errors.length) throw new Error(`Page errors: ${errors.join("; ")}`);
  console.log("OK: all tabs rendered, dialogs open, a failed upload is kept and recovered, the waveform seeks");
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});

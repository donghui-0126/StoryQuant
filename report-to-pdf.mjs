import { chromium } from 'playwright';
const URL = 'http://127.0.0.1:8765/report.html';
(async () => {
  const browser = await chromium.launch({
    executablePath: '/home/amuredo/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome',
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto(URL, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  await page.pdf({
    path: './report.pdf',
    format: 'A4',
    printBackground: true,
    margin: { top: '18mm', right: '16mm', bottom: '16mm', left: '16mm' },
  });
  await browser.close();
  console.log('done');
})();

import { chromium } from 'playwright';
const BASE = 'http://127.0.0.1:8765';
(async () => {
  const browser = await chromium.launch({
    executablePath: '/home/amuredo/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome',
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await ctx.newPage();

  // ux-mocks.pdf (A4 landscape, 1 page)
  console.log('▶ ux-mocks.pdf');
  await page.goto(`${BASE}/ux-mocks.html`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  await page.pdf({
    path: './ux-mocks.pdf',
    width: '420mm',  // 큰 가로 페이지로 4개 mock + 비교표 fit
    height: '297mm',
    printBackground: true,
    margin: { top: '10mm', right: '10mm', bottom: '10mm', left: '10mm' },
  });

  await browser.close();
  console.log('▶ done');
})();

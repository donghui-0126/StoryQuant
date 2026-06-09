// presentation.html → PDF 4 버전:
//   presentation-main.pdf      : 라이트, 메인 10장
//   presentation-full.pdf      : 라이트, 전체 18장
//   presentation-main-dark.pdf : 다크, 메인 10장
//   presentation-full-dark.pdf : 다크, 전체 18장
import { chromium } from 'playwright';

const URL = 'http://127.0.0.1:8765/presentation.html';

const pdfOpts = (path) => ({
  path,
  width: '297mm',
  height: '210mm',
  printBackground: true,
  preferCSSPageSize: true,
  margin: { top: 0, right: 0, bottom: 0, left: 0 },
});

(async () => {
  const browser = await chromium.launch({
    executablePath: '/home/amuredo/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome',
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(URL, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2500);
  await page.emulateMedia({ media: 'print' });
  await page.waitForTimeout(400);

  const variants = [
    { name: 'presentation-full-dark.pdf', light: false, mainOnly: false },
    { name: 'presentation-main-dark.pdf', light: false, mainOnly: true },
    { name: 'presentation-full.pdf',      light: true,  mainOnly: false },
    { name: 'presentation-main.pdf',      light: true,  mainOnly: true },
  ];

  for (const v of variants) {
    console.log(`▶ ${v.name}  (${v.light ? 'light' : 'dark'}, ${v.mainOnly ? 'main 10장' : 'full 18장'})`);
    await page.evaluate(({ light, mainOnly }) => {
      document.body.classList.toggle('print-light', light);
      document.body.classList.toggle('print-main-only', mainOnly);
    }, v);
    await page.waitForTimeout(400);
    await page.pdf(pdfOpts(`./${v.name}`));
  }

  await browser.close();
  console.log('▶ done');
})();

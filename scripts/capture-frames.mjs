// 각 메인 슬라이드(1~10)를 1920×1080 viewport로 캡처
import { chromium } from 'playwright';
import { existsSync, mkdirSync } from 'fs';

const OUT = './video-frames';
if (!existsSync(OUT)) mkdirSync(OUT, { recursive: true });

const URL_BASE = 'http://127.0.0.1:8765/presentation.html';

(async () => {
  const browser = await chromium.launch({
    executablePath: '/home/amuredo/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome',
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
  });
  const page = await ctx.newPage();
  await page.goto(URL_BASE, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);

  // 메인 1~10: 숫자 키
  for (let i = 1; i <= 10; i++) {
    if (i !== 1) await page.keyboard.press(i === 10 ? '0' : String(i));
    await page.waitForTimeout(600);
    await page.screenshot({
      path: `${OUT}/slide-${i}.png`,
      clip: { x: 0, y: 0, width: 1920, height: 1080 },
    });
    console.log(`✓ slide-${i}.png`);
  }
  // 백업 A1~A8: B키로 진입 (slide 10 → A1) 후 → 키로 이동
  await page.keyboard.press('b');
  await page.waitForTimeout(700);
  for (let j = 1; j <= 8; j++) {
    if (j > 1) {
      await page.keyboard.press('ArrowRight');
      await page.waitForTimeout(600);
    }
    await page.screenshot({
      path: `${OUT}/slide-A${j}.png`,
      clip: { x: 0, y: 0, width: 1920, height: 1080 },
    });
    console.log(`✓ slide-A${j}.png`);
  }

  await browser.close();
  console.log('▶ done');
})();

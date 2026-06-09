// StoryQuant dashboard 섹션별 스크린샷 캡처 — v3 (화질 극대화)
// 1) DPR 3 (HiDPI 4K 풀 대응)
// 2) dashboard 글씨 자체를 키우는 CSS inject
// 3) 좁은 sub-element 선택해 다운스케일 비율 최소화
import { chromium } from 'playwright';

const URL = 'http://127.0.0.1:8765/story_quant.html?market=kr';
const OUT = './screenshots';

// 각 섹션의 메인 캡처 대상: sub-element 우선 (clip 좁으면 글씨 크게 보임)
const SECTIONS = [
  // 헤드라인 모니터 — sweep + feed 두 핵심부 따로
  { id: 'knm-sweep',       file: 'a5-headline.png',   wait: 4000, maxH: 1200, title: '헤드라인 (sweep Top5)' },
  { id: 'knm-feed',        file: 'a5-feed.png',       wait: 4000, maxH: 1200, title: '헤드라인 stream' },
  { id: 'theme-rotation',  file: 'a6-theme.png',      wait: 2500, maxH: 1600, title: '테마 회전 14 카드' },
  { id: 'walkforward',     file: 'a7-backtest.png',   wait: 3000, maxH: 1600, title: '백테스트' },
];

(async () => {
  const browser = await chromium.launch({
    executablePath: '/home/amuredo/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome',
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext({
    viewport: { width: 1400, height: 1700 },
    deviceScaleFactor: 3,    // 4K/HiDPI 풀 대응 — 픽셀 밀도 3배
  });
  const page = await ctx.newPage();
  console.log('▶ goto', URL);
  await page.goto(URL, { waitUntil: 'domcontentloaded' });
  console.log('▶ waiting initial load (15s)...');
  await page.waitForTimeout(15000);

  // 글씨 키우기 + 캡처용 보정 CSS (dashboard layout 가능한 한 안 깨는 선)
  await page.addStyleTag({
    content: `
      /* 캡처용 살짝 키우기 — body font-size 베이스 (대시보드 자체가 rem 기반이면 영향) */
      html { font-size: 17px !important; }
      /* 표/카드 내부 텍스트 한 단계 강화 */
      table, td, th { font-size: 14px !important; }
      .num, .knm-num, .wf-num { font-weight: 700 !important; }
      /* 헤더 한 단계 더 크게 */
      h1 { font-size: 28px !important; }
      h2 { font-size: 22px !important; }
      h3 { font-size: 18px !important; }
    `
  });
  await page.waitForTimeout(800);

  for (const s of SECTIONS) {
    console.log(`▶ ${s.title} (#${s.id})`);
    try {
      const el = await page.$(`#${s.id}`);
      if (!el) { console.log(`  ! #${s.id} not found, skipping`); continue; }
      await page.evaluate((id) => {
        const el = document.getElementById(id);
        if (el) { el.scrollIntoView({ behavior: 'instant', block: 'start' }); window.scrollBy(0, -10); }
      }, s.id);
      await page.waitForTimeout(s.wait);
      const box = await el.boundingBox();
      if (!box) { console.log(`  ! no bbox`); continue; }
      const clip = {
        x: Math.max(0, box.x - 4),
        y: Math.max(0, box.y - 4),
        width: Math.min(box.width + 8, 1400),
        height: Math.min(box.height + 8, s.maxH),
      };
      await page.screenshot({ path: `${OUT}/${s.file}`, clip, animations: 'disabled' });
      console.log(`  ✓ ${s.file}  ${Math.round(clip.width)}×${Math.round(clip.height)} (CSS)`);
    } catch (e) {
      console.log(`  ✗ ${s.file}: ${e.message.split('\n')[0]}`);
    }
  }

  // 종목 상세
  console.log('▶ 종목 상세');
  try {
    await page.evaluate(() => {
      document.getElementById('kr-news-monitor')?.scrollIntoView({ block: 'start' });
    });
    await page.waitForTimeout(1500);
    const tags = await page.$$('#kr-news-monitor [data-code]');
    if (tags.length > 0) {
      await tags[0].click({ timeout: 3000 });
      console.log(`  ✓ clicked first [data-code]`);
      await page.waitForTimeout(3500);
      const detail = await page.$('#knm-detail');
      if (detail) {
        await detail.scrollIntoViewIfNeeded();
        await page.waitForTimeout(500);
        const box = await detail.boundingBox();
        if (box && box.height > 100) {
          const clip = {
            x: Math.max(0, box.x - 4),
            y: Math.max(0, box.y - 4),
            width: Math.min(box.width + 8, 1400),
            height: Math.min(box.height + 8, 1500),
          };
          await page.screenshot({ path: `${OUT}/a8-stock-detail.png`, clip, animations: 'disabled' });
          console.log(`  ✓ a8-stock-detail.png  ${Math.round(clip.width)}×${Math.round(clip.height)} (CSS)`);
        }
      }
    }
  } catch (e) {
    console.log(`  ✗ a8: ${e.message.split('\n')[0]}`);
  }

  await browser.close();
  console.log('▶ done');
})();

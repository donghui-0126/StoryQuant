import { chromium } from 'playwright';
(async () => {
  const b = await chromium.launch({
    executablePath: '/home/amuredo/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome',
    args: ['--no-sandbox'],
  });
  const p = await b.newPage();
  await p.goto('http://127.0.0.1:8765/consulting-questions.html', { waitUntil: 'networkidle' });
  await p.waitForTimeout(800);
  await p.pdf({
    path: './consulting-questions.pdf',
    format: 'A4',
    printBackground: true,
    margin: { top: '16mm', right: '16mm', bottom: '16mm', left: '16mm' },
  });
  await b.close();
  console.log('done');
})();

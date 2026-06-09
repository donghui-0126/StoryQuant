"""OpenAI TTS로 narration.json → audio/slide-*.mp3 생성.

사용법:
  1) .env 파일에 OPENAI_API_KEY=sk-... 작성
  2) pip install openai
  3) python tts-generate.py --sample 1     # 슬라이드 1만 (샘플)
     python tts-generate.py --sample A1    # 백업 A1만
     python tts-generate.py                # 전체

옵션 (아래 CONFIG):
  MODEL  — 'tts-1' (빠름, $15/1M char) / 'tts-1-hd' (고음질, $30/1M char)
  VOICE  — 'nova' (여성, 추천) / 'alloy' / 'echo' / 'fable' / 'onyx' / 'shimmer'
  SPEED  — 0.25 ~ 4.0 (1.0=기본)

전체 비용: tts-1 약 $0.07 (4,964자). tts-1-hd 약 $0.15.
샘플 1개: 약 $0.005 (300자 기준).
"""
import argparse
import json
import os
import sys
from pathlib import Path

MODEL = 'tts-1'
VOICE = 'nova'
SPEED = 1.15    # 약간 빠르게 (1.0=기본, 1.2까지 자연스러움 유지)
ROOT = Path(__file__).parent
OUT_DIR = ROOT / 'audio'

def load_env():
    """간단한 .env 로더 (python-dotenv 없이도 동작)."""
    env_path = ROOT / '.env'
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sample', help="특정 슬라이드 label만 생성 (예: 1, 7, A1)")
    parser.add_argument('--voice', default=VOICE, help=f"기본 {VOICE}")
    parser.add_argument('--model', default=MODEL, help=f"기본 {MODEL}")
    parser.add_argument('--force', action='store_true', help="이미 존재해도 덮어쓰기")
    args = parser.parse_args()

    load_env()
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        print('❌ OPENAI_API_KEY 없음.')
        print('   해결: .env 파일에 다음 한 줄 추가 후 다시 실행')
        print('   OPENAI_API_KEY=sk-...')
        sys.exit(1)

    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    OUT_DIR.mkdir(exist_ok=True)
    with (ROOT / 'narration.json').open(encoding='utf-8') as f:
        slides = json.load(f)

    if args.sample:
        slides = [s for s in slides if s['label'] == args.sample]
        if not slides:
            print(f'❌ label "{args.sample}" 슬라이드 없음 (가능: 1~10, A1~A8)')
            sys.exit(1)

    total_chars = sum(s['chars'] for s in slides)
    rate = 15 if args.model == 'tts-1' else 30
    est_cost = total_chars * rate / 1_000_000
    print(f'▶ {len(slides)} 슬라이드 · {total_chars}자 · {args.model} · {args.voice}')
    print(f'▶ 예상 비용: ${est_cost:.4f}\n')

    for s in slides:
        out_path = OUT_DIR / f'slide-{s["label"]}.mp3'
        if out_path.exists() and not args.force:
            print(f'  ⏭  {out_path.name} 이미 존재 (--force로 덮어쓰기)')
            continue
        print(f'  → {out_path.name}  ({s["chars"]}자)', end=' ', flush=True)
        try:
            resp = client.audio.speech.create(
                model=args.model,
                voice=args.voice,
                input=s['text'],
                speed=SPEED,
            )
            with out_path.open('wb') as f:
                f.write(resp.content)
            print(f'✓ {out_path.stat().st_size//1024}KB')
        except Exception as e:
            print(f'✗ {e}')

    print(f'\n▶ done — audio/ 폴더에 mp3 생성됨.')
    print(f'   presentation.html 열고 T 키로 음성 ON → 슬라이드 이동 시 자동 재생.')

if __name__ == '__main__':
    main()

"""통계 유틸 — 외부 의존 없이 stdlib only."""


def pearson(xs, ys):
    """Pearson correlation coefficient. None if 표본 부족 또는 분산 0."""
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs) ** 0.5
    vy = sum((y - my) ** 2 for y in ys) ** 0.5
    if vx * vy == 0:
        return None
    return num / (vx * vy)

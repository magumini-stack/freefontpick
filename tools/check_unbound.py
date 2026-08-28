"""함수 안에서 '정의하기 전에 쓰는 지역변수'를 찾는다.

로컬에 fastapi 가 없어 앱을 띄워 볼 수 없다. 그래서 라우터를 직접 실행하는
대신 흉내 내어 검증해 왔는데, 그러다 실제로 사고가 났다 — magazine_post 에서
og_image 를 만들기 전에 JSON-LD 안에서 먼저 써서 운영이 500 을 냈다.
문법 검사(ast.parse)는 이걸 못 잡는다. 실행해야만 드러나기 때문이다.

이 검사는 함수마다 '이름이 처음 대입되는 줄'과 '그 이름을 읽는 줄'을 비교해,
읽는 쪽이 더 위에 있으면 알린다.

    python tools/check_unbound.py app

한계: 분기(if/else)나 반복문 안에서 위치가 뒤바뀌는 정상적인 코드도 걸릴 수
있다. 걸리면 사람이 보고 판단한다 — 조용히 지나가는 것보다 낫다.
"""
import ast
import sys
from pathlib import Path


# 이 아래는 전부 '따로 노는 이름 공간'이다. 컴프리헨션도 파이썬 3에서는
# 자기만의 스코프라, 안 가리면 {k: v for k, v in ...} 의 k·v 가 전부
# "정의 전에 쓴다"로 잘못 걸린다.
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
          ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _own_nodes(fn):
    """이 함수 자신의 몸통에 있는 노드만. 중첩 스코프는 들어가지 않는다."""
    out = []

    def rec(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, SCOPES):
                continue
            out.append(child)
            rec(child)

    rec(fn)
    return out


def check_function(fn, path):
    """대입보다 먼저 읽는 지역 이름을 찾는다."""
    assigned, loaded, out = {}, [], []
    args = {a.arg for a in
            fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs}
    if fn.args.vararg:
        args.add(fn.args.vararg.arg)
    if fn.args.kwarg:
        args.add(fn.args.kwarg.arg)

    nodes = _own_nodes(fn)
    for node in nodes:
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Store):
                assigned.setdefault(node.id, node.lineno)
            elif isinstance(node.ctx, ast.Load):
                loaded.append((node.id, node.lineno))

    globals_ = set()
    for node in nodes:
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            globals_.update(node.names)

    for name, line in loaded:
        if name in args or name in globals_:
            continue
        first = assigned.get(name)
        if first is not None and line < first:
            out.append("%s:%d  %s() 가 %s 를 %d행에서 만들기 전에 %d행에서 쓴다"
                       % (path, line, fn.name, name, first, line))
    return out


def main(targets):
    problems = []
    files = []
    for t in targets:
        p = Path(t)
        files.extend(sorted(p.rglob("*.py")) if p.is_dir() else [p])

    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except SyntaxError as e:
            problems.append("%s: 문법 오류 %s" % (f, e))
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                problems.extend(check_function(node, f))

    print("파일 %d개 검사" % len(files))
    for p in problems:
        print("  X " + p)
    if problems:
        return 1
    print("정의 전에 쓰는 지역변수 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["app"]))

"""평가 세트 원본(.src.tsv, 인라인 마크업)을 JSONL로 바꾼다.

    [[PERSON:P1|한서윤]]  →  text에는 "한서윤"만 남고, spans에 start/end/type/entity_id가 기록된다.
오프셋을 손으로 세지 않기 위한 도구다.

사용: python tools/build_eval.py data/eval/eval_v1.src.tsv data/eval/eval_v1.jsonl
"""
import json
import re
import sys

MARK = re.compile(r"\[\[([A-Z_]+)(?::([A-Za-z0-9_]+))?\|(.+?)\]\]")
TYPES = {"PERSON", "EMAIL", "PHONE", "POSTAL", "ADDRESS", "URL", "ID_NUMBER", "ORG",
         "PROJECT", "COMPONENT", "ALGORITHM", "TERM", "SECRET"}  # C1: 프로젝트 용어·비밀키


def parse(marked: str):
    text, spans, pos = "", [], 0
    for m in MARK.finditer(marked):
        text += marked[pos:m.start()]
        typ, eid, surface = m.groups()
        if typ not in TYPES:
            raise ValueError(f"알 수 없는 유형 {typ}: {marked}")
        span = {"start": len(text), "end": len(text) + len(surface), "type": typ}
        if eid:
            span["entity_id"] = eid
        spans.append(span)
        text += surface
        pos = m.end()
    text += marked[pos:]
    if "[[" in text or "]]" in text:
        raise ValueError(f"마크업이 덜 닫힘: {marked}")
    return text, spans


def main(src, dst):
    rows = []
    for line in open(src, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        lang, marked, note = line.split("\t")
        text, spans = parse(marked)
        for s in spans:  # 자기 검사: 오프셋으로 잘라낸 값이 원문과 같아야 한다
            assert text[s["start"]:s["end"]].strip() == text[s["start"]:s["end"]]
        rows.append({"id": f"e{len(rows) + 1:03d}", "lang": lang, "text": text, "spans": spans, "note": note})
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_spans = sum(len(r["spans"]) for r in rows)
    print(f"{len(rows)} sentences, {n_spans} spans -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

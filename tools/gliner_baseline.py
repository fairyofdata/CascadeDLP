"""기준선: GLiNER(urchade/gliner_multi_pii-v1)로 스팬 탐지. 비교용이라 piigate 본체에는 넣지 않는다."""
import time

from piigate.spans import Span

MODEL_ID = "urchade/gliner_multi_pii-v1"
THRESHOLD = 0.5
# GLiNER 라벨(자연어) → 우리 유형
LABELS = {
    "person": "PERSON",
    "email": "EMAIL",
    "phone number": "PHONE",
    "postal code": "POSTAL",
    "address": "ADDRESS",
    "url": "URL",
    "national id number": "ID_NUMBER",
    "organization": "ORG",
}

_model = None


def detect(text: str) -> tuple[list[Span], float]:
    global _model
    if _model is None:
        from gliner import GLiNER
        _model = GLiNER.from_pretrained(MODEL_ID)
    t0 = time.perf_counter()
    ents = _model.predict_entities(text, list(LABELS), threshold=THRESHOLD)
    spans = [Span(e["start"], e["end"], LABELS[e["label"]], "llm") for e in ents]
    return spans, time.perf_counter() - t0

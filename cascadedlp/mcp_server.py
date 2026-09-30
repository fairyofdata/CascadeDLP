"""MCP 서버 — 다른 Claude Code 대화에서 CascadeDLP를 도구로 쓰게 한다 (stdio).

등록 (다른 프로젝트에서도 쓰려면 user 범위):
  claude mcp add --scope user cascadedlp -- <저장소 경로>\\.venv\\Scripts\\cascadedlp-mcp.exe

🔴 경계: 호출자(Claude)는 외부 LLM이다.
- 원문은 '파일 경로'로만 받는다. 원문 텍스트를 인자로 받는 도구는 없다.
- 돌려주는 것은 가명화된 텍스트·job_id·유형별 개수뿐. 복원 결과는 파일로만 쓰고 내용을 돌려주지 않는다.
- 허용 범위(~/.cascadedlp/config.json 의 allowed_roots, 기본 = 사용자 폴더) 밖은 읽지도 쓰지도 않는다.
  가명 맵 폴더·.ssh·.claude·AppData 등은 항상 막는다(gate.DENIED_UNDER_HOME).
"""
from mcp.server.mcpserver import MCPServer

from .gate import Gate, PathNotAllowed

INSTRUCTIONS = """CascadeDLP: 개인정보와 프로젝트 고유 용어를 로컬에서 토큰([PERSON_001], [COMPONENT_01: 설명] 등)으로 바꿔 주는 도구.
- 프로젝트 용어집이 있으면 project 인자로 지정한다(생략하면 폴더 매핑으로 자동). [X_01: 설명] 형식은 이름만 숨긴 것이므로 설명을 참고해 작업한다.
- blocked가 오면(외부 금지 용어 포함) 그 문서 내용을 추측하거나 다른 방법으로 읽으려 하지 말고, 사용자에게 로컬 처리가 필요하다고 알린다."""
INSTRUCTIONS += """
- 사용자가 개인정보가 담긴 문서를 다루려 하면, 내용을 대화에 붙여 넣게 하지 말고 파일 경로를 받아 mask_file을 쓴다.
- 경로·파일명·형식은 사용자가 그때그때 지정한다. UTF-8 텍스트면 형식 무관(.md .json .txt .csv 등). json은 가명화 후에도 유효한 json.
- 복원 파일 이름을 사용자가 정하지 않았으면 원본 옆에 '<원본이름>.restored.<확장자>'처럼 새 이름을 제안한다.
- 가명화된 텍스트로 작업하고, 답에서도 토큰을 그대로 유지한다(토큰을 추측해 실제 이름으로 바꾸지 않는다).
- 사용자가 원래 값이 들어간 결과가 필요하면 unmask_to_file로 로컬 파일에 쓰고, 그 경로만 알려 준다.
- 한·일·영 혼용 문서를 지원한다. 같은 사람의 다른 표기(한글/한자/가나/로마자)는 같은 토큰이 될 수 있다."""

server = MCPServer("cascadedlp", instructions=INSTRUCTIONS)
_gate: Gate | None = None


def gate() -> Gate:
    global _gate
    if _gate is None:
        _gate = Gate(restrict_paths=True)
    return _gate


@server.tool()
def mask_file(path: str, project: str | None = None) -> dict:
    """로컬 파일의 개인정보·프로젝트 용어를 토큰으로 바꾼 텍스트를 돌려준다. 원래 값은 로컬에만 남는다.
    project: 적용할 용어집 이름(생략하면 폴더 매핑). 반환: masked_text, job_id(복원용), counts(유형별 개수).
    외부 금지(L3) 용어가 있으면 blocked=true와 안내만 돌려준다. 허용 폴더 안의 파일만."""
    try:
        r = gate().mask_file(path, project)
    except (PathNotAllowed, FileNotFoundError, ValueError) as e:
        return {"error": str(e)}
    if r.blocked:
        return {"blocked": True, "notice": r.notice, "project": r.project}
    return {"masked_text": r.masked_text, "job_id": r.job_id, "counts": r.counts, "seconds": r.seconds,
            "project": r.project}


@server.tool()
def unmask_to_file(masked_text: str, job_id: str, out_path: str) -> dict:
    """가명 토큰이 든 텍스트(예: 네가 쓴 답)를 원래 값으로 되돌려 로컬 파일(out_path)에 쓴다.
    복원된 내용은 돌려주지 않는다 — 경로와 개수만. 허용 폴더 안의 새 파일에만 쓴다(덮어쓰기 금지)."""
    try:
        return gate().unmask_to_file(masked_text, job_id, out_path)
    except (PathNotAllowed, FileExistsError, FileNotFoundError, ValueError) as e:
        return {"error": str(e)}


@server.tool()
def list_entities() -> list[dict]:
    """가명 맵에 있는 토큰 목록(토큰·유형·표기 개수). 원래 값은 포함하지 않는다."""
    return gate().entities()


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()

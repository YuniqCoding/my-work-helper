# -*- coding: utf-8 -*-
"""
업무 도우미 (work-files 기반 질의응답)

work-files/ 아래 schedule(일정), meetings(회의록), reports(보고서) 폴더의
파일을 모두 읽어서, 터미널에서 입력한 질문에 그 내용을 바탕으로 답합니다.

- Anthropic Claude API(anthropic 패키지) 사용
- 모델: claude-sonnet-4-6
- 파일에 없는 내용은 추측하지 않고 "모른다"고 답합니다.

실행 전 준비:
    pip install anthropic
    같은 폴더의 .env 파일에 ANTHROPIC_API_KEY 를 넣어 두세요.
        예) ANTHROPIC_API_KEY=sk-ant-xxxxxxxx

실행:
    python agent.py
"""

import os
import re
import sys
from datetime import date
from pathlib import Path

import anthropic

# Windows 등에서 한글 입출력이 깨지지 않도록 표준 입출력을 UTF-8로 맞춘다.
for _stream in (sys.stdin, sys.stdout):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

MODEL = "claude-sonnet-4-6"

# work-files 폴더 위치 (이 스크립트와 같은 폴더 기준)
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
WORK_DIR = BASE_DIR / "work-files"
FOLDERS = {
    "schedule": "일정",
    "meetings": "회의록",
    "reports": "보고서",
}

SYSTEM_PROMPT = """당신은 총무팀 사무 담당자를 돕는 업무 도우미입니다.

아래에 사용자의 업무 파일(일정·회의록·보고서) 내용이 주어집니다.
이 내용만을 근거로 사용자의 질문에 답하세요.

규칙:
- 사용자를 "유코"라고 부릅니다. 첫 답변은 "유코님, 안녕하세요"처럼 인사로 시작하고,
  이후 답변에서도 필요하면 자연스럽게 "유코님"이라고 부릅니다.
- 항상 한국어로, 공손하고 간결하게 답합니다.
- 날짜는 반드시 YYYY-MM-DD 형식으로 씁니다.
- 파일에 없는 내용은 추측하지 말고, "문서에서 확인되지 않습니다"라고 솔직히 답합니다.
- 문서에 담긴 미확정 표시(??, "확정 아님", ※재확인 필요 등)는
  확정된 사실로 바꾸지 말고 "미확정"·"확인 필요"로 남깁니다.
- 답변의 근거가 된 파일이 있으면 어느 파일인지 짧게 덧붙이면 좋습니다.
"""


def load_env_file():
    """같은 폴더의 .env 파일을 읽어 환경변수로 넣는다. (추가 패키지 불필요)

    이미 환경변수로 설정되어 있으면 그 값을 우선한다.
    """
    if not ENV_FILE.exists():
        return
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def read_schedule_file(date_str: str) -> str | None:
    """work-files/schedule 폴더에서 '연-월-일.txt' 파일 내용을 읽어 돌려준다.

    파일이 없으면 None 을 돌려준다.
    """
    schedule_path = WORK_DIR / "schedule" / f"{date_str}.txt"
    if not schedule_path.exists():
        return None
    try:
        return schedule_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return schedule_path.read_text(encoding="cp949", errors="replace")


def load_today_schedule() -> str | None:
    """오늘 날짜(YYYY-MM-DD)와 같은 이름의 일정 파일을 찾아 내용을 출력한다."""
    today = date.today().isoformat()  # 예: "2026-07-07"
    content = read_schedule_file(today)
    if content is None:
        print(f"[오늘 일정] 오늘({today}) 날짜의 일정 파일이 없습니다.\n")
        return None
    print(f"[오늘 일정] {today}.txt")
    print(content.strip() + "\n")
    return content


def load_schedule_for_date(date_str: str) -> str | None:
    """지정한 날짜(YYYY-MM-DD)의 일정 파일을 찾아 내용을 출력한다."""
    content = read_schedule_file(date_str)
    if content is None:
        print(f"[일정] 그 날짜({date_str})의 일정 파일이 없습니다.\n")
        return None
    print(f"[일정] {date_str}.txt")
    print(content.strip() + "\n")
    return content


def summarize_today_schedule(client) -> None:
    """오늘 날짜의 일정 파일을 찾아 3줄로 요약해 출력한다.

    오늘 날짜 파일을 찾는 부분은 기존 read_schedule_file() 을 그대로 활용한다.
    """
    today = date.today().isoformat()
    content = read_schedule_file(today)
    if content is None:
        print(f"[오늘 일정 요약] 오늘({today}) 날짜의 일정 파일이 없습니다.\n")
        return

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=(
                "너는 일정 요약 도우미다. 주어진 하루 일정을 정확히 3줄로 요약해라. "
                "각 줄은 '- '로 시작하고, 핵심(중요한 회의·마감·급한 일)만 간결하게 담는다. "
                "한국어로 쓰고, 문서에 없는 내용은 지어내지 않는다."
            ),
            messages=[
                {
                    "role": "user",
                    "content": f"다음은 {today} 일정입니다. 3줄로 요약해 주세요.\n\n{content}",
                }
            ],
        )
    except anthropic.APIError as e:
        print(f"[오류] 요약에 실패했습니다: {e}\n")
        return

    summary = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    print(f"[오늘 일정 요약] {today}")
    print(summary + "\n")


def extract_meeting_todos(client) -> None:
    """meetings 폴더의 회의록에서 '누가 / 무엇을 / 언제까지' 할 일만 뽑아 목록으로 출력한다."""
    meetings_dir = WORK_DIR / "meetings"
    parts = []
    if meetings_dir.exists():
        for file_path in sorted(meetings_dir.glob("*")):
            if file_path.suffix.lower() not in (".txt", ".md"):
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = file_path.read_text(encoding="cp949", errors="replace")
            parts.append(f"===== 파일: {file_path.name} =====\n{content.strip()}\n")

    if not parts:
        print("[회의 할 일] 회의록 파일이 없습니다.\n")
        return

    meetings_text = "\n".join(parts)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=(
                "너는 회의록에서 후속 할 일(액션 아이템)만 뽑아내는 도우미다. "
                "각 할 일을 '- 담당자: OOO / 할 일: ... / 마감: ...' 형식의 한 줄로 정리한다. "
                "담당자나 마감이 회의록에 적혀 있지 않으면 '미정'이라고 쓴다. "
                "날짜는 YYYY-MM-DD 형식으로 쓰고, 회의록에 없는 내용은 지어내지 않는다. "
                "단순 논의·결정 사항 등 할 일이 아닌 것은 목록에 넣지 않는다."
            ),
            messages=[
                {
                    "role": "user",
                    "content": "다음 회의록들에서 할 일만 뽑아 목록으로 정리해 주세요.\n\n"
                    + meetings_text,
                }
            ],
        )
    except anthropic.APIError as e:
        print(f"[오류] 회의 할 일 추출에 실패했습니다: {e}\n")
        return

    result = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    print("[회의 할 일 목록]")
    print(result + "\n")


def answer_from_reports(client, question: str) -> None:
    """reports 폴더의 보고서만 근거로 사용자의 질문에 답한다.

    보고서에 없는 내용은 지어내지 않고 '모른다'고 답하게 한다.
    """
    reports_dir = WORK_DIR / "reports"
    parts = []
    if reports_dir.exists():
        for file_path in sorted(reports_dir.glob("*")):
            if file_path.suffix.lower() not in (".txt", ".md"):
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = file_path.read_text(encoding="cp949", errors="replace")
            parts.append(f"===== 파일: {file_path.name} =====\n{content.strip()}\n")

    if not parts:
        print("[보고서] 보고서 파일이 없습니다.\n")
        return

    reports_text = "\n".join(parts)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=(
                "너는 아래 보고서 문서만 근거로 답하는 도우미다. "
                "보고서에 없는 내용은 절대 지어내지 말고 '보고서에서 확인되지 않습니다'라고 답한다. "
                "한국어로 공손하고 간결하게 답하고, 날짜는 YYYY-MM-DD 형식으로 쓴다. "
                "보고서에 담긴 미확정 표시(※재확인 필요 등)는 확정 사실로 바꾸지 말고 그대로 알린다."
            ),
            messages=[
                {
                    "role": "user",
                    "content": f"[보고서 내용]\n{reports_text}\n\n[질문]\n{question}",
                }
            ],
        )
    except anthropic.APIError as e:
        print(f"[오류] 보고서 답변에 실패했습니다: {e}\n")
        return

    answer = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    print("[보고서 답변]")
    print(answer + "\n")


def search_documents(keyword: str) -> None:
    """work-files 폴더 전체에서 키워드가 든 파일과 해당 줄을 찾아 보여준다.

    어떤 파일의 몇 번째 줄에서 나왔는지 함께 출력한다. (API 호출 없이 로컬 검색)
    """
    keyword = keyword.strip()
    if not keyword:
        print("[검색] 찾을 키워드를 입력해 주세요. 예) 검색 예산\n")
        return

    lowered = keyword.lower()
    print(f"[검색 결과: '{keyword}']")
    total = 0
    for folder, label in FOLDERS.items():
        folder_path = WORK_DIR / folder
        if not folder_path.exists():
            continue
        for file_path in sorted(folder_path.glob("*")):
            if file_path.suffix.lower() not in (".txt", ".md"):
                continue
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                lines = file_path.read_text(encoding="cp949", errors="replace").splitlines()

            matches = [
                (line_no, line)
                for line_no, line in enumerate(lines, start=1)
                if lowered in line.lower()
            ]
            if not matches:
                continue

            rel = file_path.relative_to(BASE_DIR).as_posix()
            print(f"- [{label}] {rel}")
            for line_no, line in matches:
                print(f"    {line_no}행: {line.strip()}")
            total += len(matches)

    if total == 0:
        print(f"'{keyword}' 를 포함한 내용을 찾지 못했습니다.\n")
    else:
        print(f"\n총 {total}건을 찾았습니다.\n")


def extract_date(question: str) -> str | None:
    """질문에서 '연-월-일' 형태의 날짜를 찾아 YYYY-MM-DD 문자열로 돌려준다.

    없거나 실제로 존재하지 않는 날짜면 None 을 돌려준다.
    """
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", question)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day).isoformat()  # 존재하는 날짜인지 검증 + 0채움
    except ValueError:
        return None


def has_schedule_word(question: str) -> bool:
    """질문에 일정 관련 단어가 들어 있는지 확인한다."""
    text = question.replace(" ", "")
    schedule_words = ("일정", "스케줄", "할일", "일과", "약속", "예정")
    return any(word in text for word in schedule_words)


def is_today_schedule_question(question: str) -> bool:
    """질문이 '오늘 일정'을 묻는 것인지 간단히 판별한다."""
    return "오늘" in question.replace(" ", "") and has_schedule_word(question)


def load_work_files() -> str:
    """work-files 아래 세 폴더의 파일을 모두 읽어 하나의 문자열로 만든다."""
    if not WORK_DIR.exists():
        print(f"[오류] work-files 폴더를 찾을 수 없습니다: {WORK_DIR}")
        sys.exit(1)

    parts = []
    file_count = 0
    for folder, label in FOLDERS.items():
        folder_path = WORK_DIR / folder
        if not folder_path.exists():
            continue
        # .txt, .md 파일을 이름순으로 읽는다.
        for file_path in sorted(folder_path.glob("*")):
            if file_path.suffix.lower() not in (".txt", ".md"):
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = file_path.read_text(encoding="cp949", errors="replace")
            rel = file_path.relative_to(BASE_DIR).as_posix()
            parts.append(
                f"===== [{label}] 파일: {rel} =====\n{content.strip()}\n"
            )
            file_count += 1

    if file_count == 0:
        print("[오류] 읽을 수 있는 문서(.txt/.md)가 없습니다.")
        sys.exit(1)

    print(f"[안내] 문서 {file_count}개를 읽었습니다. 질문을 입력해 주세요.\n")
    return "\n".join(parts)


def build_system_blocks(files_text: str):
    """시스템 프롬프트 + 파일 내용. 반복 질문에서 캐시가 되도록 cache_control 지정."""
    return [
        {"type": "text", "text": SYSTEM_PROMPT},
        {
            "type": "text",
            "text": "다음은 참고할 업무 파일 내용입니다.\n\n" + files_text,
            "cache_control": {"type": "ephemeral"},
        },
    ]


def main():
    load_env_file()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key or api_key == "여기에-실제-API-키를-넣으세요":
        print("[오류] ANTHROPIC_API_KEY 가 설정되어 있지 않습니다.")
        print(f"       {ENV_FILE} 파일을 열어 실제 API 키를 넣어 주세요.")
        print("       예) ANTHROPIC_API_KEY=sk-ant-xxxxxxxx")
        sys.exit(1)

    client = anthropic.Anthropic()
    system_blocks = build_system_blocks(load_work_files())

    print("업무 도우미입니다. 무엇이든 물어보세요.")
    print("(종료하려면 '종료', 'exit', 'quit' 입력)\n")

    # 대화 이력 (후속 질문을 위해 유지)
    messages = []

    while True:
        try:
            question = input("질문> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n이용해 주셔서 감사합니다. 좋은 하루 보내세요!")
            break

        if not question:
            continue
        if question.lower() in ("종료", "exit", "quit", "q"):
            print("이용해 주셔서 감사합니다. 좋은 하루 보내세요!")
            break

        text = question.replace(" ", "")

        # "검색 ○○" / "찾기 ○○" 이면 work-files 전체에서 키워드를 찾아 준다.
        if text.startswith("검색") or text.startswith("찾"):
            keyword = question.strip()
            for trigger in ("검색해줘", "검색해", "검색", "찾아줘", "찾아봐", "찾아", "찾기"):
                if keyword.startswith(trigger):
                    keyword = keyword[len(trigger):]
                    break
            keyword = keyword.strip(" :：-\t")
            if keyword.endswith("해줘"):
                keyword = keyword[:-2].strip()
            search_documents(keyword)
            continue

        # "오늘 ... 요약" 이면 오늘 일정을 3줄로 요약해 준다.
        if "오늘" in text and "요약" in text:
            summarize_today_schedule(client)
            continue

        # "회의 ... 할 일/담당/액션" 이면 회의록에서 할 일 목록을 뽑아 준다.
        if "회의" in text and (
            "할일" in text or "todo" in text.lower() or "액션" in text or "담당" in text
        ):
            extract_meeting_todos(client)
            continue

        # "보고서" 관련 질문이면 보고서 내용만 근거로 답한다.
        if "보고서" in text:
            answer_from_reports(client, question)
            continue

        # 일정 관련 질문이면, 특정 날짜가 있으면 그 날짜를, 없으면 오늘 것을 보여준다.
        requested_date = extract_date(question)
        if requested_date and has_schedule_word(question):
            load_schedule_for_date(requested_date)
        elif is_today_schedule_question(question):
            load_today_schedule()

        messages.append({"role": "user", "content": question})

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=system_blocks,
                messages=messages,
            )
        except anthropic.APIError as e:
            print(f"[오류] API 호출에 실패했습니다: {e}\n")
            messages.pop()  # 실패한 질문은 이력에서 제거
            continue

        answer = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()

        print(f"\n{answer}\n")
        messages.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    main()

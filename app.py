# -*- coding: utf-8 -*-
"""업무 도우미 웹 화면 (Streamlit)

터미널에 글자를 치지 않고, 웹 화면에서 버튼으로 쓰는 업무 도우미입니다.
기능은 새로 만들지 않고, agent.py 에 이미 만들어 둔 함수를 그대로 가져다 씁니다.

각 결과 아래에 내려받기 버튼이 있습니다.
- 목록형 결과(할 일 목록, 검색 결과) → CSV(표) 파일
- 줄글형 결과(일정·요약·보고서 답변) → PDF(문서) 파일
PDF 한글은 fonts/malgun.ttf(맑은 고딕) 폰트로 표시합니다.

실행 방법:
    pip install streamlit anthropic fpdf2
    streamlit run app.py
"""

import contextlib
import csv
import io
import os
import re
from datetime import date
from pathlib import Path

import streamlit as st

import agent  # 지금까지 만든 기능 그대로 재사용

BASE_DIR = Path(__file__).resolve().parent


# ==========================================================
# 공통 도우미
# ==========================================================
def run_capture(func, *args, **kwargs) -> str:
    """agent.py 함수들이 print 로 출력하는 결과를 문자열로 받아온다."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        func(*args, **kwargs)
    return buffer.getvalue().strip()


def find_korean_font() -> str | None:
    """한글 PDF용 폰트 경로를 찾는다. 프로젝트 fonts 폴더 → 시스템 폰트 순."""
    candidates = [
        BASE_DIR / "fonts" / "malgun.ttf",
        BASE_DIR / "fonts" / "NanumGothic.ttf",
        Path(r"C:\Windows\Fonts\malgun.ttf"),
        Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None


KOREAN_FONT = find_korean_font()


def _clean_for_pdf(text: str) -> str:
    """PDF 로 넣기 전에 마크다운 기호와 이모지 변형선택자를 정리한다."""
    text = text.replace("**", "").replace("️", "")
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)  # 인용부호 >
    text = re.sub(r"^\s*-{3,}\s*$", "────────────", text, flags=re.MULTILINE)
    return text


def make_pdf(title: str, body_text: str) -> bytes:
    """제목과 본문을 한글 폰트로 넣은 PDF 바이트를 만든다."""
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    if KOREAN_FONT:
        pdf.add_font("KR", "", KOREAN_FONT)
        title_font, body_font = ("KR", "KR")
    else:
        title_font, body_font = ("Helvetica", "Helvetica")

    pdf.set_font(title_font, size=15)
    pdf.multi_cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font(body_font, size=11)
    for line in _clean_for_pdf(body_text).split("\n"):
        pdf.multi_cell(0, 7, line if line.strip() else " ", new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())


def _rows_to_csv(rows: list[tuple]) -> bytes:
    """행 목록을 CSV 바이트로 만든다. (엑셀 한글 호환 위해 utf-8-sig)"""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def search_result_to_csv(text: str) -> bytes | None:
    """검색 결과 텍스트를 '폴더/파일/행/내용' 표(CSV)로 만든다."""
    rows: list[tuple] = [("폴더", "파일", "행", "내용")]
    folder, path = "", ""
    for line in text.splitlines():
        head = re.match(r"- \[(.+?)\]\s+(.+)$", line)
        if head:
            folder, path = head.group(1), head.group(2)
            continue
        hit = re.match(r"\s+(\d+)행:\s?(.*)$", line)
        if hit:
            rows.append((folder, path, hit.group(1), hit.group(2)))
    if len(rows) == 1:
        return None
    return _rows_to_csv(rows)


def todos_to_csv(text: str) -> bytes:
    """회의록 할 일 목록 텍스트를 '담당자/할 일/마감' 표(CSV)로 만든다."""
    rows: list[tuple] = [("담당자", "할 일", "마감")]
    for line in text.splitlines():
        item = line.strip().lstrip("-").strip()
        matched = re.search(
            r"담당자:\s*(.*?)\s*/\s*할\s?일:\s*(.*?)\s*/\s*마감:\s*(.*)$", item
        )
        if matched:
            rows.append((matched.group(1), matched.group(2), matched.group(3)))
    if len(rows) == 1:  # 형식이 다르면 한 줄씩 그대로 담는다.
        rows = [("내용",)] + [(l,) for l in text.splitlines() if l.strip()]
    return _rows_to_csv(rows)


@st.cache_resource
def get_client():
    import anthropic

    return anthropic.Anthropic()


# ==========================================================
# 화면 꾸미기 (어두운 배경 + 보라 오로라 + 세리프 헤드라인)
# ==========================================================
THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&display=swap');

.stApp { background-color: #0a0b14; }
[data-testid="stHeader"] { background: transparent; }

/* 상단 보라빛 오로라 글로우 */
.stApp::before {
  content: ""; position: fixed; top: 0; left: 50%; transform: translateX(-50%);
  width: 1200px; height: 700px; pointer-events: none; z-index: 0;
  background:
    radial-gradient(ellipse 80% 55% at 50% 12%, rgba(139,92,246,0.20) 0%, transparent 60%),
    radial-gradient(ellipse 55% 45% at 62% 22%, rgba(236,72,153,0.12) 0%, transparent 55%),
    radial-gradient(ellipse 65% 40% at 38% 18%, rgba(59,130,246,0.12) 0%, transparent 55%);
}
.block-container { position: relative; z-index: 1; padding-top: 3rem; }

/* 글자색 */
.stApp, p, span, label, li, .stMarkdown { color: #cbd2e0; }
h1, h2, h3, h4 { color: #ffffff !important; }

/* 히어로 헤더 */
.hero-kicker { color: #b794ff; font-size: .8rem; letter-spacing: .18em; font-weight: 600; margin-bottom: .6rem; }
.hero-title { font-size: 3.1rem; line-height: 1.08; font-weight: 300; color: #f5f5f7; letter-spacing: -.02em; }
.hero-title .accent { font-family: 'Instrument Serif', serif; font-style: italic; font-weight: 400; color: #ffffff; }
.hero-sub { color: #9ca3af; font-size: 1.05rem; margin-top: 1rem; max-width: 640px; }

/* 버튼 */
.stButton > button, .stDownloadButton > button {
  background: #9b6dff; color: #fff; border: 1px solid #9b6dff;
  border-radius: 10px; font-weight: 600; padding: .5rem 1.1rem;
  transition: all .15s ease; box-shadow: 0 4px 20px rgba(155,109,255,.25);
}
.stButton > button:hover, .stDownloadButton > button:hover {
  background: #b794ff; border-color: #b794ff; color: #fff; transform: translateY(-1px);
}

/* 입력칸 */
[data-baseweb="input"], [data-baseweb="input"] input,
.stTextInput input, .stDateInput input {
  background-color: #0f1119 !important; color: #ffffff !important;
  border-radius: 8px !important;
}
[data-baseweb="input"] { border: 1px solid #1a1c2a !important; }

/* 결과 텍스트 박스 (일정·검색) */
[data-testid="stText"], pre {
  background-color: #0f1119 !important; color: #cbd2e0 !important;
  border: 1px solid #1a1c2a; border-radius: 12px; padding: 14px 16px;
}

/* 안내창 / 구분선 */
[data-testid="stAlert"] { border-radius: 12px; }
hr { border-color: #1a1c2a !important; }

/* 탭 (기능을 상단 탭으로) */
[data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid #1a1c2a; }
button[data-baseweb="tab"] { color: #9ca3af; font-weight: 500; }
button[data-baseweb="tab"]:hover { color: #ffffff; }
button[data-baseweb="tab"][aria-selected="true"] { color: #ffffff; }
[data-baseweb="tab-highlight"] { background-color: #9b6dff !important; }
[data-baseweb="tab-panel"] { padding-top: 1rem; }
</style>
"""

HERO_HTML = """
<div class="hero-kicker">🗂️ 업무 도우미</div>
<div class="hero-title">A smarter way to <span class="accent">work</span></div>
<div class="hero-sub">work-files의 일정·회의록·보고서를 바탕으로, 버튼 하나로 정리해 드립니다.</div>
"""


# ==========================================================
# 준비: .env 에서 키 읽기
# ==========================================================
agent.load_env_file()
_api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
API_READY = bool(_api_key) and _api_key != "여기에-실제-API-키를-넣으세요"

st.set_page_config(page_title="업무 도우미", page_icon="🗂️")
st.markdown(THEME_CSS, unsafe_allow_html=True)
st.markdown(HERO_HTML, unsafe_allow_html=True)

# 화면 맨 위에 오늘 날짜를 자동으로 표시한다. (YYYY-MM-DD 형식 + 한글 요일)
_today = date.today()
_weekday_kr = ["월", "화", "수", "목", "금", "토", "일"][_today.weekday()]
st.markdown(
    f"<div class='hero-sub' style='margin-top:.4rem;'>"
    f"📅 오늘은 <b>{_today.isoformat()} ({_weekday_kr})</b> 입니다.</div>",
    unsafe_allow_html=True,
)

st.write("")

if not KOREAN_FONT:
    st.warning("한글 PDF용 폰트를 찾지 못했습니다. fonts/malgun.ttf 파일을 준비해 주세요.")

if not API_READY:
    st.warning(
        "`.env` 파일에 ANTHROPIC_API_KEY 가 없어서 AI 기능(오늘 할 일 정리·"
        "회의록 할 일·보고서 질문)은 잠시 쉬어요. "
        "날짜별 일정 보기와 문서 검색은 그대로 사용할 수 있습니다."
    )

# ==========================================================
# 기능을 상단 탭으로 나눈다.
# ==========================================================
tab_schedule, tab_today, tab_meeting, tab_report, tab_search = st.tabs(
    ["📅 일정", "📋 오늘 할 일", "✅ 회의록 할 일", "📄 보고서 질문", "🔍 문서 검색"]
)

# ---- 탭 1: 날짜별 일정 (줄글 → PDF) ----
with tab_schedule:
    st.subheader("📅 날짜별 일정")
    picked = st.date_input("날짜를 고르세요", value=date.today())
    picked_str = picked.isoformat()
    schedule_text = agent.read_schedule_file(picked_str)
    if schedule_text:
        st.text(schedule_text.strip())
        st.download_button(
            "📄 이 일정 PDF로 내려받기",
            data=make_pdf(f"{picked_str} 일정", schedule_text),
            file_name=f"일정_{picked_str}.pdf",
            mime="application/pdf",
            key="dl_schedule",
        )
    else:
        st.info(f"{picked_str} 날짜의 일정 파일이 없습니다.")

# ---- 탭 2: 오늘 할 일 정리 (줄글 → PDF) ----
with tab_today:
    st.subheader("📋 오늘 할 일 정리")
    if st.button("오늘 할 일 정리하기", use_container_width=True):
        if API_READY:
            with st.spinner("오늘 일정을 정리하는 중..."):
                st.session_state["today_result"] = run_capture(
                    agent.summarize_today_schedule, get_client()
                )
        else:
            st.error("이 기능은 ANTHROPIC_API_KEY 가 필요합니다.")
    if st.session_state.get("today_result"):
        today_text = st.session_state["today_result"]
        st.markdown(today_text)
        st.download_button(
            "📄 오늘 할 일 PDF로 내려받기",
            data=make_pdf("오늘 할 일 정리", today_text),
            file_name="오늘_할일_정리.pdf",
            mime="application/pdf",
            key="dl_today",
        )

# ---- 탭 3: 회의록 할 일 뽑기 (목록 → CSV) ----
with tab_meeting:
    st.subheader("✅ 회의록 할 일 뽑기")
    if st.button("회의록에서 할 일 뽑기", use_container_width=True):
        if API_READY:
            with st.spinner("회의록에서 할 일을 뽑는 중..."):
                st.session_state["meeting_result"] = run_capture(
                    agent.extract_meeting_todos, get_client()
                )
        else:
            st.error("이 기능은 ANTHROPIC_API_KEY 가 필요합니다.")
    if st.session_state.get("meeting_result"):
        meeting_text = st.session_state["meeting_result"]
        st.markdown(meeting_text)
        st.download_button(
            "📊 회의 할 일 목록 CSV로 내려받기",
            data=todos_to_csv(meeting_text),
            file_name="회의_할일_목록.csv",
            mime="text/csv",
            key="dl_meeting",
        )

# ---- 탭 4: 보고서 질문 (줄글 → PDF) ----
with tab_report:
    st.subheader("📄 보고서 질문")
    report_q = st.text_input(
        "보고서에 대해 궁금한 점을 적어 주세요",
        key="report_question",
        placeholder="예: 보고서 결론이 뭐야?",
    )
    if st.button("질문하기"):
        if not report_q.strip():
            st.info("질문을 입력해 주세요.")
        elif not API_READY:
            st.error("이 기능은 ANTHROPIC_API_KEY 가 필요합니다.")
        else:
            with st.spinner("보고서를 살펴보는 중..."):
                st.session_state["report_result"] = run_capture(
                    agent.answer_from_reports, get_client(), report_q
                )
    if st.session_state.get("report_result"):
        report_text = st.session_state["report_result"]
        st.markdown(report_text)
        st.download_button(
            "📄 보고서 답변 PDF로 내려받기",
            data=make_pdf("보고서 질문 답변", report_text),
            file_name="보고서_답변.pdf",
            mime="application/pdf",
            key="dl_report",
        )

# ---- 탭 5: 문서 검색 (목록 → CSV) ----
with tab_search:
    st.subheader("🔍 문서 검색")
    keyword = st.text_input("찾을 단어를 입력하세요", placeholder="예: 예산")
    if keyword.strip():
        search_text = run_capture(agent.search_documents, keyword)
        st.text(search_text)
        csv_bytes = search_result_to_csv(search_text)
        if csv_bytes:
            st.download_button(
                "📊 검색 결과 CSV로 내려받기",
                data=csv_bytes,
                file_name=f"검색_{keyword.strip()}.csv",
                mime="text/csv",
                key="dl_search",
            )

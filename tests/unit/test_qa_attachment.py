"""附件材料链路的边界测试：材料不作依据、OCR 需用户确认、识别结果要收敛成纯文本。"""

from __future__ import annotations

import asyncio
import io
import json

import pytest
from fastapi import HTTPException

from app.chains.qa_chain import QAChain
from app.services.ocr_service import normalize_ocr_text
from app.services.qa_attachment_service import (
    QAAttachment,
    attachment_warnings,
    material_block,
    store_attachment,
)


class _FakeCache:
    """只实现 store_attachment 需要的两个方法，避免测试依赖 Redis。"""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def set(self, key: str, value, ttl=None) -> bool:  # noqa: ANN001
        self.data[key] = json.dumps(value, ensure_ascii=False)
        return True

    async def get(self, key: str):
        return json.loads(self.data[key]) if key in self.data else None


def _png(text: str = "第六条 预备党员预备期为一年。") -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (640, 160), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 24)
    except OSError:  # pragma: no cover - 无中文字体的环境
        font = ImageFont.load_default()
    draw.text((20, 50), text, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_material_block_is_numbered_apart_from_citations():
    items = [
        QAAttachment(id="a", file_name="细则.txt", size=10, chars=5, truncated=False, text="第五条"),
        QAAttachment(id="b", file_name="通知.txt", size=10, chars=4, truncated=False, text="第六条"),
    ]
    block = material_block(items)
    assert block.startswith("<用户上传材料>")
    assert "〔材料 1〕" in block and "〔材料 2〕" in block
    # 材料编号不能长得像引用角标，否则模型会把材料当成 [n] 来源
    assert "[1]" not in block


def test_image_requires_explicit_cloud_consent():
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            store_attachment(
                _FakeCache(),
                tenant_id="t",
                user_id="u",
                file_name="通知.png",
                data=_png(),
            )
        )
    assert error.value.status_code == 428
    assert error.value.detail["code"] == "OCR_CONSENT_REQUIRED"


def test_normalize_ocr_text_handles_latex_and_structured_output():
    latex = (
        "$" + chr(92) + "begin{aligned}& " + chr(92) + "text { 第五条 正文 } "
        + chr(92) + chr(92) + "& " + chr(92) + "text { 第六条 正文 }" + chr(92) + "end{aligned}$"
    )
    assert normalize_ocr_text(latex) == "第五条 正文\n第六条 正文"
    structured = '```json\n[{"text": "第五条 正文"}, {"rotate_rect": [1], "text": "第六条 正文"}]\n```'
    assert normalize_ocr_text(structured) == "第五条 正文\n第六条 正文"
    assert normalize_ocr_text("普通文本\n第二行") == "普通文本\n第二行"


def test_attachment_warnings_cover_truncation_and_ocr_notes():
    items = [
        QAAttachment(
            id="a",
            file_name="长文.txt",
            size=1,
            chars=6000,
            truncated=True,
            ocr=True,
            notes=["《长文.txt》的文字由云端识别（OCR）生成，可能存在识别误差，请对照原件核对。"],
        )
    ]
    warnings = attachment_warnings(items)
    assert any("OCR" in item for item in warnings)
    assert any("只读取了前 6000 字" in item for item in warnings)


class _EmptyRetriever:
    async def retrieve(self, *, question: str, tenant_id: str, include_expired: bool = False):
        return []


class _EchoGenerator:
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, *, question, chunks):  # noqa: ANN001
        self.calls += 1
        return "根据材料，预备期为一年 [1]。"


def test_no_kb_evidence_with_material_answers_without_citations():
    chain = QAChain(
        retriever=_EmptyRetriever(),
        generator=_EchoGenerator(),
        supplemental_material="<用户上传材料>\n〔材料 1〕文件名：a.txt\n预备期为一年\n</用户上传材料>",
    )
    response = asyncio.run(chain.ask(question="预备期多久", tenant_id="t"))
    assert response.refused is False
    assert response.citations == []
    # 没有引用就不能留 [n] 角标：界面上点了会没反应
    assert "[1]" not in response.answer
    assert any("仅依据你上传的材料" in item for item in response.warnings)


def test_no_kb_evidence_without_material_still_refuses():
    chain = QAChain(retriever=_EmptyRetriever(), generator=_EchoGenerator())
    response = asyncio.run(chain.ask(question="预备期多久", tenant_id="t"))
    assert response.refused is True
    assert response.citations == []

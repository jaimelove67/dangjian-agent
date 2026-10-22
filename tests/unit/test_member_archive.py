"""扫描件归档：格式判定、识别降级、文本脱敏。

三条底线在这里验证：
1. 没确认出网时**绝不调用**模型，只标 skipped；
2. 敏感/涉密材料即使勾选也不出网（由服务层按密级拦，这里验证密级判断）；
3. 识别文本出口把身份证号、手机号脱敏，不原文直给。
"""

import pytest

from app.core.desensitization import mask_text
from app.rules.data_sensitivity import cloud_allowed
from app.services.member_archive_service import (
    OCR_NOTE,
    SKIPPED_CONSENT_NOTE,
    extract_scan_text,
    scan_supported,
)

PDF_MAGIC = b"%PDF-1.4\n%fake\n"


class TestSupportedFormats:
    def test_scan_formats(self):
        for name in ("a.pdf", "a.PDF", "b.png", "c.jpg", "d.jpeg"):
            assert scan_supported(name), name

    def test_rejects_office_and_tiff(self):
        for name in ("a.docx", "a.tif", "a.txt"):
            assert not scan_supported(name), name


class TestExtractDegrades:
    @pytest.mark.asyncio
    async def test_skips_without_consent(self):
        """未勾选云端识别：不调用模型，返回 skipped 且有说明。"""
        result = await extract_scan_text(b"x", file_name="scan.png", cloud_ocr=False)
        assert result.status == "skipped"
        assert result.text == ""
        assert result.notes == [SKIPPED_CONSENT_NOTE]

    @pytest.mark.asyncio
    async def test_broken_pdf_is_not_swallowed_silently(self):
        """坏 PDF 且未同意识别：仍按 skipped 处理，不抛异常中断归档。"""
        result = await extract_scan_text(PDF_MAGIC, file_name="broken.pdf", cloud_ocr=False)
        assert result.status in {"skipped", "failed"}
        assert result.text == ""

    def test_ocr_note_mentions_original(self):
        assert "原件" in OCR_NOTE


class TestSensitiveMaterialNeverLeaves:
    def test_classified_material_is_not_cloud_allowed(self):
        """政审这类敏感/涉密材料按既有密级规则不允许出网。"""
        assert cloud_allowed("sensitive") is False
        assert cloud_allowed("classified") is False
        assert cloud_allowed("internal") is True


class TestMaskText:
    def test_masks_id_card_in_long_text(self):
        text = "本人李思远，身份证号 430102199001011234，现申请入党。"
        masked = mask_text(text)
        assert "430102199001011234" not in masked
        assert "430102********1234" in masked
        assert "现申请入党" in masked

    def test_masks_mobile_in_long_text(self):
        masked = mask_text("联系电话 13812345678 请在工作日联系")
        assert "13812345678" not in masked
        assert "138****5678" in masked

    def test_keeps_plain_text_and_newlines(self):
        text = "第一行\n第二行\n没有号码"
        assert mask_text(text) == text

    def test_handles_empty(self):
        assert mask_text("") == ""

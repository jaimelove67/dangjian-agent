"""WF-03 / WF-04 标准接口契约测试（T-WF02-13）。

这里锁定的是**契约**而不是实现：出入参可序列化、带版本号、判定结果为数据（不抛异常），
且与既有实现行为一致。日后把两个环节拆成独立工作流或独立服务时，这些断言必须仍然成立。
"""

from datetime import date

from app.chains.workflow_interfaces import (
    citation_check,
    sensitive_check,
    to_citation_input,
    to_retrieved_chunk,
)
from app.rag.verifier import CitationVerifier, RetrievedChunk
from app.schemas.wf import WF03_VERSION, WF04_VERSION, CitationCheckRequest, SensitiveCheckRequest


def _chunk(index: int = 1, **overrides) -> RetrievedChunk:
    base = {
        "index": index,
        "doc_id": f"d{index}",
        "doc_name": f"文件{index}",
        "content": "第一条 内容。",
        "article": "第一条",
        "status": "effective",
    }
    base.update(overrides)
    return RetrievedChunk(**base)


class TestCitationContract:
    """WF-03 出参契约：清洗后的答案 + 有效引用 + 风险提示 + 是否通过"""

    def test_valid_citation_passes(self):
        response = citation_check(
            CitationCheckRequest(
                answer="根据第一条，培养期不少于一年[1]。",
                citations=[to_citation_input(_chunk(1, content="第一条 培养期一般不少于一年。"))],
            )
        )
        assert response.workflow == "WF-03"
        assert response.version == WF03_VERSION
        assert response.valid is True
        assert [c.index for c in response.citations] == [1]
        assert response.warnings == []

    def test_invalid_citation_removed_with_warning(self):
        response = citation_check(
            CitationCheckRequest(answer="结论[9]", citations=[to_citation_input(_chunk(1))])
        )
        assert "[9]" not in response.answer
        assert response.valid is False
        assert response.citations == []
        assert any("引用[9]不存在" in w for w in response.warnings)

    def test_behaviour_matches_verifier_implementation(self):
        """标准入口与底层实现同源：换实现也不能换口径"""
        answer = "培养期不少于一年[1]，结论[7]。"
        chunks = [_chunk(1, content="第一条 培养期一般不少于一年。")]
        expected = CitationVerifier().verify(answer, chunks)
        actual = citation_check(
            CitationCheckRequest(answer=answer, citations=[to_citation_input(c) for c in chunks])
        )
        assert actual.answer == expected.answer
        assert actual.valid == expected.valid
        assert actual.warnings == expected.warnings
        assert [c.index for c in actual.citations] == [c.index for c in expected.citations]

    def test_today_is_part_of_the_contract(self):
        """核验基准日可传入，保证时效判定可复现"""
        expiring = _chunk(1, expiration_date=date(2026, 1, 10))
        response = citation_check(
            CitationCheckRequest(
                answer="培养期不少于一年[1]。",
                citations=[to_citation_input(expiring)],
                today=date(2026, 1, 5),
            )
        )
        assert any("即将于" in w and "失效" in w for w in response.warnings)

    def test_adapter_round_trip_keeps_every_field(self):
        original = _chunk(
            3,
            article="第十二条",
            doc_number="中发〔2021〕1号",
            issuer="中共中央",
            effective_date=date(2021, 1, 1),
            expiration_date=date(2030, 1, 1),
            score=0.87,
            file_name="细则.pdf",
            visibility="internal",
            level="2",
            security_level="internal",
            chunk_id="c-3",
            authority="authoritative",
            validity="effective",
        )
        contract = to_citation_input(original)
        assert to_retrieved_chunk(contract) == original

    def test_request_and_response_are_serializable(self):
        """可序列化是可拆分的前提：契约里不允许出现链路内部对象"""
        request = CitationCheckRequest(answer="结论[1]", citations=[to_citation_input(_chunk(1))])
        payload = citation_check(request).model_dump_json()
        assert '"workflow":"WF-03"' in payload
        assert f'"version":"{WF03_VERSION}"' in payload


class TestSensitiveContract:
    """WF-04 出参契约：级别 + 能否出网 + 命中原因 + 可执行出路"""

    def test_plain_question_is_internal_and_allowed(self):
        response = sensitive_check(SensitiveCheckRequest(text="入党申请书的材料有哪些？"))
        assert response.workflow == "WF-04"
        assert response.version == WF04_VERSION
        assert response.level == "internal"
        assert response.cloud_allowed is True
        assert response.reasons == []
        assert response.guidance == ""

    def test_personal_identifier_blocks_cloud_with_guidance(self):
        response = sensitive_check(
            SensitiveCheckRequest(text="合成手机号 13900000000", declared_level="public")
        )
        assert response.level == "sensitive"
        assert response.cloud_allowed is False
        assert any("个人标识" in r for r in response.reasons)
        assert "本地模型" in response.guidance

    def test_declared_public_cannot_lower_detected_level(self):
        response = sensitive_check(
            SensitiveCheckRequest(text="合成身份证 110101200001010019", declared_level="public")
        )
        assert response.level == "sensitive"
        assert response.cloud_allowed is False

    def test_confidential_marker_blocks_with_offline_guidance(self):
        response = sensitive_check(SensitiveCheckRequest(text="密级：机密\n合成档案"))
        assert response.level == "classified"
        assert response.cloud_allowed is False
        assert any("涉密标记" in r for r in response.reasons)
        assert "线下人工" in response.guidance

    def test_declared_classified_blocks(self):
        response = sensitive_check(
            SensitiveCheckRequest(text="合成普通问题", declared_level="classified")
        )
        assert response.level == "classified"
        assert response.cloud_allowed is False
        assert any("声明密级" in r for r in response.reasons)

    def test_minimum_level_is_configurable(self):
        assert sensitive_check(SensitiveCheckRequest(text="合成普通问题")).level == "internal"
        lowered = sensitive_check(
            SensitiveCheckRequest(text="合成普通问题", minimum_level="public")
        )
        assert lowered.level == "public"

    def test_decision_is_data_not_exception(self):
        """硬拦截也要能返回原因与出路，便于调用方选择拒答 / 本地模型 / 人工路径"""
        response = sensitive_check(SensitiveCheckRequest(text="合成手机号 13900000000"))
        assert response.cloud_allowed is False
        assert response.model_dump_json()

"""向知识库批量导入党建制度文件（开发 / 演示用）

用法（在应用容器内运行，容器已具备要的依赖与网络）：

    docker exec party-agent-app-run python scripts/seed_knowledge_docs.py

说明：
- 通过真实入库接口 POST /knowledge-docs 上传（走解析 → 章条切分 → 落库），
  再调用 POST /embeddings/embed-all-pending 生成向量，使问答可检索。
- 内容为公开党内法规与校内制度的**节选要点整理**，非官方全文；正式使用请替换为
  权威文本。写入登录账号（默认 admin-verify）所属租户。
- 幂等：doc_id 已存在时后端返回 409，脚本跳过该文档。
"""
from __future__ import annotations

import sys

import httpx

BASE = "http://localhost:8000/api/v1"
USERNAME = "admin-verify"
PASSWORD = "admin123"

# 每篇：doc_id / 文件 / 元数据 / 正文（以「第X条」组织，便于章条切分）
DOCS: list[dict[str, str]] = [
    {
        "doc_id": "DOC-PARTY-CONSTITUTION",
        "file_name": "中国共产党章程（节选）.txt",
        "title": "中国共产党章程（节选）",
        "issuer": "中国共产党第二十次全国代表大会",
        "level": "central",
        "visibility": "public",
        "security_level": "public",
        "effective_date": "2022-10-22",
        "doc_number": "",
        "tags": "党章,党员义务,入党程序",
        "summary": "党章党员部分节选：入党条件、党员义务、发展党员基本程序与预备期。",
        "status": "effective",
        "content": """中国共产党章程（节选）

第一章 党员

第一条 年满十八岁的中国工人、农民、军人、知识分子和其他社会阶层的先进分子，承认党的纲领和章程，愿意参加党的一个组织并在其中积极工作、执行党的决议和按期交纳党费的，可以申请加入中国共产党。

第二条 中国共产党党员是中国工人阶级的有共产主义觉悟的先锋战士。中国共产党党员必须全心全意为人民服务，不惜牺牲个人的一切，为实现共产主义奋斗终身。中国共产党党员永远是劳动人民的普通一员。

第三条 党员必须履行下列义务：
（一）认真学习马克思列宁主义、毛泽东思想、邓小平理论、"三个代表"重要思想、科学发展观、习近平新时代中国特色社会主义思想，学习党的路线、方针、政策及决议，学习党的基本知识，学习科学、文化、法律和业务知识，努力提高为人民服务的本领。
（二）贯彻执行党的基本路线和各项方针、政策，带头参加改革开放和社会主义现代化建设，带动群众为经济发展和社会进步艰苦奋斗，在生产、工作、学习和社会生活中起先锋模范作用。
（三）坚持党和人民的利益高于一切，个人利益服从党和人民的利益，吃苦在前，享受在后，克己奉公，多做贡献。
（四）自觉遵守党的纪律，首先是党的政治纪律和政治规矩，模范遵守国家的法律法规，严格保守党和国家的秘密，执行党的决定，服从组织分配，积极完成党的任务。

第五条 发展党员，必须把政治标准放在首位，经过党的支部，坚持个别吸收的原则。申请入党的人，要填写入党志愿书，要有两名正式党员作介绍人，要经过支部大会通过和上级党组织批准，并且经过预备期的考察，才能成为正式党员。预备党员的预备期为一年。党组织对预备党员应当认真教育和考察。
""",
    },
    {
        "doc_id": "DOC-BRANCH-REGULATION",
        "file_name": "中国共产党支部工作条例（试行）（节选）.txt",
        "title": "中国共产党支部工作条例（试行）（节选）",
        "issuer": "中共中央",
        "level": "central",
        "visibility": "public",
        "security_level": "public",
        "effective_date": "2018-10-28",
        "doc_number": "",
        "tags": "支部工作,三会一课,组织生活",
        "summary": "支部工作条例节选：党支部职责、会议频次、组织生活及发展党员要求。",
        "status": "effective",
        "content": """中国共产党支部工作条例（试行）（节选）

第十条 党支部应当组织党员认真学习习近平新时代中国特色社会主义思想，推进"两学一做"学习教育常态化制度化，学习党的路线方针政策和决议，学习党的基本知识，学习科学、文化、法律和业务知识。

第十一条 党支部党员大会一般每季度召开1次；党支部委员会会议一般每月召开1次；党小组会一般每月召开1次。党支部应当组织党员按期参加党课学习，一般每季度至少1次。

第十二条 党支部应当严格执行党的组织生活制度，经常、认真、严肃地开展批评和自我批评，增强党内政治生活的政治性、时代性、原则性、战斗性。党员领导干部应当以普通党员身份参加所在党支部或者党小组的组织生活。

第十三条 党支部应当做好党员发展工作，把政治标准放在首位，严格程序、严肃纪律。对要求入党的积极分子进行教育培养，做好经常性的发展党员工作。

第十四条 党支部应当加强党员教育管理，落实"三会一课"、主题党日、民主评议党员、谈心谈话等制度，了解掌握党员思想、工作、生活情况。
""",
    },
    {
        "doc_id": "DOC-MEMBER-EDU-REGULATION",
        "file_name": "中国共产党党员教育管理工作条例（节选）.txt",
        "title": "中国共产党党员教育管理工作条例（节选）",
        "issuer": "中共中央",
        "level": "central",
        "visibility": "public",
        "security_level": "public",
        "effective_date": "2019-05-06",
        "doc_number": "",
        "tags": "党员教育,组织生活,学时",
        "summary": "党员教育管理工作条例节选：教育任务、集中培训学时、组织生活与从严管理。",
        "status": "effective",
        "content": """中国共产党党员教育管理工作条例（节选）

第六条 党员教育基本任务包括：政治理论教育、政治教育和政治训练、党章党规党纪教育、党的宗旨教育、革命传统教育、形势政策教育、知识技能教育等。

第九条 党支部每年对党员进行集中学习培训，一般不少于32学时；对流动党员，应当采取灵活方式组织学习培训。

第十五条 党员应当按期参加党的组织生活，按时足额交纳党费。党支部应当通过"三会一课"、主题党日、组织生活会、民主评议党员、谈心谈话等方式，对党员进行经常性教育管理。

第二十条 党组织应当坚持从严管理党员，对不履行党员义务、不符合党员条件的党员，及时进行教育帮助；情节严重、经教育仍不改正的，按照有关规定作出组织处置或者纪律处分。
""",
    },
    {
        "doc_id": "DOC-DISCIPLINE-REGULATION",
        "file_name": "中国共产党纪律处分条例（节选）.txt",
        "title": "中国共产党纪律处分条例（节选）",
        "issuer": "中共中央",
        "level": "central",
        "visibility": "public",
        "security_level": "public",
        "effective_date": "2024-01-01",
        "doc_number": "",
        "tags": "纪律处分,合规,党纪",
        "summary": "纪律处分条例节选：处分种类、纪律处理措施与从严要求。",
        "status": "effective",
        "content": """中国共产党纪律处分条例（节选）

第一条 为了维护党章和其他党内法规，严肃党的纪律，纯洁党的组织，保障党员民主权利，教育党员遵纪守法，维护党的团结统一，保证党的理论、路线、方针、政策、决议和国家法律法规的贯彻执行，根据《中国共产党章程》，制定本条例。

第七条 对党员的纪律处分种类：（一）警告；（二）严重警告；（三）撤销党内职务；（四）留党察看；（五）开除党籍。

第八条 对严重违犯党纪的党组织的纪律处理措施：（一）改组；（二）解散。

第十八条 党的纪律是党的各级组织和全体党员必须遵守的行为规则。党组织和党员必须牢固树立政治意识、大局意识、核心意识、看齐意识，自觉遵守党章，严格执行和维护党的纪律，自觉接受党的纪律约束，模范遵守国家法律法规。

第十九条 对于违犯党纪应当给予警告或者严重警告处分，但是具有从轻或者减轻情形的，可以给予批评教育、责令检查或者予以诫勉，免予党纪处分。对违纪党员免予处分，应当作出书面结论。
""",
    },
    {
        "doc_id": "DOC-SCHOOL-STUDENT-MEMBER",
        "file_name": "关于加强高校学生党员教育管理的实施意见.txt",
        "title": "关于加强高校学生党员教育管理的实施意见",
        "issuer": "中共某某大学委员会组织部",
        "level": "school",
        "visibility": "school",
        "security_level": "internal",
        "effective_date": "2023-09-01",
        "expiration_date": "2028-08-31",
        "doc_number": "校党组〔2023〕15号",
        "tags": "学生党员,教育管理,考察",
        "summary": "校级实施意见：学生党员与入党积极分子的培养教育、程序与组织生活要求。",
        "status": "effective",
        "content": """关于加强高校学生党员教育管理的实施意见

第一条 各院系党组织要把学生党员教育管理作为基层党建的重要任务，纳入党建工作责任制考核，确保组织落实、责任落实。

第二条 做好入党积极分子培养教育。党支部应当为每名入党积极分子指定一至两名正式党员作为培养联系人，每半年至少进行一次考察并形成考察记录。

第三条 严格发展党员工作程序。坚持把政治标准放在首位，落实政治审查、公示、支部大会讨论、上级党组织审批等环节，做到程序完备、材料齐全。

第四条 加强预备党员预备期教育考察。预备期内党支部应当通过谈心谈话、集中学习、实践锻炼等方式加强考察，预备期满及时讨论转正事宜。

第五条 落实"三会一课"和主题党日制度。学生党支部应当结合学习生活实际，创新组织生活形式，增强组织生活吸引力和实效性。
""",
    },
    {
        "doc_id": "DOC-SCHOOL-TUIYOU",
        "file_name": "高校共青团推优入党工作实施办法.txt",
        "title": "高校共青团推优入党工作实施办法",
        "issuer": "中共某某大学委员会组织部、校团委",
        "level": "school",
        "visibility": "school",
        "security_level": "internal",
        "effective_date": "2024-03-01",
        "doc_number": "校党组〔2024〕5号",
        "tags": "推优,共青团,入党积极分子",
        "summary": "推优入党实施办法：原则、推优对象条件、程序与团组织跟踪培养。",
        "status": "effective",
        "content": """高校共青团推优入党工作实施办法

第一条 推荐优秀团员作为入党积极分子人选（以下简称"推优"）是共青团组织的重要职责，是发展党员工作的重要环节。

第二条 推优工作坚持公开、公平、公正原则，坚持标准、保证质量，把政治标准放在首位。

第三条 推优对象应当是从团员中培养、经团组织考察了解、表现优秀、群众公认、本人有入党意愿的青年。推优比例一般控制在本单位团员数的合理范围内。

第四条 推优程序一般包括：本人申请、团总支（团支部）推荐、民主评议、公示、报党组织审定等环节。

第五条 团组织应当与党组织加强沟通衔接，做好推优对象的跟踪培养，及时向党组织报告培养考察情况。
""",
    },
    {
        "doc_id": "DOC-DEPT-TRAINING-RECORD",
        "file_name": "入党积极分子培养考察记录填写规范.txt",
        "title": "入党积极分子培养考察记录填写规范",
        "issuer": "某某大学某某学院党委",
        "level": "department",
        "visibility": "department",
        "security_level": "internal",
        "effective_date": "2022-04-01",
        "doc_number": "院党字〔2022〕03号",
        "tags": "培养考察,记录填写",
        "summary": "院系规范：培养考察记录的填写要求、频次、内容与归档。",
        "status": "effective",
        "content": """入党积极分子培养考察记录填写规范

第一条 培养考察记录是入党积极分子培养教育过程的重要档案材料，应当真实、准确、及时填写，不得追记、补记或代填。

第二条 记录内容包括：培养联系人与被培养人谈心谈话情况、被培养人思想汇报及表现、参加组织生活和实践活动情况、存在不足与改进方向等。

第三条 培养联系人应当每半年至少填写一次考察意见，如实反映被培养人的思想、学习、工作和生活情况。

第四条 党支部应当定期检查培养考察记录填写情况，将其作为讨论确定发展对象的重要依据。

第五条 考察记录应当妥善保管，做到一人一档、随发展阶段同步归档，确保材料完整可追溯。
""",
    },
]


def _metadata_fields(doc: dict[str, str]) -> dict[str, str]:
    """提取除正文/文件名外的表单字段"""
    keys = (
        "doc_id",
        "file_name",
        "title",
        "issuer",
        "level",
        "visibility",
        "security_level",
        "effective_date",
        "doc_number",
        "tags",
        "summary",
        "status",
    )
    data = {k: doc.get(k, "") for k in keys}
    if doc.get("expiration_date"):
        data["expiration_date"] = doc["expiration_date"]
    return data


def main() -> None:
    with httpx.Client(timeout=120.0) as client:
        # 登录取得令牌
        resp = client.post(
            f"{BASE}/auth/login",
            json={"username": USERNAME, "password": PASSWORD},
        )
        resp.raise_for_status()
        token = resp.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        created = skipped = failed = 0
        for doc in DOCS:
            files = {
                "file": (doc["file_name"], doc["content"].encode("utf-8"), "text/plain")
            }
            resp = client.post(
                f"{BASE}/knowledge-docs",
                headers=headers,
                data=_metadata_fields(doc),
                files=files,
            )
            if resp.status_code in (200, 201):
                chunk_count = resp.json().get("data", {}).get("chunk_count", "?")
                print(f"[ok]   {doc['doc_id']}  切分 {chunk_count} 段")
                created += 1
            elif resp.status_code == 409:
                print(f"[skip] {doc['doc_id']}  已存在")
                skipped += 1
            else:
                print(f"[FAIL] {doc['doc_id']}  HTTP {resp.status_code}: {resp.text[:160]}")
                failed += 1

        # 生成向量（使新文档可被问答检索）
        resp = client.post(
            f"{BASE}/embeddings/embed-all-pending",
            headers=headers,
            params={"data_level": "public"},
        )
        embedded = "?"
        if resp.status_code == 200:
            embedded = resp.json().get("data", {}).get("embedded_count", "?")
        else:
            print(f"[FAIL] embed-all-pending HTTP {resp.status_code}: {resp.text[:160]}")

        print(
            f"\n汇总：新增 {created}，跳过 {skipped}，失败 {failed}；本次向量化片段 {embedded}"
        )


if __name__ == "__main__":
    main()

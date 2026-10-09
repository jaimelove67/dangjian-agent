"""评测脚本

运行检索和问答的离线评测。
"""
import asyncio
import json
from pathlib import Path
from typing import List, Dict, Any

# 评测配置
RETRIEVAL_SAMPLES_FILE = Path(__file__).parent / "retrieval_samples.json"
QA_SAMPLES_FILE = Path(__file__).parent / "qa_samples.json"
OUTPUT_DIR = Path(__file__).parent / "results"


async def evaluate_retrieval():
    """评测检索准确率

    指标：
    - Recall@K: 期望文档在top-K中的召回率
    - MRR (Mean Reciprocal Rank): 平均倒数排名
    - Precision@K: top-K中相关文档的比例
    """
    print("=" * 60)
    print("检索评测")
    print("=" * 60)

    # 加载样本
    with open(RETRIEVAL_SAMPLES_FILE, "r", encoding="utf-8") as f:
        samples = json.load(f)

    print(f"\n加载了 {len(samples)} 个检索样本")
    print("\n注意：需要真实数据库和知识库数据才能运行评测")
    print("建议：")
    print("1. 确保数据库已启动并包含党建文档数据")
    print("2. 确保文档已向量化")
    print("3. 设置DashScope API Key")

    # 评测逻辑（需要真实环境）
    print("\n评测指标定义：")
    print("- Recall@5: 期望文档在top-5结果中的比例")
    print("- Recall@10: 期望文档在top-10结果中的比例")
    print("- MRR: 期望文档首次出现的平均倒数排名")
    print("- Precision@5: top-5中相关文档的平均比例")

    print("\n样本示例：")
    for sample in samples[:3]:
        print(f"  [{sample['id']}] {sample['query']}")
        print(f"      期望文档: {', '.join(sample['expected_docs'])}")
        print(f"      期望条款: {', '.join(sample.get('expected_articles', []))}")

    return {
        "total_samples": len(samples),
        "note": "需要真实环境运行",
    }


async def evaluate_qa():
    """评测问答质量

    指标：
    - 答案相关性: 答案是否包含期望内容
    - 引用准确性: 是否有正确的引用
    - 拒答准确率: 无关问题的拒答率
    """
    print("\n" + "=" * 60)
    print("问答评测")
    print("=" * 60)

    # 加载样本
    with open(QA_SAMPLES_FILE, "r", encoding="utf-8") as f:
        samples = json.load(f)

    refuse_samples = [s for s in samples if s["should_refuse"]]
    answer_samples = [s for s in samples if not s["should_refuse"]]

    print(f"\n加载了 {len(samples)} 个问答样本")
    print(f"  - 正常回答样本: {len(answer_samples)}")
    print(f"  - 拒答测试样本: {len(refuse_samples)}")

    print("\n评测指标定义：")
    print("- 答案相关性: 答案是否包含期望关键词")
    print("- 引用准确性: 是否有正确的文档引用")
    print("- 拒答准确率: 无关问题的拒答比例")
    print("- 拒答误报率: 有关问题被错误拒答的比例")

    print("\n正常回答样本示例：")
    for sample in answer_samples[:3]:
        print(f"  [{sample['id']}] {sample['question']}")
        print(f"      期望包含: {', '.join(sample['expected_answer_contains'])}")

    print("\n拒答测试样本示例：")
    for sample in refuse_samples[:3]:
        print(f"  [{sample['id']}] {sample['question']}")
        print(f"      应该拒答: 是")

    return {
        "total_samples": len(samples),
        "answer_samples": len(answer_samples),
        "refuse_samples": len(refuse_samples),
        "note": "需要真实环境运行",
    }


async def main():
    """主函数"""
    print("党建工作智能体 - 离线评测")
    print("=" * 60)

    # 创建输出目录
    OUTPUT_DIR.mkdir(exist_ok=True)

    # 运行评测
    retrieval_result = await evaluate_retrieval()
    qa_result = await evaluate_qa()

    # 保存结果
    results = {
        "retrieval": retrieval_result,
        "qa": qa_result,
    }

    output_file = OUTPUT_DIR / "evaluation_summary.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"评测摘要已保存到: {output_file}")
    print("=" * 60)

    print("\n下一步：")
    print("1. 准备真实数据库环境")
    print("2. 导入党建知识文档")
    print("3. 运行完整评测并记录指标")
    print("4. 根据评测结果调优参数（阈值、top_k等）")


if __name__ == "__main__":
    asyncio.run(main())

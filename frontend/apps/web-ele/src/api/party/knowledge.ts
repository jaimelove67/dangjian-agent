/**
 * 党建工作智能助手 —— 知识库接口
 *
 * 后端真实接口：/api/v1/knowledge-docs
 * 注意：后端目前只有「创建 / 按 id 查 / 改状态」三个接口，缺少列表分页接口，
 * 因此列表在 Mock 模式下可用，切到真实接口前需要后端补 GET /knowledge-docs。
 */

import { requestClient } from '#/api/request';

import { MOCK_DOCS, PARTY_USE_MOCK } from './mock';
import type {
  KnowledgeDoc,
  KnowledgeDocCreatePayload,
  KnowledgeDocCreateResult,
  PageResult,
} from './types';

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 文档列表查询参数 */
export interface KnowledgeDocQuery {
  page?: number;
  pageSize?: number;
  keyword?: string;
  /** 文件层级 */
  level?: string;
  /** 状态：effective / expired / abolished */
  status?: string;
}

/** 查询文档列表（分页） */
export async function listKnowledgeDocsApi(
  query: KnowledgeDocQuery = {},
): Promise<PageResult<KnowledgeDoc>> {
  const { page = 1, pageSize = 10, keyword = '', level, status } = query;

  if (PARTY_USE_MOCK) {
    await delay(300);
    const filtered = MOCK_DOCS.filter((doc) => {
      const kw = keyword.trim();
      const matchKeyword =
        !kw ||
        doc.title.includes(kw) ||
        doc.issuer.includes(kw) ||
        doc.docNumber?.includes(kw);
      const matchLevel = !level || doc.level === level;
      const matchStatus = !status || doc.status === status;
      return matchKeyword && matchLevel && matchStatus;
    });
    const start = (page - 1) * pageSize;
    return {
      items: filtered.slice(start, start + pageSize),
      total: filtered.length,
      page,
      pageSize,
    };
  }

  return await requestClient.get<PageResult<KnowledgeDoc>>('/v1/knowledge-docs', {
    params: query,
  });
}

/** 查询单篇文档 */
export async function fetchKnowledgeDocApi(id: string): Promise<KnowledgeDoc> {
  if (PARTY_USE_MOCK) {
    await delay(200);
    const doc = MOCK_DOCS.find((item) => item.id === id);
    if (!doc) {
      throw new Error(`文档不存在：${id}`);
    }
    return doc;
  }

  return await requestClient.get<KnowledgeDoc>(`/v1/knowledge-docs/${id}`);
}

/** 文档入库 */
export async function createKnowledgeDocApi(
  payload: KnowledgeDocCreatePayload,
): Promise<KnowledgeDocCreateResult> {
  if (PARTY_USE_MOCK) {
    await delay(900);
    const doc: KnowledgeDoc = {
      id: String(Date.now()),
      docId: `DOC-${new Date().getFullYear()}-${Math.floor(Math.random() * 9000 + 1000)}`,
      fileName: payload.fileName,
      title: payload.title,
      issuer: payload.issuer,
      docNumber: payload.docNumber,
      level: payload.level,
      visibility: payload.visibility,
      securityLevel: payload.securityLevel,
      status: 'effective',
      effectiveDate: payload.effectiveDate,
      expirationDate: payload.expirationDate,
      tags: payload.tags,
      summary: payload.summary,
    };
    MOCK_DOCS.unshift(doc);
    return { document: doc, chunkCount: 68 };
  }

  return await requestClient.post<KnowledgeDocCreateResult>(
    '/v1/knowledge-docs',
    payload,
  );
}

/** 变更文档状态 */
export async function updateDocStatusApi(
  id: string,
  status: KnowledgeDoc['status'],
): Promise<KnowledgeDoc> {
  if (PARTY_USE_MOCK) {
    await delay(250);
    const doc = MOCK_DOCS.find((item) => item.id === id);
    if (!doc) {
      throw new Error(`文档不存在：${id}`);
    }
    doc.status = status;
    return doc;
  }

  return await requestClient.patch<KnowledgeDoc>(`/v1/knowledge-docs/${id}/status`, {
    status,
  });
}

/** 可选的文件层级 */
export const DOC_LEVELS = ['中央级', '省级', '市级', '校级'];
/** 可选的公开属性 */
export const DOC_VISIBILITIES = ['主动公开', '依申请公开', '不予公开'];
/** 可选的密级 */
export const DOC_SECURITY_LEVELS = ['公开', '内部', '秘密', '机密'];

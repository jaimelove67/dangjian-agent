import type { RouteRecordRaw } from 'vue-router';

/**
 * 党建工作智能助手 —— 业务路由
 *
 * 该目录下的文件会被 src/router/routes/index.ts 通过 import.meta.glob 自动合并。
 * 后端菜单接口就绪后，可改为由后端下发（见 src/router/access.ts 的 accessMode）。
 */
const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:messages-square',
      order: -5,
      title: '党建智能助手',
    },
    name: 'Party',
    path: '/party',
    children: [
      {
        name: 'PartyQa',
        path: 'qa',
        component: () => import('#/views/party/qa/index.vue'),
        meta: {
          icon: 'lucide:sparkles',
          title: '智能问答',
        },
      },
      {
        name: 'PartyKnowledgeList',
        path: 'knowledge',
        component: () => import('#/views/party/knowledge/list.vue'),
        meta: {
          icon: 'lucide:library',
          title: '知识库管理',
        },
      },
      {
        name: 'PartyKnowledgeIntake',
        path: 'knowledge-intake',
        component: () => import('#/views/party/knowledge/intake.vue'),
        meta: {
          icon: 'lucide:file-up',
          title: '文档入库',
        },
      },
    ],
  },
];

export default routes;
